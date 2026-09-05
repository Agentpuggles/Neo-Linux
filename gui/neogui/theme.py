"""The Neo design language.

One token set, two palettes. Everything visual in the app resolves from here —
views never hard-code a colour, a radius or a font size, so the whole product
re-skins from this file and dark/light stay in step.

The language itself: near-black graphite surfaces with a violet-to-cyan accent
(taken from the Neo mark), one elevation step per layer, 8px rhythm, 10px radii,
and exactly one strong colour on screen at a time so the primary action is never
ambiguous.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication, QPalette

# ------------------------------------------------------------------ tokens
SPACE = {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24, "2xl": 32, "3xl": 48}
RADIUS = {"sm": 6, "md": 10, "lg": 14, "xl": 20, "pill": 999}

ACCENTS = {
    "violet": ("#8b5cf6", "#a78bfa", "#6d28d9"),
    "cyan": ("#06b6d4", "#22d3ee", "#0e7490"),
    "emerald": ("#10b981", "#34d399", "#047857"),
    "amber": ("#f59e0b", "#fbbf24", "#b45309"),
    "rose": ("#f43f5e", "#fb7185", "#be123c"),
    "blue": ("#3b82f6", "#60a5fa", "#1d4ed8"),
}


@dataclass(frozen=True)
class Palette:
    name: str
    # surfaces, darkest → lightest in dark mode (inverted in light)
    canvas: str
    surface: str
    surface_alt: str
    elevated: str
    overlay: str
    # lines
    border: str
    border_strong: str
    # text
    text: str
    text_dim: str
    text_faint: str
    on_accent: str
    # accents
    accent: str
    accent_hover: str
    accent_press: str
    accent_soft: str
    # semantic
    success: str
    warning: str
    danger: str
    info: str
    success_soft: str
    warning_soft: str
    danger_soft: str
    info_soft: str
    shadow: str
    scrim: str

    @property
    def is_dark(self) -> bool:
        return self.name == "dark"


def _soft(hex_color: str, alpha: int) -> str:
    c = QColor(hex_color)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {alpha / 255:.3f})"


def build_palette(mode: str, accent_key: str) -> Palette:
    accent, hover, press = ACCENTS.get(accent_key, ACCENTS["violet"])
    if mode == "light":
        return Palette(
            name="light",
            canvas="#f4f5f8",
            surface="#ffffff",
            surface_alt="#f8f9fc",
            elevated="#ffffff",
            overlay="#ffffff",
            border="#e2e5ec",
            border_strong="#cfd4df",
            text="#12141a",
            text_dim="#525a6b",
            text_faint="#858da0",
            on_accent="#ffffff",
            accent=accent,
            accent_hover=press,
            accent_press=press,
            accent_soft=_soft(accent, 34),
            success="#0f9960",
            warning="#b26b00",
            danger="#d33a3a",
            info="#2563eb",
            success_soft=_soft("#0f9960", 30),
            warning_soft=_soft("#b26b00", 30),
            danger_soft=_soft("#d33a3a", 30),
            info_soft=_soft("#2563eb", 30),
            shadow="rgba(15, 18, 28, 0.10)",
            scrim="rgba(12, 14, 20, 0.42)",
        )
    return Palette(
        name="dark",
        canvas="#0b0c11",
        surface="#101218",
        surface_alt="#15171f",
        elevated="#191c25",
        overlay="#1c1f2a",
        border="#23262f",
        border_strong="#2f333f",
        text="#f2f4f8",
        text_dim="#9aa1b1",
        text_faint="#6b7284",
        on_accent="#ffffff",
        accent=accent,
        accent_hover=hover,
        accent_press=press,
        accent_soft=_soft(accent, 40),
        success="#3ddc84",
        warning="#f7b955",
        danger="#ff6b6b",
        info="#7da2ff",
        success_soft=_soft("#3ddc84", 34),
        warning_soft=_soft("#f7b955", 34),
        danger_soft=_soft("#ff6b6b", 34),
        info_soft=_soft("#7da2ff", 34),
        shadow="rgba(0, 0, 0, 0.45)",
        scrim="rgba(4, 5, 9, 0.62)",
    )


# ------------------------------------------------------------------ typography
UI_FAMILIES = (
    "Inter",
    "Inter Display",
    "Cantarell",
    "Noto Sans",
    "Ubuntu",
    "DejaVu Sans",
    "Liberation Sans",
)
MONO_FAMILIES = (
    "JetBrains Mono",
    "Fira Code",
    "Cascadia Mono",
    "Source Code Pro",
    "Noto Sans Mono",
    "Ubuntu Mono",
    "DejaVu Sans Mono",
    "monospace",
)


def pick_family(candidates) -> str:
    available = set(QFontDatabase.families())
    for name in candidates:
        if name in available:
            return name
    return candidates[-1]


TYPE = {
    "display": (30, QFont.Weight.DemiBold),
    "title": (21, QFont.Weight.DemiBold),
    "heading": (15, QFont.Weight.DemiBold),
    "body": (13, QFont.Weight.Normal),
    "small": (12, QFont.Weight.Normal),
    "caption": (11, QFont.Weight.Medium),
    "mono": (12, QFont.Weight.Normal),
}


class Theme(QObject):
    """Live theme. Changing mode or accent restyles the running app."""

    changed = Signal()

    def __init__(self, mode: str = "system", accent: str = "violet", parent=None) -> None:
        super().__init__(parent)
        self._mode = mode
        self._accent = accent if accent in ACCENTS else "violet"
        self.ui_family = pick_family(UI_FAMILIES)
        self.mono_family = pick_family(MONO_FAMILIES)
        self.p = build_palette(self.resolved_mode(), self._accent)

    # ------------------------------------------------------------------ mode
    def resolved_mode(self) -> str:
        if self._mode in ("dark", "light"):
            return self._mode
        return detect_system_mode()

    @property
    def mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str) -> None:
        if mode == self._mode:
            return
        self._mode = mode
        self._rebuild()

    @property
    def accent(self) -> str:
        return self._accent

    def set_accent(self, accent: str) -> None:
        if accent == self._accent or accent not in ACCENTS:
            return
        self._accent = accent
        self._rebuild()

    def system_mode_changed(self) -> None:
        if self._mode == "system":
            self._rebuild()

    def _rebuild(self) -> None:
        self.p = build_palette(self.resolved_mode(), self._accent)
        self.changed.emit()

    # ----------------------------------------------------------------- fonts
    def font(self, role: str = "body") -> QFont:
        size, weight = TYPE.get(role, TYPE["body"])
        family = self.mono_family if role == "mono" else self.ui_family
        f = QFont(family, size)
        f.setWeight(weight)
        if role == "display":
            f.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 98)
        if role == "caption":
            f.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 104)
        return f

    def color(self, name: str) -> QColor:
        return QColor(getattr(self.p, name))

    # ------------------------------------------------------------------- QSS
    def stylesheet(self) -> str:
        p = self.p
        return QSS_TEMPLATE.format(
            p=p,
            ui=self.ui_family,
            mono=self.mono_family,
            r_sm=RADIUS["sm"],
            r_md=RADIUS["md"],
            r_lg=RADIUS["lg"],
            r_xl=RADIUS["xl"],
            hover=_hover_layer(p),
            press=_press_layer(p),
        )

    def qpalette(self) -> QPalette:
        p = self.p
        pal = QPalette()
        role = QPalette.ColorRole
        pal.setColor(role.Window, QColor(p.canvas))
        pal.setColor(role.WindowText, QColor(p.text))
        pal.setColor(role.Base, QColor(p.surface))
        pal.setColor(role.AlternateBase, QColor(p.surface_alt))
        pal.setColor(role.Text, QColor(p.text))
        pal.setColor(role.PlaceholderText, QColor(p.text_faint))
        pal.setColor(role.Button, QColor(p.surface_alt))
        pal.setColor(role.ButtonText, QColor(p.text))
        pal.setColor(role.Highlight, QColor(p.accent))
        pal.setColor(role.HighlightedText, QColor(p.on_accent))
        pal.setColor(role.ToolTipBase, QColor(p.overlay))
        pal.setColor(role.ToolTipText, QColor(p.text))
        pal.setColor(role.Link, QColor(p.accent_hover))
        group = QPalette.ColorGroup.Disabled
        pal.setColor(group, role.WindowText, QColor(p.text_faint))
        pal.setColor(group, role.Text, QColor(p.text_faint))
        pal.setColor(group, role.ButtonText, QColor(p.text_faint))
        return pal


def _hover_layer(p: Palette) -> str:
    return "rgba(255, 255, 255, 0.06)" if p.is_dark else "rgba(10, 14, 24, 0.05)"


def _press_layer(p: Palette) -> str:
    return "rgba(255, 255, 255, 0.10)" if p.is_dark else "rgba(10, 14, 24, 0.09)"


def detect_system_mode() -> str:
    """Follow the desktop. Portal setting first, then Qt's own palette."""
    forced = os.environ.get("NEO_GUI_THEME", "").lower()
    if forced in ("dark", "light"):
        return forced

    scheme = _portal_color_scheme()
    if scheme in ("dark", "light"):
        return scheme

    app = QGuiApplication.instance()
    if app is not None:
        try:
            hint = app.styleHints().colorScheme()
            from PySide6.QtCore import Qt

            if hint == Qt.ColorScheme.Light:
                return "light"
            if hint == Qt.ColorScheme.Dark:
                return "dark"
        except Exception:
            pass
        window = app.palette().color(QPalette.ColorRole.Window)
        if window.isValid() and window.lightness() > 127:
            return "light"
    return "dark"


def _portal_color_scheme() -> str:
    """xdg-desktop-portal org.freedesktop.appearance color-scheme (0/1/2).

    Works on every DE that ships a portal (GNOME, Plasma, XFCE with
    xdg-desktop-portal-gtk, wlroots compositors, COSMIC) and silently gives up
    everywhere else.
    """
    try:
        from PySide6.QtDBus import QDBusConnection, QDBusInterface
    except ImportError:
        return ""
    try:
        bus = QDBusConnection.sessionBus()
        if not bus.isConnected():
            return ""
        iface = QDBusInterface(
            "org.freedesktop.portal.Desktop",
            "/org/freedesktop/portal/desktop",
            "org.freedesktop.portal.Settings",
            bus,
        )
        if not iface.isValid():
            return ""
        reply = iface.call("Read", "org.freedesktop.appearance", "color-scheme")
        args = reply.arguments()
        if not args:
            return ""
        value = args[0]
        for _ in range(4):  # unwrap nested variants
            if hasattr(value, "variant"):
                value = value.variant()
            else:
                break
        value = int(value)
        return {1: "dark", 2: "light"}.get(value, "")
    except Exception:
        return ""


QSS_TEMPLATE = """
* {{
    font-family: "{ui}";
    outline: 0;
}}
QWidget {{
    color: {p.text};
    background: transparent;
}}
QMainWindow, #RootSurface {{
    background: {p.canvas};
}}
QToolTip {{
    background: {p.overlay};
    color: {p.text};
    border: 1px solid {p.border_strong};
    border-radius: {r_sm}px;
    padding: 6px 9px;
    font-size: 12px;
}}

/* ------------------------------------------------------------ navigation */
#NavRail {{
    background: {p.surface};
    border-right: 1px solid {p.border};
}}
#NavButton {{
    border: none;
    border-radius: {r_md}px;
    padding: 9px 12px;
    text-align: left;
    color: {p.text_dim};
    font-size: 13px;
    font-weight: 500;
    background: transparent;
}}
#NavButton:hover {{ background: {hover}; color: {p.text}; }}
#NavButton:checked {{
    background: {p.accent_soft};
    color: {p.text};
    font-weight: 600;
}}
#NavButton:focus {{ border: 1px solid {p.accent}; }}
#NavSection {{
    color: {p.text_faint};
    font-size: 11px;
    font-weight: 600;
    padding: 0 12px;
}}
#AccountChip {{
    background: {p.surface_alt};
    border: 1px solid {p.border};
    border-radius: {r_md}px;
    padding: 8px;
    text-align: left;
}}
#AccountChip:hover {{ border-color: {p.border_strong}; background: {p.elevated}; }}
#AccountChip:focus {{ border-color: {p.accent}; }}
#AccountChip[active="true"] {{ background: {p.accent_soft}; border-color: {p.accent}; }}

/* ---------------------------------------------------------------- surfaces */
#Card {{
    background: {p.surface};
    border: 1px solid {p.border};
    border-radius: {r_lg}px;
}}
#CardFlat {{
    background: {p.surface_alt};
    border: 1px solid {p.border};
    border-radius: {r_md}px;
}}
#Hero {{
    border: 1px solid {p.border};
    border-radius: {r_xl}px;
}}
#Divider {{ background: {p.border}; border: none; }}
#Header {{ background: {p.canvas}; }}

/* ----------------------------------------------------------------- labels */
#Display {{ font-size: 30px; font-weight: 600; color: {p.text}; }}
#Title {{ font-size: 21px; font-weight: 600; color: {p.text}; }}
#Heading {{ font-size: 15px; font-weight: 600; color: {p.text}; }}
#Body {{ font-size: 13px; color: {p.text}; }}
#Dim {{ font-size: 13px; color: {p.text_dim}; }}
#Small {{ font-size: 12px; color: {p.text_dim}; }}
#Caption {{
    font-size: 11px; font-weight: 600; color: {p.text_faint};
    letter-spacing: 0.6px;
}}
#Mono {{ font-family: "{mono}"; font-size: 12px; color: {p.text_dim}; }}

/* ---------------------------------------------------------------- buttons */
QPushButton {{
    background: {p.surface_alt};
    color: {p.text};
    border: 1px solid {p.border};
    border-radius: {r_md}px;
    padding: 8px 15px;
    font-size: 13px;
    font-weight: 500;
    min-height: 18px;
}}
QPushButton:hover {{ background: {p.elevated}; border-color: {p.border_strong}; }}
QPushButton:pressed {{ background: {press}; }}
QPushButton:focus {{ border-color: {p.accent}; }}
QPushButton:disabled {{ color: {p.text_faint}; background: {p.surface}; border-color: {p.border}; }}

QPushButton#Primary {{
    background: {p.accent};
    color: {p.on_accent};
    border: 1px solid {p.accent};
    font-weight: 600;
}}
QPushButton#Primary:hover {{ background: {p.accent_hover}; border-color: {p.accent_hover}; }}
QPushButton#Primary:pressed {{ background: {p.accent_press}; }}
QPushButton#Primary:disabled {{
    background: {p.surface_alt}; color: {p.text_faint}; border-color: {p.border};
}}
QPushButton#Danger {{ color: {p.danger}; border-color: {p.danger_soft}; }}
QPushButton#Danger:hover {{ background: {p.danger_soft}; }}
QPushButton#Ghost {{ background: transparent; border-color: transparent; color: {p.text_dim}; }}
QPushButton#Ghost:hover {{ background: {hover}; color: {p.text}; }}
QPushButton#Ghost:focus {{ border-color: {p.accent}; }}
QPushButton#IconOnly {{ padding: 7px; border-radius: {r_md}px; }}
QPushButton#Play {{
    background: {p.accent};
    color: {p.on_accent};
    border: none;
    border-radius: {r_md}px;
    font-size: 16px;
    font-weight: 700;
    padding: 14px 40px;
    letter-spacing: 0.4px;
}}
QPushButton#Play:hover {{ background: {p.accent_hover}; }}
QPushButton#Play:pressed {{ background: {p.accent_press}; }}
QPushButton#Play:disabled {{ background: {p.surface_alt}; color: {p.text_faint}; }}

/* ------------------------------------------------------------------ input */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QComboBox {{
    background: {p.surface_alt};
    border: 1px solid {p.border};
    border-radius: {r_md}px;
    padding: 8px 11px;
    color: {p.text};
    font-size: 13px;
    selection-background-color: {p.accent};
    selection-color: {p.on_accent};
}}
QLineEdit:hover, QSpinBox:hover, QComboBox:hover {{ border-color: {p.border_strong}; }}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus, QComboBox:focus {{
    border-color: {p.accent};
}}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{ color: {p.text_faint}; }}
QLineEdit[invalid="true"] {{ border-color: {p.danger}; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox::down-arrow {{ image: none; }}
QComboBox QAbstractItemView {{
    background: {p.overlay};
    border: 1px solid {p.border_strong};
    border-radius: {r_md}px;
    padding: 4px;
    selection-background-color: {p.accent_soft};
    selection-color: {p.text};
    outline: 0;
}}
QSpinBox::up-button, QSpinBox::down-button {{ width: 0; border: none; }}
QPlainTextEdit, QTextEdit {{ font-family: "{mono}"; }}

/* ------------------------------------------------------------------ lists */
QListWidget, QTreeWidget, QTableWidget {{
    background: transparent;
    border: none;
    outline: 0;
}}
QListWidget::item {{ border-radius: {r_md}px; padding: 2px; }}
QListWidget::item:hover {{ background: {hover}; }}
QListWidget::item:selected {{ background: {p.accent_soft}; }}

/* -------------------------------------------------------------- scrollbars */
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{
    background: transparent; width: 10px; margin: 2px 2px 2px 0;
}}
QScrollBar::handle:vertical {{
    background: {p.border_strong}; border-radius: 4px; min-height: 32px;
}}
QScrollBar::handle:vertical:hover {{ background: {p.text_faint}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0 2px 2px 2px; }}
QScrollBar::handle:horizontal {{
    background: {p.border_strong}; border-radius: 4px; min-width: 32px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; border: none; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* -------------------------------------------------------------- progress */
QProgressBar {{
    background: {p.surface_alt};
    border: none;
    border-radius: 5px;
    height: 8px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{ background: {p.accent}; border-radius: 5px; }}

/* --------------------------------------------------------------- switches */
QCheckBox, QRadioButton {{ font-size: 13px; spacing: 9px; color: {p.text}; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 18px; height: 18px; }}
QCheckBox::indicator {{
    border: 1px solid {p.border_strong};
    border-radius: 5px;
    background: {p.surface_alt};
}}
QCheckBox::indicator:hover {{ border-color: {p.accent}; }}
QCheckBox::indicator:checked {{ background: {p.accent}; border-color: {p.accent}; }}

/* ------------------------------------------------------------------- tabs */
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{
    background: transparent;
    color: {p.text_dim};
    padding: 7px 14px;
    margin-right: 4px;
    border-radius: {r_md}px;
    font-size: 13px;
    font-weight: 500;
}}
QTabBar::tab:hover {{ background: {hover}; color: {p.text}; }}
QTabBar::tab:selected {{ background: {p.accent_soft}; color: {p.text}; font-weight: 600; }}

/* ------------------------------------------------------------------ menus */
QMenu {{
    background: {p.overlay};
    border: 1px solid {p.border_strong};
    border-radius: {r_md}px;
    padding: 5px;
}}
QMenu::item {{ padding: 7px 26px 7px 12px; border-radius: {r_sm}px; font-size: 13px; }}
QMenu::item:selected {{ background: {p.accent_soft}; }}
QMenu::separator {{ height: 1px; background: {p.border}; margin: 5px 8px; }}
QMenuBar {{ background: {p.surface}; }}
QMenuBar::item {{ padding: 6px 10px; border-radius: {r_sm}px; }}
QMenuBar::item:selected {{ background: {hover}; }}

/* ---------------------------------------------------------------- dialogs */
QDialog {{ background: {p.canvas}; }}
QSplitter::handle {{ background: {p.border}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}
"""
