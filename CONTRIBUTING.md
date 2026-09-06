# Contributing to neo

Thanks for being here. Neo is a desktop-first launcher with a shared Python backend
and an optional command-line workflow. The GUI uses PySide6; explicit CLI commands
stay standard-library-only. Read the constraints below before you start.

`neo` and this repository were written with substantial AI assistance (see
[README → Acknowledgements](README.md#acknowledgements)). That does not lower the bar:
a change still has to compile, pass `make check`, keep `docs/protocol.md` honest, and
be something the author has actually run. Generated dumps that nobody executed are not
a contribution.

## Contents

| Section | What it covers |
| --- | --- |
| [Ground rules](#ground-rules) | the four constraints that shape every change |
| [Set up a dev environment](#set-up-a-dev-environment) | clone, lint, test — five minutes |
| [Repo layout](#repo-layout) | where things live and why |
| [Making a change](#making-a-change) | commands, code style, adding a subcommand |
| [Testing](#testing) | what runs in CI, what only runs on real hardware |
| [Documentation](#documentation) | which doc owns which kind of fact |
| [Pull requests](#pull-requests) | branches, commits, the checklist |
| [Releasing](#releasing) | version bumps, tags, changelog |
| [Reporting protocol findings](#reporting-protocol-findings) | the most useful thing you can contribute |

## Ground rules

1. **Keep the core stdlib-only.** `neo` remains a single executable Python file.
   Importing it or running an explicit CLI command must not import Qt or require a
   display. The default no-argument invocation hands off to `gui/neo-gui`; the GUI
   imports the shared backend rather than duplicating protocol code.
2. **Support Python ≥ 3.9.** That is the floor CI tests against. No `match`, no
   `X | Y` type syntax at runtime, no `str.removeprefix` on older assumptions.
3. **Never trust the CDN, never trust the manifest.** Anything arriving from the
   network is verified (chunk SHA-1, file SHA-1, prism SHA-256) and contained
   (`install_path` refuses paths that escape the install directory). New fetch or
   extract code must keep that property.
4. **No game assets, no credentials of ours.** Don't add downloaded content, session
   tokens, or anything that has to stay private to the repo — including in tests and
   fixtures.

## Set up a dev environment

```sh
git clone https://github.com/Agentpuggles/Neo-Linux.git
cd Neo-Linux
make dev-gui      # a venv with Ruff and PySide6
source .venv/bin/activate
make check        # lint + offline tests + CLI smoke
make check-gui    # also run the offscreen Qt tests and desktop self-check
```

For CLI/backend-only development, `make dev` installs Ruff without Qt. Explicit
terminal commands need no third-party packages:

```sh
python3 neo --help
```

`make` targets worth knowing: `lint`, `lint-fix`, `format` (tests only), `test`,
`smoke`, `check`, `run-gui`, `test-gui`, `install` (GUI), `install-cli`, `install-all` (both), `appimage`,
`clean`. See [desktop setup](docs/desktop-setup.md) for runtime installation and
packaging, or run `make help` for the full list.

## Repo layout

```
neo                          shared core + CLI; no arguments opens the GUI
gui/neo-gui                  desktop bootstrap
gui/neogui/                  Qt UI, Qt-free backend adapter and desktop integration
packaging/                   distro recipes, installer helpers and desktop metadata
docs/protocol.md             the wire format, validated against production
docs/engineering-notes.md    what broke, why, and how it was diagnosed
CHANGELOG.md                 release history and known issues
tests/                       offline unit tests (stdlib unittest, no network)
  support.py                 imports ./neo and points $HOME-ish paths at a sandbox
  test_protocol.py           manifest numerics, URL derivation
  test_chunks.py             chunk header, download + resume cache
  test_installer.py          build selection, file assembly, path containment
  test_auth.py               OAuth quirks, session store, refresh timing
  test_cli.py                exit codes, help text, config persistence
  test_desktop_entry.py       GUI dispatch, source installs and safe uninstall
  test_cli_tool.py           optional CLI install safety and prompt preference
  test_gui_backend.py         Qt-free service tests
  test_gui_widgets.py         offscreen Qt interaction tests
  test_docs.py               links, anchors, structure, version drift
.github/                     CI, issue and PR templates, dependabot
ruff.toml                    lint config (see the comment about the dense style)
Makefile                     the shortcuts above
```

## Making a change

- **Style.** Ruff enforces everything except line-per-statement density: `neo`
  deliberately uses `if flag: do_thing()` one-liners, so `E701`/`E702` are ignored in
  [`ruff.toml`](ruff.toml). Don't reformat `neo` with `ruff format` — the file is read
  top-to-bottom as a linear script and that density is part of it. `tests/` *is*
  formatted; `make format` covers it.
- **Keep the section banners.** `neo` is organised as `# ---- constants`, `# ---- http`,
  `# ---- auth`, `# ---- manifest`, `# ---- chunks`, `# ---- install`, `# ---- launch`,
  `# ---- login`, `# ---- main`. New code goes in the section it belongs to, not at the
  end of the file.
- **Adding a command** is three edits:

  ```python
  # 1. summary in _COMMANDS, then argparse in make_parser():
  # "repair": ("game", "repair an installed build"),
  s = add("repair"); s.add_argument("version", nargs="?")

  # 2. a handler, in the section that owns the behaviour:
  def cmd_repair(args, auth): ...

  # 3. dispatch, at the bottom of main():
  if args.cmd == "repair": return cmd_repair(args, auth)
  ```

  Then document it in [the CLI reference](docs/cli-reference.md) and add `repair`
  to the subcommand lists in `tests/test_cli.py` (that test is what keeps `--help` honest).
- **User-facing failures** print one line of actionable text and `sys.exit(1)`. No
  tracebacks for network, auth or disk errors — that is the difference between a bug
  report and a support thread.

## Testing

CI runs the offline suite and CLI smoke checks on every push across Python
3.9 → 3.13. The suite is deliberately offline:
`tests/support.py` redirects `NEO_HOME`, `NEO_CACHE` and `XDG_CONFIG_HOME` into a
temporary directory and stubs `neo.http` / `neo.jhttp`, so tests never touch the real
account, cache, or network.

Write new tests against the same fixtures:

| If you changed… | Add a test using |
| --- | --- |
| manifest numeric decoding | `support.blob` / `num_le` and `neo.parse_num` |
| chunk or CDN handling | `support.build_chunk` + a stubbed `neo.http` |
| install/verify logic | `support.manifest_dict` and `neo.assemble_file` |
| auth or token shape | `stub_json_http` in `tests/test_auth.py` |
| CLI surface | `support.run_cli(...)` with the expected exit code |
| Default entry point or packaging | `tests/test_desktop_entry.py`; test both user and staged installs |
| GUI behaviour | `tests/test_gui_widgets.py`, with Qt driven offscreen |

Run it directly when you need the verbose output:

```sh
make test
make test-gui
python3 -m unittest tests.test_chunks -v
```

Some things only exist on real hardware. Before a release, and whenever install,
verify or launch paths change, do the manual pass and paste the result in the PR:

```sh
neo install <version> && neo verify && neo launch --dry-run
```

## Documentation

Each fact has one home; keep it there.

| Document | Owns |
| --- | --- |
| [`README.md`](README.md) | the player-facing GUI quick start and common fixes |
| [`docs/desktop-setup.md`](docs/desktop-setup.md) | desktop installation, virtualenvs, updates and packaging |
| [`docs/cli-reference.md`](docs/cli-reference.md) | all terminal commands, settings, paths and environment variables |
| [`docs/troubleshooting.md`](docs/troubleshooting.md) | detailed startup, account, download and launch fixes |
| [`docs/gui-architecture.md`](docs/gui-architecture.md) | GUI entry points, layers and platform integration |
| [`docs/protocol.md`](docs/protocol.md) | the wire format: endpoints, encodings, chunk layout, launch recipe |
| [`docs/engineering-notes.md`](docs/engineering-notes.md) | diagnoses, dead ends, lessons — the narrative |
| [`CHANGELOG.md`](CHANGELOG.md) | what changed per release, plus current known issues |

If you change how `neo` talks to a service, `docs/protocol.md` changes in the same
PR; the doc names the function it describes (`parse_num`, `parse_chunk`, …) and
`tests/test_protocol.py` pins the doc's own examples, so drift fails CI. `tests/test_docs.py`
additionally checks that every relative link and `#anchor` resolves, that headings and
tables stay well-formed, that any Contents section covers the README headings, and
that the version in the README and CHANGELOG matches `neo --version`.

## Pull requests

- Branch from `main`; one concern per PR.
- Conventional-ish prefixes keep the log readable: `fix:`, `feat:`, `docs:`,
  `tests:`, `ci:`, `chore:`.
- Put `Closes #NNN` in the description when an issue exists.
- Add a `CHANGELOG.md` entry under `## [Unreleased]` — with a subheading of `Added`,
  `Fixed`, `Changed` or `Removed`.
- Fill in the PR template and make sure `make check` and
  [CI](https://github.com/Agentpuggles/Neo-Linux/actions/workflows/ci.yml) are green.
- Anything that changes behaviour on disk (cache layout, `.neo-manifest.json`,
  `state.json`, `auth.json`) needs a migration note in the PR *and* in the changelog:
  people have 60 GB installs that must keep working.

## Reporting protocol findings

The most valuable contribution is not code — it is a verified observation about the
service. Open an issue with:

- the exact request (method, path, headers with the token redacted) and the exact
  response body,
- which official launcher version you compared against, if any,
- whether you reproduced it twice.

Those get folded into `docs/protocol.md` with the pitfall called out, which is how the
case-sensitive `/challenge/Discord` route and the `authorization_code` field name
stopped being other people's problem.

## Releasing

Maintainers only, and deliberately boring:

1. Bump `VERSION` in `neo`, update `README.md` → *Status* ("Current release"), and
   move `## [Unreleased]` in `CHANGELOG.md` to `## [X.Y.Z] — YYYY-MM-DD`.
   `make test` checks all three agree.
2. Add the `[X.Y.Z]: …/compare/vPREV...vX.Y.Z` link definition to `CHANGELOG.md`.
3. `make check`, then the manual install/verify/launch pass.
4. Push a version tag matching `neo`'s `VERSION`. The [AppImage workflow](.github/workflows/appimage.yml)
   builds on Ubuntu 22.04, checks the actual image and Qt widgets, and prepares a
   **draft** release with the AppImage, SHA-256 checksum and build information.
   Ordinary branch pushes/manual runs only upload test artifacts.
5. Review the draft's notes, add the changelog highlights, and complete its manual
   X11/Wayland, Discord callback, game-launch and license/source-availability checks.
   Publish the draft explicitly; the workflow never publishes or overwrites a public
   release. See [AppImage release details](docs/appimage.md#github-actions-and-publishing).
   The single `neo` file alone is CLI-only, not the default desktop distribution.
