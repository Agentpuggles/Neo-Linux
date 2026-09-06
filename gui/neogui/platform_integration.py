"""Everything environment-specific, behind functions that never raise.

The rule: if a desktop feature is missing (no portal, no notification daemon, no
tray, no xdg-mime) the call becomes a no-op and the app keeps working. Nothing
here assumes a particular DE, display server, package manager or filesystem.
"""

from __future__ import annotations

import contextlib
import os
import shlex
import sys
import shutil
import subprocess
from pathlib import Path

from PySide6.QtCore import QStandardPaths, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication

from .runtime import desktop_argument, desktop_value, host_environment, launch_argv

APP_ID = "dev.neofn.NeoLauncher"
APP_NAME = "Neo"


# ------------------------------------------------------------------ session
def is_wayland() -> bool:
    app = QGuiApplication.instance()
    if app is not None:
        with contextlib.suppress(Exception):
            return "wayland" in app.platformName().lower()
    return bool(os.environ.get("WAYLAND_DISPLAY"))


def desktop_environment() -> str:
    for var in ("XDG_CURRENT_DESKTOP", "XDG_SESSION_DESKTOP", "DESKTOP_SESSION"):
        value = os.environ.get(var)
        if value:
            return value.split(":")[0]
    return "unknown"


def in_flatpak() -> bool:
    return os.path.exists("/.flatpak-info")


def session_summary() -> str:
    return (
        f"{desktop_environment()} · {'Wayland' if is_wayland() else 'X11'}"
        f"{' · Flatpak' if in_flatpak() else ''}"
    )


# ------------------------------------------------------------ opening things
def open_path(path: str) -> bool:
    """Open a file or folder with the user's chosen handler (portal-aware)."""
    if not path:
        return False
    if getattr(sys, "frozen", False) and _host_open(os.path.abspath(os.path.expanduser(path))):
        return True
    return QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.expanduser(path)))


def open_url(url: str) -> bool:
    if not url:
        return False
    if getattr(sys, "frozen", False) and _host_open(url):
        return True
    if QDesktopServices.openUrl(QUrl(url)):
        return True
    # Fallback for minimal sessions where Qt has no URL handler registered.
    return _host_open(url)


def _host_open(url: str) -> bool:
    opener = shutil.which("xdg-open")
    if opener:
        with contextlib.suppress(OSError):
            subprocess.Popen(
                [opener, url], env=host_environment(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            return True
    return False


def reveal_in_file_manager(path: str) -> bool:
    """Show a file in its folder, falling back to just opening the folder."""
    path = os.path.expanduser(path or "")
    if not path:
        return False
    if os.path.isdir(path):
        return open_path(path)
    return open_path(os.path.dirname(path) or ".")


# ----------------------------------------------------------- notifications
def notify(title: str, body: str = "", *, tray=None, urgent: bool = False) -> None:
    """Desktop notification: tray bubble if we have one, else notify-send."""
    if tray is not None:
        with contextlib.suppress(Exception):
            from PySide6.QtWidgets import QSystemTrayIcon

            if tray.isVisible():
                tray.showMessage(
                    title,
                    body,
                    QSystemTrayIcon.MessageIcon.Critical
                    if urgent
                    else QSystemTrayIcon.MessageIcon.Information,
                    6000,
                )
                return
    binary = shutil.which("notify-send")
    if not binary:
        return
    args = [binary, "-a", APP_NAME, "-i", APP_ID]
    if urgent:
        args += ["-u", "critical"]
    args += [title, body]
    with contextlib.suppress(Exception):
        subprocess.run(
            args, env=host_environment(), timeout=5, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )


def tray_available() -> bool:
    with contextlib.suppress(Exception):
        from PySide6.QtWidgets import QSystemTrayIcon

        return bool(QSystemTrayIcon.isSystemTrayAvailable())
    return False


# ------------------------------------------------------------------ clipboard
def copy_to_clipboard(text: str) -> bool:
    app = QGuiApplication.instance()
    if app is None:
        return False
    app.clipboard().setText(text or "")
    return True


# ------------------------------------------------------- desktop integration
DESKTOP_FILE = f"""[Desktop Entry]
Type=Application
Version=1.0
Name=Neo
GenericName=Game Launcher
Comment=Launch and manage NeoFN builds on Linux
Exec={{exec}} %u
TryExec={{tryexec}}
Icon={APP_ID}
Terminal=false
Categories=Game;
Keywords=neo;neofn;fortnite;launcher;game;
StartupNotify=true
StartupWMClass={APP_ID}
MimeType=x-scheme-handler/neolauncher;
X-GNOME-UsesNotifications=true
SingleMainWindow=true
"""


def data_home() -> Path:
    return Path(
        os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    )


def desktop_entry_path() -> Path:
    return data_home() / "applications" / f"{APP_ID}.desktop"


def icon_install_path(size: str = "scalable") -> Path:
    return data_home() / "icons" / "hicolor" / size / "apps" / f"{APP_ID}.svg"


def is_desktop_entry_installed() -> bool:
    return desktop_entry_path().exists()


def install_desktop_entry(launch_command: str | None = None) -> Path:
    """Write ~/.local/share/applications/<app-id>.desktop and the icon.

    Makes the app appear in every DE's application menu and pinnable to any
    dock — the entry is the standard freedesktop one, so this works the same on
    Plasma, GNOME, XFCE, Cinnamon, COSMIC and wlroots panels.
    """
    from . import icons as icon_module

    argv = shlex.split(launch_command) if launch_command else launch_argv()
    if not argv:
        raise ValueError("The desktop launch command is empty")
    exec_cmd = " ".join(desktop_argument(arg) for arg in argv)
    entry = desktop_entry_path()
    entry.parent.mkdir(parents=True, exist_ok=True)
    tryexec = desktop_value(argv[0])
    entry.write_text(DESKTOP_FILE.format(exec=exec_cmd, tryexec=tryexec), encoding="utf-8")
    entry.chmod(0o755)

    svg = icon_install_path()
    svg.parent.mkdir(parents=True, exist_ok=True)
    svg.write_text(icon_module.app_icon_svg(), encoding="utf-8")

    for tool, args in (
        ("update-desktop-database", [str(entry.parent)]),
        ("gtk-update-icon-cache", ["-qtf", str(data_home() / "icons" / "hicolor")]),
    ):
        binary = shutil.which(tool)
        if binary:
            with contextlib.suppress(Exception):
                subprocess.run(
                    [binary, *args],
                    env=host_environment(),
                    check=False,
                    timeout=20,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
    return entry


def remove_desktop_entry() -> None:
    with contextlib.suppress(OSError):
        desktop_entry_path().unlink()
    with contextlib.suppress(OSError):
        icon_install_path().unlink()


def detect_launch_command() -> str:
    """The command that starts this app, however it was installed."""
    return shlex.join(launch_argv())


def register_scheme_handler(service) -> bool:
    """Own neolauncher:// so the Discord redirect comes back into the GUI."""
    # Re-register the current launcher: an AppImage may have moved or replaced
    # a source install. Never retain a stale /tmp/.mount_... callback command.
    try:
        install_desktop_entry()
    except Exception:
        return False
    binary = shutil.which("xdg-mime")
    if not binary:
        return False
    with contextlib.suppress(Exception):
        result = subprocess.run(
            [binary, "default", f"{APP_ID}.desktop", "x-scheme-handler/neolauncher"],
            env=host_environment(),
            check=False,
            timeout=10,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return result.returncode == 0
    return False


def scheme_handler_owner() -> str:
    binary = shutil.which("xdg-mime")
    if not binary:
        return ""
    try:
        out = subprocess.run(
            [binary, "query", "default", "x-scheme-handler/neolauncher"],
            env=host_environment(),
            check=False,
            timeout=10,
            capture_output=True,
            text=True,
        )
        return out.stdout.strip()
    except Exception:
        return ""


def default_documents_dir() -> str:
    return (
        QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        or os.path.expanduser("~")
    )
