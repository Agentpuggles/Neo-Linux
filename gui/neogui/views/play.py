"""Play — the dashboard, and the whole point of the app.

Everything a normal user needs on one screen: what will launch, whether it can,
and one button. Status, account state, news and recent activity sit around it,
each one clickable through to the page that can act on it.
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QVBoxLayout, QWidget

from ..backend.models import Progress
from ..theme import SPACE
from ..widgets.common import (
    Card,
    EmptyState,
    IconButton,
    SectionHeader,
    StatusDot,
    hline,
    label,
)
from ..widgets.hero import HeroPanel
from .base import View


class StatCard(Card):
    """One compact metric with a state dot, a value and a caption."""

    def __init__(self, ctx, title: str, parent=None) -> None:
        super().__init__(parent, flat=True, padding=SPACE["md"])
        self.v.setSpacing(SPACE["xs"])
        row = QHBoxLayout()
        row.setSpacing(SPACE["sm"])
        self.dot = StatusDot(ctx.theme, "muted", size=8)
        row.addWidget(self.dot, 0, Qt.AlignmentFlag.AlignVCenter)
        self.caption = label(title, "caption")
        row.addWidget(self.caption)
        row.addStretch(1)
        self.add_layout(row)
        self.value = label("—", "heading")
        self.add(self.value)
        self.note = label("", "small", wrap=True)
        self.note.setVisible(False)
        self.add(self.note)

    def set(self, value: str, tone: str = "muted", note: str = "") -> None:
        self.value.setText(value)
        self.dot.set_tone(tone)
        self.note.setText(note)
        self.note.setVisible(bool(note))
        self.setToolTip(f"{self.caption.text()}: {value}" + (f" — {note}" if note else ""))


class PlayView(View):
    title = "Play"

    def __init__(self, ctx, parent=None) -> None:
        super().__init__(ctx, parent)
        self.selected_version: str | None = None
        self._activity: list = []

        self.refresh_btn = IconButton(self.theme, "refresh", "Refresh everything  (F5)")
        self.refresh_btn.clicked.connect(self.refresh)
        self.add_header_action(self.refresh_btn)

        # ---------------------------------------------------------- the hero
        self.hero = HeroPanel(self.theme)
        self.hero.launch_requested.connect(self._primary_action)
        self.hero.stop_requested.connect(self.ctx.cancel_current_operation)
        self.hero.build_changed.connect(self._select_build)
        self.hero.configure_requested.connect(
            lambda: self.ctx.navigate("library", detail=self.selected_version)
        )
        self.body.addWidget(self.hero)

        # --------------------------------------------------------- the stats
        grid = QGridLayout()
        grid.setSpacing(SPACE["md"])
        self.stat_service = StatCard(ctx, "SERVICE")
        self.stat_account = StatCard(ctx, "ACCOUNT")
        self.stat_access = StatCard(ctx, "GAME ACCESS")
        self.stat_build = StatCard(ctx, "INSTALLED BUILD")
        for col, card in enumerate(
            (self.stat_service, self.stat_account, self.stat_access, self.stat_build)
        ):
            grid.addWidget(card, 0, col)
            grid.setColumnStretch(col, 1)
        self.body.addLayout(grid)

        # ---------------------------------------------- news + activity split
        split = QHBoxLayout()
        split.setSpacing(SPACE["lg"])

        news_card = Card()
        news_head = SectionHeader("News", "Announcements from NeoFN")
        self.news_refresh = IconButton(self.theme, "refresh", "Reload news", size=15)
        self.news_refresh.clicked.connect(lambda: self.state.refresh_news())
        news_head.add_action(self.news_refresh)
        news_card.add(news_head)
        news_card.add(hline())
        self.news_body = QVBoxLayout()
        self.news_body.setSpacing(SPACE["md"])
        news_card.add_layout(self.news_body)
        self.news_empty = EmptyState(
            self.theme, "bell", "No news right now", "Announcements will appear here."
        )
        news_card.add(self.news_empty)
        news_card.add_stretch()
        split.addWidget(news_card, 3)

        activity_card = Card()
        activity_card.add(SectionHeader("Recent activity", "What Neo has done this session"))
        activity_card.add(hline())
        self.activity_body = QVBoxLayout()
        self.activity_body.setSpacing(SPACE["sm"])
        activity_card.add_layout(self.activity_body)
        self.activity_empty = EmptyState(
            self.theme, "clock", "Nothing yet", "Installs, launches and errors show up here."
        )
        activity_card.add(self.activity_empty)
        activity_card.add_stretch()
        split.addWidget(activity_card, 2)
        self.body.addLayout(split, 1)

        # ------------------------------------------------------------ wiring
        self.state.session_changed.connect(self._on_session)
        self.state.status_changed.connect(self._on_status)
        self.state.installs_changed.connect(self._on_installs)
        self.state.news_changed.connect(self._on_news)
        self.state.activity.connect(self.add_activity)

    # ---------------------------------------------------------------- events
    def on_show(self) -> None:
        self._sync_hero()

    def refresh(self) -> None:
        self.state.refresh_session()
        self.state.refresh_status()
        self.state.refresh_installs()
        self.state.refresh_news()

    def _select_build(self, version: str) -> None:
        self.selected_version = version
        self._sync_hero()

    def _primary_action(self) -> None:
        mode = self.hero.mode
        if mode == "needs_login":
            self.ctx.open_login()
        elif mode == "needs_install":
            self.ctx.navigate("library")
            self.ctx.start_install()
        else:
            self.ctx.launch(self.selected_version)

    # ----------------------------------------------------------- state sync
    def _on_session(self, session) -> None:
        if session.logged_in:
            self.stat_account.set(
                session.display_name or "Signed in",
                "success",
                "Display name not set yet" if session.setup_completed is False else "",
            )
        else:
            self.stat_account.set("Signed out", "muted", "Sign in with Discord to play")
        self._sync_hero()

    def _on_status(self, status) -> None:
        if not status.reachable:
            self.stat_service.set("Unreachable", "danger", status.error or "No response")
        elif status.banned:
            self.stat_service.set("Banned", "danger", status.ban_reason)
        else:
            note = status.message
            if status.players_online is not None:
                note = f"{status.players_online:,} players online" + (
                    f" · {note}" if note else ""
                )
            self.stat_service.set(status.status.title(), status.tone, note)

        if not self.state.session.logged_in:
            self.stat_access.set("—", "muted", "Sign in to check")
        elif status.access_gate == "unknown":
            self.stat_access.set("Unknown", "muted", "Could not check right now")
        else:
            self.stat_access.set(
                status.access_label,
                status.access_tone,
                (status.entitlements if status.access_gate == "granted" else "")
                or status.access_note,
            )
        self._sync_hero()

    def _on_installs(self, installs: list) -> None:
        if not installs:
            self.stat_build.set("None", "muted", "Install a build from the Library")
        else:
            preferred = self.state.preferred_install()
            broken = [i for i in installs if not i.exists]
            note = f"{len(installs)} installed" if len(installs) > 1 else preferred.path
            if broken:
                note = f"{len(broken)} missing from disk"
            self.stat_build.set(
                preferred.short, "warning" if broken else "success", note
            )
        if self.selected_version not in [i.version for i in installs]:
            preferred = self.state.preferred_install()
            self.selected_version = preferred.version if preferred else None
        self.hero.set_builds(installs, self.selected_version)
        self._sync_hero()

    def _on_news(self, items: list) -> None:
        while self.news_body.count():
            item = self.news_body.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.news_empty.setVisible(not items)
        for entry in items[:4]:
            self.news_body.addWidget(self._news_row(entry))

    def _news_row(self, entry) -> QWidget:
        row = QWidget()
        v = QVBoxLayout(row)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)
        head = QHBoxLayout()
        head.setSpacing(SPACE["sm"])
        title = label(entry.title or "Untitled", "body")
        title.setWordWrap(True)
        head.addWidget(title, 1)
        if entry.date:
            head.addWidget(label(entry.date, "caption"), 0, Qt.AlignmentFlag.AlignTop)
        v.addLayout(head)
        if entry.body:
            body = label(entry.body[:260], "small", wrap=True)
            v.addWidget(body)
        return row

    # -------------------------------------------------------------- activity
    def add_activity(self, text: str) -> None:
        stamp = datetime.now().strftime("%H:%M")
        self._activity.insert(0, (stamp, text))
        del self._activity[8:]
        while self.activity_body.count():
            item = self.activity_body.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.activity_empty.setVisible(not self._activity)
        for when, what in self._activity:
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(SPACE["md"])
            h.addWidget(label(when, "caption"), 0, Qt.AlignmentFlag.AlignTop)
            text_label = label(what, "small", wrap=True)
            h.addWidget(text_label, 1)
            self.activity_body.addWidget(row)

    # ------------------------------------------------------------ hero state
    def _sync_hero(self) -> None:
        if self._showing_progress:
            # A background refresh must never yank the hero out from under a
            # running download.
            self.hero.set_mode("busy")
            return
        session = self.state.session
        installs = self.state.installs
        status = self.state.status

        if self.ctx.busy_operation:
            self.hero.set_mode("busy")
        elif self.state.game_running:
            self.hero.set_mode("running")
            self.hero.set_headline("Fortnite is running", "Neo is watching the game process.")
            self.hero.set_state("PLAYING", "accent")
            return
        elif not session.logged_in:
            self.hero.set_mode("needs_login")
        elif not installs:
            self.hero.set_mode("needs_install")
        else:
            self.hero.set_mode("idle")

        if not session.logged_in:
            self.hero.set_headline(
                "Sign in to play",
                "Neo uses your Discord account through NeoFN. Nothing is stored beyond "
                "the session token, and it never leaves your machine.",
            )
            self.hero.set_state("SIGNED OUT", "muted")
            self.hero.set_session_note("")
            return

        if not installs:
            self.hero.set_headline(
                "No build installed",
                "Download the live build to start playing. It is large — around 62 GiB "
                "compressed, and roughly double that at peak while it assembles.",
            )
            self.hero.set_state("SETUP", "warning")
        else:
            current = next(
                (i for i in installs if i.version == self.selected_version), installs[0]
            )
            detail = current.path
            if not current.exists:
                self.hero.set_state("MISSING", "danger")
                detail = f"The folder is gone: {current.path}"
            elif not current.playable:
                self.hero.set_state("INCOMPLETE", "warning")
                detail = "Game binaries are missing — run Verify & Repair."
            elif status.banned or status.prism_banned:
                self.hero.set_state("BANNED", "danger")
            elif status.reachable and not status.up:
                self.hero.set_state(status.status.upper()[:12], "warning")
            elif status.access_denied:
                self.hero.set_state("NO ACCESS", "warning")
                detail = "Your account does not have play access yet."
            else:
                self.hero.set_state("READY", "success")
            self.hero.set_headline(f"Fortnite {current.short}", detail)

        self.hero.set_session_note(session.label, "accent")

    # ------------------------------------------------------ progress bridging
    _showing_progress = False

    def show_progress(self, progress: Progress) -> None:
        percent = progress.percent if progress.total else None
        detail = progress.detail
        if progress.unit == "bytes" and progress.total:
            detail = (
                f"{self.service.human(progress.done)} of "
                f"{self.service.human(progress.total)}"
                + (f" · {self.service.human(progress.rate)}/s" if progress.rate else "")
            )
        elif progress.unit in ("files", "chunks") and progress.total:
            detail = f"{progress.done} / {progress.total}" + (
                f" · {progress.detail}" if progress.detail else ""
            )
        self._showing_progress = True
        self.hero.set_progress(progress.label or "Working…", percent, detail)
        self.hero.set_mode("busy")

    def clear_progress(self) -> None:
        self._showing_progress = False
        self._sync_hero()
