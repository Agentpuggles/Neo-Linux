# Changelog

All notable changes to `neo` are documented here, newest first. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the version numbers follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html) with `0.x` meaning
"works, but the interfaces may still move".

> No git tags exist yet, so release headings are text rather than links to a diff.
> Once releases are tagged, add a `[X.Y.Z]: …/compare/vPREV...vX.Y.Z` definition per
> entry (see [CONTRIBUTING.md → Releasing](CONTRIBUTING.md#releasing)).

## [Unreleased]

Repository hygiene and a test suite; nothing here changes how the launcher talks to
the services. Validated with `make check` (ruff + 90 offline tests + CLI smoke).

### Added

- Offline unit test suite (`tests/`, stdlib `unittest`, no network, no writes to a
  real `~/.local/share/neo`): manifest numerics, chunk header and CDN round-trip,
  install assembly, auth request shapes, CLI exit codes — plus `tests/test_docs.py`,
  which fails CI on broken links/anchors, a Contents table that misses a section, or a
  version that disagrees between `neo --version`, README and this file.
- CI (`.github/workflows/ci.yml`): `ruff check` over `neo` and `tests/`, a Python
  3.9 → 3.14 test matrix, an executable-bit guard, and a docs job. `make check` runs
  the same three things locally.
- `install_path()` — a manifest-supplied file name can no longer write outside the
  install directory (`../` and absolute paths are rejected at assembly time).
- `CONTRIBUTING.md` (design constraints, how to add a command, what to test, release
  checklist), `SECURITY.md` (private reporting, scope, what the public OAuth client
  credentials are and are not), `CODE_OF_CONDUCT.md`, issue forms for bugs and feature
  requests, a pull-request template, and `.github/dependabot.yml` for the actions.
- `Makefile` (`help`, `check`, `lint`, `format`, `test`, `smoke`, `dev`, `install`),
  `ruff.toml`, `.editorconfig`, `.gitattributes`.
- README header artwork and a repository social-preview image (`docs/assets/`).

### Changed

- `neo`: `to_winpath()` and `changelist_number()` are module-level functions instead of
  nested closures — they carry real bug-fix logic (see below) and are now unit-tested.
  Behaviour is unchanged.
- `neo`: `datetime`/`re` imported once at module level instead of inline, and every
  config/session/manifest read goes through a context manager so file handles are not
  left open across a 411-file install.
- `docs/protocol.md` §5.1: corrected the `"00000000063"` row — 11 digits is *not* a
  multiple of 3, so `parse_num` reads it as a plain int rather than a 3-byte blob.
  Verified against the implementation and pinned by `tests/test_protocol.py`.
- README restructured with badges, a banner, and `Acknowledgements` / `Contributing`
  sections; the technical content is the same.
- README Acknowledgements (and matching notes in `neo`, `CONTRIBUTING.md`, and
  `docs/engineering-notes.md`) now record that `neo` and this repository were written
  with substantial AI assistance under human direction.

### Fixed

- The `0.2.0` changelog entry linked a `v0.1.0...v0.2.0` compare diff that never
  existed (no tags in this repository).

## [0.3.0] — 2026-08-30

Diagnostics for the access gates. `neo status` now shows store entitlements,
and the protocol doc gains a section on how the official launcher updates
itself and decides who may play — read out of the decompiled NeoLauncher 1.0.7
binary and its bundled web app, not guessed.

### Added

- `neo status`: "Entitlements" line — `GET store.neofn.dev/api/v1/entitlements/{id}`
  summarised as offer ids, paid/refunded orders and subscriptions, so an
  early-access purchase can be watched registering on the account. Best-effort:
  failures warn and never abort the rest of the status output.
- `docs/protocol.md` §11 "Launcher self-update and access gating": the Velopack
  feed (`/api/public/releases`, client-credentials bearer) and the 30-minute
  check-apply-restart cycle; the three playability gates (the per-account
  `fortniteAccess` flag, the `["10.40"]` build allowlist baked into both the
  DLL and the web bundle, and the in-game `PLAY` entitlement); the store
  entitlements endpoint; a map of the WebView2 bridge. Established negative:
  no launch-date or countdown logic exists anywhere in the client. Store and
  analytics services added to the §1 table.

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
  `--proton` are unaffected. Pinned by `tests/test_cli.py::TestKnownLimitations` so the
  changelog cannot quietly drift away from the code.
- Playing still depends on NeoFN granting the `PLAY` entitlement; `neo launch` boots the
  client and logs it in, but the game stops at the entitlement check
  ([README → Status](README.md#status)).
