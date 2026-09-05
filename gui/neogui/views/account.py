"""Account — session state, display name, entitlements, sign in/out.

Nothing sensitive is rendered: the account id is shown because it is what
support asks for, but access and refresh tokens never leave `auth.json`.
"""

from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QVBoxLayout, QWidget

from ..backend.errors import NeoError
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
    selectable,
)
from ..widgets.dialogs import ConfirmDialog
from .base import View


class AccountView(View):
    title = "Account"
    subtitle = "Your NeoFN session, display name and entitlements."
    max_content_width = 860

    def __init__(self, ctx, parent=None) -> None:
        super().__init__(ctx, parent)
        self.refresh_btn = IconButton(self.theme, "refresh", "Reload account details  (F5)")
        self.refresh_btn.clicked.connect(self.refresh)
        self.add_header_action(self.refresh_btn)

        # ------------------------------------------------------------ signed in
        self.profile_card = Card()
        top = QHBoxLayout()
        top.setSpacing(SPACE["lg"])
        self.avatar = Avatar(self.theme, 60)
        top.addWidget(self.avatar, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(SPACE["xs"])
        name_row = QHBoxLayout()
        name_row.setSpacing(SPACE["md"])
        self.name_label = label("—", "title")
        name_row.addWidget(self.name_label)
        self.session_badge = Badge("SIGNED IN", "success", self.theme)
        name_row.addWidget(self.session_badge, 0, Qt.AlignmentFlag.AlignVCenter)
        name_row.addStretch(1)
        col.addLayout(name_row)
        self.id_label = selectable(label("", "mono"))
        col.addWidget(self.id_label)
        self.email_label = label("", "small")
        col.addWidget(self.email_label)
        top.addLayout(col, 1)
        self.profile_card.add_layout(top)
        self.profile_card.add(hline())

        actions = QHBoxLayout()
        actions.setSpacing(SPACE["sm"])
        actions.addWidget(
            Button(
                "Copy account ID",
                self.theme,
                "copy",
                on_click=self._copy_id,
                tooltip="What NeoFN support will ask you for",
            )
        )
        actions.addStretch(1)
        actions.addWidget(
            Button("Sign out", self.theme, "logout", variant="danger", on_click=self._sign_out)
        )
        self.profile_card.add_layout(actions)
        self.body.addWidget(self.profile_card)

        # ---------------------------------------------------------- name setup
        self.name_card = Card()
        self.name_card.add(
            SectionHeader(
                "Display name",
                "The name other players see. It can only be set once, so choose "
                "carefully — 3 to 16 characters.",
            )
        )
        self.name_card.add(hline())
        name_row2 = QWidget()
        nh = QHBoxLayout(name_row2)
        nh.setContentsMargins(0, 0, 0, 0)
        nh.setSpacing(SPACE["sm"])
        self.name_field = QLineEdit()
        self.name_field.setPlaceholderText("Choose a display name")
        self.name_field.setMaxLength(16)
        self.name_field.setAccessibleName("Display name")
        self.name_field.textChanged.connect(self._name_typed)
        nh.addWidget(self.name_field, 1)
        self.check_btn = Button("Check", self.theme, "search", on_click=self._check_name)
        nh.addWidget(self.check_btn)
        self.claim_btn = Button(
            "Claim name", self.theme, "check", variant="primary", on_click=self._claim_name
        )
        self.claim_btn.setEnabled(False)
        nh.addWidget(self.claim_btn)
        self.name_card.add(name_row2)
        self.name_hint = label("", "small", wrap=True)
        self.name_card.add(self.name_hint)
        self.body.addWidget(self.name_card)

        # ------------------------------------------------------------- access
        self.access_card = Card()
        self.access_card.add(
            SectionHeader("Access & entitlements", "What NeoFN has enabled for this account.")
        )
        self.access_card.add(hline())
        self.access_rows = QVBoxLayout()
        self.access_rows.setSpacing(SPACE["md"])
        self.access_card.add_layout(self.access_rows)
        self.body.addWidget(self.access_card)

        # ----------------------------------------------------------- signed out
        self.signed_out = EmptyState(
            self.theme,
            "user",
            "You are signed out",
            "Neo signs in through NeoFN's Discord flow. The session token is stored "
            "in your home directory with owner-only permissions and is never shown "
            "in this window.",
        )
        self.signed_out.add_action(
            Button("Sign in with Discord", self.theme, "discord", variant="primary",
                   on_click=self.ctx.open_login)
        )
        self.body.addWidget(self.signed_out)
        self.body.addStretch(1)

        self.state.session_changed.connect(lambda *_: self._render())
        self.state.status_changed.connect(lambda *_: self._render())

    def on_first_show(self) -> None:
        self._render()

    def on_show(self) -> None:
        self._render()

    def refresh(self) -> None:
        self.state.refresh_session()
        self.state.refresh_status()

    # ---------------------------------------------------------------- render
    def _render(self) -> None:
        session = self.state.session
        signed_in = session.logged_in
        self.profile_card.setVisible(signed_in)
        self.access_card.setVisible(signed_in)
        self.signed_out.setVisible(not signed_in)
        self.name_card.setVisible(signed_in and not session.display_name)

        if not signed_in:
            return

        self.avatar.set_text(session.initials)
        self.name_label.setText(session.display_name or "No display name yet")
        self.id_label.setText(session.account_id)
        self.email_label.setText(session.email or "")
        self.email_label.setVisible(bool(session.email))

        expiry = self._expiry_text(session.refresh_expires_at)
        self.session_badge.set_tone("success", "SIGNED IN")
        self.session_badge.setToolTip(expiry)

        while self.access_rows.count():
            item = self.access_rows.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        status = self.state.status
        rows = [
            (
                "Game access",
                "Granted" if status.fortnite_access else
                ("Not granted" if status.fortnite_access is False else "Unknown"),
                "success" if status.fortnite_access else
                ("warning" if status.fortnite_access is False else "muted"),
                "" if status.fortnite_access else
                "NeoFN enables play per account. During private testing this stays "
                "off until they grant it.",
            ),
            (
                "Service ban",
                "Banned" if status.banned else "None",
                "danger" if status.banned else "success",
                status.ban_reason,
            ),
            (
                "Anti-cheat ban",
                "Banned" if status.prism_banned else
                ("None" if status.prism_banned is False else "Unknown"),
                "danger" if status.prism_banned else
                ("success" if status.prism_banned is False else "muted"),
                status.prism_reason,
            ),
            (
                "Store entitlements",
                status.entitlements or "None on file",
                "info" if status.entitlements else "muted",
                "",
            ),
            ("Session", expiry, "muted", ""),
        ]
        for title, value, tone, note in rows:
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(SPACE["md"])
            h.addWidget(StatusDot(self.theme, tone, size=8), 0, Qt.AlignmentFlag.AlignTop)
            col = QVBoxLayout()
            col.setContentsMargins(0, 0, 0, 0)
            col.setSpacing(1)
            head = QHBoxLayout()
            head.setSpacing(SPACE["md"])
            key = label(title, "caption")
            key.setMinimumWidth(150)
            head.addWidget(key)
            head.addWidget(label(value, "body"), 1)
            col.addLayout(head)
            if note:
                col.addWidget(label(note, "small", wrap=True))
            h.addLayout(col, 1)
            self.access_rows.addWidget(row)

    @staticmethod
    def _expiry_text(iso: str) -> str:
        if not iso:
            return "Active"
        try:
            when = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        except ValueError:
            return "Active"
        delta = when - datetime.now(timezone.utc)
        days = delta.days
        if days > 1:
            return f"Active — renews automatically, valid for another {days} days"
        if delta.total_seconds() > 0:
            return "Active — expires soon, Neo will refresh it automatically"
        return "Expired — sign in again"

    # --------------------------------------------------------------- actions
    def _copy_id(self) -> None:
        copy_to_clipboard(self.state.session.account_id)
        self.ctx.toast("Account ID copied.", "info")

    def _sign_out(self) -> None:
        if ConfirmDialog(
            self.ctx,
            title="Sign out of Neo?",
            body="Your stored session is deleted. Installed builds and settings stay.",
            confirm_text="Sign out",
            destructive=True,
        ).exec():
            self.ctx.sign_out()

    def _name_typed(self, text: str) -> None:
        self.claim_btn.setEnabled(False)
        self.name_hint.setText("")
        self.check_btn.setEnabled(3 <= len(text.strip()) <= 16)

    def _check_name(self) -> None:
        name = self.name_field.text().strip()
        self.check_btn.setEnabled(False)
        self.tasks.run(
            self.service.display_name_available,
            name,
            key="checkname",
            action="Checking that name",
            on_result=lambda available: self._name_checked(name, available),
            on_error=self._name_error,
        )

    def _name_checked(self, name: str, available: bool) -> None:
        self.check_btn.setEnabled(True)
        p = self.theme.p
        if available:
            self.name_hint.setText(f"“{name}” is available.")
            self.name_hint.setStyleSheet(f"color: {p.success}; font-size: 12px;")
            self.claim_btn.setEnabled(True)
        else:
            self.name_hint.setText(f"“{name}” is already taken — try another.")
            self.name_hint.setStyleSheet(f"color: {p.warning}; font-size: 12px;")
            self.claim_btn.setEnabled(False)

    def _name_error(self, error: NeoError) -> None:
        self.check_btn.setEnabled(True)
        self.ctx.show_error(error)

    def _claim_name(self) -> None:
        name = self.name_field.text().strip()
        if not ConfirmDialog(
            self.ctx,
            title=f"Claim “{name}”?",
            body="Display names cannot be changed afterwards.",
            confirm_text="Claim it",
        ).exec():
            return
        self.claim_btn.setEnabled(False)
        self.tasks.run(
            self.service.set_display_name,
            name,
            key="setname",
            action="Setting your display name",
            on_result=self._name_claimed,
            on_error=self._name_error,
        )

    def _name_claimed(self, confirmed: str) -> None:
        self.ctx.toast(f"You are now {confirmed}.", "success")
        self.state.log_activity(f"Display name set to {confirmed}")
        self.state.refresh_session()
