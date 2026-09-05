"""In-window notifications.

Transient feedback belongs in the window, not in a modal box the user has to
dismiss. Toasts stack bottom-right, auto-dismiss, and errors carry a "Details"
affordance so the technical text is one click away instead of in the way.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QTimer,
    Qt,
)
from PySide6.QtGui import QRegion
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from .. import icons
from ..theme import RADIUS, SPACE, Theme
from .common import Button, IconButton, label

TONE_ICON = {
    "success": "check",
    "warning": "warning",
    "danger": "error",
    "error": "error",
    "info": "info",
    "accent": "sparkle",
}


class Toast(QFrame):
    def __init__(
        self,
        theme: Theme,
        text: str,
        tone: str = "info",
        parent=None,
        *,
        detail: str = "",
        action_text: str = "",
        on_action: Callable | None = None,
        timeout: int = 5200,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self._tone = tone
        self.setObjectName("ToastCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMaximumWidth(400)
        self.setMinimumWidth(320)

        row = QHBoxLayout(self)
        row.setContentsMargins(SPACE["md"], SPACE["md"], SPACE["sm"], SPACE["md"])
        row.setSpacing(SPACE["md"])

        self.glyph = QLabel()
        self.glyph.setFixedSize(20, 20)
        row.addWidget(self.glyph, 0, Qt.AlignmentFlag.AlignTop)

        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(SPACE["xs"])
        self.message = label(text, "body", wrap=True)
        self.message.setAccessibleName(f"{tone} notification")
        col.addWidget(self.message)

        self.detail_label = label(detail, "mono", wrap=True)
        self.detail_label.setVisible(False)
        self.detail_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.detail_label.setMaximumHeight(160)
        col.addWidget(self.detail_label)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(SPACE["sm"])
        if detail:
            self.details_btn = Button("Details", theme, variant="ghost")
            self.details_btn.setFixedHeight(26)
            self.details_btn.clicked.connect(self._toggle_detail)
            buttons.addWidget(self.details_btn)
        if action_text and on_action:
            act = Button(action_text, theme, variant="ghost")
            act.setFixedHeight(26)
            act.clicked.connect(lambda: (on_action(), self.dismiss()))
            buttons.addWidget(act)
        buttons.addStretch(1)
        if detail or (action_text and on_action):
            col.addLayout(buttons)
        row.addLayout(col, 1)

        self.close_btn = IconButton(theme, "close", "Dismiss", size=14)
        self.close_btn.clicked.connect(self.dismiss)
        row.addWidget(self.close_btn, 0, Qt.AlignmentFlag.AlignTop)

        self.retheme()
        theme.changed.connect(self.retheme)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)
        if timeout and not detail:
            self._timer.start(timeout)
        elif timeout:
            self._timer.start(int(timeout * 1.8))

    def _toggle_detail(self) -> None:
        shown = not self.detail_label.isVisible()
        self.detail_label.setVisible(shown)
        self.details_btn.setText("Hide details" if shown else "Details")
        if shown:
            self._timer.stop()
        self.adjustSize()
        if self.parent():
            self.parent().reflow()

    def enterEvent(self, event):
        self._timer.stop()
        super().enterEvent(event)

    def retheme(self) -> None:
        p = self._theme.p
        fg = {
            "success": p.success,
            "warning": p.warning,
            "danger": p.danger,
            "error": p.danger,
            "info": p.info,
            "accent": p.accent,
        }.get(self._tone, p.info)
        self.setStyleSheet(
            f"#ToastCard {{ background: {p.overlay}; border: 1px solid {p.border_strong};"
            f"border-left: 3px solid {fg}; border-radius: {RADIUS['md']}px; }}"
        )
        self.glyph.setPixmap(icons.pixmap(TONE_ICON.get(self._tone, "info"), 20, fg))

    def dismiss(self) -> None:
        effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", self)
        anim.setDuration(150)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.finished.connect(self._remove)
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        self._anim = anim

    def _remove(self) -> None:
        host = self.parent()
        self.setParent(None)
        self.deleteLater()
        if isinstance(host, ToastHost):
            host.forget(self)


class ToastHost(QWidget):
    """Transparent overlay pinned to the bottom-right of the window.

    The host is stretched over the *whole* window so toasts can be positioned
    freely, which makes it the topmost child everywhere — including on top of
    every button in the app. Mouse input has to be handled deliberately:

      * `WA_TransparentForMouseEvents` on the host is not usable, because Qt
        propagates it to children during hit-testing, so the toasts' own
        Details/Dismiss buttons would stop working too.
      * Instead the host carries a *mask* covering only the rectangles the
        toasts actually occupy. Clicks inside a toast reach the toast; clicks
        anywhere else fall straight through to the UI underneath.

    `reflow()` is the single place that repositions toasts, so it is also the
    single place that keeps the mask in sync.
    """

    MAX = 4

    # A mask that is empty is treated by Qt as "no mask at all" (the widget
    # goes back to swallowing everything), so "click-through everywhere" has to
    # be expressed as a one-pixel region outside the widget instead.
    _NO_INPUT = QRegion(-1, -1, 1, 1)

    def __init__(self, theme: Theme, parent=None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._toasts: list = []
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setMask(self._NO_INPUT)

    def show_toast(self, text: str, tone: str = "info", **kwargs) -> Toast:
        while len(self._toasts) >= self.MAX:
            self._toasts[0].dismiss()
            self._toasts.pop(0)
        toast = Toast(self._theme, text, tone, self, **kwargs)
        toast.adjustSize()
        self._toasts.append(toast)
        toast.show()
        self.reflow()
        self._slide_in(toast)
        return toast

    def show_error(self, error, **kwargs) -> Toast:
        detail = "\n".join(x for x in (error.hint, error.detail) if x)
        return self.show_toast(error.summary, "danger", detail=detail, **kwargs)

    def _slide_in(self, toast: Toast) -> None:
        import os

        if os.environ.get("NEO_GUI_NO_ANIMATION"):
            return
        end = toast.geometry()
        start = end.translated(0, 18)
        anim = QPropertyAnimation(toast, b"geometry", toast)
        anim.setDuration(170)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.setStartValue(start)
        anim.setEndValue(end)
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        toast._slide = anim

    def forget(self, toast: Toast) -> None:
        if toast in self._toasts:
            self._toasts.remove(toast)
        self.reflow()

    def reflow(self) -> None:
        margin = SPACE["lg"]
        y = self.height() - margin
        for toast in reversed(self._toasts):
            toast.adjustSize()
            w = max(320, min(toast.sizeHint().width(), 400))
            h = toast.sizeHint().height()
            y -= h
            toast.setGeometry(self.width() - w - margin, y, w, h)
            y -= SPACE["sm"]
        self._sync_mask()

    def _sync_mask(self) -> None:
        """Accept mouse input only where a toast is actually drawn.

        Without this the overlay covers the window and eats every click meant
        for the app underneath it.
        """
        region = QRegion()
        for toast in self._toasts:
            if toast.isVisible() or not toast.isHidden():
                region = region.united(QRegion(toast.geometry()))
        self.setMask(region if not region.isEmpty() else self._NO_INPUT)

    def resizeEvent(self, event):
        self.reflow()
        super().resizeEvent(event)
