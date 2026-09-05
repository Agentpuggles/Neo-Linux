"""A small, self-contained icon set.

Icons are SVG paths compiled to QIcon at the requested colour and DPR. Drawing
them ourselves rather than depending on the desktop's icon theme is what keeps
the app looking identical on Plasma, GNOME, XFCE and a bare wlroots session —
Qt's theme lookup returns wildly different (or missing) glyphs across those.

All paths are drawn on a 24×24 grid, stroked, round caps/joins — one visual
weight across the whole set.
"""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

STROKE = {
    "play": "M8 5.5 19 12 8 18.5z",
    "library": "M4 5h6v14H4zM14 5h6v6h-6zM14 14h6v5h-6z",
    "friends": "M16 19v-1.6a3.4 3.4 0 0 0-3.4-3.4H6.4A3.4 3.4 0 0 0 3 17.4V19M9.5 10.6a3.3 3.3 0 1 0 0-6.6 3.3 3.3 0 0 0 0 6.6M21 19v-1.6a3.4 3.4 0 0 0-2.6-3.3M15.4 4.2a3.3 3.3 0 0 1 0 6.4",
    "activity": "M3 12h3.5l2.5-7 4 14 2.5-7H21",
    "diagnostics": "M9 4h6M12 4v5M6.5 9h11l1.5 9a2 2 0 0 1-2 2.2H7a2 2 0 0 1-2-2.2zM8 15h8",
    "settings": "M12 15.2a3.2 3.2 0 1 0 0-6.4 3.2 3.2 0 0 0 0 6.4M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-2.9 1.2v.2a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0-1.2-2.9h-.2a2 2 0 1 1 0-4h.1A1.7 1.7 0 0 0 4.6 9a1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3h.1A1.7 1.7 0 0 0 10.1 3v-.2a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 2.9 1.2l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9v.1a1.7 1.7 0 0 0 1.5 1h.2a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1.1z",
    "download": "M12 3.5v11M7.5 10 12 14.5 16.5 10M4.5 19.5h15",
    "refresh": "M20 5.5v5h-5M4 18.5v-5h5M19.2 9.4A7.5 7.5 0 0 0 6.3 7.1L4 9.5M4.8 14.6a7.5 7.5 0 0 0 12.9 2.3L20 14.5",
    "check": "M4.5 12.5 9.5 17.5 19.5 6.5",
    "close": "M6 6l12 12M18 6 6 18",
    "warning": "M12 4 2.8 20h18.4zM12 10v4.5M12 17.4v.2",
    "error": "M12 3.2a8.8 8.8 0 1 0 0 17.6 8.8 8.8 0 0 0 0-17.6M12 7.6v5M12 15.6v.2",
    "info": "M12 3.2a8.8 8.8 0 1 0 0 17.6 8.8 8.8 0 0 0 0-17.6M12 11v5.4M12 7.8v.2",
    "folder": "M3.5 6.5A1.5 1.5 0 0 1 5 5h4l2 2.5h8a1.5 1.5 0 0 1 1.5 1.5v8.5A1.5 1.5 0 0 1 19 19H5a1.5 1.5 0 0 1-1.5-1.5z",
    "copy": "M9 9h9.5a1 1 0 0 1 1 1v9.5a1 1 0 0 1-1 1H9a1 1 0 0 1-1-1V10a1 1 0 0 1 1-1M6 15H5a1 1 0 0 1-1-1V4.5a1 1 0 0 1 1-1h9.5a1 1 0 0 1 1 1V6",
    "external": "M14 4h6v6M20 4l-9 9M18 14v5.5a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 4 19.5v-11A1.5 1.5 0 0 1 5.5 7H11",
    "trash": "M4.5 6.5h15M9 6.5V4.8A1.3 1.3 0 0 1 10.3 3.5h3.4A1.3 1.3 0 0 1 15 4.8v1.7M6.5 6.5l1 13a1.5 1.5 0 0 0 1.5 1.4h6a1.5 1.5 0 0 0 1.5-1.4l1-13M10 10.5v6M14 10.5v6",
    "search": "M11 18.2a7.2 7.2 0 1 0 0-14.4 7.2 7.2 0 0 0 0 14.4M20.5 20.5l-4.3-4.3",
    "user": "M12 12.5a4.2 4.2 0 1 0 0-8.4 4.2 4.2 0 0 0 0 8.4M4.5 20.5a7.5 7.5 0 0 1 15 0",
    "logout": "M15.5 16.5 20 12l-4.5-4.5M20 12H9M12 20H5.5A1.5 1.5 0 0 1 4 18.5v-13A1.5 1.5 0 0 1 5.5 4H12",
    "login": "M10 7.5 14.5 12 10 16.5M14.5 12h-11M12 4h6.5A1.5 1.5 0 0 1 20 5.5v13a1.5 1.5 0 0 1-1.5 1.5H12",
    "discord": "M8.4 6.6a15 15 0 0 1 7.2 0M8.4 6.6C5.6 8 4 11.4 4 15.6c1.8 1.4 3.6 2.2 5.3 2.4l1-1.6M15.6 6.6c2.8 1.4 4.4 4.8 4.4 9-1.8 1.4-3.6 2.2-5.3 2.4l-1-1.6M9.6 13.2a1 1 0 1 0 0-.2M14.4 13.2a1 1 0 1 0 0-.2",
    "chevron-right": "M9.5 5.5 16 12l-6.5 6.5",
    "chevron-down": "M5.5 9.5 12 16l6.5-6.5",
    "chevron-left": "M14.5 5.5 8 12l6.5 6.5",
    "plus": "M12 5v14M5 12h14",
    "shield": "M12 3.2 4.8 6v6c0 4.3 2.9 7.7 7.2 8.8 4.3-1.1 7.2-4.5 7.2-8.8V6z",
    "shield-check": "M12 3.2 4.8 6v6c0 4.3 2.9 7.7 7.2 8.8 4.3-1.1 7.2-4.5 7.2-8.8V6zM9 12l2.2 2.2L15.2 10",
    "wrench": "M20 6.4a5 5 0 0 1-6.7 6.7L6.6 19.8a2 2 0 0 1-2.9-2.9l6.7-6.7A5 5 0 0 1 17.1 3.5l-3 3 1.4 3.4L19 8.5z",
    "terminal": "M5 6.5 10 12l-5 5.5M12.5 17.5h6.5",
    "file-text": "M13.5 3.5H7A1.5 1.5 0 0 0 5.5 5v14A1.5 1.5 0 0 0 7 20.5h10a1.5 1.5 0 0 0 1.5-1.5V8.5zM13.5 3.5V8.5h5M9 12.5h6M9 16h6",
    "clock": "M12 3.5a8.5 8.5 0 1 0 0 17 8.5 8.5 0 0 0 0-17M12 7v5.3l3.4 2",
    "cloud": "M7.2 18.5a4.2 4.2 0 0 1-.4-8.4A5.6 5.6 0 0 1 17.6 9.9a3.8 3.8 0 0 1 .3 8.6z",
    "gauge": "M12 20.5a8.5 8.5 0 1 1 8.5-8.5M12 12l4.2-3.4",
    "sparkle": "M12 3.5 13.8 9 19.5 10.8 13.8 12.6 12 18.2 10.2 12.6 4.5 10.8 10.2 9zM18.5 16.5l.7 2 2 .7-2 .7-.7 2-.7-2-2-.7 2-.7z",
    "pause": "M9 5.5v13M15 5.5v13",
    "stop": "M6.5 6.5h11v11h-11z",
    "bell": "M18 9a6 6 0 1 0-12 0c0 5-2 6.5-2 6.5h16S18 14 18 9M13.7 19a2 2 0 0 1-3.4 0",
    "gamepad": "M7.5 11h3M9 9.5v3M15 11h.1M17 13h.1M8.5 6.5h7A5.5 5.5 0 0 1 21 12v.6a4.4 4.4 0 0 1-7.9 2.6l-.3-.4h-1.6l-.3.4A4.4 4.4 0 0 1 3 12.6V12a5.5 5.5 0 0 1 5.5-5.5",
    "hdd": "M4 13.5h16M6.5 4.5h11l2.5 9v4.5a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 18V13.5zM7.5 16.5h.2M11 16.5h.2",
    "link": "M10 13.5a3.6 3.6 0 0 0 5.4.4l2.6-2.6a3.6 3.6 0 0 0-5.1-5.1l-1.5 1.5M14 10.5a3.6 3.6 0 0 0-5.4-.4L6 12.7a3.6 3.6 0 0 0 5.1 5.1l1.5-1.5",
    "eye": "M2.5 12S6 5.8 12 5.8 21.5 12 21.5 12 18 18.2 12 18.2 2.5 12 2.5 12M12 14.9a2.9 2.9 0 1 0 0-5.8 2.9 2.9 0 0 0 0 5.8",
    "import": "M12 14.5v-11M7.5 8 12 3.5 16.5 8M4.5 15.5v3a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2v-3",
    "filter": "M4 5.5h16l-6.2 7.3v5.4l-3.6 2v-7.4z",
    "palette": "M12 3.5a8.5 8.5 0 0 0 0 17c1.4 0 2.3-.9 2.3-2 0-.6-.2-1-.6-1.4-.4-.4-.6-.8-.6-1.3 0-1 .9-1.8 2-1.8h1.3c2.3 0 3.6-1.4 3.6-3.6 0-3.8-3.6-6.9-8-6.9M7.5 12.5h.2M9.5 8.5h.2M14 7.5h.2",
    "menu": "M4 7h16M4 12h16M4 17h16",
    "key": "M15.5 3.5a5 5 0 1 0-4.3 7.6L4 18.3v2.2h2.6l1-1h2v-2h2l1.6-1.6a5 5 0 0 0 2.3-12.4M16.8 7.8h.2",
}

# Aliases so views can name things semantically.
STROKE["home"] = STROKE["play"]
STROKE["success"] = STROKE["check"]
STROKE["verify"] = STROKE["shield-check"]

_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
    'stroke="{color}" stroke-width="{width}" stroke-linecap="round" '
    'stroke-linejoin="round"><path d="{path}"/></svg>'
)


@lru_cache(maxsize=1024)
def _pixmap(name: str, size: int, color: str, width: float, dpr: float) -> QPixmap:
    path = STROKE.get(name) or STROKE["info"]
    svg = _SVG.format(color=color, width=width, path=path)
    renderer = QSvgRenderer(QByteArray(svg.encode()))
    px = QPixmap(int(size * dpr), int(size * dpr))
    px.setDevicePixelRatio(dpr)
    px.fill(Qt.GlobalColor.transparent)
    painter = QPainter(px)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    renderer.render(painter, QRectF(0, 0, size * dpr, size * dpr))
    painter.end()
    return px


def pixmap(name: str, size: int = 18, color: str = "#ffffff", width: float = 1.7) -> QPixmap:
    from PySide6.QtGui import QGuiApplication

    app = QGuiApplication.instance()
    dpr = app.devicePixelRatio() if app else 1.0
    dpr = max(1.0, round(float(dpr) * 2) / 2)
    return _pixmap(name, size, color, width, dpr)


def icon(name: str, size: int = 18, color: str = "#ffffff", width: float = 1.7) -> QIcon:
    ic = QIcon()
    px = pixmap(name, size, color, width)
    ic.addPixmap(px, QIcon.Mode.Normal, QIcon.State.Off)
    faded = QPixmap(px.size())
    faded.setDevicePixelRatio(px.devicePixelRatio())
    faded.fill(Qt.GlobalColor.transparent)
    painter = QPainter(faded)
    painter.setOpacity(0.42)
    painter.drawPixmap(0, 0, px)
    painter.end()
    ic.addPixmap(faded, QIcon.Mode.Disabled, QIcon.State.Off)
    return ic


def app_icon(size: int = 256, accent: str = "#8b5cf6", accent2: str = "#22d3ee") -> QIcon:
    """The Neo mark, rendered at any size. Used for the window and the tray."""
    from PySide6.QtGui import QGuiApplication

    app = QGuiApplication.instance()
    dpr = max(1.0, float(app.devicePixelRatio()) if app else 1.0)
    svg = app_icon_svg(accent, accent2)
    renderer = QSvgRenderer(QByteArray(svg.encode()))
    result = QIcon()
    for s in (16, 24, 32, 48, 64, 128, 256):
        px = QPixmap(int(s * dpr), int(s * dpr))
        px.setDevicePixelRatio(dpr)
        px.fill(Qt.GlobalColor.transparent)
        painter = QPainter(px)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        renderer.render(painter, QRectF(0, 0, s * dpr, s * dpr))
        painter.end()
        result.addPixmap(px)
    return result


def app_icon_svg(accent: str = "#8b5cf6", accent2: str = "#22d3ee") -> str:
    """The N mark inside a rounded squircle — the product icon.

    Written as plain SVG so the same source produces the window icon, the tray
    icon and the installed hicolor icon.
    """
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" width="256" height="256">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#1b1e29"/>
      <stop offset="1" stop-color="#0a0b10"/>
    </linearGradient>
    <linearGradient id="mark" x1="0" y1="1" x2="1" y2="0">
      <stop offset="0" stop-color="{accent}"/>
      <stop offset="1" stop-color="{accent2}"/>
    </linearGradient>
    <linearGradient id="rim" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{accent}" stop-opacity="0.85"/>
      <stop offset="1" stop-color="{accent2}" stop-opacity="0.25"/>
    </linearGradient>
  </defs>
  <rect x="12" y="12" width="232" height="232" rx="58" fill="url(#bg)"/>
  <rect x="13.5" y="13.5" width="229" height="229" rx="56.5" fill="none"
        stroke="url(#rim)" stroke-width="3"/>
  <path d="M78 182V74h22l56 74V74h22v108h-22L100 108v74z" fill="url(#mark)"/>
  <circle cx="178" cy="80" r="9" fill="{accent2}"/>
</svg>"""


def clear_cache() -> None:
    """Called on theme change — icons are tinted, so they must be re-rendered."""
    _pixmap.cache_clear()
