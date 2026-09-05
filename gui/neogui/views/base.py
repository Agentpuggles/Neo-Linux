"""Shared scaffolding for the top-level pages."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from ..theme import SPACE, Theme
from ..widgets.common import label


class View(QWidget):
    """A page in the main stack.

    Provides a consistent header (title + subtitle + action slot) and a
    scrollable body with a max content width, so nothing stretches into
    unreadable line lengths on a 4K monitor while still filling a laptop screen.
    """

    title = "Neo"
    subtitle = ""
    max_content_width = 1180

    def __init__(self, ctx, parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.theme: Theme = ctx.theme
        self.state = ctx.state
        self.service = ctx.service
        self.tasks = ctx.tasks
        self._built = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QWidget()
        header.setObjectName("Header")
        hv = QVBoxLayout(header)
        hv.setContentsMargins(SPACE["xl"], SPACE["lg"], SPACE["xl"], SPACE["md"])
        hv.setSpacing(2)
        row = QHBoxLayout()
        row.setSpacing(SPACE["md"])
        self.title_label = label(self.title, "title")
        row.addWidget(self.title_label)
        row.addStretch(1)
        self.header_actions = QHBoxLayout()
        self.header_actions.setSpacing(SPACE["sm"])
        row.addLayout(self.header_actions)
        hv.addLayout(row)
        self.subtitle_label = label(self.subtitle, "small", wrap=True)
        self.subtitle_label.setVisible(bool(self.subtitle))
        hv.addWidget(self.subtitle_label)
        root.addWidget(header)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        holder = QWidget()
        hz = QHBoxLayout(holder)
        hz.setContentsMargins(SPACE["xl"], SPACE["sm"], SPACE["xl"], SPACE["xl"])
        hz.addStretch(1)
        self.content = QWidget()
        self.content.setMaximumWidth(self.max_content_width)
        self.body = QVBoxLayout(self.content)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(SPACE["lg"])
        hz.addWidget(self.content, 20)
        hz.addStretch(1)
        self.scroll.setWidget(holder)
        root.addWidget(self.scroll, 1)

    def add_header_action(self, widget: QWidget):
        self.header_actions.addWidget(widget)
        return widget

    def set_subtitle(self, text: str) -> None:
        self.subtitle_label.setText(text)
        self.subtitle_label.setVisible(bool(text))

    # ------------------------------------------------------------ lifecycle
    def on_first_show(self) -> None:
        """Called once, the first time the page is shown (lazy loading)."""

    def on_show(self) -> None:
        """Called every time the page becomes visible."""

    def refresh(self) -> None:
        """F5 / the refresh button."""

    def _enter(self) -> None:
        if not self._built:
            self._built = True
            self.on_first_show()
        self.on_show()
