# Neo Desktop — GUI architecture

`neo-gui` is the native Linux desktop client for NeoFN. It is a real X11/Wayland
application (Qt 6 / PySide6, QtWidgets): it has a `.desktop` entry, an icon, a
window class (`dev.neofn.NeoLauncher`), desktop notifications, native file
dialogs and a system tray icon. It is **not** a web view, an Electron shell or a
localhost server.

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
