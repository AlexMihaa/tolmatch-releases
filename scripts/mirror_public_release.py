#!/usr/bin/env python3
"""Mirror a published stable Tolmatch release to Timeweb S3; never publish a release."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import scan_public_release as public

REPOSITORY = "AlexMihaa/tolmatch-releases"
BUCKET = "tolmatch-public"
ENDPOINT = "https://s3.twcstorage.ru"
REGION = "ru-1"
ORIGIN = f"{ENDPOINT}/{BUCKET}/"
CDN = "https://cdn.tolmatch.app/"
MIME = {".dmg": "application/x-apple-diskimage", ".sha256": "text/plain; charset=utf-8",
        ".json": "application/json", ".xml": "application/xml",
        ".mp4": "video/mp4", ".jpg": "image/jpeg", ".vtt": "text/vtt; charset=utf-8"}
MAX_METADATA_BYTES = 1024 * 1024


def release_assets(tag):
    match = re.fullmatch(r"v([0-9]+\.[0-9]+(?:\.[0-9]+)?)-([1-9][0-9]{0,9})", tag)
    if not match:
        raise ValueError("expected a canonical stable release tag")
    info = public.read_json(f"https://api.github.com/repos/{REPOSITORY}")
    if info.get("private") is not False or info.get("visibility") != "public":
        raise ValueError("distribution repository must be public")
    release = public.read_json(f"https://api.github.com/repos/{REPOSITORY}/releases/tags/{tag}")
    if (release.get("draft") is not False or release.get("prerelease") is not False
            or release.get("tag_name") != tag or not release.get("published_at")):
        raise ValueError("only published stable releases may be mirrored")
    names = [f"Tolmatch-{match[1]}.dmg", f"Tolmatch-{match[1]}.dmg.sha256",
             "tolmatch-release.json", "appcast.xml"]
    assets = []
    for name in names:
        found = [a for a in release.get("assets", []) if a.get("name") == name]
        if len(found) != 1:
            raise ValueError("release lacks exactly four canonical assets")
        asset = found[0]
        expected = f"https://github.com/{REPOSITORY}/releases/download/{tag}/{name}"
        limit = public.MAX_FILE_BYTES if name.endswith(".dmg") else MAX_METADATA_BYTES
        size = asset.get("size")
        if (type(asset.get("id")) is not int or asset["id"] < 1
                or asset.get("state") != "uploaded" or asset.get("browser_download_url") != expected
                or not re.fullmatch(r"sha256:[a-f0-9]{64}", asset.get("digest") or "")
                or type(size) is not int or not 0 < size <= limit):
            raise ValueError("invalid release asset URL, digest or size")
        assets.append(asset)
    return match[1], match[2], assets


def download_asset(asset, path):
    # GitHub's website download route can return 504 even inside Actions. Use
    # its official asset API via gh, which handles binary responses/redirects.
    command = ["gh", "api", "--method", "GET", "-H", "Accept: application/octet-stream",
               f"repos/{REPOSITORY}/releases/assets/{asset['id']}"]
    with path.open("wb") as output:
        subprocess.run(command, stdout=output, stderr=subprocess.PIPE, check=True, timeout=180)
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            size += len(block)
            if size > asset["size"]:
                raise ValueError("download exceeds advertised asset size")
            digest.update(block)
    if size != asset["size"] or "sha256:" + digest.hexdigest() != asset["digest"]:
        raise ValueError("asset API download differs from published GitHub digest")


def validate_package(tag, version, build, assets, directory):
    """All source bytes are verified before the first authenticated S3 operation."""
    for asset in assets:
        download_asset(asset, directory / asset["name"])
    dmg = assets[0]
    sha = dmg["digest"].removeprefix("sha256:")
    checksum = (directory / assets[1]["name"]).read_text().strip()
    if checksum != f"{sha}  {dmg['name']}":
        raise ValueError("checksum file does not match the installer")
    metadata = json.loads((directory / "tolmatch-release.json").read_text())
    expected = {"tag": tag, "version": version, "build": build, "file": dmg["name"],
                "sizeBytes": dmg["size"], "sha256": sha, "sourceTreeDirty": False,
                "prerelease": False, "channel": "production-self-signed",
                "automaticUpdates": True, "appcastFile": "appcast.xml"}
    if any(type(metadata.get(k)) is not type(v) or metadata[k] != v for k, v in expected.items()):
        raise ValueError("release metadata does not match the canonical stable package")


def s3_environment():
    if not os.environ.get("AWS_ACCESS_KEY_ID") or not os.environ.get("AWS_SECRET_ACCESS_KEY"):
        raise ValueError("publisher credentials are not configured")
    return dict(os.environ, AWS_EC2_METADATA_DISABLED="true", AWS_DEFAULT_REGION=REGION,
                AWS_REQUEST_CHECKSUM_CALCULATION="when_required",
                AWS_RESPONSE_CHECKSUM_VALIDATION="when_required")


def key_exists(key):
    """An anonymous S3 403 can mean no key, but is never sufficient evidence itself."""
    if not key.startswith(("releases/", "site-media/")) or any(p in ("", ".", "..") for p in key.split("/")):
        raise ValueError("unexpected public object key")
    command = ["aws", "--endpoint-url", ENDPOINT, "--no-cli-pager", "s3api", "list-objects-v2",
               "--bucket", BUCKET, "--prefix", key, "--max-keys", "2", "--no-paginate", "--output", "json"]
    result = subprocess.run(command, env=s3_environment(), check=True, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=60)
    if len(result.stdout) > 64 * 1024:
        raise ValueError("oversized existence response")
    listing = json.loads(result.stdout)
    contents = listing.get("Contents", [])
    if not isinstance(contents, list) or any(not isinstance(item, dict) or not isinstance(item.get("Key"), str)
                                            or not item["Key"].startswith(key) for item in contents):
        raise ValueError("invalid existence response")
    if any(item["Key"] == key for item in contents):
        return True
    if listing.get("IsTruncated") is not False or listing.get("KeyCount") != len(contents):
        raise ValueError("incomplete existence response")
    return False


def object_digest(key, limit):
    """Read anonymously from the origin, bypassing CDN negative/old caches."""
    try:
        with urlopen(Request(ORIGIN + key, headers={"User-Agent": "Tolmatch-release-mirror"}), timeout=60) as response:
            if response.status != 200 or response.geturl() != ORIGIN + key:
                raise ValueError("unexpected object response")
            digest = hashlib.sha256()
            size = 0
            while block := response.read(1024 * 1024):
                size += len(block)
                if size > limit:
                    raise ValueError("existing object exceeds the expected size")
                digest.update(block)
            return size, "sha256:" + digest.hexdigest()
    except HTTPError as error:
        if error.code == 404:
            return None
        if (error.code == 403 and os.environ.get("AWS_ACCESS_KEY_ID")
                and os.environ.get("AWS_SECRET_ACCESS_KEY") and not key_exists(key)):
            return None
        raise


def upload(path, key, digest):
    """AWS CLI signs HTTPS S3 requests; credentials stay in the environment."""
    environment = s3_environment()
    cache = "no-store,max-age=0" if key.endswith("/mirror.json") else "public,max-age=31536000,immutable"
    command = ["aws", "--endpoint-url", ENDPOINT, "--no-cli-pager",
               "s3api", "put-object", "--bucket", BUCKET, "--key", key, "--body", str(path),
               "--content-type", MIME[path.suffix], "--cache-control", cache,
               "--metadata", json.dumps({"sha256": digest.removeprefix("sha256:")})]
    # Never echo subprocess errors: SDK diagnostics can contain request details.
    subprocess.run(command, env=environment, check=True, stdout=subprocess.DEVNULL,
                   stderr=subprocess.PIPE, timeout=300)


def mirror(tag, assets, directory, put=upload, read=object_digest):
    prefix = f"releases/{tag}/"
    # Preflight every destination before writing, so conflicts cannot cause partial overwrites.
    for asset in assets:
        previous = read(prefix + asset["name"], asset["size"])
        if previous is not None and previous != (asset["size"], asset["digest"]):
            raise ValueError("refusing to overwrite different versioned bytes")
    for asset in assets:
        key = prefix + asset["name"]
        # Identical files may be PUT again to apply correct MIME/cache metadata, including manual bootstrap copies.
        put(directory / asset["name"], key, asset["digest"])
        if read(key, asset["size"]) != (asset["size"], asset["digest"]):
            raise ValueError("public mirror verification failed")
        print(f"Verified: {key} ({asset['size']} bytes)")
    manifest = {"schemaVersion": 1, "repository": REPOSITORY, "tag": tag,
                "files": [{"name": a["name"], "sizeBytes": a["size"],
                           "sha256": a["digest"].removeprefix("sha256:"),
                           "url": CDN + prefix + a["name"]} for a in assets]}
    path = directory / "mirror.json"
    path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    expected = (path.stat().st_size, "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest())
    previous = read(prefix + path.name, expected[0])
    if previous is not None and previous != expected:
        raise ValueError("existing completion marker conflicts with the release")
    put(path, prefix + path.name, expected[1])
    if read(prefix + path.name, expected[0]) != expected:
        raise ValueError("completion marker verification failed")
    print(f"Mirror ready: {CDN}{prefix}mirror.json")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag")
    args = parser.parse_args()
    version, build, assets = release_assets(args.tag)
    print(f"Validated public stable release metadata: {args.tag}", flush=True)
    with tempfile.TemporaryDirectory(prefix="tolmatch-mirror-") as directory:
        path = Path(directory)
        validate_package(args.tag, version, build, assets, path)
        print("Verified all four GitHub downloads and package metadata", flush=True)
        mirror(args.tag, assets, path)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        detail = type(error).__name__
        if isinstance(error, HTTPError):
            detail += f" HTTP {error.code}"
        elif isinstance(error, subprocess.CalledProcessError):
            code = re.search(rb"An error occurred \(([A-Za-z0-9]{1,64})\)", error.stderr or b"")
            if code:
                detail += " S3 " + code[1].decode("ascii")
            status = re.search(rb"HTTP ([0-9]{3})", error.stderr or b"")
            if status:
                detail += " upstream HTTP " + status[1].decode("ascii")
        raise SystemExit(f"Release mirror failed ({detail}); no readiness is asserted.") from None
