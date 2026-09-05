"""The Play hero — the one thing on screen that matters most.

A gradient panel carrying the build identity, the launch button and, while a
launch or install is running, the live progress. It replaces itself in place
rather than swapping pages, so the primary action never moves under the cursor.
"""

from __future__ import annotations


from PySide6.QtCore import QPointF, QRectF, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QRadialGradient
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QProgressBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..theme import RADIUS, SPACE, Theme
from .common import Badge, Button, FlowLayout, IconButton, label


class HeroPanel(QFrame):
    launch_requested = Signal()
    stop_requested = Signal()
    install_requested = Signal()
    build_changed = Signal(str)
    configure_requested = Signal()

    def __init__(self, theme: Theme, parent=None) -> None:
        super().__init__(parent)
        self._theme = theme
        self.setObjectName("Hero")
        self.setMinimumHeight(210)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(SPACE["xl"], SPACE["xl"], SPACE["xl"], SPACE["xl"])
        outer.setSpacing(SPACE["md"])

        top = QHBoxLayout()
        top.setSpacing(SPACE["md"])
        self.eyebrow = label("NEOFN", "caption")
        top.addWidget(self.eyebrow)
        self.state_badge = Badge("READY", "success", theme)
        top.addWidget(self.state_badge)
        top.addStretch(1)
        self.session_badge = Badge("", "muted", theme)
        self.session_badge.setVisible(False)
        top.addWidget(self.session_badge)
        outer.addLayout(top)

        self.headline = label("Nothing installed yet", "display")
        self.headline.setWordWrap(False)
        outer.addWidget(self.headline)

        self.subline = label("Install a build to get started.", "dim")
        self.subline.setWordWrap(True)
        outer.addWidget(self.subline)

        outer.addStretch(1)

        # --- progress (shown only while something is running)
        self.progress_box = QWidget()
        pv = QVBoxLayout(self.progress_box)
        pv.setContentsMargins(0, 0, 0, 0)
        pv.setSpacing(SPACE["xs"])
        prow = QHBoxLayout()
        prow.setSpacing(SPACE["md"])
        self.progress_label = label("Working…", "body")
        prow.addWidget(self.progress_label)
        prow.addStretch(1)
        self.progress_detail = label("", "small")
        prow.addWidget(self.progress_detail)
        pv.addLayout(prow)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(8)
        self.progress.setRange(0, 100)
        pv.addWidget(self.progress)
        self.progress_box.setVisible(False)
        outer.addWidget(self.progress_box)

        # --- action row
        actions = FlowLayout(spacing=SPACE["md"])

        self.play_btn = Button("PLAY", theme, variant="play")
        self.play_btn.setMinimumWidth(180)
        self.play_btn.setToolTip("Launch the selected build  (Ctrl+L)")
        self.play_btn.setAccessibleName("Launch the game")
        self.play_btn.clicked.connect(self.launch_requested.emit)
        actions.addWidget(self.play_btn)

        self.cancel_btn = Button("Cancel", theme, "stop", variant="default")
        self.cancel_btn.setVisible(False)
        self.cancel_btn.clicked.connect(self.stop_requested.emit)
        actions.addWidget(self.cancel_btn)

        self.build_picker = QComboBox()
        self.build_picker.setMinimumWidth(230)
        self.build_picker.setToolTip("Which installed build to launch")
        self.build_picker.setAccessibleName("Build to launch")
        self.build_picker.currentIndexChanged.connect(self._picker_changed)
        actions.addWidget(self.build_picker)

        self.configure_btn = IconButton(theme, "settings", "Launch options", size=18)
        self.configure_btn.clicked.connect(self.configure_requested.emit)
        actions.addWidget(self.configure_btn)
        outer.addLayout(actions)

        self._versions: list = []
        self._mode = "idle"
        self.retheme()
        theme.changed.connect(self.retheme)

    # ------------------------------------------------------------------ data
    def set_builds(self, installs: list, current: str | None = None) -> None:
        self._versions = [i.version for i in installs]
        self.build_picker.blockSignals(True)
        self.build_picker.clear()
        for inst in installs:
            text = inst.short + (f"  ·  CL {inst.version.split('-CL-')[-1]}"
                                 if "-CL-" in inst.version else "")
            if not inst.exists:
                text += "  (missing)"
            self.build_picker.addItem(text, inst.version)
        if current and current in self._versions:
            self.build_picker.setCurrentIndex(self._versions.index(current))
        self.build_picker.blockSignals(False)
        self.build_picker.setVisible(len(installs) > 1)
        self.configure_btn.setVisible(bool(installs))

    def selected_version(self) -> str:
        return self.build_picker.currentData() or ""

    def _picker_changed(self, index: int) -> None:
        if 0 <= index < len(self._versions):
            self.build_changed.emit(self._versions[index])

    def set_headline(self, title: str, subtitle: str = "") -> None:
        self.headline.setText(title)
        self.subline.setText(subtitle)
        self.subline.setVisible(bool(subtitle))

    def set_state(self, text: str, tone: str) -> None:
        self.state_badge.set_tone(tone, text)

    def set_session_note(self, text: str, tone: str = "muted") -> None:
        self.session_badge.setVisible(bool(text))
        if text:
            self.session_badge.set_tone(tone, text)

    # ----------------------------------------------------------------- modes
    def set_mode(self, mode: str) -> None:
        """idle | busy | running | needs_install | needs_login"""
        self._mode = mode
        busy = mode in ("busy", "running")
        self.progress_box.setVisible(mode == "busy")
        self.cancel_btn.setVisible(mode == "busy")
        self.build_picker.setEnabled(not busy)
        if mode == "needs_install":
            self.play_btn.setText("INSTALL")
            self.play_btn.setEnabled(True)
            self.play_btn.setToolTip("Download and install the live build")
        elif mode == "needs_login":
            self.play_btn.setText("SIGN IN")
            self.play_btn.setEnabled(True)
            self.play_btn.setToolTip("Sign in with Discord to continue")
        elif mode == "running":
            self.play_btn.setText("RUNNING")
            self.play_btn.setEnabled(False)
            self.play_btn.setToolTip("The game is running")
        elif mode == "busy":
            self.play_btn.setText("WORKING…")
            self.play_btn.setEnabled(False)
            self.play_btn.setToolTip("")
        else:
            self.play_btn.setText("PLAY")
            self.play_btn.setEnabled(True)
            self.play_btn.setToolTip("Launch the selected build  (Ctrl+L)")

    @property
    def mode(self) -> str:
        return self._mode

    def set_progress(self, label_text: str, percent: int | None, detail: str = "") -> None:
        self.progress_label.setText(label_text)
        self.progress_detail.setText(detail)
        if percent is None:
            self.progress.setRange(0, 0)
        else:
            self.progress.setRange(0, 100)
            self.progress.setValue(max(0, min(100, percent)))

    # ---------------------------------------------------------------- paint
    def retheme(self) -> None:
        self.update()

    def paintEvent(self, event) -> None:
        p = self._theme.p
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, RADIUS["xl"], RADIUS["xl"])

        base = QLinearGradient(rect.topLeft(), rect.bottomRight())
        if p.is_dark:
            base.setColorAt(0.0, QColor(p.elevated))
            base.setColorAt(1.0, QColor(p.surface))
        else:
            base.setColorAt(0.0, QColor("#ffffff"))
            base.setColorAt(1.0, QColor(p.surface_alt))
        painter.fillPath(path, base)

        painter.setClipPath(path)
        glow = QRadialGradient(
            QPointF(rect.right() - rect.width() * 0.16, rect.top() - rect.height() * 0.28),
            rect.width() * 0.62,
        )
        accent = QColor(p.accent)
        accent.setAlpha(96 if p.is_dark else 52)
        glow.setColorAt(0.0, accent)
        accent_fade = QColor(p.accent)
        accent_fade.setAlpha(0)
        glow.setColorAt(1.0, accent_fade)
        painter.fillRect(rect, glow)

        cool = QRadialGradient(
            QPointF(rect.left() + rect.width() * 0.06, rect.bottom() + rect.height() * 0.3),
            rect.width() * 0.5,
        )
        c2 = QColor(p.info)
        c2.setAlpha(52 if p.is_dark else 30)
        cool.setColorAt(0.0, c2)
        c2f = QColor(p.info)
        c2f.setAlpha(0)
        cool.setColorAt(1.0, c2f)
        painter.fillRect(rect, cool)
        painter.setClipping(False)

        painter.setPen(QColor(p.border))
        painter.drawPath(path)
        painter.end()
