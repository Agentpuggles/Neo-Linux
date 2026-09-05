"""The application window and the controller that ties everything together.

`AppContext` is what views talk to: navigation, toasts, errors, and the three
long-running operations (install, verify, launch). Keeping those here rather
than in the views means only one of them can run at a time, progress always has
somewhere to go, and cancelling works from anywhere.
"""

from __future__ import annotations

import subprocess

from PySide6.QtCore import QEvent, QSettings, QTimer, Signal
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QMainWindow,
    QMenu,
    QStackedWidget,
    QSystemTrayIcon,
    QWidget,
)

from . import icons
from .backend.errors import NeoError
from .backend.models import LaunchPlan, Progress
from .backend.service import NeoService
from .backend.tasks import TaskRunner
from .platform_integration import (
    APP_ID,
    notify,
    session_summary,
    tray_available,
)
from .state import AppState
from .theme import Theme
from .views.account import AccountView
from .views.diagnostics import DiagnosticsView
from .views.friends import FriendsView
from .views.library import LibraryView
from .views.play import PlayView
from .views.settings import SettingsView
from .widgets.dialogs import ConfirmDialog, DetailDialog, InstallDialog, LoginDialog
from .widgets.toast import ToastHost

DESTINATIONS = [
    ("play", "Play", "play"),
    ("library", "Library", "library"),
    ("friends", "Friends", "friends"),
    ("diagnostics", "Diagnostics", "diagnostics"),
    ("settings", "Settings", "settings"),
]
COLLAPSE_WIDTH = 1080


class AppContext:
    """The seam between views and everything else. Views hold one of these."""

    def __init__(self, window: MainWindow) -> None:
        self.window = window

    # -- shared services -----------------------------------------------------
    @property
    def theme(self) -> Theme:
        return self.window.theme

    @property
    def state(self) -> AppState:
        return self.window.state

    @property
    def service(self) -> NeoService:
        return self.window.service

    @property
    def tasks(self) -> TaskRunner:
        return self.window.tasks

    @property
    def busy_operation(self) -> str:
        return self.window.busy_operation

    # -- delegated actions ---------------------------------------------------
    def navigate(self, key: str, **kwargs) -> None:
        self.window.navigate(key, **kwargs)

    def toast(self, text: str, tone: str = "info", **kwargs) -> None:
        self.window.toasts.show_toast(text, tone, **kwargs)

    def show_error(self, error: NeoError) -> None:
        self.window.show_error(error)

    def open_login(self) -> None:
        self.window.open_login()

    def sign_out(self) -> None:
        self.window.sign_out()

    def launch(self, version: str | None = None) -> None:
        self.window.start_launch(version)

    def start_install(self, version: str | None = None) -> None:
        self.window.start_install(version)

    def start_verify(self, version: str | None, *, repair: bool) -> None:
        self.window.start_verify(version, repair=repair)

    def cancel_current_operation(self) -> None:
        self.window.cancel_current_operation()

    def library_select(self, version: str) -> None:
        self.window.navigate("library", detail=version)

    def apply_theme(self, *, mode: str | None = None, accent: str | None = None) -> None:
        self.window.apply_theme(mode=mode, accent=accent)

    def log(self, text: str) -> None:
        self.window.log(text)


class MainWindow(QMainWindow):
    callback_received = Signal(str)

    def __init__(self, service: NeoService) -> None:
        super().__init__()
        self.service = service
        self.tasks = TaskRunner(self)
        self.state = AppState(service, self.tasks, self)

        cfg = service.config()
        self.theme = Theme(cfg.get("gui_theme", "system"), cfg.get("gui_accent", "violet"), self)

        self.busy_operation = ""
        self._game_process: subprocess.Popen | None = None
        self._launch_plan: LaunchPlan | None = None
        self._login_dialog: LoginDialog | None = None
        self._launch_output: list = []

        self.setWindowTitle("Neo")
        self.setMinimumSize(940, 640)
        self.setWindowIcon(icons.app_icon())

        self.ctx = AppContext(self)
        self._build_ui()
        self._build_shortcuts()
        self._build_tray()
        self._restore_geometry()
        self.apply_theme()

        self.state.error.connect(self.show_error)
        self.state.notice.connect(lambda tone, text: self.toasts.show_toast(text, tone))
        self.state.session_changed.connect(self._sync_chrome)
        self.state.status_changed.connect(self._sync_chrome)
        self.state.activity.connect(self.log)

        self.callback_received.connect(self._handle_callback)
        QTimer.singleShot(0, self.state.start)
        QTimer.singleShot(50, lambda: self.log(f"Neo {service.version} on {session_summary()}"))

    # ------------------------------------------------------------------ chrome
    def _build_ui(self) -> None:
        from .widgets.navrail import NavRail

        root = QWidget()
        root.setObjectName("RootSurface")
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.rail = NavRail(self.theme, DESTINATIONS)
        self.rail.navigate.connect(self.navigate)
        self.rail.account_clicked.connect(lambda: self.navigate("account"))
        self.rail.set_version(f"v{self.service.version}")
        layout.addWidget(self.rail)

        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)

        self.views: dict = {}
        for key, cls in (
            ("play", PlayView),
            ("library", LibraryView),
            ("friends", FriendsView),
            ("diagnostics", DiagnosticsView),
            ("settings", SettingsView),
            ("account", AccountView),
        ):
            view = cls(self.ctx)
            self.views[key] = view
            self.stack.addWidget(view)

        self.setCentralWidget(root)

        self.toasts = ToastHost(self.theme, root)
        self.toasts.setGeometry(root.rect())
        root.installEventFilter(self)

        self.navigate("play")

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Resize and obj is self.centralWidget():
            self.toasts.setGeometry(obj.rect())
            self.rail.set_collapsed(obj.width() < COLLAPSE_WIDTH)
        return super().eventFilter(obj, event)

    def _build_shortcuts(self) -> None:
        pairs = [
            ("Ctrl+L", lambda: self.start_launch()),
            ("Ctrl+,", lambda: self.navigate("settings")),
            ("Ctrl+6", lambda: self.navigate("account")),
            ("Ctrl+7", lambda: self.navigate("account")),
            ("F5", self._refresh_current),
            ("Ctrl+R", self._refresh_current),
            ("Ctrl+Q", self.quit),
            ("Ctrl+W", self.close),
            ("Ctrl+Shift+D", lambda: self.navigate("diagnostics")),
        ]
        for keys, slot in pairs:
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.activated.connect(slot)

    def _build_tray(self) -> None:
        self.tray: QSystemTrayIcon | None = None
        if not tray_available():
            return
        self.tray = QSystemTrayIcon(icons.app_icon(), self)
        self.tray.setToolTip("Neo")
        menu = QMenu()
        show = QAction("Open Neo", self)
        show.triggered.connect(self._restore_window)
        menu.addAction(show)
        play = QAction("Launch game", self)
        play.triggered.connect(lambda: (self._restore_window(), self.start_launch()))
        menu.addAction(play)
        menu.addSeparator()
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self.quit)
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: self._restore_window()
            if reason == QSystemTrayIcon.ActivationReason.Trigger
            else None
        )
        self.tray.show()

    def _restore_window(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    # ------------------------------------------------------------------- theme
    def apply_theme(self, *, mode: str | None = None, accent: str | None = None) -> None:
        if mode:
            self.theme.set_mode(mode)
        if accent:
            self.theme.set_accent(accent)
        icons.clear_cache()
        app = QApplication.instance()
        if app:
            app.setPalette(self.theme.qpalette())
            app.setStyleSheet(self.theme.stylesheet())
        self.rail.retheme()

    def system_theme_changed(self) -> None:
        if self.theme.mode == "system":
            self.theme.system_mode_changed()
            self.apply_theme()

    # -------------------------------------------------------------- navigation
    def navigate(self, key: str, *, detail: str | None = None) -> None:
        view = self.views.get(key)
        if view is None:
            return
        self.stack.setCurrentWidget(view)
        self.rail.set_active(key)
        view._enter()
        if detail and key == "library":
            view.select(detail)
        self.setWindowTitle(f"Neo — {view.title}" if key != "play" else "Neo")

    def _refresh_current(self) -> None:
        current = self.stack.currentWidget()
        if hasattr(current, "refresh"):
            current.refresh()

    def _sync_chrome(self, *_args) -> None:
        self.rail.set_account(self.state.session, self.state.status)
        if self.tray:
            self.tray.setToolTip(
                f"Neo — {self.state.session.label}"
                if self.state.session.logged_in
                else "Neo — signed out"
            )

    # ------------------------------------------------------------------ errors
    def show_error(self, error: NeoError) -> None:
        self.log(f"error: {error.summary} — {error.detail[:200]}")
        self.toasts.show_error(
            error,
            action_text="Full details" if len(error.detail) > 220 else "",
            on_action=lambda: DetailDialog(
                self.ctx,
                error.summary,
                error.hint or "Technical details follow — safe to paste into an issue.",
                error.detail,
            ).exec(),
        )

    def log(self, text: str) -> None:
        diagnostics = self.views.get("diagnostics")
        if diagnostics is not None:
            diagnostics.log(text)

    def notify_user(self, title: str, body: str, *, urgent: bool = False) -> None:
        if not self.state.config.get("gui_notify_on_finish", True):
            return
        if self.isActiveWindow() and not urgent:
            return
        notify(title, body, tray=self.tray, urgent=urgent)

    # ------------------------------------------------------------------- auth
    def open_login(self) -> None:
        if self._login_dialog is not None:
            self._login_dialog.raise_()
            return
        dialog = LoginDialog(self.ctx)
        self._login_dialog = dialog
        try:
            accepted = dialog.exec()
        finally:
            self._login_dialog = None
        if accepted:
            self.state.refresh_session()
            self.state.refresh_status()
            self.state.refresh_installs()
            session = self.state.session
            self.toasts.show_toast(f"Signed in as {session.label}.", "success")
            self.state.log_activity(f"Signed in as {session.label}")
            if not session.display_name:
                self.navigate("account")

    def sign_out(self) -> None:
        self.state.sign_out()
        self.toasts.show_toast("Signed out.", "info")

    def handle_callback_url(self, url: str) -> None:
        """Entry point for a second instance delivering neolauncher://…"""
        self.callback_received.emit(url)

    def _handle_callback(self, url: str) -> None:
        self._restore_window()
        if self._login_dialog is not None:
            self._login_dialog.accept_code(url)
            return
        try:
            session = self.service.login_with_code(url)
        except NeoError as exc:
            self.show_error(exc)
            return
        self.state.refresh_session()
        self.state.refresh_status()
        self.toasts.show_toast(f"Signed in as {session.label}.", "success")
        self.state.log_activity(f"Signed in as {session.label}")

    # ---------------------------------------------------------------- install
    def start_install(self, version: str | None = None) -> None:
        if self._reject_if_busy():
            return
        if not self.state.session.logged_in:
            self.open_login()
            return
        if not self.state.builds:
            self.toasts.show_toast(
                "The build catalog has not loaded yet — check your connection.", "warning"
            )
            self.state.refresh_builds()
            return
        dialog = InstallDialog(self.ctx, self.state.builds, version)
        if not dialog.exec():
            return
        options = dialog.result_options()
        self._begin("install", "Preparing the download")
        self.tasks.run(
            self.service.install_build,
            options["version"],
            target_dir=options["target_dir"],
            workers=options["workers"],
            keep_cache=options["keep_cache"],
            key="operation",
            action="Installing the build",
            on_progress=self._on_progress,
            on_message=self.log,
            on_result=self._install_done,
            on_error=self._operation_failed,
            on_cancelled=lambda: self._operation_cancelled("Download cancelled."),
        )
        self.state.log_activity(f"Started downloading {options['version']}")

    def _install_done(self, install) -> None:
        self._end()
        self.toasts.show_toast(
            f"Fortnite {install.short} is installed.",
            "success",
            action_text="Play",
            on_action=lambda: self.start_launch(install.version),
        )
        self.state.log_activity(f"Installed {install.short} to {install.path}")
        self.notify_user("Download finished", f"Fortnite {install.short} is ready to play.")
        self.state.refresh_installs()

    # ----------------------------------------------------------------- verify
    def start_verify(self, version: str | None, *, repair: bool) -> None:
        if self._reject_if_busy():
            return
        self._begin("verify", "Verifying files")
        self.tasks.run(
            self.service.verify_install,
            version,
            repair=repair,
            key="operation",
            action="Verifying the build",
            on_progress=self._on_progress,
            on_message=self.log,
            on_result=self._verify_done,
            on_error=self._operation_failed,
            on_cancelled=lambda: self._operation_cancelled("Verification cancelled."),
        )

    def _verify_done(self, report) -> None:
        self._end()
        if report.clean:
            self.toasts.show_toast(
                f"All {report.checked} files verified — this build is intact.", "success"
            )
            self.state.log_activity(f"Verified {report.version}: clean")
        elif report.repaired and not report.failed:
            self.toasts.show_toast(
                f"Repaired {report.repaired} file(s). The build is now intact.", "success"
            )
            self.state.log_activity(f"Repaired {report.repaired} file(s) in {report.version}")
        elif report.failed:
            self.show_error(
                NeoError(
                    f"{len(report.failed)} file(s) could not be repaired.",
                    "\n".join(f"{n}: {e}" for n, e in report.failed[:20]),
                    "Try again — a failed chunk download usually succeeds on a retry. "
                    "If it keeps failing, reinstall the build.",
                )
            )
        else:
            broken = len(report.missing) + len(report.corrupt)
            self.toasts.show_toast(
                f"{broken} file(s) are missing or corrupt.",
                "warning",
                action_text="Repair now",
                on_action=lambda: self.start_verify(report.version, repair=True),
            )
            self.state.log_activity(f"Verified {report.version}: {broken} bad file(s)")
        self.notify_user("Verification finished", f"Checked {report.checked} files.")
        self.state.refresh_installs()

    # ----------------------------------------------------------------- launch
    def start_launch(self, version: str | None = None) -> None:
        if self.state.game_running:
            self.toasts.show_toast("The game is already running.", "info")
            return
        if self._reject_if_busy():
            return
        if not self.state.session.logged_in:
            self.open_login()
            return
        if not self.state.installs:
            self.toasts.show_toast("Install a build first.", "warning")
            self.navigate("library")
            return
        version = version or self.views["play"].selected_version
        self._begin("launch", "Preparing to launch")
        self._launch_output = []
        self.tasks.run(
            self.service.build_launch_plan,
            version,
            key="operation",
            action="Preparing the launch",
            on_progress=self._on_progress,
            on_message=self.log,
            on_result=self._plan_ready,
            on_error=self._operation_failed,
            on_cancelled=lambda: self._operation_cancelled("Launch cancelled."),
        )

    def _plan_ready(self, plan: LaunchPlan) -> None:
        self._launch_plan = plan
        if self.state.config.get("gui_confirm_launch"):
            preview = "\n".join(plan.display_command())
            dialog = DetailDialog(
                self.ctx,
                "Launch Fortnite?",
                f"Working directory: {plan.working_dir}"
                + (f"\nPROTONPATH: {plan.proton}" if plan.proton else ""),
                preview,
            )
            dialog.add_button("Launch", variant="primary", on_click=dialog.accept)
            if not dialog.exec():
                self._end()
                return
        self._spawn(plan)

    def _spawn(self, plan: LaunchPlan) -> None:
        self.state.game_running = True
        self._begin("launch", "Starting the game")
        self.views["play"].hero.set_mode("running")
        self.tasks.run(
            self.service.run_launch,
            plan,
            key="game",
            action="Running the game",
            on_message=self._game_output,
            on_result=self._game_exited,
            on_error=self._launch_failed,
        )
        self.toasts.show_toast(
            f"Launching Fortnite {plan.version.split('/')[-1].split('-CL-')[0]}…", "info"
        )
        self.state.log_activity(f"Launched {plan.version}")
        self._end()

    def _game_output(self, line: str) -> None:
        self._launch_output.append(line)
        del self._launch_output[:-800]
        self.log(line)

    def _game_exited(self, rc: int) -> None:
        self.state.game_running = False
        self.views["play"].clear_progress()
        tail = "\n".join(self._launch_output[-200:])
        if rc == 0:
            self.toasts.show_toast("The game closed normally.", "info")
            self.state.log_activity("Game exited cleanly")
        else:
            error = self.service.launch_failure(rc, tail)
            self.show_error(error)
            self.state.log_activity(f"Game exited with code {rc}")
            self.notify_user("The game exited unexpectedly", error.summary, urgent=True)

    def _launch_failed(self, error: NeoError) -> None:
        self.state.game_running = False
        self.views["play"].clear_progress()
        self.show_error(error)

    # ------------------------------------------------------- operation plumbing
    def _reject_if_busy(self) -> bool:
        if self.busy_operation:
            self.toasts.show_toast(
                "Neo is already busy — wait for the current operation, or cancel it.",
                "warning",
            )
            return True
        return False

    def _begin(self, name: str, label: str) -> None:
        self.busy_operation = name
        self.views["play"].show_progress(Progress(label=label))

    def _end(self) -> None:
        self.busy_operation = ""
        self.views["play"].clear_progress()

    def _on_progress(self, progress: Progress) -> None:
        self.views["play"].show_progress(progress)

    def _operation_failed(self, error: NeoError) -> None:
        self._end()
        self.show_error(error)
        self.notify_user("Something went wrong", error.summary, urgent=True)

    def _operation_cancelled(self, text: str) -> None:
        self._end()
        self.toasts.show_toast(text, "info")
        self.state.log_activity(text)
        self.state.refresh_installs()

    def cancel_current_operation(self) -> None:
        if not self.busy_operation:
            return
        self.tasks.cancel("operation")
        self.toasts.show_toast("Cancelling…", "info")

    # ------------------------------------------------------------- lifecycle
    def _restore_geometry(self) -> None:
        settings = QSettings(APP_ID, "window")
        geometry = settings.value("geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        else:
            self.resize(1240, 820)

    def _save_geometry(self) -> None:
        settings = QSettings(APP_ID, "window")
        settings.setValue("geometry", self.saveGeometry())

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.state.config.get("gui_minimise_to_tray") and self.tray is not None:
            event.ignore()
            self.hide()
            self.toasts.show_toast("", "info")  # no-op to keep host alive
            notify("Neo is still running", "Find it in the system tray.", tray=self.tray)
            return
        if self.busy_operation:
            confirm = ConfirmDialog(
                self.ctx,
                title="Quit while Neo is busy?",
                body=(
                    "A download or repair is still running. Progress that has already "
                    "been written to disk is kept, and resuming picks up where it left off."
                ),
                confirm_text="Quit anyway",
                destructive=True,
            )
            if not confirm.exec():
                event.ignore()
                return
        self._shutdown()
        event.accept()

    def quit(self) -> None:
        self._shutdown()
        app = QApplication.instance()
        if app:
            app.quit()

    def _shutdown(self) -> None:
        self._save_geometry()
        self.state.stop()
        self.tasks.shutdown()
        if self.tray:
            self.tray.hide()
