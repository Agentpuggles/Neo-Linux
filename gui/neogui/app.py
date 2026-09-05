"""Application entry point.

Handles the things that must happen before any widget exists: HiDPI policy,
the desktop/window identity every DE keys off, single-instance handover (so
clicking `neolauncher://…` reaches the running window instead of starting a
second copy), and a readable failure when the `neo` launcher cannot be found.
"""

from __future__ import annotations

import argparse
import os
import signal
import sys

# The app must be importable both from a checkout and from an installed prefix.
_PACKAGE_PARENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PACKAGE_PARENT not in sys.path:
    sys.path.insert(0, _PACKAGE_PARENT)

from PySide6.QtCore import QCoreApplication, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtNetwork import QLocalServer, QLocalSocket  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from neogui import icons  # noqa: E402
from neogui.backend.core import LauncherNotFound  # noqa: E402
from neogui.backend.service import NeoService  # noqa: E402
from neogui.platform_integration import APP_ID, APP_NAME  # noqa: E402

VERSION = "1.0.0"
SOCKET_NAME = f"{APP_ID}.instance"


def parse_args(argv: list) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="neo-gui",
        description="Neo — the desktop client for NeoFN on Linux.",
    )
    parser.add_argument("--version", action="version", version=f"neo-gui {VERSION}")
    parser.add_argument(
        "url",
        nargs="?",
        help="a neolauncher:// callback URL (used by the sign-in handler)",
    )
    parser.add_argument(
        "--install-desktop-entry",
        action="store_true",
        help="install the .desktop file and icon, then exit",
    )
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="build the window and open every page once, then exit (for CI)",
    )
    parser.add_argument(
        "--theme",
        choices=("system", "dark", "light"),
        help="override the theme for this run",
    )
    return parser.parse_args(argv)


def hand_off_to_running_instance(url: str) -> bool:
    """If Neo is already running, give it the URL and let this process exit."""
    socket = QLocalSocket()
    socket.connectToServer(SOCKET_NAME)
    if not socket.waitForConnected(400):
        return False
    socket.write((url or "raise").encode())
    socket.flush()
    socket.waitForBytesWritten(600)
    socket.disconnectFromServer()
    return True


def configure_application_identity() -> None:
    """Everything a Linux desktop needs to identify the app correctly.

    `setDesktopFileName` is what makes Wayland compositors match the window to
    the .desktop entry — without it the app shows a generic icon in the dock and
    cannot be pinned properly. On X11 the same string becomes WM_CLASS.
    """
    QCoreApplication.setOrganizationName("NeoFN")
    QCoreApplication.setOrganizationDomain("neofn.dev")
    QCoreApplication.setApplicationName(APP_NAME)
    QCoreApplication.setApplicationVersion(VERSION)
    QGuiApplication.setDesktopFileName(APP_ID)
    QGuiApplication.setApplicationDisplayName(APP_NAME)
    # High-DPI: Qt 6 scales by default; we only opt into fractional rounding
    # that matches what GNOME/Plasma do, so 125%/150% scaling looks right.
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )


def fatal(app, title: str, text: str, detail: str = "") -> int:
    box = QMessageBox()
    box.setIcon(QMessageBox.Icon.Critical)
    box.setWindowTitle(title)
    box.setText(text)
    if detail:
        box.setDetailedText(detail)
    box.exec()
    return 1


def main(argv: list | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    args = parse_args(argv)

    if args.install_desktop_entry:
        # Import lazily: this path must work without a display server.
        from neogui.platform_integration import install_desktop_entry

        path = install_desktop_entry()
        print(f"installed {path}")
        return 0

    url = args.url or ""
    if url and not url.startswith("neolauncher://"):
        url = ""

    configure_application_identity()
    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)  # the tray may keep us alive
    app.setWindowIcon(icons.app_icon())

    if hand_off_to_running_instance(url):
        return 0

    if args.theme:
        os.environ["NEO_GUI_THEME"] = args.theme

    try:
        service = NeoService()
    except LauncherNotFound as exc:
        return fatal(
            app,
            "Neo launcher not found",
            "Neo's desktop client is a front end for the `neo` launcher, and that "
            "file could not be found on this system.",
            f"{exc}\n\nInstall it with:\n    make install\n\nor set NEO_BIN to the "
            "path of the `neo` file.",
        )
    except Exception as exc:  # pragma: no cover - defensive
        return fatal(
            app,
            "Neo could not start",
            "The launcher module failed to load.",
            f"{type(exc).__name__}: {exc}",
        )

    from neogui.mainwindow import MainWindow

    window = MainWindow(service)

    # Single-instance server: later invocations hand their URL over to us.
    QLocalServer.removeServer(SOCKET_NAME)
    server = QLocalServer(app)
    server.listen(SOCKET_NAME)

    def on_connection():
        conn = server.nextPendingConnection()
        if conn is None:
            return

        def read():
            payload = bytes(conn.readAll()).decode("utf-8", "replace").strip()
            conn.disconnectFromServer()
            window.showNormal()
            window.raise_()
            window.activateWindow()
            if payload.startswith("neolauncher://"):
                window.handle_callback_url(payload)

        conn.readyRead.connect(read)

    server.newConnection.connect(on_connection)

    # Follow the desktop's light/dark preference while running.
    app.styleHints().colorSchemeChanged.connect(lambda *_: window.system_theme_changed())

    if args.self_check:
        return self_check(app, window)

    window.show()
    if url:
        QTimer.singleShot(300, lambda: window.handle_callback_url(url))

    # Ctrl-C in a terminal should close the window, not wedge the event loop.
    signal.signal(signal.SIGINT, lambda *_: window.quit())
    heartbeat = QTimer()
    heartbeat.start(400)
    heartbeat.timeout.connect(lambda: None)

    code = app.exec()
    server.close()
    return code


def self_check(app, window) -> int:
    """Open every page once and report. Used by `make smoke-gui`.

    This is a real exercise of the UI, not an import test: each view is
    constructed, entered, refreshed and repainted offscreen, so a broken layout
    or a missing attribute fails the build instead of the user's first launch.
    """
    from PySide6.QtCore import QEvent

    window.resize(1280, 800)
    window.show()
    app.processEvents()

    failures = []
    for key in list(window.views):
        try:
            window.navigate(key)
            app.processEvents()
            view = window.views[key]
            view.refresh()
            app.processEvents()
            if view.grab().isNull():
                raise RuntimeError("the page rendered nothing")
            print(f"  ok    {key}")
        except Exception as exc:
            failures.append(f"{key}: {type(exc).__name__}: {exc}")
            print(f"  FAIL  {key}: {exc}")

    for mode in ("light", "dark"):
        try:
            window.apply_theme(mode=mode)
            app.processEvents()
            print(f"  ok    {mode} theme")
        except Exception as exc:
            failures.append(f"{mode} theme: {exc}")
            print(f"  FAIL  {mode} theme: {exc}")

    window.state.stop()
    window.tasks.shutdown(2000)
    window.close()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    if failures:
        print(f"self-check: {len(failures)} failure(s)")
        return 1
    print("self-check: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
