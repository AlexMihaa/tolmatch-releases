# Tolmatch for macOS

Public binary distribution for Tolmatch. Application source code remains in a separate private repository. No application source, licence keys, signing keys or customer data belongs here.

## Downloads

The first [Local Preview v0.1.0-2](https://github.com/AlexMihaa/tolmatch-releases/releases/tag/v0.1.0-2) is published as a prerelease. It is a DEBUG test build requiring the matching local stand, not a customer version. Stable customer releases are now published alongside this historical preview.

Each published stable tag uses `v<version>-<build>` (for example `v0.1.0-1`) and includes:

- `Tolmatch-<version>.dmg`
- its SHA-256 checksum file
- `tolmatch-release.json` metadata
- signed `appcast.xml` update feed

The default/production website catalogue reads published stable release assets and SHA-256 digests, with a cache of up to five minutes. Prereleases appear only when explicitly enabled in a local test catalogue. Drafts and assets without a digest remain excluded.

## Integrity and installation

Current stable packages use the persistent self-signed Tolmatch identity and signed Sparkle updates, without Apple Developer ID or notarization. Compare the downloaded DMG SHA-256 against the published checksum. Only allow this app to open in macOS Privacy & Security after checking its source and hash; do not disable Gatekeeper globally. Hash equality confirms file integrity, not absence of malware.

A VirusTotal report can be looked up at `https://www.virustotal.com/gui/file/<sha256>`. A link does not mean a report exists, the file has been scanned or the file is safe.

## Release checks

The included workflow runs on stable published releases. It verifies public metadata and the exact canonical DMG/hash. A repository secret named `VIRUSTOTAL_API_KEY` optionally enables submission of the already public DMG; without the key, no upload occurs. An accepted submission is pending analysis, not a clean verdict. Never upload private build artifacts.

Before the first stable customer installer, the native ad-hoc Release licence trust policy and production lease public keys must be configured and tested. Local Preview is a separate Debug channel; it does not close production release gates.

## Current Local Preview prerequisites

Requires the matching owner local stand: licence adapter http://127.0.0.1:46805 (Go API46801), website https://localhost:46314. The bundled public verification key matches that stand; other stands require a rebuild with their public key. Preview has separate app identity, licence/provider Keychain services and disabled automatic updates. No server private keys or credentials are bundled. SHA-256 is shown in the release notes and checksum asset. The prerelease was not uploaded to VirusTotal.

## Automatic Timeweb mirror

Publishing a stable release automatically runs `.github/workflows/release-mirror.yml`. It validates all four canonical assets against the public GitHub size/SHA-256, checks package metadata and checksum consistency, then uploads them through the S3 API to `tolmatch-public/releases/<tag>/`. Every uploaded file is downloaded anonymously from the Timeweb S3 origin and verified again. `mirror.json` is written last as a versioned readiness marker. Drafts, prereleases, missing hashes, mismatched package metadata and different pre-existing versioned bytes stop the run. Retrying the same tag with identical bytes is supported.

No installer rebuild or manual cloud upload is needed after publication. The signed appcast is copied byte-for-byte; existing Sparkle feed and archive URLs are unchanged. The mirror does not publish releases or install applications.

Repository Actions Secrets `TIMEWEB_RELEASES_ACCESS_KEY_ID` and `TIMEWEB_RELEASES_SECRET_ACCESS_KEY` belong to a dedicated S3 user. Its custom policy permits object reads/writes only under `releases/*` and bucket listing only for that prefix, needed to distinguish missing keys from Timeweb anonymous HTTP403 responses. It has no delete rights, media writes or bucket administration. Public reads remain anonymous. The endpoint is `https://s3.twcstorage.ru`, region `ru-1`; readiness markers use `Cache-Control: no-store,max-age=0`. Never put credentials in this repository, release assets or logs.

For recovery or verification, run **Mirror stable release to Timeweb** using `workflow_dispatch` with an already published stable tag, for example `v0.1.9-12`. Publication must happen through a user/PAT or GitHub App token that generates release events; events created using this repository's `GITHUB_TOKEN` do not launch another workflow, so such a publisher must explicitly dispatch the mirror. A failed mirror leaves GitHub available; consumers must only use mirrored releases with a verified readiness marker.

The public delivery domain is `https://cdn.tolmatch.app`. Timeweb cutover accepted2026-11-11: existing release URLs retain the exact signed bytes; trusted TLS and the real website/Sparkle download were verified. [Successful Timeweb mirror run](https://github.com/AlexMihaa/tolmatch-releases/actions/runs/42993458639). Provider cutover is performed separately from workflow preparation. Existing signed feed and archive URLs remain unchanged; switch DNS only after the new origin and permissions pass verification.
