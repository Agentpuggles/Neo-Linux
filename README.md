# neo — a native Linux launcher for NeoFN

`neo` is a single-file, stdlib-only Python launcher for [NeoFN](https://neofn.dev)
(private Fortnite seasons). It does everything the official Windows launcher does —
Discord login, chunked build downloads with hash verification, patched-client
management, and game launch — natively on Linux. The game itself runs through
[umu-run](https://github.com/Open-Wine-Components/umu-launcher)/Proton; the launcher
needs no Wine.

```
login → pick build → manifest → parallel chunk download → zlib + SHA-1 verify →
assemble → verify → prism-patched exe + 2 exchange codes → umu-run
```

> **Unofficial, interoperability-focused tool.** Not affiliated with or endorsed by
> NeoFN or Epic Games. It talks only to NeoFN's own public services using the
> credentials of their official launcher (extracted for compatibility, the same
> approach as [legendary](https://github.com/derrod/legendary)). No game assets are
> included or redistributed. Use at your own risk.

## Status

| feature | state |
|---|---|
| Discord OAuth login (`neolauncher://` handler + manual fallback) | ✅ |
| Session refresh, display-name setup, ban/access status | ✅ |
| Build catalog + Epic BuildPatchServices manifest parsing | ✅ |
| Parallel chunk downloader (16+ workers, resumable, SHA-1 per chunk **and** per file) | ✅ — 62 GB / 62k chunks validated |
| Install/verify/reinstall with relocatable cache | ✅ |
| Prism asset management (sha256-verified, auto-updated) | ✅ |
| Launch via umu-run (exact Windows-launcher command line) | ✅ boots, auto-logs in |
| Playing | ⏳ waits on NeoFN granting the `PLAY` entitlement (pre-launch as of v0.2.0) |

## Requirements

- Python ≥ 3.9 (stdlib only — nothing to pip install)
- [`umu-run`](https://github.com/Open-Wine-Components/umu-launcher) + any Proton
- a Wine prefix for the game (one is created on first run if you don't set `WINEPREFIX`)

## Install

```sh
git clone https://github.com/<you>/neo-linux.git
install -Dm755 neo-linux/neo ~/.local/bin/neo
```

## Usage

```sh
neo login                     # opens Discord in your browser; callback is automatic
neo setup YourName            # pick a display name (first run)
neo status                    # service status, bans, play access, online counts
neo list                      # available builds

neo install 10.40             # substring or "live"; -d DIR, -j WORKERS, --keep-cache
neo verify 10.40              # re-hash every installed file against the manifest

WINEPREFIX=~/prefixes/fortnite neo launch 10.40
```

Interrupted installs resume — just re-run the same command.

### Locations & configuration

| path | contents |
|---|---|
| `~/.local/share/neo/auth.json` | session (0600) |
| `~/.local/share/neo/state.json` | installed builds → paths |
| `~/.local/share/neo/prism/` | prism-patched client binaries (sha256-checked each launch) |
| `~/.local/share/neo/cache/` | chunk/manifest cache — relocate big installs with `neo config cache_dir <dir>` |

| setting | default | change with |
|---|---|---|
| install root | `~/Games/Neo` | `neo config install_root <dir>` or `install -d` |
| cache dir | `~/.local/share/neo/cache` | `neo config cache_dir <dir>` or `NEO_CACHE` |
| download workers | 16 | `neo config workers N` or `install -j` |

Env: `NEO_HOME` (data dir), `NEO_CACHE` (cache dir), `NEO_UMU` (umu-run command),
`WINEPREFIX` (game prefix — **set it**, otherwise umu uses `~/.wine`).

Peak disk during install ≈ compressed build size (cache) + full build size (install
dir); the cache is purged on success unless `--keep-cache`.

## How it works

The full wire protocol — endpoints, the OAuth quirks (case-sensitive provider route,
nonstandard `authorization_code` field), the Epic JSON manifest format with its
fixed-width decimal "blob" numerics, the BuildPatchServices chunk URL scheme and
on-disk format, prism assets, and the exact launch command line with its
Wine-specific pitfalls — is documented in **[docs/protocol.md](docs/protocol.md)**,
validated live against production.

## Troubleshooting

- **Login callback didn't fire** — copy the whole `neolauncher://callback/auth?code=…`
  URL from the address bar: `neo login --callback '<url>'`. Codes are single-use and
  expire quickly; when in doubt `neo login` again.
- **CDN 403** — R2 rejects some default user agents; `neo` sends its own. If you use a
  proxy/VPN, try without.
- **Transient chunk 404s** — the CDN edge occasionally 404s objects that exist; `neo`
  retries with backoff. Hard failures name the chunk GUID.
- **Game shows an email/password screen** — the login itself usually succeeded; check
  `neo status` for play access, and see the log at
  `<prefix>/drive_c/users/<user>/AppData/Local/FortniteGame/Saved/Logs/FortniteGame.log`.
- **`-basedir` trouble** — pass it bare (no quotes); Wine's argv rebuilding escapes
  embedded quotes and UE4's parser chokes. `neo` already does this.

## License

MIT — see [LICENSE](LICENSE). The launcher is not affiliated with NeoFN or Epic Games.
Fortnite is a trademark of Epic Games, Inc.
