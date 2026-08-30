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

## [0.5.4] — 2026-08-30

Launch-day proof pass on the command line itself.

### Added

- The game argument vector is now pinned to the decompiled client: every base
  flag, its order, the literal `-AUTH_LOGIN=unused`, and the fltoken charset
  (a-z0-9, 24 chars) were re-read from `GameLauncher.LaunchAsync` in
  NeoLauncher.dll and matched — a golden test (`TestLaunchArgVector`) fails if
  either side drifts.

### Changed

- `fltoken` now uses `secrets.choice` (cryptographic), matching the official
  client's `RandomNumberGenerator.GetString`; the argv construction moved into
  `game_argv()`/`OFFICIAL_ARGS` so it is unit-testable.

### Verified

- All twelve base arguments are character-for-character identical to the
  official client. The only deviation stays deliberate: `-basedir` unquoted,
  because embedded quotes are re-escaped through the umu/wine boundary
  (docs/protocol.md §8.1, engineering note 11).

## [0.5.3] — 2026-08-30

Live validation round two — the session now completes against production.

### Fixed

- iq replies are correlated by **id** (`id="sess_1"`), not by a literal closing
  tag: the live server answers empty-bodied iqs self-closing
  (`<iq type='result' id='sess_1'/>`), so waiting for `</iq>` timed out after
  the server had already said yes. iq `type="error"` replies now raise with the
  stanza attached. The scripted-server test replies mirror the production form.

### Validated live (from the `-v` trace of a logged-in machine)

- SASL PLAIN with authcid = account id and password = the account access token
  — accepted; there is no separate friends token (matches the IL reading).
- The server accepts the official `neo_launcher_bind_` resource pattern.
- REST fallback payload at an empty roster is a bare `[]`.
- (Follow-up run, same day: full session through the roster iq and the
  own-presence echo — the empty roster is simply a pre-launch service.)

## [0.5.2] — 2026-08-30

First live run feedback (`neo friends -v` on a logged-in machine — thanks,
flynn): the XMPP handshake was refused with `400 Bad Request`, and the REST
fallback parsed to zero friends. Both causes found in the DLL and fixed.

### Fixed

- The websocket upgrade now sends `Sec-WebSocket-Protocol: xmpp` — the official
  client calls `AddSubProtocol("xmpp")` before connecting and the edge rejects
  the handshake without it. This was the `400`.
- Handshake failures now include whatever body the server sent (a plain
  `400 Bad Request` line alone no longer has to be enough).
- REST fallback: official query string `?includePending=true`, escaped account
  id, dict-wrapped payloads, `id`-keyed entries, and `--verbose` dumps the raw
  JSON so the real shape can be confirmed from one run.

## [0.5.1] — 2026-08-30

### Fixed

- `neo friends -v` — the short form of `--verbose` that the release notes
  documented now actually exists (0.5.0 shipped only the long flag).
- SyntaxWarning on Python 3.12+: `to_winpath`'s docstring contained `C:\…`, an
  invalid escape in a non-raw string. It is a raw docstring now, and a new
  source-hygiene test tokenizes `neo` and fails on any invalid escape in any
  non-raw string, on every Python the CI matrix runs.

## [0.5.0] — 2026-08-30

Social: `neo friends` speaks the official client's XMPP-over-websocket protocol
directly — no library, stdlib only.

### Added

- `neo friends [--wait N] [--verbose]` — friends roster with display names and
  live presence. Session per protocol.md §12: RFC 7395 open, SASL PLAIN
  (authcid = account id, password = the account access token — confirmed from
  the IL, there is no separate friends token), bind with the official
  `neo_launcher_bind_` resource, roster iq, presence window, clean unavailable.
  Falls back to `GET /friends/api/public/friends/{id}` when the websocket is
  unreachable (no presence over the fallback). `NEO_XMPP` overrides the endpoint
  (`ws://` accepted — capture proxies welcome); `--verbose` prints every stanza,
  which doubles as the capture tool for correcting the doc against the live
  service.
- A minimal RFC 6455 websocket client (client-masked frames, ping/pong,
  fragmentation, 16/64-bit lengths) as reusable functions plus `WsClient`.
- Name resolution through the batch public-profile endpoint (50 ids per call).
- `docs/protocol.md` §12 promoted from scoping notes to an implementation
  record with the auth confirmed.

### Notes

- Live-service validation pending: the whole exchange is pinned by a
  scripted-server test (`tests/test_friends.py`); the first `neo friends -v`
  against production settles the last unknowns (bind-resource strictness, REST
  payload shapes).

## [0.4.0] — 2026-08-30

The maintenance release: repair instead of reinstall, import instead of re-download,
and the ability to wait out the access gate from the terminal. Nine new capabilities,
all offline-tested (108 tests).

### Added

- `neo verify --repair` — missing/corrupt files are rebuilt by re-fetching only the
  chunks they need (cache-first); the previous advice was a full 62 GB reinstall.
- `neo import <path> <version>` — register a build folder that already exists on
  disk (e.g. downloaded by the Windows launcher); fetches the manifest so `verify`
  has something to check against. Mirrors the official client's `import_neo_build`.
- `neo status --watch [--interval N]` — polls `fortniteAccess` (min 10 s) and fires
  a desktop notification once granted. The official client checks once per start
  and never re-checks (protocol.md gotcha 11) — this closes that gap in the CLI.
- `neo news [--json]` — launcher news from the content service, defensively
  formatted across payload shapes.
- `neo uninstall [version] [--yes]` — deletes the build folder only when it still
  carries neo's `.neo-manifest.json`, then drops the state entry.
- `neo cache [stats|clear] [--all]` — visibility and cleanup for the bulk cache.
- `neo log [-f] [-p PATH]` — locates `FortniteGame.log` under `WINEPREFIX` (or a
  given path), highlights login/entitlement/error lines, `-f` tails live.
- Install-time free-space preflight — cache and target volumes are checked against
  worst-case need before any bytes move (engineering note 9, now a guard, not a
  war story); `--force` overrides.
- `main()` split so the parser is built by `make_parser()` — argument handling is
  now unit-testable directly.

### Fixed

- `neo launch 10.40 -windowed` exits 2 no more: `extra` is now an argparse
  REMAINDER, so flag-shaped UE4 arguments reach the game (options like `--dry-run`
  must come before them; a `--` separator is also accepted). The limitation was
  pinned by a test that now pins the fix instead.

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

- Playing still depends on NeoFN granting the `PLAY` entitlement; `neo launch` boots the
  client and logs it in, but the game stops at the entitlement check
  ([README → Status](README.md#status)).
