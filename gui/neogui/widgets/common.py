"""Shared building blocks: cards, labels, buttons, badges, empty states.

Everything here is theme-aware — widgets register with the Theme and restyle in
place when the palette changes, so switching dark/light never needs a restart.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import (
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRect,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QFrame,
    QLayout,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .. import icons
from ..theme import RADIUS, SPACE, Theme


# ---------------------------------------------------------------- primitives
def mnemonic_safe(text: str) -> str:
    """Qt reads `&` in button/label text as a mnemonic marker; we never use those,
    so a literal ampersand must be doubled or "Verify & repair" renders as
    "Verify _repair"."""
    return (text or "").replace("&", "&&")


def label(text: str = "", role: str = "body", parent=None, wrap: bool = False) -> QLabel:
    lb = QLabel(text, parent)
    lb.setObjectName(
        {
            "display": "Display",
            "title": "Title",
            "heading": "Heading",
            "body": "Body",
            "dim": "Dim",
            "small": "Small",
            "caption": "Caption",
            "mono": "Mono",
        }.get(role, "Body")
    )
    lb.setWordWrap(wrap)
    lb.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
    return lb


def selectable(lb: QLabel) -> QLabel:
    lb.setTextInteractionFlags(
        Qt.TextInteractionFlag.TextSelectableByMouse
        | Qt.TextInteractionFlag.TextSelectableByKeyboard
    )
    lb.setCursor(Qt.CursorShape.IBeamCursor)
    return lb


def hline(parent=None) -> QFrame:
    line = QFrame(parent)
    line.setObjectName("Divider")
    line.setFrameShape(QFrame.Shape.NoFrame)
    line.setFixedHeight(1)
    line.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    return line


def spacer(w: int = 0, h: int = 0) -> QWidget:
    s = QWidget()
    s.setFixedSize(QSize(w, h) if (w or h) else QSize(0, 0))
    if not w:
        s.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    if not h:
        s.setSizePolicy(s.sizePolicy().horizontalPolicy(), QSizePolicy.Policy.Expanding)
    return s


def hstretch() -> QWidget:
    s = QWidget()
    s.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    s.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    return s


class Card(QFrame):
    """The standard panel. `flat` is the inset variant used inside cards."""

    def __init__(self, parent=None, *, flat: bool = False, padding: int = SPACE["lg"]) -> None:
        super().__init__(parent)
        self.setObjectName("CardFlat" if flat else "Card")
        self.v = QVBoxLayout(self)
        self.v.setContentsMargins(padding, padding, padding, padding)
        self.v.setSpacing(SPACE["md"])

    def add(self, widget: QWidget, *, stretch: int = 0):
        self.v.addWidget(widget, stretch)
        return widget

    def add_layout(self, layout):
        self.v.addLayout(layout)
        return layout

    def add_stretch(self, n: int = 1):
        self.v.addStretch(n)


class SectionHeader(QWidget):
    """Caption + optional description + optional right-hand action slot."""

    def __init__(self, title: str, description: str = "", parent=None) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(SPACE["md"])
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)
        self.title = label(title, "heading")
        col.addWidget(self.title)
        self.description = label(description, "small", wrap=True)
        self.description.setVisible(bool(description))
        col.addWidget(self.description)
        row.addLayout(col, 1)
        self.actions = QHBoxLayout()
        self.actions.setContentsMargins(0, 0, 0, 0)
        self.actions.setSpacing(SPACE["sm"])
        row.addLayout(self.actions)

    def add_action(self, widget: QWidget):
        self.actions.addWidget(widget)
        return widget


class IconButton(QPushButton):
    def __init__(
        self,
        theme: Theme,
        name: str,
        tooltip: str = "",
        parent=None,
        *,
        size: int = 18,
        tone: str = "text_dim",
    ) -> None:
        super().__init__(parent)
        self.setObjectName("IconOnly")
        self._theme = theme
        self._name = name
        self._size = size
        self._tone = tone
        self.setIconSize(QSize(size, size))
        self.setToolTip(tooltip)
        self.setAccessibleName(tooltip or name)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAutoDefault(True)  # see Button: Enter must work outside dialogs too
        self.retheme()
        theme.changed.connect(self.retheme)

    def set_icon_name(self, name: str) -> None:
        self._name = name
        self.retheme()

    def retheme(self) -> None:
        self.setIcon(
            icons.icon(self._name, self._size, getattr(self._theme.p, self._tone))
        )


class Button(QPushButton):
    """Text button with an optional leading icon that follows the theme."""

    def __init__(
        self,
        text: str,
        theme: Theme | None = None,
        icon_name: str = "",
        parent=None,
        *,
        variant: str = "default",  # default | primary | ghost | danger | play
        on_click: Callable | None = None,
        tooltip: str = "",
    ) -> None:
        super().__init__(mnemonic_safe(text), parent)
        self.setObjectName(
            {
                "primary": "Primary",
                "ghost": "Ghost",
                "danger": "Danger",
                "play": "Play",
            }.get(variant, "")
        )
        self._theme = theme
        self._icon_name = icon_name
        self._variant = variant
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        # QPushButton only enables autoDefault inside a QDialog, so in the main
        # window Enter on a focused button did nothing while Space worked. Users
        # (and screen-reader users especially) expect both.
        self.setAutoDefault(True)
        if tooltip:
            self.setToolTip(tooltip)
        self.setAccessibleName(text or tooltip)
        if icon_name and theme is not None:
            self.setIconSize(QSize(17, 17))
            self.retheme()
            theme.changed.connect(self.retheme)
        if on_click:
            self.clicked.connect(on_click)

    def setText(self, text: str) -> None:
        super().setText(mnemonic_safe(text))

    def retheme(self) -> None:
        if not (self._icon_name and self._theme):
            return
        tone = {
            "primary": "on_accent",
            "play": "on_accent",
            "danger": "danger",
        }.get(self._variant, "text_dim")
        self.setIcon(icons.icon(self._icon_name, 17, getattr(self._theme.p, tone)))


class Badge(QLabel):
    """A pill. `tone` is one of accent/success/warning/danger/info/muted."""

    def __init__(self, text: str = "", tone: str = "muted", theme: Theme | None = None,
                 parent=None) -> None:
        super().__init__(text, parent)
        self._tone = tone
        self._theme = theme
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        if theme:
            self.retheme()
            theme.changed.connect(self.retheme)

    def set_tone(self, tone: str, text: str | None = None) -> None:
        self._tone = tone
        if text is not None:
            self.setText(text)
        self.retheme()

    def retheme(self) -> None:
        if not self._theme:
            return
        p = self._theme.p
        fg, bg = {
            "accent": (p.accent, p.accent_soft),
            "success": (p.success, p.success_soft),
            "warning": (p.warning, p.warning_soft),
            "danger": (p.danger, p.danger_soft),
            "info": (p.info, p.info_soft),
        }.get(self._tone, (p.text_dim, p.surface_alt))
        self.setStyleSheet(
            f"color: {fg}; background: {bg}; border-radius: {RADIUS['pill']}px;"
            f"padding: 3px 10px; font-size: 11px; font-weight: 700;"
            f"letter-spacing: 0.5px;"
        )


class StatusDot(QWidget):
    """A coloured dot with a soft halo — used everywhere a state is shown."""

    def __init__(self, theme: Theme, tone: str = "muted", parent=None, size: int = 10) -> None:
        super().__init__(parent)
        self._theme = theme
        self._tone = tone
        self._size = size
        self.setFixedSize(size + 6, size + 6)
        theme.changed.connect(self.update)

    def set_tone(self, tone: str) -> None:
        if tone != self._tone:
            self._tone = tone
            self.update()

    def paintEvent(self, event) -> None:
        p = self._theme.p
        color = QColor(
            {
                "success": p.success,
                "warning": p.warning,
                "danger": p.danger,
                "info": p.info,
                "accent": p.accent,
            }.get(self._tone, p.text_faint)
        )
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        halo = QColor(color)
        halo.setAlpha(58)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(halo)
        painter.drawEllipse(self.rect())
        painter.setBrush(color)
        r = self.rect().adjusted(3, 3, -3, -3)
        painter.drawEllipse(r)
        painter.end()


class Avatar(QWidget):
    """Initials on an accent gradient. No network avatars, no tracking."""

    def __init__(self, theme: Theme, size: int = 36, parent=None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._text = "?"
        self._size = size
        self.setFixedSize(size, size)
        theme.changed.connect(self.update)

    def set_text(self, text: str) -> None:
        self._text = (text or "?")[:2].upper()
        self.update()

    def paintEvent(self, event) -> None:
        from PySide6.QtGui import QLinearGradient

        p = self._theme.p
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        grad = QLinearGradient(0, 0, self.width(), self.height())
        grad.setColorAt(0.0, QColor(p.accent))
        grad.setColorAt(1.0, QColor(p.accent_press))
        path = QPainterPath()
        path.addRoundedRect(0, 0, self.width(), self.height(), self._size * 0.34,
                            self._size * 0.34)
        painter.fillPath(path, grad)
        f = QFont(self._theme.ui_family, max(9, int(self._size * 0.36)))
        f.setWeight(QFont.Weight.Bold)
        painter.setFont(f)
        painter.setPen(QColor(p.on_accent))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._text)
        painter.end()


class EmptyState(QWidget):
    """What a page shows when it has nothing — never a blank rectangle."""

    def __init__(
        self,
        theme: Theme,
        icon_name: str,
        title: str,
        body: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self._icon_name = icon_name
        v = QVBoxLayout(self)
        v.setContentsMargins(SPACE["xl"], SPACE["2xl"], SPACE["xl"], SPACE["2xl"])
        v.setSpacing(SPACE["sm"])
        v.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.glyph = QLabel()
        self.glyph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(self.glyph, 0, Qt.AlignmentFlag.AlignHCenter)
        v.addSpacing(SPACE["xs"])

        self.title = label(title, "heading")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(self.title)

        self.body = label(body, "small", wrap=True)
        self.body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.body.setMaximumWidth(420)
        self.body.setMinimumWidth(0)
        self.body.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self.body.setVisible(bool(body))
        v.addWidget(self.body, 0, Qt.AlignmentFlag.AlignHCenter)

        self.actions = QHBoxLayout()
        self.actions.setSpacing(SPACE["sm"])
        self.actions.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addSpacing(SPACE["sm"])
        v.addLayout(self.actions)

        self.retheme()
        theme.changed.connect(self.retheme)

    def add_action(self, widget: QWidget):
        self.actions.addWidget(widget)
        return widget

    def set_text(self, title: str, body: str = "") -> None:
        self.title.setText(title)
        self.body.setText(body)
        self.body.setVisible(bool(body))

    def retheme(self) -> None:
        self.glyph.setPixmap(
            icons.pixmap(self._icon_name, 40, self._theme.p.text_faint, width=1.4)
        )


class Field(QWidget):
    """A labelled setting row: title, help text, and a control on the right."""

    def __init__(
        self,
        title: str,
        control: QWidget,
        description: str = "",
        parent=None,
        *,
        stacked: bool = False,
    ) -> None:
        super().__init__(parent)
        self.control = control
        if stacked:
            outer = QVBoxLayout(self)
            outer.setSpacing(SPACE["sm"])
        else:
            outer = QHBoxLayout(self)
            outer.setSpacing(SPACE["lg"])
        outer.setContentsMargins(0, 0, 0, 0)

        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)
        self.title = label(mnemonic_safe(title), "body")
        self.title.setBuddy(control)
        col.addWidget(self.title)
        self.description = label(description, "small", wrap=True)
        self.description.setVisible(bool(description))
        col.addWidget(self.description)
        outer.addLayout(col, 1)
        if not stacked:
            control.setMinimumWidth(240)
        outer.addWidget(control, 0 if not stacked else 1)
        control.setAccessibleName(title)
        control.setAccessibleDescription(description)


class Toggle(QWidget):
    """An accessible switch. It is a real focusable control with Space/Enter."""

    toggled = Signal(bool)

    def __init__(self, theme: Theme, checked: bool = False, parent=None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._checked = checked
        self._pos = 1.0 if checked else 0.0
        self.setFixedSize(44, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("Toggle")
        theme.changed.connect(self.update)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, value: bool, *, emit: bool = False) -> None:
        value = bool(value)
        if value == self._checked:
            return
        self._checked = value
        self._animate()
        if emit:
            self.toggled.emit(value)

    def _animate(self) -> None:
        anim = QPropertyAnimation(self, b"knob", self)
        anim.setDuration(150)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.setStartValue(self._pos)
        anim.setEndValue(1.0 if self._checked else 0.0)
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        self._anim = anim

    def get_knob(self) -> float:
        return self._pos

    def set_knob(self, value: float) -> None:
        self._pos = value
        self.update()

    from PySide6.QtCore import Property

    knob = Property(float, get_knob, set_knob)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.setChecked(not self._checked, emit=True)
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.setChecked(not self._checked, emit=True)
            return
        super().keyPressEvent(event)

    def paintEvent(self, event) -> None:
        p = self._theme.p
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        track = QColor(p.accent) if self._checked else QColor(p.border_strong)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(track)
        painter.drawRoundedRect(self.rect(), 12, 12)
        if self.hasFocus():
            pen = QPen(QColor(p.accent_hover))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 11, 11)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#ffffff"))
        x = 3 + self._pos * (self.width() - 21)
        painter.drawEllipse(int(x), 3, 18, 18)
        painter.end()


def add_shadow(widget: QWidget, *, blur: int = 26, y: int = 6, alpha: int = 110) -> None:
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, y)
    effect.setColor(QColor(0, 0, 0, alpha))
    widget.setGraphicsEffect(effect)


def fade_in(widget: QWidget, duration: int = 180) -> None:
    """A short cross-fade when a page appears. Respects reduced-motion."""
    import os

    if os.environ.get("NEO_GUI_NO_ANIMATION"):
        return
    effect = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(effect)
    anim = QPropertyAnimation(effect, b"opacity", widget)
    anim.setDuration(duration)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    anim.finished.connect(lambda: widget.setGraphicsEffect(None))
    anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
    widget._fade_anim = anim


class FlowLayout(QLayout):
    """A layout that wraps its children onto the next line when they run out of room.

    Qt has no built-in equivalent, and button rows are exactly where a fixed
    QHBoxLayout breaks on a small laptop screen — the last actions simply get
    clipped off the edge. This keeps every action reachable at any width.
    """

    def __init__(self, parent=None, *, spacing: int = SPACE["sm"]) -> None:
        super().__init__(parent)
        self._items: list = []
        self._spacing = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._layout(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect) -> None:
        super().setGeometry(rect)
        self._layout(rect, apply=True)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(
            margins.left() + margins.right(), margins.top() + margins.bottom()
        )

    def _layout(self, rect, *, apply: bool) -> int:
        margins = self.contentsMargins()
        effective = rect.adjusted(
            margins.left(), margins.top(), -margins.right(), -margins.bottom()
        )
        x, y, line_height = effective.x(), effective.y(), 0
        for item in self._items:
            widget = item.widget()
            if widget is not None and not widget.isVisible():
                continue
            hint = item.sizeHint()
            next_x = x + hint.width() + self._spacing
            if next_x - self._spacing > effective.right() and line_height > 0:
                x = effective.x()
                y += line_height + self._spacing
                next_x = x + hint.width() + self._spacing
                line_height = 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y() + margins.bottom()
