"""Publication-boundary tests. No real credentials or cloud writes."""
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

import mirror_public_release as mirror


def fixture():
    sha = hashlib.sha256(b"installer").hexdigest()
    meta = {"tag": "v0.1.9-12", "version": "0.1.9", "build": "12", "file": "Tolmatch-0.1.9.dmg",
            "sizeBytes": 9, "sha256": sha, "sourceTreeDirty": False, "prerelease": False,
            "channel": "production-self-signed", "automaticUpdates": True, "appcastFile": "appcast.xml"}
    blobs = {"Tolmatch-0.1.9.dmg": b"installer",
             "Tolmatch-0.1.9.dmg.sha256": f"{sha}  Tolmatch-0.1.9.dmg\n".encode(),
             "tolmatch-release.json": json.dumps(meta).encode(), "appcast.xml": b"signed feed bytes"}
    assets = [{"id": i + 1, "name": name, "size": len(body), "digest": "sha256:" + hashlib.sha256(body).hexdigest(),
               "state": "uploaded", "browser_download_url": f"https://github.com/{mirror.REPOSITORY}/releases/download/v0.1.9-12/{name}"}
              for i, (name, body) in enumerate(blobs.items())]
    release = {"tag_name": "v0.1.9-12", "published_at": "2026-11-06T00:00:00Z",
               "draft": False, "prerelease": False, "assets": assets}
    return blobs, assets, release


class ReleaseBoundaryTests(unittest.TestCase):
    def test_public_stable_four_assets(self):
        _, assets, release = fixture()
        with patch.object(mirror.public, "read_json", side_effect=[{"private": False, "visibility": "public"}, release]):
            self.assertEqual(mirror.release_assets("v0.1.9-12"), ("0.1.9", "12", assets))

    def test_private_repository_rejected_before_fetching_release(self):
        with patch.object(mirror.public, "read_json", return_value={"private": True}) as read:
            with self.assertRaises(ValueError): mirror.release_assets("v0.1.9-12")
            self.assertEqual(read.call_count, 1)

    def test_untrusted_tag_rejected_before_network(self):
        for tag in ["main", "v0.1.9-0", "v0.1.9-12/../../x", "v0.1.9-12; echo bad", "v0.1.9-12\n"]:
            with self.subTest(tag=tag), patch.object(mirror.public, "read_json") as read:
                with self.assertRaises(ValueError): mirror.release_assets(tag)
                read.assert_not_called()

    def test_draft_prerelease_and_incomplete_publication_rejected(self):
        _, _, release = fixture()
        for field, value in [("draft", True), ("prerelease", True), ("published_at", None), ("tag_name", "v0.1.8-11")]:
            bad = dict(release, **{field: value})
            with self.subTest(field=field), patch.object(mirror.public, "read_json", side_effect=[{"private": False, "visibility": "public"}, bad]):
                with self.assertRaises(ValueError): mirror.release_assets("v0.1.9-12")

    def test_missing_duplicate_or_unsigned_asset_rejected(self):
        _, _, release = fixture()
        cases = []
        bad = copy.deepcopy(release); bad["assets"].pop(); cases.append(bad)
        bad = copy.deepcopy(release); bad["assets"].append(bad["assets"][0]); cases.append(bad)
        for field, value in [("id", "foreign"), ("digest", None), ("size", True), ("size", -1), ("state", "new"),
                             ("browser_download_url", "https://attacker.invalid/file")]:
            bad = copy.deepcopy(release); bad["assets"][0][field] = value; cases.append(bad)
        for bad in cases:
            with self.subTest(bad=bad), patch.object(mirror.public, "read_json", side_effect=[{"private": False, "visibility": "public"}, bad]):
                with self.assertRaises(ValueError): mirror.release_assets("v0.1.9-12")

    def test_large_metadata_rejected(self):
        _, _, release = fixture(); release["assets"][2]["size"] = mirror.MAX_METADATA_BYTES + 1
        with patch.object(mirror.public, "read_json", side_effect=[{"private": False, "visibility": "public"}, release]):
            with self.assertRaises(ValueError): mirror.release_assets("v0.1.9-12")

    def test_package_rejects_tampered_download(self):
        _, assets, _ = fixture()
        def fake_cli(command, **kwargs): kwargs["stdout"].write(b"tampered")
        with tempfile.TemporaryDirectory() as tmp, patch.object(mirror.subprocess, "run", side_effect=fake_cli):
            with self.assertRaises(ValueError): mirror.validate_package("v0.1.9-12", "0.1.9", "12", assets, Path(tmp))

    def test_asset_download_uses_official_api_and_verifies_bytes(self):
        blobs, assets, _ = fixture()
        def fake_cli(command, **kwargs): kwargs["stdout"].write(blobs[assets[0]["name"]])
        with tempfile.TemporaryDirectory() as tmp, patch.object(mirror.subprocess, "run", side_effect=fake_cli) as run:
            mirror.download_asset(assets[0], Path(tmp) / assets[0]["name"])
            self.assertEqual(run.call_args.args[0][-1], f"repos/{mirror.REPOSITORY}/releases/assets/1")
            self.assertIn("Accept: application/octet-stream", run.call_args.args[0])

    def test_metadata_and_checksum_must_match_installer(self):
        for target in ["checksum", "sha256", "sourceTreeDirty", "build", "sizeBytes"]:
            blobs, assets, _ = fixture()
            if target == "checksum": blobs[assets[1]["name"]] = b"wrong checksum"
            else:
                meta = json.loads(blobs["tolmatch-release.json"])
                meta[target] = True if target == "sourceTreeDirty" else "wrong"
                blobs["tolmatch-release.json"] = json.dumps(meta).encode()
            def download(asset, path): path.write_bytes(blobs[asset["name"]])
            with self.subTest(target=target), tempfile.TemporaryDirectory() as tmp, patch.object(mirror, "download_asset", side_effect=download):
                with self.assertRaises(ValueError): mirror.validate_package("v0.1.9-12", "0.1.9", "12", assets, Path(tmp))


class FakeStore:
    def __init__(self): self.objects = {}; self.puts = []; self.fail_key = None
    def read(self, key, limit):
        data = self.objects.get(key)
        return None if data is None else (len(data), "sha256:" + hashlib.sha256(data).hexdigest())
    def put(self, path, key, digest):
        if self.fail_key and key.endswith(self.fail_key): raise OSError("simulated upload failure")
        self.puts.append(key); self.objects[key] = path.read_bytes()


class MirrorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name); self.blobs, self.assets, _ = fixture()
        for name, body in self.blobs.items(): (self.path / name).write_bytes(body)
        self.store = FakeStore()

    def run_mirror(self):
        with patch("builtins.print"):
            mirror.mirror("v0.1.9-12", self.assets, self.path, self.store.put, self.store.read)

    def test_completion_marker_is_last_and_contains_exact_versioned_urls(self):
        self.run_mirror()
        self.assertEqual(self.store.puts[-1], "releases/v0.1.9-12/mirror.json")
        manifest = json.loads(self.store.objects[self.store.puts[-1]])
        self.assertEqual(len(manifest["files"]), 4)
        self.assertTrue(all(f["url"].startswith(mirror.CDN + "releases/v0.1.9-12/") for f in manifest["files"]))

    def test_identical_retry_preserves_manifest_and_signed_feed_bytes(self):
        self.run_mirror(); previous = dict(self.store.objects)
        self.run_mirror(); self.assertEqual(self.store.objects, previous)
        self.assertEqual(self.store.objects["releases/v0.1.9-12/appcast.xml"], self.blobs["appcast.xml"])

    def test_all_conflicts_detected_before_any_upload(self):
        self.store.objects["releases/v0.1.9-12/appcast.xml"] = b"different existing feed"
        with self.assertRaises(ValueError): self.run_mirror()
        self.assertEqual(self.store.puts, [])

    def test_upload_failure_does_not_publish_completion(self):
        self.store.fail_key = "appcast.xml"
        with self.assertRaises(OSError): self.run_mirror()
        self.assertFalse(any(key.endswith("mirror.json") for key in self.store.objects))

    def test_public_verification_failure_does_not_publish_completion(self):
        original = self.store.put
        def corrupt(path, key, digest): original(path, key, digest); self.store.objects[key] = b"corrupt"
        self.store.put = corrupt
        with self.assertRaises(ValueError): self.run_mirror()
        self.assertFalse(any(key.endswith("mirror.json") for key in self.store.objects))

    def test_credentials_required_before_calling_cli(self):
        with patch.dict("os.environ", {}, clear=True), patch.object(mirror.subprocess, "run") as run:
            with self.assertRaises(ValueError): mirror.upload(self.path / "appcast.xml", "releases/v0.1.9-12/appcast.xml", self.assets[-1]["digest"])
            run.assert_not_called()

    def test_cli_uses_fixed_endpoint_and_never_puts_credentials_in_arguments(self):
        with patch.dict("os.environ", {"AWS_ACCESS_KEY_ID": "test-access", "AWS_SECRET_ACCESS_KEY": "test-secret"}), patch.object(mirror.subprocess, "run") as run:
            mirror.upload(self.path / "appcast.xml", "releases/v0.1.9-12/appcast.xml", self.assets[-1]["digest"])
        args, kwargs = run.call_args
        self.assertIn("https://storage.yandexcloud.net", args[0]); self.assertNotIn("test-secret", repr(args))
        self.assertEqual(kwargs["env"]["AWS_EC2_METADATA_DISABLED"], "true")
        self.assertEqual(kwargs["env"]["AWS_REQUEST_CHECKSUM_CALCULATION"], "when_required")
        self.assertEqual(kwargs["stderr"], mirror.subprocess.PIPE)

    def test_origin_failure_is_not_treated_as_absence(self):
        for code in [403, 500]:
            with self.subTest(code=code), patch.object(mirror, "urlopen", side_effect=HTTPError("url", code, "error", {}, None)):
                with self.assertRaises(HTTPError): mirror.object_digest("releases/x", 1)
        with patch.object(mirror, "urlopen", side_effect=HTTPError("url", 404, "error", {}, None)):
            self.assertIsNone(mirror.object_digest("releases/x", 1))


if __name__ == "__main__": unittest.main()
