#!/usr/bin/env python3
"""Optionally submit an already public GitHub DMG to VirusTotal; no release publication."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import tempfile
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import build_opener, HTTPRedirectHandler, Request, urlopen

MAX_FILE_BYTES = 650 * 1024 * 1024


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def read_json(url: str, api_key: str = "") -> dict:
    headers = {"Accept": "application/json", "User-Agent": "Tolmatch-release-check"}
    if api_key:
        headers["x-apikey"] = api_key
    with build_opener(NoRedirect).open(Request(url, headers=headers), timeout=30) as response:
        body = response.read(4 * 1024 * 1024 + 1)
    if len(body) > 4 * 1024 * 1024:
        raise ValueError("oversized API response")
    return json.loads(body)


def public_asset(repository: str, tag: str) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9][A-Za-z0-9._-]{0,99}", repository):
        raise ValueError("invalid public distribution repository")
    match = re.fullmatch(r"v([0-9]+\.[0-9]+(?:\.[0-9]+)?)-[1-9][0-9]{0,9}", tag)
    if not match:
        raise ValueError("expected v<version>-<positive build> tag")
    # Unauthenticated lookup deliberately refuses a private source repository.
    info = read_json(f"https://api.github.com/repos/{repository}")
    if info.get("private") is not False or info.get("visibility") != "public":
        raise ValueError("only already public binary distribution repositories may be scanned")
    release = read_json(f"https://api.github.com/repos/{repository}/releases/tags/{tag}")
    if release.get("draft") or release.get("prerelease") or not release.get("published_at"):
        raise ValueError("only published stable releases may be scanned")
    name = f"Tolmatch-{match[1]}.dmg"
    expected_url = f"https://github.com/{repository}/releases/download/{tag}/{name}"
    for asset in release.get("assets", []):
        if (asset.get("name") == name and asset.get("state") == "uploaded"
                and asset.get("browser_download_url") == expected_url
                and re.fullmatch(r"sha256:[a-f0-9]{64}", asset.get("digest") or "")
                and 0 < asset.get("size", 0) <= MAX_FILE_BYTES):
            return asset
    raise ValueError("release lacks an exact canonical DMG with GitHub SHA-256 digest")


def download(asset: dict, path: Path) -> None:
    digest = hashlib.sha256()
    size = 0
    # No token is sent to GitHub or its asset CDN. Verify the final bytes against GitHub's digest.
    with urlopen(asset["browser_download_url"], timeout=60) as response, path.open("wb") as output:
        while block := response.read(1024 * 1024):
            size += len(block)
            if size > asset["size"] or size > MAX_FILE_BYTES:
                raise ValueError("download exceeds advertised asset size")
            digest.update(block)
            output.write(block)
    if size != asset["size"] or "sha256:" + digest.hexdigest() != asset["digest"]:
        raise ValueError("downloaded DMG differs from published GitHub digest")


def submit(path: Path, api_key: str) -> None:
    upload_url = "https://www.virustotal.com/api/v3/files"
    if path.stat().st_size > 32 * 1024 * 1024:
        upload_url = read_json(upload_url + "/upload_url", api_key)["data"]
    parsed = urlparse(upload_url)
    if parsed.scheme != "https" or parsed.netloc != "www.virustotal.com" or parsed.username or parsed.fragment:
        raise ValueError("invalid VirusTotal upload URL")
    boundary = secrets.token_hex(24)
    prefix = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{path.name}\"\r\n"
              "Content-Type: application/octet-stream\r\n\r\n").encode()
    # urllib streams an iterable request body. A known length avoids buffering the whole DMG.
    suffix = f"\r\n--{boundary}--\r\n".encode()

    def body():
        yield prefix
        with path.open("rb") as stream:
            while block := stream.read(1024 * 1024):
                yield block
        yield suffix

    req = Request(upload_url, data=body(), method="POST", headers={
        "x-apikey": api_key,
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(len(prefix) + path.stat().st_size + len(suffix)),
    })
    with build_opener(NoRedirect).open(req, timeout=120) as response:
        data = json.loads(response.read(1024 * 1024))
    if not data.get("data", {}).get("id"):
        raise ValueError("VirusTotal did not return an analysis ID")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository")
    parser.add_argument("tag")
    args = parser.parse_args()
    asset = public_asset(args.repository, args.tag)
    digest = asset["digest"].removeprefix("sha256:")
    print(f"SHA-256: {digest}\nVirusTotal report: https://www.virustotal.com/gui/file/{digest}")
    api_key = os.environ.get("VIRUSTOTAL_API_KEY", "")
    if not api_key:
        print("VirusTotal upload skipped: API key is not configured. Report may not exist.")
        return
    try:
        read_json(f"https://www.virustotal.com/api/v3/files/{digest}", api_key)
        print("VirusTotal already has this file; review its report separately.")
        return
    except HTTPError as error:
        if error.code != 404:
            raise ValueError(f"VirusTotal lookup failed (HTTP {error.code})") from None
    with tempfile.TemporaryDirectory(prefix="tolmatch-public-scan-") as directory:
        path = Path(directory) / asset["name"]
        download(asset, path)
        submit(path, api_key)
    print("Public DMG submitted to VirusTotal. Analysis is pending; no safety verdict is asserted.")


if __name__ == "__main__":
    try:
        main()
    except (HTTPError, OSError, ValueError, KeyError) as error:
        # Do not print URLs, request headers, API response bodies or credentials.
        raise SystemExit(f"Release scan failed ({type(error).__name__}); review public asset/configuration.") from None
