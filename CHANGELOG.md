# Changelog

All notable changes to neo are documented here.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## [0.2.0] — 2026-08-29

First public/repository release. Everything below validated live against production
and on target hardware (CachyOS, umu-launcher 1.4.3, Proton-CachyOS 11.0).

### Added

- `neo setup [name]` — first-run display name (status / availability check / set).
- `neo config [key] [value]` — persistent settings: `install_root`, `cache_dir`, `workers`.
- Relocatable bulk cache (`NEO_CACHE` env / `cache_dir` config) — chunk cache no longer
  has to live on the same filesystem as `$HOME` (a full 62 GB install's cache can be
  pointed at a big disk; small root partitions no longer fill up mid-install).
- Graceful Ctrl-C during installs: instant exit with a "re-run to resume" hint
  (all chunk writes are atomic tmp+rename, so interruption is always safe).
- Friendly rejection of placeholder/truncated OAuth callback codes with instructions.
- Desktop notification on login success/failure (the scheme handler runs headless).
- `neo status`: play-access (`fortniteAccess`) and `allowedActions` visibility.
- Exchange-code lifetime printed at launch (they expire; game must redeem in time).
- Full wire-protocol documentation ([`docs/protocol.md`](docs/protocol.md)) and
  engineering notes ([`docs/engineering-notes.md`](docs/engineering-notes.md)).

### Fixed

- **Login: challenge route is case-sensitive.** `/api/oauth/challenge/Discord` (capital D)
  is required; lowercase returns HTTP 500 `numericErrorCode 1012`, which looks like a
  server outage instead of a bad route.
- **Login: token exchange field name.** NeoFN expects the OAuth code in a form field
  literally named `authorization_code`, not the standard `code`. Wrong field →
  `400 common.oauth.invalid_request` (the error message names the field it wanted).
- **Launch: `-basedir` mangling through Wine.** Embedded quotes in the argument are
  escaped when umu/Wine rebuilds the Windows command line, leaving UE4's parser a
  stray backslash → *"Failed to open descriptor file"* → instant exit. Also fixed a
  doubled backslash after the `Z:` drive letter. basedir is now passed bare, and
  paths inside the prefix's `drive_c` map to `C:\…` automatically.
- **Chunk header parsing**: storedAs/SHA-1 were read at byte offsets 32/33 instead of
  40/41 — every downloaded chunk "failed" SHA verification, and the retry logic masked
  it as an HTTP 404 from the CDN.
- Prism asset handling now mirrors the Windows launcher exactly: the patched exe is
  mandatory (fatal on failure), all other assets are best-effort.

## 0.1.0 — 2026-08-28

Internal first cut; never released, so no tag or diff exists for it.

- Discord OAuth login (`neolauncher://` xdg handler + `--code`/`--callback` fallbacks),
  session persistence + refresh, kill-other-sessions on fresh login.
- `status` / `list` / `whoami` / `logout`.
- Epic BuildPatchServices JSON manifest parsing (fixed-width decimal "blob" numerics,
  little-endian u64 hash decode, plain-int vs blob field discrimination).
- Chunk engine: `ChunksV3/<group:02>/<rollingHash:016X>_<GUID>.chunk` URL derivation,
  v2 header parse, zlib inflate, per-chunk and per-file SHA-1 verification.
- Parallel resumable installer (16 workers default), disk chunk cache with reuse,
  cache purge on success (`--keep-cache` to retain), `.neo-manifest.json` persistence.
- `verify` — full re-hash of installed files.
- `launch` — ban gates, sha256-verified prism assets, two exchange codes, exact
  Windows-launcher command line via umu-run.

## Known issues

- `neo launch` cannot pass extra UE4 command-line arguments. The `extra` positional
  exists, but argparse rejects flag-shaped tokens after the subcommand, so
  `neo launch 10.40 -windowed` exits 2 with `unrecognized arguments`. `--dry-run` and
  `--proton` are unaffected.

[0.2.0]: https://github.com/Agentpuggles/Neo-Linux/compare/v0.1.0...v0.2.0
