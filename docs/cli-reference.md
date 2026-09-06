# Command-line reference

The desktop app is the default. Install the optional terminal command from its
first-run prompt or **Settings → Command-line tool**, or use the CLI-only setup
below. Once installed, `neo` with no arguments opens the GUI when it is available.
Explicit commands such as `neo login`, `neo install` and `neo launch` still work exactly as
before, without PySide6 or a graphical session. `neo --help` shows terminal usage;
`neo-gui --help` lists desktop-specific options.

## CLI-only installation

You need Python 3.9 or newer. From the repository root:

```sh
make install-cli
```

This installs only `~/.local/bin/neo`. You can also keep the single-file setup:

```sh
install -Dm755 neo ~/.local/bin/neo
```

Make sure `~/.local/bin` is on your `PATH`, or use that full path. To run from a
checkout without installing, use `python3 neo --help`. To add the desktop app later,
follow the [desktop setup guide](desktop-setup.md) and run `make install`.

## First game from the terminal

Install [umu-launcher](https://github.com/Open-Wine-Components/umu-launcher) before
launching the game. Allow about 124 GiB of free space at peak for build 10.40, plus
room for Proton and its runtime.

```sh
neo login                          # sign in with Discord in your browser
neo setup YourName                 # choose a display name, if not already set
neo status                         # check the service and your account
neo install                        # download the live build; interrupted downloads resume
neo verify                         # optional: check the installed files again
WINEPREFIX=~/prefixes/neofn neo launch
```

`WINEPREFIX` gives the game a dedicated Windows-compatibility environment. Keep
using the same prefix on later launches; without it, umu uses its own default.

## Usage

```
neo <command> [options]

  account   login · whoami · setup · logout · status · news · friends
  game      list · install · import · verify · uninstall · launch
  system    cache · log · config               (see Configuration)
```

`neo help` (or `neo --help`) prints the command directory, grouped under `account` /
`game` / `system`. Run `neo <command> --help` for a command's own options —
`neo help <command>` and `neo <command> help` do the same thing.

### Account

| Command | What it does |
| --- | --- |
| `neo login` | Opens the Discord OAuth challenge in your browser and registers the `neolauncher://` handler, so the callback is handled automatically. Fallbacks: `neo login --callback '<url>'` with the full callback URL, or `neo login --code <CODE>`. |
| `neo whoami` | Display name, account id and email for the current session. |
| `neo setup [name]` | With no name: shows first-run setup status. With a name: checks availability, then sets the display name. |
| `neo logout` | Drops the stored session (`auth.json` is emptied, not deleted). |
| `neo status` | Lightswitch service status, ban status (both services), play access, store entitlements, players online. Play access has three answers: `granted`, `not granted`, or `open` — the last one meaning NeoFN no longer gates play per account (the endpoint 404s), which is what a launched service looks like. `--json` dumps the raw payloads behind the summary. `--watch` polls until access opens up and fires a desktop notification; `--interval N` sets the period (min 10 s). |
| `neo news` | Launcher news from the content service (`--json` for the raw payload). |
| `neo friends` | Roster with display names and live presence, speaking the official client's own XMPP-over-websocket protocol (protocol.md §12): SASL PLAIN with the account id + access token, official bind resource. `--wait N` presence window, `--verbose` prints the raw stanzas. Falls back to the friends REST API when the websocket is unreachable. `NEO_XMPP` overrides the endpoint. |

### Game

| Command | What it does |
| --- | --- |
| `neo list` | Every build in the catalog with size, release date and the `[LIVE]` marker. |
| `neo install [version]` | Downloads and assembles a build. `version` is a substring such as `10.40`, or `live` (the default). Options: `-d DIR`, `-j WORKERS`, `--keep-cache`. Free space on both the cache and the target volume is checked first (engineering note 9); `--force` skips that check. |
| `neo import <path> <version>` | Registers a build folder that already exists on disk (must contain `FortniteGame/` and `Engine/`) — no 62 GB re-download. Fetches the manifest so `verify` works, and marks the install as imported. |
| `neo verify [version]` | Re-hashes every installed file against the stored manifest. `--repair` re-fetches only the chunks the broken files need and rebuilds just those files — a full reinstall is never needed for a few bad files. |
| `neo uninstall [version]` | Removes an install: deletes the build folder (only if it still carries neo's `.neo-manifest.json`) and drops the state entry. Prompts unless `--yes`. |
| `neo launch [version]` | Checks the gates (lightswitch, bans), refreshes prism assets, mints two exchange codes and runs the game through umu-run. Options: `--dry-run` (print the command line and stop), `--proton PROTON` (overrides the config `proton` for this launch; umu receives it as `PROTONPATH`), `--edit-on-release` / `--instant-reset` / `--disable-pre-edit` (and `--no-…` to override a config default for this launch — the Windows Options → Modifiers toggles, sent as `-NeoModifiers=`). The Proton defaults to the config `proton` setting, else your exported `PROTONPATH`, else umu's default. Extra UE4 arguments go last: `neo launch 10.40 -windowed` (options like `--dry-run` must come before them). |

`version` defaults to the newest installed build (highest `CL-` number) for `verify`,
`uninstall` and `launch`.

### System

| Command | What it does |
| --- | --- |
| `neo cache stats` / `neo cache clear` | Size of the chunk/manifest caches, and cleanup. `clear` drops cached chunks (manifests stay unless `--all`). |
| `neo log [-f] [-p PATH]` | Prints the game's `FortniteGame.log` from the Wine prefix (auto-located via `WINEPREFIX`), with login/entitlement/error lines highlighted. `-f` follows new lines live, useful for diagnosing launch failures. |

## Configuration

### The `config` command

| Command | What it does |
| --- | --- |
| `neo config` | Print every setting and the config file path. |
| `neo config <key>` | Print one setting. |
| `neo config <key> <value>` | Set a setting. Keys: `install_root`, `cache_dir`, `workers`, `proton`, `edit_on_release`, `instant_reset`, `disable_pre_edit`, `launch_options`. |

### Files

| Path | Contents |
| --- | --- |
| `~/.local/share/neo/auth.json` | Session tokens (mode `0600`) |
| `~/.local/share/neo/state.json` | Installed builds → paths |
| `~/.local/share/neo/prism/` | Prism-patched client binaries, sha256-checked on every launch |
| `~/.local/share/neo/cache/` | Chunk and manifest cache |
| `~/.config/neo/config.json` | Settings |

Paths above are the defaults. `XDG_DATA_HOME` and `XDG_CONFIG_HOME` are honoured;
the GUI and CLI share these files, sessions and installed builds.

### Settings

| Key | Default | Also settable via |
| --- | --- | --- |
| `install_root` | `~/Games/Neo` | `neo install -d DIR` |
| `cache_dir` | `~/.local/share/neo/cache` | `NEO_CACHE` |
| `workers` | `16` | `neo install -j N` |
| `proton` | *(umu's default)* | `PROTONPATH`, `neo launch --proton` |
| `edit_on_release` | `false` | `neo launch --edit-on-release` |
| `instant_reset` | `false` | `neo launch --instant-reset` |
| `disable_pre_edit` | `false` | `neo launch --disable-pre-edit` |
| `launch_options` | *(empty)* | extra args on `neo launch` (appended after these) |

### Environment

| Variable | Meaning |
| --- | --- |
| `NEO_HOME` | Override the data directory |
| `NEO_CACHE` | Override the cache directory |
| `NEO_XMPP` | Override the friends XMPP websocket endpoint |
| `NEO_UMU` | umu-run command to invoke (default `umu-run`) |
| `WINEPREFIX` | Game prefix, honoured by umu-run; set it to give NeoFN its own environment, otherwise umu chooses its default |
| `PROTONPATH` | Proton umu should use (a name like `GE-Proton` or a path); read by umu. `neo` honours it, and `neo config proton <p>` / `neo launch --proton <p>` set it for the child |

### Disk usage

Peak during an install ≈ compressed build size (cache) + full build size (install
directory), both checked before the download starts. The cache is purged on success
unless you pass `--keep-cache`, which keeps it for offline repair at the cost of
roughly one build's worth of disk. `neo cache stats` shows what is sitting there;
`neo cache clear` reclaims it.
