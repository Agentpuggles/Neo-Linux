# Troubleshooting

Start with **Diagnostics** in the desktop app: it shows Neo's log, the game log
and environment details. Export a diagnostics report when asking for help, then
review it before sharing. Tokens are redacted, but local paths and account details
may still identify you. Never post `auth.json`, access/refresh tokens or sign-in
callback codes. Security problems should be [reported privately](../SECURITY.md).

## Desktop startup

Run `~/.local/bin/neo-gui` in a terminal to see why the window did not open.

| Symptom | Fix |
| --- | --- |
| `Neo's desktop app is not installed` | You have the single-file CLI, not the desktop app. Install PySide6, then run `make install` from a full checkout. See [Desktop setup](desktop-setup.md). Terminal commands still work with `neo --help`. |
| `Neo's desktop app needs PySide6` | Install your distro's PySide6 package, or use the [virtualenv setup](desktop-setup.md#virtualenv-setup). A virtualenv created only with `make dev` has Ruff, not Qt; use `make dev-gui` or install PySide6 into it. |
| `No graphical session was found` | Run Neo from a Wayland/X11 desktop. On SSH or a headless machine, use `neo --help` and explicit terminal commands. Do not set a fake `DISPLAY` just to bypass this check. |
| `could not start`, or an interpreter path no longer exists | If you moved or deleted the virtualenv used at installation, recreate it and run `make install` again. The installed GUI records its Python interpreter. |
| `neo: command not found` | The CLI is optional. Install it from **Settings → Command-line tool**, or run `make install-cli` from the checkout. If already installed, Settings shows its full path and PATH guidance. Open the GUI with `neo-gui` or the app menu. |
| No Neo entry in the application menu | Run `make install` from the checkout. If your desktop caches the menu, log out and back in. |
| Qt says it cannot load the `xcb` or `wayland` platform plugin | Check your distro's Qt platform libraries and graphics drivers. This is different from a missing Python module; installing PySide6 alone may not supply every native library. Include the full Qt error and desktop environment in your report. |
| `Failed to register with host portal … App info not found for 'dev.neofn.NeoLauncher'` | Usually harmless when running from a checkout with no desktop entry. Install with `make install` to add the matching app identity. |

## Sign-in and account status

**The browser did not return to Neo.** Paste the entire
`neolauncher://callback/auth?code=…` URL into the sign-in dialog. The code is
single-use and expires quickly; start sign-in again if it has expired. Do not share
the real URL in an issue or screenshot.

For the terminal fallback, run `neo login --callback '<full-callback-url>'`.
The CLI and GUI share the same session. Switching between their sign-in flows may
change the default URL handler; starting a new sign-in from your preferred
interface registers it again.

**`fortniteAccess -> HTTP 404` on an older version.** Update Neo. Since NeoFN's
launch, that route can be unpublished for ungated accounts. Version 0.5.6 treats
that as **open**, not denied; see the [playability gates](protocol.md#112-playability-gates).

**No entitlements, even though you play.** Entitlements record store purchases,
not playtime. An account that bought nothing can correctly show none.
`neo status --json` shows the underlying service responses.

## Downloads and disk space

- **Interrupted download:** start the same build's install again with the same
  cache and target locations. Valid cached chunks are reused.
- **Not enough space:** the download cache and installed files coexist during
  installation. For 10.40, budget about 124 GiB at peak, plus Proton/runtime space.
  Set **Settings → Game → Download cache / Install location** to a larger drive
  before retrying. Changing a path setting does not move existing files for you.
  If relocating the cache, close Neo and move its contents to the new location
  first to preserve resumable downloads.
- **Damaged or missing files:** use **Library → Verify & repair**, or
  `neo verify --repair`. Only files that fail verification are rebuilt.
- **CDN 403:** Neo sends its own user agent because the CDN rejects some defaults.
  If you use a proxy or VPN, try without it.
- **Chunk 404:** CDN edges sometimes return a temporary 404 for existing chunks.
  Neo retries with backoff. If it still fails, the error names the chunk GUID;
  include that in a report, not account credentials.

The cache is normally cleared after a successful installation. **Settings → Game
→ Clear cache** or `neo cache clear` can reclaim retained downloads; this does not
remove installed game files. More detail: [disk usage](cli-reference.md#disk-usage).

## Game launch

**`umu-run` not found.** Install
[umu-launcher](https://github.com/Open-Wine-Components/umu-launcher#installation).
PySide6 runs the launcher UI; umu/Proton runs the Windows game. Both are needed
for the full desktop experience; the optional CLI is not.

**The game aborts with “unimplemented function”.** Try another Proton build:
select **GE-Proton** in **Settings → Launch → Proton build**, then launch again.
The equivalent terminal command is `neo config proton GE-Proton`. Recreating the
same prefix with the same crashing Proton build is not a fix; see
[engineering note 14](engineering-notes.md#14-wine-unimplemented-function-abort--the-proton-build-not-the-prefix).

**The game shows an email/password screen.** Check service status and your account
in Neo, then inspect **Diagnostics → Game log**. From the terminal, use
`neo status` and `neo log -f`. A typical log path is
`<prefix>/drive_c/users/<user>/AppData/Local/FortniteGame/Saved/Logs/FortniteGame.log`.

**`Failed to open descriptor file`.** This can be caused by `-basedir` quoting.
Neo already constructs that argument; do not add your own quoted `-basedir`.

**Extra game arguments.** Use **Settings → Launch → Default arguments**, or
`neo config launch_options "-windowed -log"`. For a one-off terminal launch, put
Neo's options before the game arguments:

```sh
neo launch --dry-run --edit-on-release -- -windowed
```

Use `WINEPREFIX` if you want a dedicated prefix. If it is unset, umu picks its own
default. See [environment variables](cli-reference.md#environment) for overrides.

## Still stuck?

[Open an issue](https://github.com/Agentpuggles/Neo-Linux/issues/new/choose) with:

- your distro, desktop environment and Wayland/X11 session;
- the Neo version shown in Diagnostics (or `neo --version` if the CLI is installed) and Proton build;
- what you clicked or ran, what you expected and the exact error;
- a reviewed, redacted diagnostics report when possible.

A service outage or an account restriction cannot be fixed by reinstalling Neo.
