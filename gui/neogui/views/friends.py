"""Friends — the roster with live presence over XMPP, REST as the fallback."""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QVBoxLayout, QWidget

from ..platform_integration import copy_to_clipboard
from ..theme import SPACE
from ..widgets.common import (
    Avatar,
    Badge,
    Button,
    Card,
    EmptyState,
    IconButton,
    SectionHeader,
    StatusDot,
    hline,
    label,
)
from .base import View


class FriendRow(QWidget):
    def __init__(self, ctx, friend, parent=None) -> None:
        super().__init__(parent)
        self.friend = friend
        row = QHBoxLayout(self)
        row.setContentsMargins(0, SPACE["xs"], 0, SPACE["xs"])
        row.setSpacing(SPACE["md"])

        avatar = Avatar(ctx.theme, 34)
        avatar.set_text(friend.label)
        row.addWidget(avatar)

        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(1)
        col.addWidget(label(friend.label, "body"))
        detail = friend.status or friend.state
        col.addWidget(label(detail, "small"))
        row.addLayout(col, 1)

        row.addWidget(StatusDot(ctx.theme, "success" if friend.online else "muted", size=8))
        row.addWidget(
            Badge(friend.state.upper(), "success" if friend.online else "muted", ctx.theme)
        )
        copy = IconButton(ctx.theme, "copy", "Copy account ID", size=15)
        copy.clicked.connect(
            lambda: (
                copy_to_clipboard(friend.account_id),
                ctx.toast("Account ID copied.", "info"),
            )
        )
        row.addWidget(copy)
        self.setAccessibleName(f"{friend.label}, {friend.state}")


class FriendsView(View):
    title = "Friends"
    subtitle = "Your NeoFN roster, with presence straight from the XMPP service."

    def __init__(self, ctx, parent=None) -> None:
        super().__init__(ctx, parent)
        self.refresh_btn = IconButton(self.theme, "refresh", "Reload the roster  (F5)")
        self.refresh_btn.clicked.connect(self.refresh)
        self.add_header_action(self.refresh_btn)

        self.card = Card()
        head = SectionHeader("Roster")
        self.transport_badge = Badge("", "muted", self.theme)
        self.transport_badge.setVisible(False)
        head.add_action(self.transport_badge)
        self.card.add(head)

        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Search friends…")
        self.filter.setClearButtonEnabled(True)
        self.filter.setAccessibleName("Search friends")
        self.filter.textChanged.connect(self._render)
        self.card.add(self.filter)
        self.card.add(hline())

        self.rows = QVBoxLayout()
        self.rows.setSpacing(0)
        self.card.add_layout(self.rows)

        self.empty = EmptyState(
            self.theme,
            "friends",
            "No friends yet",
            "When someone adds you on NeoFN they will show up here, with live "
            "presence while they are online.",
        )
        self.card.add(self.empty)

        self.signed_out = EmptyState(
            self.theme,
            "user",
            "Sign in to see your friends",
            "The roster comes from your NeoFN account.",
        )
        self.signed_out.add_action(
            Button("Sign in", self.theme, "discord", variant="primary",
                   on_click=self.ctx.open_login)
        )
        self.card.add(self.signed_out)
        self.card.add_stretch()
        self.body.addWidget(self.card, 1)

        self.state.friends_changed.connect(lambda *_: self._render())
        self.state.session_changed.connect(lambda *_: self._render())

    def on_first_show(self) -> None:
        self._render()
        if self.state.session.logged_in:
            self.refresh()

    def on_show(self) -> None:
        self._render()

    def refresh(self) -> None:
        if not self.state.session.logged_in:
            return
        self.filter.setEnabled(False)
        self.refresh_btn.setEnabled(False)
        self.set_subtitle("Connecting to the presence service…")
        self.state.refresh_friends(on_error=self._failed)

    def _failed(self, error) -> None:
        self.filter.setEnabled(True)
        self.refresh_btn.setEnabled(True)
        # An auth error here just means "signed out" — the empty state already
        # says so, and a toast on top of it would be noise.
        if error.kind == "auth":
            self._render()
            return
        self.set_subtitle("Could not load the roster — " + error.summary)
        self.empty.set_text(
            "Could not load your friends",
            error.hint or "Check your connection and try again.",
        )
        self.ctx.show_error(error)

    def _render(self) -> None:
        self.filter.setEnabled(True)
        self.refresh_btn.setEnabled(True)
        signed_in = self.state.session.logged_in
        self.signed_out.setVisible(not signed_in)
        self.filter.setVisible(signed_in)
        while self.rows.count():
            item = self.rows.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not signed_in:
            self.empty.setVisible(False)
            self.transport_badge.setVisible(False)
            self.set_subtitle(self.subtitle)
            return

        needle = self.filter.text().strip().lower()
        friends = [
            f for f in self.state.friends
            if needle in f.label.lower() or needle in f.account_id.lower()
        ]
        self.empty.setVisible(not friends)
        if needle and not friends:
            self.empty.set_text("No matches", "No friend matches that search.")
        else:
            self.empty.set_text(
                "No friends yet",
                "When someone adds you on NeoFN they will show up here, with live "
                "presence while they are online.",
            )
        for i, friend in enumerate(friends):
            if i:
                self.rows.addWidget(hline())
            self.rows.addWidget(FriendRow(self.ctx, friend))

        transport = self.state.friends_transport
        self.transport_badge.setVisible(bool(transport))
        if transport == "xmpp":
            self.transport_badge.set_tone("success", "LIVE PRESENCE")
            self.set_subtitle(
                f"{len(self.state.friends)} friend(s) · presence over XMPP."
            )
        elif transport:
            self.transport_badge.set_tone("warning", "NO PRESENCE")
            self.set_subtitle(
                "The presence service was unreachable, so this list came from the "
                "REST API — online/offline is not available."
            )
