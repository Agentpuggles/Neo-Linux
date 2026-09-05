"""Diagnostics — logs, environment and a paste-ready report.

Three tabs: the launcher's own session log (what Neo did), the game log
(FortniteGame.log, wherever the prefix hid it) and the environment report.
Everything here is copyable and exportable, and everything token-shaped is
redacted before it leaves the process.
"""

from __future__ import annotations

import os
from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..backend.errors import NeoError
from ..backend.service import redact
from ..platform_integration import copy_to_clipboard, reveal_in_file_manager, session_summary
from ..theme import SPACE
from ..widgets.common import (
    Badge,
    Button,
    Card,
    SectionHeader,
    hline,
    label,
    selectable,
)
from .base import View

TAIL_MS = 2000


class LogPane(QWidget):
    """A monospace viewer with search, wrap, follow and copy/export."""

    def __init__(self, ctx, *, placeholder: str, parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.theme = ctx.theme
        self._lines: list = []

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(SPACE["sm"])

        bar = QHBoxLayout()
        bar.setSpacing(SPACE["sm"])
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter lines…")
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName("Filter log lines")
        self.search.textChanged.connect(self._render)
        bar.addWidget(self.search, 1)

        self.only_important = QCheckBox("Errors && auth only")
        self.only_important.setToolTip(
            "Show only lines mentioning login, entitlements, bans or errors"
        )
        self.only_important.toggled.connect(self._render)
        bar.addWidget(self.only_important)

        self.wrap = QCheckBox("Wrap")
        self.wrap.toggled.connect(self._set_wrap)
        bar.addWidget(self.wrap)

        self.copy_btn = Button("Copy", self.theme, "copy", on_click=self.copy_all)
        bar.addWidget(self.copy_btn)
        self.save_btn = Button("Save…", self.theme, "download", on_click=self.save_as)
        bar.addWidget(self.save_btn)
        v.addLayout(bar)

        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setPlaceholderText(placeholder)
        self.view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.view.setMaximumBlockCount(20000)
        self.view.setAccessibleName("Log contents")
        v.addWidget(self.view, 1)

    def _set_wrap(self, on: bool) -> None:
        self.view.setLineWrapMode(
            QPlainTextEdit.LineWrapMode.WidgetWidth if on else QPlainTextEdit.LineWrapMode.NoWrap
        )

    def set_lines(self, lines: list) -> None:
        self._lines = lines
        self._render()

    def append(self, line: str) -> None:
        self._lines.append(line)
        del self._lines[:-20000]
        if self._passes(line):
            at_end = (
                self.view.verticalScrollBar().value()
                >= self.view.verticalScrollBar().maximum() - 4
            )
            self.view.appendPlainText(line)
            if at_end:
                self.view.verticalScrollBar().setValue(
                    self.view.verticalScrollBar().maximum()
                )

    def _passes(self, line: str) -> bool:
        needle = self.search.text().strip().lower()
        if needle and needle not in line.lower():
            return False
        return not (self.only_important.isChecked() and not self.ctx.service.log_is_interesting(line))

    def _render(self) -> None:
        shown = [line for line in self._lines if self._passes(line)]
        self.view.setPlainText("\n".join(shown))
        self.view.moveCursor(QTextCursor.MoveOperation.End)

    def text(self) -> str:
        return "\n".join(self._lines)

    def copy_all(self) -> None:
        copy_to_clipboard(redact(self.view.toPlainText()))
        self.ctx.toast("Log copied to the clipboard.", "success")

    def save_as(self) -> None:
        default = os.path.expanduser(
            f"~/neo-log-{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"
        )
        path, _ = QFileDialog.getSaveFileName(self, "Save log", default, "Text files (*.txt)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(redact(self.text()))
        except OSError as exc:
            self.ctx.show_error(
                NeoError("Could not save the log.", str(exc), kind="permission")
            )
            return
        self.ctx.toast(f"Saved to {path}", "success", action_text="Show",
                       on_action=lambda: reveal_in_file_manager(path))


class DiagnosticsView(View):
    title = "Diagnostics"
    subtitle = "Logs, environment and everything you need to file a good bug report."

    def __init__(self, ctx, parent=None) -> None:
        super().__init__(ctx, parent)
        self.export_btn = Button(
            "Export report", self.theme, "download", variant="primary",
            on_click=self._export,
            tooltip="Save a redacted diagnostics report you can attach to an issue",
        )
        self.copy_report_btn = Button(
            "Copy report", self.theme, "copy", on_click=self._copy_report
        )
        self.add_header_action(self.copy_report_btn)
        self.add_header_action(self.export_btn)

        self._tail_timer = QTimer(self)
        self._tail_timer.setInterval(TAIL_MS)
        self._tail_timer.timeout.connect(self._tail)
        self._tail_offset = 0
        self._tail_path = ""

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.currentChanged.connect(self._tab_changed)

        # --- session log
        self.session_log = LogPane(
            ctx, placeholder="Neo's own activity for this session appears here."
        )
        self.tabs.addTab(self._wrap(self.session_log), "Neo log")

        # --- game log
        game = QWidget()
        gv = QVBoxLayout(game)
        gv.setContentsMargins(0, 0, 0, 0)
        gv.setSpacing(SPACE["md"])
        path_row = QHBoxLayout()
        path_row.setSpacing(SPACE["sm"])
        self.game_path = QLineEdit()
        self.game_path.setPlaceholderText("Path to FortniteGame.log")
        self.game_path.setAccessibleName("Game log path")
        path_row.addWidget(self.game_path, 1)
        path_row.addWidget(Button("Browse", self.theme, "folder", on_click=self._browse_log))
        path_row.addWidget(Button("Reload", self.theme, "refresh", on_click=self._load_game_log))
        self.follow = QCheckBox("Follow")
        self.follow.setToolTip("Keep reading new lines as the game writes them")
        self.follow.toggled.connect(self._set_follow)
        path_row.addWidget(self.follow)
        gv.addLayout(path_row)
        self.game_log = LogPane(
            ctx,
            placeholder=(
                "No game log found yet. It appears once the game has run — Neo looks "
                "inside WINEPREFIX and umu's default prefixes."
            ),
        )
        gv.addWidget(self.game_log, 1)
        self.tabs.addTab(self._wrap(game), "Game log")

        # --- environment
        env = QWidget()
        ev = QVBoxLayout(env)
        ev.setContentsMargins(0, 0, 0, 0)
        ev.setSpacing(SPACE["lg"])

        self.env_card = Card()
        self.env_card.add(
            SectionHeader("Environment", "What Neo detected about this system.")
        )
        self.env_card.add(hline())
        self.env_body = QVBoxLayout()
        self.env_body.setSpacing(SPACE["sm"])
        self.env_card.add_layout(self.env_body)
        ev.addWidget(self.env_card)

        self.checks_card = Card()
        self.checks_card.add(
            SectionHeader("Readiness checks", "Everything Neo needs in order to launch.")
        )
        self.checks_card.add(hline())
        self.checks_body = QVBoxLayout()
        self.checks_body.setSpacing(SPACE["sm"])
        self.checks_card.add_layout(self.checks_body)
        ev.addWidget(self.checks_card)
        ev.addStretch(1)
        self.tabs.addTab(self._wrap(env), "Environment")

        self.body.addWidget(self.tabs, 1)

    @staticmethod
    def _wrap(widget: QWidget) -> QWidget:
        holder = QWidget()
        v = QVBoxLayout(holder)
        v.setContentsMargins(0, SPACE["md"], 0, 0)
        v.addWidget(widget)
        return holder

    # ------------------------------------------------------------------ life
    def on_first_show(self) -> None:
        self._load_environment()
        self._load_game_log(quiet=True)

    def on_show(self) -> None:
        self._load_environment()

    def refresh(self) -> None:
        self._load_environment()
        self._load_game_log()

    def _tab_changed(self, index: int) -> None:
        if index != 1 and self._tail_timer.isActive():
            self._tail_timer.stop()
            self.follow.setChecked(False)

    def log(self, text: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.session_log.append(f"{stamp}  {redact(text)}")

    # ------------------------------------------------------------- game log
    def _browse_log(self) -> None:
        start = os.path.dirname(self.game_path.text()) or os.path.expanduser("~")
        path, _ = QFileDialog.getOpenFileName(self, "Choose FortniteGame.log", start,
                                              "Log files (*.log);;All files (*)")
        if path:
            self.game_path.setText(path)
            self._load_game_log()

    def _load_game_log(self, *, quiet: bool = False) -> None:
        path = self.game_path.text().strip() or self.service.game_log_path()
        if not path:
            self.game_log.set_lines([])
            if not quiet:
                self.ctx.toast(
                    "No game log found yet — it appears after the first launch.", "info"
                )
            return
        self.game_path.setText(path)
        try:
            lines = self.service.read_log(path)
        except NeoError as exc:
            self.ctx.show_error(exc)
            return
        self.game_log.set_lines(lines)
        self._tail_path = path
        try:
            self._tail_offset = os.path.getsize(path)
        except OSError:
            self._tail_offset = 0

    def _set_follow(self, on: bool) -> None:
        if on:
            if not self._tail_path:
                self._load_game_log()
            if self._tail_path:
                self._tail_timer.start()
        else:
            self._tail_timer.stop()

    def _tail(self) -> None:
        if not self._tail_path or not os.path.exists(self._tail_path):
            return
        try:
            size = os.path.getsize(self._tail_path)
            if size < self._tail_offset:  # rotated
                self._tail_offset = 0
            if size == self._tail_offset:
                return
            with open(self._tail_path, encoding="utf-8", errors="replace") as fh:
                fh.seek(self._tail_offset)
                new = fh.read()
                self._tail_offset = fh.tell()
        except OSError:
            self._tail_timer.stop()
            self.follow.setChecked(False)
            return
        for line in new.splitlines():
            self.game_log.append(line)

    # ---------------------------------------------------------- environment
    def _load_environment(self) -> None:
        while self.env_body.count():
            item = self.env_body.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for key, value in self.service.environment().items():
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(SPACE["lg"])
            k = label(key.title(), "caption")
            k.setMinimumWidth(150)
            h.addWidget(k, 0, Qt.AlignmentFlag.AlignTop)
            h.addWidget(selectable(label(str(value), "mono", wrap=True)), 1)
            self.env_body.addWidget(row)

        while self.checks_body.count():
            item = self.checks_body.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for ok, title, detail in self._checks():
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(SPACE["md"])
            h.addWidget(
                Badge("OK" if ok else "CHECK", "success" if ok else "warning", self.theme),
                0,
                Qt.AlignmentFlag.AlignTop,
            )
            col = QVBoxLayout()
            col.setContentsMargins(0, 0, 0, 0)
            col.setSpacing(1)
            col.addWidget(label(title, "body"))
            if detail:
                col.addWidget(label(detail, "small", wrap=True))
            h.addLayout(col, 1)
            self.checks_body.addWidget(row)

    def _checks(self) -> list:
        out = []
        s = self.state
        out.append(
            (
                s.session.logged_in,
                "Signed in",
                "" if s.session.logged_in else "Sign in with Discord from the account panel.",
            )
        )
        out.append(
            (
                s.status.reachable and s.status.up,
                "NeoFN services reachable",
                s.status.error or s.status.message,
            )
        )
        umu = self.service.umu_available()
        out.append(
            (
                umu,
                "umu-run available",
                ""
                if umu
                else "Install umu-launcher — it runs the Windows build through Proton.",
            )
        )
        playable = [i for i in s.installs if i.playable]
        out.append(
            (
                bool(playable),
                "A playable build is installed",
                "" if playable else "Install a build from the Library.",
            )
        )
        access = s.status.fortnite_access
        out.append(
            (
                access is True,
                "Account has game access",
                ""
                if access
                else "NeoFN has not granted this account play access yet — this is "
                "expected during private testing.",
            )
        )
        prefix = os.environ.get("WINEPREFIX")
        out.append(
            (
                True,
                "Wine prefix",
                prefix or "WINEPREFIX is unset — umu will create and manage its own.",
            )
        )
        return out

    # -------------------------------------------------------------- report
    def _report(self) -> str:
        return self.service.diagnostics_report(
            extra_sections={
                "Desktop session": session_summary(),
                "Neo session log (tail)": "\n".join(self.session_log._lines[-120:]),
                "Game log (tail)": "\n".join(self.game_log._lines[-120:]),
            }
        )

    def _copy_report(self) -> None:
        copy_to_clipboard(self._report())
        self.ctx.toast("Diagnostics report copied — safe to paste into an issue.", "success")

    def _export(self) -> None:
        default = os.path.expanduser(
            f"~/neo-diagnostics-{datetime.now().strftime('%Y%m%d-%H%M%S')}.md"
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "Export diagnostics", default, "Markdown (*.md);;Text files (*.txt)"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(self._report())
        except OSError as exc:
            self.ctx.show_error(
                NeoError("Could not write the report.", str(exc), kind="permission")
            )
            return
        self.ctx.toast(
            f"Report saved to {path}",
            "success",
            action_text="Show",
            on_action=lambda: reveal_in_file_manager(path),
        )
