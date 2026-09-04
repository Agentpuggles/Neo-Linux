# Contributing to neo

Thanks for being here. This is a small, opinionated tool — one executable file, no
dependencies, no build step — and most of the difficulty is in getting the protocol
details right rather than in the code volume. Read the constraints below before you
start and a review should be quick.

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

1. **One file, stdlib only.** `neo` ships as a single executable Python file with no
   dependencies. If a change needs a third-party package, it needs a very good reason
   and that reason belongs in the PR description.
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
make dev          # optional: a venv with ruff (the only dev tool)
make check        # lint + tests + CLI smoke, exactly what CI runs
```

Nothing has to be installed for the launcher itself:

```sh
python3 neo --help
```

`make` targets worth knowing: `lint`, `lint-fix`, `format` (tests only), `test`,
`smoke`, `check`, `install`, `clean`. Run `make help` for the list.

## Repo layout

```
neo                          the launcher: everything, ~800 lines, stdlib only
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
  # 1. argparse, in main():
  s = sub.add_parser("repair"); s.add_argument("version", nargs="?")

  # 2. a handler, in the section that owns the behaviour:
  def cmd_repair(args, auth): ...

  # 3. dispatch, at the bottom of main():
  if args.cmd == "repair": return cmd_repair(args, auth)
  ```

  Then document it in the README's usage table and add `repair` to the subcommand
  lists in `tests/test_cli.py` (that test is what keeps `--help` honest).
- **User-facing failures** print one line of actionable text and `sys.exit(1)`. No
  tracebacks for network, auth or disk errors — that is the difference between a bug
  report and a support thread.

## Testing

CI runs the suite on every push across Python 3.9 → 3.14. It is deliberately offline:
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

Run it directly when you need the verbose output:

```sh
python3 -m unittest discover -s tests -t . -v
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
| [`README.md`](README.md) | what the tool does, how to use it, how to fix the common failures |
| [`docs/protocol.md`](docs/protocol.md) | the wire format: endpoints, encodings, chunk layout, launch recipe |
| [`docs/engineering-notes.md`](docs/engineering-notes.md) | diagnoses, dead ends, lessons — the narrative |
| [`CHANGELOG.md`](CHANGELOG.md) | what changed per release, plus current known issues |

If you change how `neo` talks to a service, `docs/protocol.md` changes in the same
PR; the doc names the function it describes (`parse_num`, `parse_chunk`, …) and
`tests/test_protocol.py` pins the doc's own examples, so drift fails CI. `tests/test_docs.py`
additionally checks that every relative link and `#anchor` resolves, that headings and
tables stay well-formed, that the Contents table covers every README section, and
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
4. `git tag vX.Y.Z && git push origin vX.Y.Z`, publish a GitHub release with the
   changelog section as the notes, and attach nothing but the `neo` file.
