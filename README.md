# neo

**A native Linux launcher for [NeoFN](https://neofn.dev)** — Discord login, chunked
build downloads with hash verification, patched-client management and game launch,
in one stdlib-only Python file.

The game itself runs through [umu-run](https://github.com/Open-Wine-Components/umu-launcher)
/ Proton. The launcher needs no Wine.

```
login → pick build → manifest → parallel chunk download → zlib + SHA-1 verify
      → assemble → per-file verify → prism-patched exe + 2 exchange codes → umu-run
```

> **Unofficial, interoperability-focused tool.** Not affiliated with or endorsed by
> NeoFN or Epic Games. It talks only to NeoFN's own public services using the
> credentials of their official launcher (extracted for compatibility, the same
> approach as [legendary](https://github.com/derrod/legendary)). No game assets are
> included or redistributed. Use at your own risk.

## Contents

| | |
|---|---|
| [Status](#status) | what works, what is still gated |
| [Requirements](#requirements) | Python, umu-run, Wine prefix |
| [Install](#install) | clone + one `install` command |
| [Quick start](#quick-start) | the six `neo` commands, first run to playing |
| [Usage](#usage) | every command, flag by flag |
| [Configuration](#configuration) | paths, settings, environment |
| [How it works](#how-it-works) | the pipeline, and where the protocol is documented |
| [Troubleshooting](#troubleshooting) | symptoms and fixes |
| [Docs](#docs) | protocol reference, engineering notes, changelog |
| [License](#license) | MIT |

## Status

Current release: **v0.2.0**.

| Feature | State |
| --- | --- |
| Discord OAuth login (`neolauncher://` handler + manual fallback) | ✅ |
| Session refresh, display-name setup, ban / access status | ✅ |
| Build catalog + Epic BuildPatchServices manifest parsing | ✅ |
| Parallel chunk downloader (16+ workers, resumable, SHA-1 per chunk **and** per file) | ✅ 411 files / 62,032 chunks / 61.9 GiB on 10.40 |
| Install / verify / reinstall with a relocatable cache | ✅ |
| Prism asset management (sha256-verified, auto-updated) | ✅ |
| Launch via umu-run (exact Windows-launcher command line) | ✅ boots, auto-logs in |
| Playing | ⏳ waits on NeoFN granting the `PLAY` entitlement (pre-launch as of v0.2.0) |

## Requirements

| | |
| --- | --- |
| **Python** | ≥ 3.9, stdlib only — nothing to `pip install` |
| **umu-run** | [`Open-Wine-Components/umu-launcher`](https://github.com/Open-Wine-Components/umu-launcher) plus any modern Proton |
| **Wine prefix** | created on first run if you don't set `WINEPREFIX` — but do set it, see below |

## Install

```sh
git clone https://github.com/Agentpuggles/Neo-Linux.git
install -Dm755 Neo-Linux/neo ~/.local/bin/neo
neo --version
```

`neo` is a single executable file; `install` is all the setup it needs.

## Quick start

```sh
neo login                             # 1. Discord in your browser; callback is automatic
neo setup YourName                    # 2. pick a display name (first run only)
neo status                            # 3. service, bans, play access, players online

neo install                           # 4. the live build (tens of GB)
neo verify                            # 5. re-hash everything against the manifest

export WINEPREFIX=~/prefixes/neofn    # 6. give the game its own prefix
neo launch
```

Interrupted installs resume — re-run the same command and cached chunks are reused.

## Usage

```
neo <command> [options]

  account   login · whoami · setup · logout · status
  game      list · install · verify · launch
  settings  config                     (see Configuration)
```

Run `neo <command> --help` for a command's own options.

### Account

| Command | What it does |
| --- | --- |
| `neo login` | Opens the Discord OAuth challenge in your browser and registers the `neolauncher://` handler, so the callback is handled automatically. Fallbacks: `neo login --callback '<url>'` with the full callback URL, or `neo login --code <CODE>`. |
| `neo whoami` | Display name, account id and email for the current session. |
| `neo setup [name]` | With no name: shows first-run setup status. With a name: checks availability, then sets the display name. |
| `neo logout` | Drops the stored session (`auth.json` is emptied, not deleted). |
| `neo status` | Lightswitch service status, ban status (both services), `fortniteAccess`, players online. |

### Game

| Command | What it does |
| --- | --- |
| `neo list` | Every build in the catalog with size, release date and the `[LIVE]` marker. |
| `neo install [version]` | Downloads and assembles a build. `version` is a substring such as `10.40`, or `live` (the default). Options: `-d DIR`, `-j WORKERS`, `--keep-cache`. |
| `neo verify [version]` | Re-hashes every installed file against the stored manifest; reports missing and corrupted files. |
| `neo launch [version]` | Checks the gates (lightswitch, bans), refreshes prism assets, mints two exchange codes and runs the game through umu-run. Options: `--dry-run` (print the command line and stop), `--proton PROTON`. |

`version` defaults to the newest installed build (highest `CL-` number) for `verify`
and `launch`.

## Configuration

### The `config` command

| Command | What it does |
| --- | --- |
| `neo config` | Print every setting and the config file path. |
| `neo config <key>` | Print one setting. |
| `neo config <key> <value>` | Set a setting. Keys: `install_root`, `cache_dir`, `workers`. |

### Files

| Path | Contents |
| --- | --- |
| `~/.local/share/neo/auth.json` | Session tokens (mode `0600`) |
| `~/.local/share/neo/state.json` | Installed builds → paths |
| `~/.local/share/neo/prism/` | Prism-patched client binaries, sha256-checked on every launch |
| `~/.local/share/neo/cache/` | Chunk and manifest cache |
| `~/.config/neo/config.json` | Settings |

### Settings

| Key | Default | Also settable via |
| --- | --- | --- |
| `install_root` | `~/Games/Neo` | `neo install -d DIR` |
| `cache_dir` | `~/.local/share/neo/cache` | `NEO_CACHE` |
| `workers` | `16` | `neo install -j N` |

### Environment

| Variable | Meaning |
| --- | --- |
| `NEO_HOME` | Override the data directory |
| `NEO_CACHE` | Override the cache directory |
| `NEO_UMU` | umu-run command to invoke (default `umu-run`) |
| `WINEPREFIX` | Game prefix, honoured by umu-run — **set it**, otherwise umu uses `~/.wine` |

### Disk usage

Peak during an install ≈ compressed build size (cache) + full build size (install
directory). The cache is purged on success unless you pass `--keep-cache`, which
keeps it for offline repair at the cost of roughly one build's worth of disk.

## How it works

```
 1. login        Discord OAuth → neolauncher:// callback → access + refresh token
 2. catalog      /launcher/api/public/builds → pick the live build
 3. manifest     <dist>/<manifestPath> → Epic JSON manifest (~20 MB)
 4. download     chunk GUIDs → N workers → Cloudflare R2, retries + backoff
 5. verify       per chunk: header SHA-1 vs ChunkShaList; per file: SHA-1 vs FileHash
 6. assemble     concatenate chunk slices, apply +x and symlinks, atomic rename
 7. patch        prism assets → patched FortniteClient-Win64-Shipping.exe
 8. launch       two exchange codes → umu-run → Proton → DX11
```

Every endpoint, the OAuth quirks (case-sensitive provider route, nonstandard
`authorization_code` field), the manifest's fixed-width decimal numerics, the chunk
URL scheme and on-disk format, the prism assets and the exact launch command line —
with the pitfalls of running it through Wine — are written up in the docs below.

## Docs

| Document | What's in it |
| --- | --- |
| [docs/protocol.md](docs/protocol.md) | The wire protocol: endpoints, auth quirks, manifest format, chunk URLs and file layout, prism, the launch recipe. Validated live against production. |
| [docs/engineering-notes.md](docs/engineering-notes.md) | Every significant bug and dead end from building this, with the diagnosis that resolved it — including the ones that were our own fault. |
| [CHANGELOG.md](CHANGELOG.md) | Release history and known issues. |

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| Login callback didn't fire | Copy the whole `neolauncher://callback/auth?code=…` URL from the address bar and pass it to `neo login --callback '<url>'`. Codes are single-use and expire quickly — when in doubt, `neo login` again. |
| CDN returns 403 | R2 rejects some default user agents; `neo` sends its own. If you're behind a proxy or VPN, try without it. |
| Chunk downloads fail with 404 | The CDN edge transiently 404s objects that exist; `neo` retries with backoff. A hard failure names the chunk GUID. |
| Game shows an email / password screen | The login itself usually succeeded — check `neo status` for play access. Log: `<prefix>/drive_c/users/<user>/AppData/Local/FortniteGame/Saved/Logs/FortniteGame.log`. |
| `Failed to open descriptor file` | A `-basedir` quoting problem. `neo` already passes it bare; don't add quotes yourself. |
| Extra UE4 command-line arguments | The `extra` positional exists but argparse rejects flag-shaped arguments after the subcommand, so extras don't reach the game yet. `--dry-run` and `--proton` work. |

## License

MIT — see [LICENSE](LICENSE). The launcher is not affiliated with NeoFN or Epic
Games. Fortnite is a trademark of Epic Games, Inc.
