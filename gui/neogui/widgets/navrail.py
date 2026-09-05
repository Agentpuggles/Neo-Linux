"""The left navigation rail: brand, destinations, account chip.

Collapses to icons-only under 1080px so the app stays usable on a small laptop
without a hamburger menu or a hidden drawer.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .. import icons
from ..theme import SPACE, Theme
from .common import Avatar, StatusDot, label

EXPANDED = 216
COLLAPSED = 66


class NavButton(QPushButton):
    def __init__(self, theme: Theme, key: str, text: str, icon_name: str,
                 shortcut: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self.key = key
        self.full_text = text
        self._theme = theme
        self._icon_name = icon_name
        self.setObjectName("NavButton")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAutoDefault(True)  # Enter activates a focused rail item, as Space does
        self.setIconSize(QSize(19, 19))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(38)
        self.setAccessibleName(text)
        self.setToolTip(f"{text}{f'  ({shortcut})' if shortcut else ''}")
        self.retheme()
        theme.changed.connect(self.retheme)

    def retheme(self) -> None:
        tone = self._theme.p.text if self.isChecked() else self._theme.p.text_dim
        self.setIcon(icons.icon(self._icon_name, 19, tone))

    def set_collapsed(self, collapsed: bool) -> None:
        self.setText("" if collapsed else self.full_text)
        self.setStyleSheet("padding: 9px;" if collapsed else "")


class NavRail(QFrame):
    navigate = Signal(str)
    account_clicked = Signal()

    def __init__(self, theme: Theme, destinations: list, parent=None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._collapsed = False
        self.setObjectName("NavRail")
        self.setFixedWidth(EXPANDED)

        v = QVBoxLayout(self)
        v.setContentsMargins(SPACE["md"], SPACE["lg"], SPACE["md"], SPACE["md"])
        v.setSpacing(SPACE["sm"])

        # ------------------------------------------------------------- brand
        brand = QWidget()
        bh = QHBoxLayout(brand)
        bh.setContentsMargins(SPACE["xs"], 0, 0, 0)
        bh.setSpacing(SPACE["sm"])
        self.logo = QLabel()
        self.logo.setFixedSize(28, 28)
        bh.addWidget(self.logo)
        self.wordmark = label("Neo", "heading")
        bh.addWidget(self.wordmark)
        bh.addStretch(1)
        v.addWidget(brand)
        v.addSpacing(SPACE["md"])

        # -------------------------------------------------------- destinations
        self.group = QButtonGroup(self)
        # Not exclusive: destinations like Account live outside the rail, and an
        # exclusive group refuses to let every button go unchecked.
        self.group.setExclusive(False)
        self.buttons: dict = {}
        for i, (key, text, icon_name) in enumerate(destinations, 1):
            shortcut = f"Ctrl+{i}"
            btn = NavButton(theme, key, text, icon_name, shortcut)
            btn.clicked.connect(lambda _=False, k=key: self.navigate.emit(k))
            self.group.addButton(btn)
            self.buttons[key] = btn
            v.addWidget(btn)
            sc = QShortcut(QKeySequence(shortcut), self)
            sc.activated.connect(lambda k=key: self.navigate.emit(k))

        v.addStretch(1)

        # ------------------------------------------------------ account chip
        self.chip = QPushButton()
        self.chip.setObjectName("AccountChip")
        self.chip.setCursor(Qt.CursorShape.PointingHandCursor)
        self.chip.setMinimumHeight(52)
        self.chip.setToolTip("Account  (Ctrl+7)")
        self.chip.setAccessibleName("Account")
        self.chip.clicked.connect(self.account_clicked.emit)
        chip_layout = QHBoxLayout(self.chip)
        chip_layout.setContentsMargins(SPACE["sm"], SPACE["xs"], SPACE["sm"], SPACE["xs"])
        chip_layout.setSpacing(SPACE["sm"])
        self.avatar = Avatar(theme, 30)
        chip_layout.addWidget(self.avatar)
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        self.chip_name = label("Signed out", "body")
        col.addWidget(self.chip_name)
        state_row = QHBoxLayout()
        state_row.setContentsMargins(0, 0, 0, 0)
        state_row.setSpacing(SPACE["xs"])
        self.chip_dot = StatusDot(theme, "muted", size=7)
        state_row.addWidget(self.chip_dot)
        self.chip_state = label("Not connected", "small")
        state_row.addWidget(self.chip_state, 1)
        col.addLayout(state_row)
        chip_layout.addLayout(col, 1)
        self.chip_widgets = [self.chip_name, self.chip_state, self.chip_dot]
        v.addWidget(self.chip)

        self.version_label = label("", "caption")
        self.version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(self.version_label)

        self.retheme()
        theme.changed.connect(self.retheme)

    # ------------------------------------------------------------------- api
    def set_active(self, key: str) -> None:
        for name, btn in self.buttons.items():
            btn.setChecked(name == key)
            btn.retheme()
        self.chip.setProperty("active", "true" if key == "account" else "false")
        self.chip.style().unpolish(self.chip)
        self.chip.style().polish(self.chip)

    def set_account(self, session, status) -> None:
        self.avatar.set_text(session.initials if session.logged_in else "?")
        self.chip_name.setText(session.label if session.logged_in else "Sign in")
        if not session.logged_in:
            self.chip_dot.set_tone("muted")
            self.chip_state.setText("Not signed in")
        elif status.banned or status.prism_banned:
            self.chip_dot.set_tone("danger")
            self.chip_state.setText("Account banned")
        elif status.access_ok:
            self.chip_dot.set_tone("success")
            self.chip_state.setText("Ready to play")
        elif status.access_denied:
            self.chip_dot.set_tone("warning")
            self.chip_state.setText("No game access")
        elif status.reachable:
            self.chip_dot.set_tone("success")
            self.chip_state.setText("Signed in")
        else:
            self.chip_dot.set_tone("muted")
            self.chip_state.setText("Offline")
        self.chip.setToolTip(f"{self.chip_name.text()} — {self.chip_state.text()}  (Ctrl+7)")

    def set_version(self, text: str) -> None:
        self.version_label.setText(text)

    def set_collapsed(self, collapsed: bool) -> None:
        if collapsed == self._collapsed:
            return
        self._collapsed = collapsed
        self.setFixedWidth(COLLAPSED if collapsed else EXPANDED)
        self.wordmark.setVisible(not collapsed)
        self.version_label.setVisible(not collapsed)
        for widget in self.chip_widgets:
            widget.setVisible(not collapsed)
        for btn in self.buttons.values():
            btn.set_collapsed(collapsed)

    def retheme(self) -> None:
        self.logo.setPixmap(
            icons.app_icon(28).pixmap(28, 28)
        )
        for btn in self.buttons.values():
            btn.retheme()
