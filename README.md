# Tolmatch for macOS

Public binary distribution for Tolmatch. Application source code remains in a separate private repository. No application source, licence keys, signing keys or customer data belongs here.

## Downloads

The first [Local Preview v0.1.0-2](https://github.com/AlexMihaa/tolmatch-releases/releases/tag/v0.1.0-2) is published as a prerelease. It is a DEBUG test build requiring the matching local stand, not a customer version. No stable customer installer is published yet.

Each published stable tag uses `v<version>-<build>` (for example `v0.1.0-1`) and includes:

- `Tolmatch-<version>.dmg`
- its SHA-256 checksum file
- `tolmatch-release.json` metadata

The default/production website catalogue reads published stable release assets and SHA-256 digests, with a cache of up to five minutes. Prereleases appear only when explicitly enabled in a local test catalogue. Drafts and assets without a digest remain excluded.

## Integrity and installation

The planned distribution uses ad-hoc signing, without Apple Developer ID or notarization. Compare the downloaded DMG SHA-256 against the published checksum. Only allow this app to open in macOS Privacy & Security after checking its source and hash; do not disable Gatekeeper globally. Hash equality confirms file integrity, not absence of malware.

A VirusTotal report can be looked up at `https://www.virustotal.com/gui/file/<sha256>`. A link does not mean a report exists, the file has been scanned or the file is safe.

## Release checks

The included workflow runs on stable published releases. It verifies public metadata and the exact canonical DMG/hash. A repository secret named `VIRUSTOTAL_API_KEY` optionally enables submission of the already public DMG; without the key, no upload occurs. An accepted submission is pending analysis, not a clean verdict. Never upload private build artifacts.

Before the first stable customer installer, the native ad-hoc Release licence trust policy and production lease public keys must be configured and tested. Local Preview is a separate Debug channel; it does not close production release gates.

## Current Local Preview prerequisites

Requires the matching owner local stand: licence adapter http://127.0.0.1:46805 (Go API46801), website https://localhost:46314. The bundled public verification key matches that stand; other stands require a rebuild with their public key. Preview has separate app identity, licence/provider Keychain services and disabled automatic updates. No server private keys or credentials are bundled. SHA-256 is shown in the release notes and checksum asset. The prerelease was not uploaded to VirusTotal.
