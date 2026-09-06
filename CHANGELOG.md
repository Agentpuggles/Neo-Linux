# Changelog

All notable changes to `neo` are documented here, newest first. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the version numbers follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html) with `0.x` meaning
"works, but the interfaces may still move".

> No git tags exist yet, so release headings are text rather than links to a diff.
> Once releases are tagged, add a `[X.Y.Z]: …/compare/vPREV...vX.Y.Z` definition per
> entry (see [CONTRIBUTING.md → Releasing](CONTRIBUTING.md#releasing)).

## [Unreleased]

### Packaging

- Added versioned x86-64 AppImage builds with an isolated, hash-pinned Python/Qt
  toolchain, reviewed appimagetool/runtime hashes, bundled license notices,
  checksums and recorded build information. The frozen backend's otherwise-hidden
  imports are now explicitly collected.
- Added Ubuntu 22.04 AppImage CI: test the actual relocated bundle without FUSE,
  run offline and Qt widget regressions, and retain downloadable test artifacts.
  Matching version tags prepare draft releases only; publishing requires review.
- AppImage desktop entries and Discord callbacks now use the durable image path,
  correctly quoting spaces/percent signs. GUI sign-in registers the GUI rather
  than trying to run the private backend through a frozen interpreter.
- Restore the host's library/plugin search environment when launching umu/Proton,
  browsers and desktop utilities. The AppImage never injects its bin folder into
  the host PATH. Self-checks block network access and leave live-instance sockets
  alone; the optional CLI remains genuinely optional inside the bundle.

Repository hygiene and a test suite, a self-diagnosing launch failure, and **Neo**, a
native desktop app for the launcher. Validated with `make check` (ruff + the offline
suite + CLI smoke) and `make check-gui` (the Qt tests + the desktop self-check).

### Added

- **Neo, a native Linux desktop app** (`neo-gui`, `gui/`). A real Qt Widgets
  application, not a rewrite: `neo` is imported as a module, so the GUI and the CLI
  share one implementation of auth, manifests, chunk downloads, verification and the
  launch recipe — and one `config.json`, so changing your install root or Proton build
  in either changes it in both. **Explicit CLI commands stay stdlib-only**;
  PySide6 is required for the default desktop experience, while commands such as
  `neo --help` still run on bare Python 3.9.

  Six pages — Play, Library, Friends, Diagnostics, Settings, Account — with real
  loading, empty and error states, dark/light themes that follow the desktop, HiDPI,
  keyboard navigation and accessible names. Desktop integration makes no
  DE-specific assumptions: freedesktop `.desktop` entry, scalable icon, AppStream
  metainfo, `StartupWMClass` for dock matching, notifications, tray, single instance
  and `neolauncher://` sign-in handover. Verified on KDE/Wayland; the same build is
  intended to run on GNOME, XFCE, Cinnamon, Hyprland, Sway and COSMIC under Wayland
  and X11.

  Security matches the CLI's posture: the GUI never writes tokens (the CLI's `0600`
  `auth.json` stays the only store), nothing is executed through a shell (launch
  arguments are `shlex`-parsed into an argv), and every log pane, exported log,
  diagnostics report and command preview is redacted first.

  Install with `make install`; run from a checkout with `./neo` or `make run-gui`.
  Packaging lives in `packaging/` (AUR `PKGBUILD`, Flatpak manifest, AppImage build
  script, freedesktop files). **No on-disk format changed** — no migration needed.

- **119 new offline tests for the desktop app.** `tests/test_gui_backend.py` (55) imports
  no Qt at all; `tests/test_gui_widgets.py` (64) drives real widgets under the
  `offscreen` platform, so both run in CI with no display server. `neo-gui
  --self-check` opens every page in both themes and is wired to `make smoke-gui`.

- **Game modifiers from the official Options panel.** Discord users were right:
  NeoLauncher 1.0.7's per-build Options → Modifiers sheet (Edit On Release, Instant
  Reset, Disable Pre-Edit) was never a UE4 flag — `EncodeGameModifiers` in
  `NeoLauncher.dll` emits `-NeoModifiers={"editOnRelease":true,…}` and the patched
  client reads that. `neo launch --edit-on-release` (also `--instant-reset`,
  `--disable-pre-edit`, and `--no-…` to override) and `neo config edit_on_release on`
  now send the same compact JSON. Bubble Builds & Performance stays locked, matching
  the 1.0.7 UI. The all-false form is omitted so the default argv stays the
  live-validated 12-flag vector. The Options → Launch text field is `neo config
  launch_options "-windowed -log"`. Documented in protocol.md §8.2.

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
- `neo help` — `help` is now a real command, not an argparse "invalid choice": `neo help`
  prints the full help (same as `neo --help`), `neo help <cmd>` prints one command's
  help, and `neo <cmd> help` is accepted alongside `neo <cmd> -h` / `--help` for every
  command (previously `neo install help` treated "help" as a build version to install).
- `CONTRIBUTING.md` (design constraints, how to add a command, what to test, release
  checklist), `SECURITY.md` (private reporting, scope, what the public OAuth client
  credentials are and are not), `CODE_OF_CONDUCT.md`, issue forms for bugs and feature
  requests, a pull-request template, and `.github/dependabot.yml` for the actions.
- `Makefile` (`help`, `check`, `lint`, `format`, `test`, `smoke`, `dev`, `install`),
  `ruff.toml`, `.editorconfig`, `.gitattributes`.
- README header artwork and a repository social-preview image (`docs/assets/`).

### Fixed

- **AppImage builds failed desktop-entry validation on Ubuntu 22.04.** Removed
  the newer `SingleMainWindow` hint from packaged and generated desktop entries;
  the app's existing single-instance handler is unchanged. Native validation stays
  enabled. CI failure annotations now retain the final exception within GitHub's
  length limit instead of truncating it behind build progress output.

- **The desktop app ignored every mouse click.** `ToastHost` is stretched over the whole
  window so notifications can be positioned freely, and it accepted mouse events, so it
  won hit-testing everywhere and each click landed on the overlay instead of the button
  beneath it. Keyboard input routes by focus and was unaffected, which is why Tab and
  Space worked while the mouse did nothing. The overlay now carries a mask covering only
  the rectangles the toasts occupy. Found on real hardware (CachyOS/Wayland).

- **Enter did not activate a focused button** outside dialogs. `QPushButton` only enables
  `autoDefault` inside a `QDialog`, so Return/Enter was inert in the main window while
  Space worked — correct Qt behaviour, wrong for accessibility. Dialogs keep their
  deliberate defaults, so a destructive button still never becomes the Enter action.

- Background jobs could drop their results: Qt deleted the runnable, and its signal
  object, before the queued completion signals reached the UI thread.

- The GUI's log redactor missed flag-style secrets (`-AUTH_PASSWORD=`, `-fltoken=`,
  `-p=`) because the pattern relied on a word boundary, which never matches before a
  `-`. Live exchange codes could have reached a saved log or an exported diagnostics
  report.

- `make run-gui`, `make test-gui` and `make smoke-gui` ran the system interpreter, so
  they failed with `ModuleNotFoundError` even after `make dev-gui` installed PySide6
  into `.venv`. They now prefer `.venv/bin/python` and fall back to a distro-packaged
  PySide6, with a clear message instead of a traceback. The CLI targets are unchanged.

### Changed

- **The GUI now offers an optional CLI installation.** The first normal launch
  offers **Install CLI (recommended)** or **Not now**, explaining that the CLI is
  highly recommended for troubleshooting and doing tasks manually, but can be
  installed later from **Settings → Command-line tool**. Declines are remembered;
  existing CLI installations, sign-in callbacks and self-checks are not prompted.
  Installation copies the bundled core into `~/.local/bin/neo` without downloads,
  sudo, shell-profile edits or overwriting existing commands. Settings includes
  PATH guidance; installation failures leave the GUI usable and can be retried.
- **GUI installs keep the shared backend private.** `make install` / `install-gui`
  place it in `share/neo/neo`, so declining the CLI does not remove any app
  functionality. Existing CLI commands are left untouched; `make install-all`
  explicitly includes both interfaces. No game data or session migration is needed.

- **The GUI is now the default way to use Neo.** Running `neo` without arguments
  opens the desktop app; `neo --help` and all explicit commands remain Qt-free.
  Checkout launches find the local virtualenv, installed launches use the matching
  `neo-gui`, and headless/missing-GUI failures point to setup or terminal usage.
- **`make install` now installs the desktop app**, menu entry and icon, offering
  the CLI from the GUI. `make install-cli` retains the lightweight installation;
  `install-gui` / `install-all` remain available for GUI-only / both interfaces. User installs retain the
  selected GUI interpreter, and desktop/backend lookup no longer depends on
  `~/.local/bin` being on PATH. The Arch recipe now requires PySide6.
- **Uninstall removes app files, not user data.** `make uninstall` and
  `make uninstall-all` preserve sessions, state, cache and settings even when they
  share the default `~/.local/share/neo` directory with the GUI package. No data
  format changes or migration are needed.
- **A shorter, player-first README** leads with desktop setup, Discord sign-in,
  install and Play. Full terminal usage, configuration and troubleshooting now
  live in linked guides under `docs/`. Offline entry-point/install tests cover
  Qt-free CLI usage, menu paths, virtualenvs, callbacks and safe removal; CI runs
  the offline suite in addition to its existing smoke checks.

- **Help got a real directory.** `neo help` / `--help` now prints the command list
  grouped under `account` / `game` / `system` with a one-line summary per command
  (a compact `usage: neo [command] [options]` replaces the stock argparse usage line,
  whose `{login,whoami,…}` choice list wrapped on every terminal). Every subcommand
  got its own summary plus helps and metavars on its positionals, so
  `neo install --help` reads `[VER]  build to install …` instead of a bare
  `[version]`. One `_COMMANDS` table drives it all, so `neo help`, `neo <cmd> --help`
  stay in sync; detailed usage lives in docs/cli-reference.md.
- `neo`: `to_winpath()` and `changelist_number()` are module-level functions instead of
  nested closures — they carry real bug-fix logic (see below) and are now unit-tested.
  Behaviour is unchanged.
- `neo`: `datetime`/`re` imported once at module level instead of inline, and every
  config/session/manifest read goes through a context manager so file handles are not
  left open across a 411-file install.
- `neo launch` now watches the game's stderr for Wine's
  `to unimplemented function <module>.<fn>, aborting` signature and, when it kills a
  launch, prints the fix instead of a bare `game exited: 1`. The diagnosis is
  documented in docs/engineering-notes §14 (which records that an earlier
  "recreate the prefix" explanation was wrong — a fresh prefix reproduces the abort,
  so the offending Proton build is the cause and the fix is switching Proton).
- **Proton selection now works and is configurable.** umu picks the Proton from the
  `PROTONPATH` env var, but `neo launch --proton <p>` had been appending a `--proton`
  flag to the umu-run command line that umu does not define (umu would misread it as
  the game executable). `neo launch` now applies `--proton <p>` by setting
  `PROTONPATH` for the child, and a persistent default is available via
  `neo config proton <name-or-path>` (e.g. `GE-Proton`); resolution order is
  `--proton` > config `proton` > exported `PROTONPATH` > umu's default. `--dry-run`
  prints the resolved `PROTONPATH`.
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

## [0.5.6] — 2026-09-05

**NeoFN launched, and `neo` played it on Linux** — install → launch → real
matches, through umu-run/Proton, from both the CLI and the desktop app. The
service changed two things on the way out of private testing, and this release
reads both of them correctly instead of reporting them as failures.

### Fixed

- **`fortniteAccess` 404 is an open gate, not an error.** With play no longer
  gated per account, `GET …/account/{id}/fortniteAccess` answers `404` for
  ungated accounts, and `neo status` printed
  `⚠ fortniteAccess: … -> HTTP 404` beside an account that plays fine. The gate
  is now tri-state — `granted` / `not granted` / `open` — and only an explicit
  `false` counts as a denial. Anything else (401, 5xx, unreachable) stays
  `unknown` and is still reported. `neo status --watch` exits immediately on an
  open gate rather than polling a route that no longer exists.
- **The desktop app no longer grays out Play on a retired gate.** `ServiceStatus`
  carries the gate state (`access_gate`, with `access_ok` / `access_denied` /
  `access_label`), so the Play hero, the nav-rail chip, Diagnostics and Account
  all read "open" as playable. Previously a 404 fell into "Unknown", which
  showed as *No game access*.
- **"Entitlements: none on file" now says what it means.** Entitlements record
  store purchases, never playtime, so an empty payload on a played account is
  correct — `neo status` says so in a follow-up line instead of leaving it
  looking like a lost purchase. The summary also handles the two other payload
  shapes seen in the wild (a bare array, and a `data`-wrapped object), and an
  unrecognised *non-empty* payload now reports its keys rather than claiming the
  account owns nothing.
- **Players online is legible.** `Players online : {'fortnite': 240, 'launcher':
  402}` (a raw Python dict) is now
  `Players online : fortnite 240 · launcher 402 (total 642)`; the GUI's single
  number prefers the game's count over the launcher's instead of whichever key
  came first.
- `neo status` prints `allowedActions` as a comma-separated list rather than a
  Python list literal.

### Added

- `neo status --json` — the raw lightswitch, prism, gate, entitlement and
  online-count payloads after the summary, for when the summary is not what you
  want to argue with.
- `HttpError` (a `RuntimeError` subclass carrying `.status`, `.url`, `.method`,
  `.body`) is raised by `jhttp`, with `http_status(exc)` to read a status back
  out of any exception. The message text is unchanged, so nothing that only
  prints an error notices. This is what lets 404 be distinguished from "the
  service is broken" instead of matching on message strings.
- Tests for all of the above: the tri-state gate, the 404-is-open rule, the
  entitlement shapes, the online-count line, `--json`, `--watch` on an open
  gate, and the GUI's status mapping (16 new).
- `docs/protocol.md` §2.5/§11.2/§11.3 record the post-launch behaviour, with
  gotchas 14 and 15 in the at-a-glance table.

## [0.5.5] — 2026-08-30

### Fixed

- `neo log`'s highlighter no longer lights up every `Display:` line — the
  pattern matched `PLAY` case-insensitively inside "Display"; it is now
  `\bPLAY\b` (the same trap this session's grep hit twice). A regression test
  pins a `Display:` line as unhighlighted.

### Added

- `docs/protocol.md` §9.1 "Launch-day tripwire": the exact log lines that
  change when the `PLAY` entitlement is granted, captured from a live
  pre-launch boot (login OK → platform OK → 403 ×2 → `AbortLoggingIn` →
  `SignIn_Credentials`), including the 3-second entitlement re-check.

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
- Live hardware pass (umu 1.4.3 / Proton-CachyOS): `/proc` cmdline of the
  running game shows the full vector delivered intact; client boots, auto-logins
  and exits cleanly at the entitlement wall while access is false.

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

- Nothing blocking. NeoFN launched on 2026-09-05 and matches have been played on
  Linux through `neo` end to end ([README → Status](README.md#status)); the
  `PLAY` entitlement wall that gated every earlier release is gone.
- Running the desktop app from a checkout (`make run-gui`) logs
  `Failed to register with host portal … App info not found for
  'dev.neofn.NeoLauncher'`. It is xdg-desktop-portal noticing there is no
  installed desktop entry for the app id; it affects nothing. Install the entry
  (`neo-gui --install-desktop-entry`, or `make install-all`) to silence it.
