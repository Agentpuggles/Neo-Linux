# Neo Desktop — GUI architecture

`neo-gui` opens the native Linux desktop client for NeoFN. When the optional
CLI is installed, `neo` without arguments also opens the GUI. It is a real X11/Wayland
application (Qt 6 / PySide6, QtWidgets): it has a `.desktop` entry, an icon, a
window class (`dev.neofn.NeoLauncher`), desktop notifications, native file
dialogs and a system tray icon. It is **not** a web view, an Electron shell or a
localhost server.

## Entry points and installation

With no arguments, `neo` finds the matching checkout or installed `neo-gui` and
executes it. Checkout runs can use `.venv`; installed launchers retain their own
interpreter or bundled runtime. `NEO_BIN` can explicitly override the shared core.
No Qt code is loaded when `neo` is imported or given an explicit CLI command.
Headless invocations get a readable message pointing to `neo --help`.

`make install` includes the GUI, private `<prefix>/share/neo/neo` backend, icon
and desktop entry, **not** the public terminal command. `make install-cli` installs
only that command; `make install-all` explicitly includes both. The desktop entry
still invokes `neo-gui %u` using an absolute path, so OAuth callbacks need no CLI.
User installs pin `GUI_PYTHON`; staged packages keep a portable interpreter.

The loader prefers the private backend over a potentially older public CLI. A
normal startup offers `CliInstallDialog` only if the CLI is absent and
`gui_cli_prompt_dismissed` is false. Declining records that preference without
restricting the GUI. Callbacks and `--self-check` skip the prompt; Settings always
keeps an install action visible outside Advanced mode.

`backend/cli_tool.py` checks for an existing CLI without executing files on PATH,
then copies the bundled source to `~/.local/bin/neo` only on explicit consent. It
publishes the complete executable with an exclusive hard link, so a concurrent
file creation or dangling symlink cannot be overwritten. No network requests,
privilege escalation or shell-profile edits are involved. Uninstall preserves
user data alongside the private backend.

## Why PySide6 / Qt 6 (QtWidgets)

| Option | Verdict |
| --- | --- |
| **PySide6 / QtWidgets** | ✅ chosen |
| GTK4/libadwaita (PyGObject) | Looks alien outside GNOME, hard to theme into a Neo design language, PyGObject introspection deps are heavy on non-GNOME distros. |
| Rust (iced / egui / Slint) | Neo's entire backend — auth, BuildPatchServices manifests, the chunk downloader, XMPP, the launch vector — is Python. A Rust GUI means either rewriting ~1800 lines of live-validated protocol code or shipping an IPC bridge. Both are worse. |
| Tauri / Electron | Explicitly a web UI. Rejected. |

The deciding factor is that the launcher is Python: Qt lets the GUI **call the
existing implementation directly**, in-process, with zero protocol duplication.
Qt 6 also gives us the compatibility matrix the project needs — one binary set
that runs on Wayland (native `wayland` platform plugin) and X11, on Plasma,
GNOME, XFCE, Cinnamon, COSMIC, Hyprland and Sway, on every major distro, with
HiDPI scaling, screen-reader (AT-SPI) support and full keyboard navigation for
free.

QtWidgets rather than QML: widgets are lighter, render identically on software
GL (many VMs / older Wayland stacks), and are fully stylable with QSS, which is
how the Neo design language is applied.

## Layers

```
                     ┌──────────────────────────────┐
  neo (CLI, 1 file)  │  protocol + logic, unchanged │
                     └──────────────┬───────────────┘
                                    │ imported as a module (backend/core.py)
                     ┌──────────────┴───────────────┐
                     │  neogui.backend.service      │  Qt-free façade:
                     │  NeoService                  │  dataclasses in/out,
                     └──────────────┬───────────────┘  NeoError on failure
                                    │
                     ┌──────────────┴───────────────┐
                     │  neogui.backend.tasks        │  QThreadPool jobs,
                     │  Job / JobSignals            │  progress + cancel
                     └──────────────┬───────────────┘
                                    │
        theme.py ── widgets/ ── views/ ── mainwindow.py ── app.py
```

* **`backend/core.py`** loads the `neo` executable as a module (it has no `.py`
  suffix), searching the checkout, `$NEO_BIN`, `PATH` and the installed prefix.
  This is the same loader trick the test-suite uses.
* **`backend/service.py`** is the only place that talks to `neo`. It is pure
  Python — no Qt — so it is unit-testable headlessly, and every failure comes
  back as a `NeoError(summary, detail, hint)` triple, which is what the UI
  renders (human sentence + expandable technical detail + actionable hint).
* **`backend/tasks.py`** runs every network / disk operation on a `QThreadPool`.
  Nothing blocking ever touches the UI thread; long jobs report progress and are
  cancellable through a `CancelToken`.
* **`theme.py`** holds design tokens (colour, spacing, radius, type scale) and
  compiles them to QSS. Dark and light are the same token set with different
  values; the active mode follows the desktop (`xdg-desktop-portal`
  `color-scheme`, then the Qt palette) or the user's override.
* **`views/`** are the six top-level destinations. Each view owns its state and
  subscribes to `AppState` signals; no view reaches into another.

## Navigation

A persistent left rail: **Play, Library, Friends, Activity, Diagnostics,
Settings**, plus an account chip at the bottom. `Ctrl+1…6` jump between them,
`Ctrl+,` opens Settings, `F5` refreshes the active view, `Ctrl+L` launches.

## State

`AppState` (in `state.py`) is a small `QObject` holding the cached snapshot:
session, service status, builds, installs, config. Views render from it and
never fetch on their own — `AppState.refresh_*()` schedules the job and emits
when the data lands, so two views showing the same fact can't disagree.

## Platform abstraction

`platform_integration.py` wraps everything environment-specific behind
functions that degrade to a no-op rather than failing:
notifications (Qt tray → `notify-send` → silent), opening files and folders
(`QDesktopServices`, i.e. the portal when sandboxed), the colour-scheme probe,
desktop-entry installation, and session detection (Wayland/X11, DE name) for the
diagnostics report. No code anywhere assumes a package manager, a DE, a display
server or a filesystem layout.

## Security

* Tokens live only in `~/.local/share/neo/auth.json` (`0600`), written by the
  existing `Auth` class. The GUI never copies them into widgets, logs or the
  diagnostics export — the diagnostics report redacts anything token-shaped.
* No `shell=True` anywhere; processes are spawned as argv lists.
* Launch arguments the user types are parsed with `shlex`, and the exchange
  codes in the launch preview are masked exactly like the CLI does.
* Uninstall keeps the CLI's guard (refuses any directory without a
  `.neo-manifest.json`) and asks for typed confirmation.

## AppImage boundary

The [AppImage build/release guide](appimage.md) describes the pinned toolchain and
CI gates. PyInstaller bundles the private source backend and explicitly analyses
its imports. `runtime.py` remains Qt-free: it resolves a durable AppImage launch
command and strips bundle-specific loader/plugin paths from environments passed
to host programs. Desktop Exec arguments use freedesktop quoting, not shell
quoting. AppRun preserves PATH and discovers the host CA bundle without replacing
explicit TLS trust overrides. GUI sign-in owns the GUI callback entry even when
no public `neo` command has been installed.
