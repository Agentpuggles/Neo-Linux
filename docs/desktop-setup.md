# Desktop setup

For most users, start with the [README installation steps](../README.md#install).
`make install` installs the desktop app and its private backend for your user
account. Open **Neo** in your application menu, or run `neo-gui`. The public `neo`
terminal command is optional; the GUI does not depend on installing it.

## Virtualenv setup

Use this if your distro does not package PySide6, or if you prefer an isolated
Python environment. You need Python 3.9+, Git, Make and a Linux desktop. Install
[umu-launcher](https://github.com/Open-Wine-Components/umu-launcher#installation)
separately to run the game.

Clone the repo if you have not already, then run these commands **inside it**:

```sh
git clone https://github.com/Agentpuggles/Neo-Linux.git
cd Neo-Linux
python3 -m venv .venv
.venv/bin/python -m pip install PySide6
make install
~/.local/bin/neo-gui
```

If creating the virtualenv fails on Debian/Ubuntu, install `python3-venv` using
your package manager and try again. Do not use `sudo pip` or bypass your distro's
externally-managed Python protections.

The Makefile automatically uses `.venv/bin/python` when it exists. A user install
records that interpreter in `neo-gui`, so the app menu works without activating
the virtualenv. **Keep the checkout and `.venv` in place** while using this setup.
If you move them, rerun `make install` from the new location. You can explicitly
select an interpreter with `make install GUI_PYTHON=/path/to/python`.

This environment is only for the GUI. `neo login`, `neo install`, `neo launch` and
all other terminal commands remain standard-library-only.

## Optional command-line tool

On the first normal launch, Neo offers **Install CLI (recommended)** or **Not now**.
It is **highly recommended for troubleshooting and doing tasks manually**, such as
checking service status, following logs or repairing a build. The GUI works fully
without it. If you decline, the choice is remembered; install it any time from
**Settings → Command-line tool**, without enabling Advanced mode.

Installing copies the bundled, standard-library-only CLI to `~/.local/bin/neo`.
It needs no download or administrator password, and it never overwrites an
existing command, directory or symlink. An existing Neo CLI is detected and left
alone. Settings shows the installed path and a working `--help` command if the
folder is not on your shell's `PATH`; Neo does not edit shell profiles for you.

The CLI requires Python 3.9+ on the machine where you run it. A copy installed
from an AppImage keeps working after the image is closed. It is a standalone
snapshot: when updating Neo, run `make install-cli` from the updated source if you
also want to update the CLI. `make install-all` explicitly installs/updates both
interfaces. `make install` alone leaves existing terminal commands untouched.

For sandboxed/custom XDG installs, check the GUI's paths in Settings → Advanced.
A host CLI needs matching `NEO_HOME` / `XDG_CONFIG_HOME` overrides to share that
sandbox's state; see the [environment reference](cli-reference.md#environment).

## Running without installing

With PySide6 installed for your Python interpreter:

```sh
./neo
```

The checkout's `.venv` is used if present, unless you are already running under
another virtualenv. `make run-gui` is also available, with
`GUI_PYTHON=/path/to/python` for an explicit override. Developers can use
`make dev-gui` to install PySide6 and Ruff together.

To get a reliable app-menu entry and browser sign-in callbacks, prefer
`make install`. The installed desktop entry uses an absolute launcher path, so it
does not depend on your desktop session having `~/.local/bin` on `PATH`.

## Updating and removing Neo

From the same checkout you installed from:

```sh
git pull --ff-only
make install
```

Close Neo before updating. If you used the virtualenv setup and need to update
Qt, run `.venv/bin/python -m pip install --upgrade PySide6` first.

To remove the launcher:

```sh
make uninstall
```

This removes the GUI, CLI, menu entry and icon, **not** your downloaded games,
session, cache or settings. Their default locations are listed in the
[CLI reference](cli-reference.md#files). For a CLI-only install,
`make uninstall-cli` removes just the `neo` executable. A CLI installed through
the GUI always lives under `~/.local/bin`; if the GUI itself used another prefix,
remove that CLI separately with `make uninstall-cli PREFIX="$HOME/.local"`.

`make install-gui` is equivalent to the default GUI installation.
`make install-all` explicitly includes the CLI too; `make uninstall-all` removes
the full app from the selected prefix. If you originally
set `PREFIX`, use the same prefix when updating or uninstalling.

## Desktop options and troubleshooting

```sh
neo-gui --help
neo-gui --theme dark
neo-gui --theme light
```

Themes, notifications and tray behaviour can also be changed in Settings. Desktop
integration is best-effort: a missing system tray or notification service should
not stop you from playing. The GUI is a native Qt application, not a browser or a
local web server. It needs a graphical session; on SSH/headless machines use the
[terminal commands](cli-reference.md) instead.

See [Troubleshooting](troubleshooting.md) for missing PySide6, display errors,
login callbacks and game-launch failures.

## Packaging for maintainers

`PREFIX` defaults to `~/.local`. Staged packaging does not need a display or
PySide6 at build time:

```sh
make install DESTDIR=/path/to/package-root PREFIX=/usr GUI_PYTHON=python3
```

The GUI's runtime dependency **must** include PySide6. Staged installs retain the
portable `#!/usr/bin/env python3` shebang and never embed `DESTDIR` or the build
machine's virtualenv. The Arch recipe declares `pyside6` as a dependency, not an
optional extra.

The [packaging directory](../packaging/PKGBUILD) contains an Arch `PKGBUILD`, a
Flatpak manifest, an AppImage build script and freedesktop metadata. These are
build recipes, **not a promise of published AUR, Flathub or AppImage downloads**;
check their versions and runtime dependencies before distributing a build.

For the AppImage recipe, use a build virtualenv with PyInstaller/PySide6 and have
`appimagetool` on `PATH`, then run `sh packaging/build-appimage.sh`. The game and
umu/Proton are not bundled. Generated packages belong outside Git.

For portable binaries, see the [AppImage build and release guide](appimage.md).
