# Tolmatch for macOS

Public binary distribution for Tolmatch. Application source code remains in a separate private repository. No application source, licence keys, signing keys or customer data belongs here.

## Downloads

Stable installers will appear in [Releases](https://github.com/AlexMihaa/tolmatch-releases/releases). There are no public installers yet. Do not treat this repository as evidence that an installer has been published or scanned.

Each published stable tag uses `v<version>-<build>` (for example `v0.1.0-1`) and includes:

- `Tolmatch-<version>.dmg`
- its SHA-256 checksum file
- `tolmatch-release.json` metadata

The website reads published stable release assets and GitHub SHA-256 digests automatically, with a cache of up to five minutes. Drafts, prereleases and assets without a digest are excluded.

## Integrity and installation

The planned distribution uses ad-hoc signing, without Apple Developer ID or notarization. Compare the downloaded DMG SHA-256 against the published checksum. Only allow this app to open in macOS Privacy & Security after checking its source and hash; do not disable Gatekeeper globally. Hash equality confirms file integrity, not absence of malware.

A VirusTotal report can be looked up at `https://www.virustotal.com/gui/file/<sha256>`. A link does not mean a report exists, the file has been scanned or the file is safe.

## Release checks

The included workflow runs on stable published releases. It verifies public metadata and the exact canonical DMG/hash. A repository secret named `VIRUSTOTAL_API_KEY` optionally enables submission of the already public DMG; without the key, no upload occurs. An accepted submission is pending analysis, not a clean verdict. Never upload private build artifacts.

Before the first public installer, the native ad-hoc Release licence trust policy and production lease public keys must be configured and tested. This setup does not publish an installer.
