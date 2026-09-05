"""Settings — categorised, not a wall of fields.

General, Appearance, Game, Launch, Network, Advanced. Everything writes through
`AppState.set_config`, which means the CLI sees the same values immediately —
the GUI has no private config of its own beyond the `gui_*` keys.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..backend.errors import NeoError
from ..platform_integration import (
    APP_ID,
    copy_to_clipboard,
    install_desktop_entry,
    is_desktop_entry_installed,
    open_path,
    register_scheme_handler,
    remove_desktop_entry,
    scheme_handler_owner,
    session_summary,
    tray_available,
)
from ..theme import ACCENTS, SPACE
from ..widgets.common import (
    Badge,
    Button,
    Card,
    Field,
    IconButton,
    SectionHeader,
    Toggle,
    hline,
    label,
    selectable,
)
from ..widgets.dialogs import ConfirmDialog
from .base import View


class PathField(QWidget):
    def __init__(self, ctx, value: str, *, on_change, dialog_title: str) -> None:
        super().__init__()
        self.on_change = on_change
        self.dialog_title = dialog_title
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(SPACE["sm"])
        self.field = QLineEdit(value)
        self.field.setAccessibleName(dialog_title)
        self.field.editingFinished.connect(self._commit)
        row.addWidget(self.field, 1)
        row.addWidget(Button("Browse", ctx.theme, "folder", on_click=self._browse))
        self.open_btn = IconButton(ctx.theme, "external", "Open this folder", size=15)
        self.open_btn.clicked.connect(lambda: open_path(self.field.text()))
        row.addWidget(self.open_btn)

    def _browse(self) -> None:
        start = os.path.expanduser(self.field.text() or "~")
        folder = QFileDialog.getExistingDirectory(self, self.dialog_title, start)
        if folder:
            self.field.setText(folder)
            self._commit()

    def _commit(self) -> None:
        self.on_change(self.field.text().strip())

    def set_value(self, value: str) -> None:
        if self.field.text() != value:
            self.field.setText(value)


class SettingsView(View):
    title = "Settings"
    subtitle = "Neo shares these settings with the command-line launcher."
    max_content_width = 900

    def __init__(self, ctx, parent=None) -> None:
        super().__init__(ctx, parent)
        self._loading = False

        self.config_btn = Button(
            "Open config file", self.theme, "file-text",
            on_click=lambda: open_path(os.path.dirname(self.service.config_path())),
            tooltip=self.service.config_path(),
        )
        self.add_header_action(self.config_btn)

        self.body.addWidget(self._general())
        self.body.addWidget(self._appearance())
        self.body.addWidget(self._game())
        self.body.addWidget(self._launch())
        self.body.addWidget(self._network())
        self.body.addWidget(self._integration())
        self.body.addWidget(self._advanced())
        self.body.addStretch(1)

        self.state.config_changed.connect(self.load)
        self.state.cache_changed.connect(self._render_cache)

    # ---------------------------------------------------------------- panels
    def _general(self) -> Card:
        card = Card()
        card.add(SectionHeader("General", "How Neo behaves day to day."))
        card.add(hline())

        self.notify_toggle = Toggle(self.theme)
        self.notify_toggle.toggled.connect(
            lambda v: self._set("gui_notify_on_finish", v)
        )
        card.add(
            Field(
                "Desktop notifications",
                self.notify_toggle,
                "Tell me when a download, repair or launch finishes — even when the "
                "window is in the background.",
            )
        )

        self.tray_toggle = Toggle(self.theme)
        self.tray_toggle.toggled.connect(lambda v: self._set("gui_minimise_to_tray", v))
        tray_field = Field(
            "Keep running in the tray",
            self.tray_toggle,
            "Closing the window leaves Neo in the system tray instead of quitting."
            + ("" if tray_available() else "  Your desktop has no tray, so this does nothing."),
        )
        self.tray_toggle.setEnabled(tray_available())
        card.add(tray_field)

        self.confirm_toggle = Toggle(self.theme)
        self.confirm_toggle.toggled.connect(lambda v: self._set("gui_confirm_launch", v))
        card.add(
            Field(
                "Show the command before launching",
                self.confirm_toggle,
                "Preview the exact umu command line (with credentials masked) and "
                "confirm before the game starts.",
            )
        )

        self.advanced_toggle = Toggle(self.theme)
        self.advanced_toggle.toggled.connect(self._set_advanced)
        card.add(
            Field(
                "Advanced mode",
                self.advanced_toggle,
                "Reveal the developer and debugging sections throughout the app.",
            )
        )
        return card

    def _appearance(self) -> Card:
        card = Card()
        card.add(SectionHeader("Appearance", "Neo follows your desktop by default."))
        card.add(hline())

        self.theme_picker = QComboBox()
        self.theme_picker.setAccessibleName("Theme")
        for text, value in (("Follow the system", "system"), ("Dark", "dark"), ("Light", "light")):
            self.theme_picker.addItem(text, value)
        self.theme_picker.currentIndexChanged.connect(self._set_theme)
        card.add(
            Field(
                "Theme",
                self.theme_picker,
                "“Follow the system” reads your desktop's colour-scheme preference "
                "through the portal, so it works on GNOME, Plasma, XFCE and wlroots alike.",
            )
        )

        accent_row = QWidget()
        ah = QHBoxLayout(accent_row)
        ah.setContentsMargins(0, 0, 0, 0)
        ah.setSpacing(SPACE["sm"])
        self.accent_buttons = {}
        for key, (colour, _hover, _press) in ACCENTS.items():
            swatch = Button("", self.theme)
            swatch.setFixedSize(30, 30)
            swatch.setToolTip(key.title())
            swatch.setAccessibleName(f"{key} accent colour")
            swatch.setStyleSheet(
                f"background: {colour}; border-radius: 15px; border: 2px solid transparent;"
            )
            swatch.clicked.connect(lambda _=False, k=key: self._set_accent(k))
            self.accent_buttons[key] = swatch
            ah.addWidget(swatch)
        ah.addStretch(1)
        card.add(Field("Accent colour", accent_row, "Used for the primary action and highlights."))
        return card

    def _game(self) -> Card:
        card = Card()
        card.add(SectionHeader("Game", "Where builds and downloads live."))
        card.add(hline())

        self.install_root = PathField(
            self.ctx, "", on_change=lambda v: self._set("install_root", v),
            dialog_title="Choose where builds are installed",
        )
        card.add(
            Field(
                "Install location",
                self.install_root,
                "A folder per build is created here. Builds are roughly 62 GiB each.",
                stacked=True,
            )
        )

        self.cache_root = PathField(
            self.ctx, "", on_change=lambda v: self._set("cache_dir", v),
            dialog_title="Choose the download cache location",
        )
        card.add(
            Field(
                "Download cache",
                self.cache_root,
                "Chunks and manifests land here while a build downloads. Put it on a "
                "disk with room — it can hold a whole compressed build.",
                stacked=True,
            )
        )

        self.cache_note = label("", "small", wrap=True)
        cache_row = QHBoxLayout()
        cache_row.setSpacing(SPACE["sm"])
        cache_row.addWidget(self.cache_note, 1)
        cache_row.addWidget(
            Button("Clear cache", self.theme, "trash", on_click=self._clear_cache)
        )
        card.add_layout(cache_row)
        return card

    def _launch(self) -> Card:
        card = Card()
        card.add(
            SectionHeader("Launch", "How the game is started. Per-build overrides live in the Library.")
        )
        card.add(hline())

        self.proton = QComboBox()
        self.proton.setEditable(True)
        self.proton.addItems(["", "GE-Proton", "Proton-Experimental", "UMU-Latest"])
        self.proton.lineEdit().setPlaceholderText("umu's default")
        self.proton.setAccessibleName("Proton build")
        self.proton.currentTextChanged.connect(lambda v: self._set("proton", v.strip()))
        card.add(
            Field(
                "Proton build",
                self.proton,
                "Handed to umu as PROTONPATH. Switch to GE-Proton if a launch dies "
                "with “unimplemented function”.",
            )
        )

        self.launch_options = QLineEdit()
        self.launch_options.setPlaceholderText("-windowed -ResX=1920 -ResY=1080")
        self.launch_options.setAccessibleName("Default launch arguments")
        self.launch_options.editingFinished.connect(self._save_launch_options)
        card.add(
            Field(
                "Default arguments",
                self.launch_options,
                "Appended to every launch, parsed like a shell command line.",
                stacked=True,
            )
        )

        self.prefix_note = label("", "small", wrap=True)
        card.add(self.prefix_note)
        return card

    def _network(self) -> Card:
        card = Card()
        card.add(SectionHeader("Network", "Download behaviour."))
        card.add(hline())

        self.workers = QSpinBox()
        self.workers.setRange(1, 64)
        self.workers.setAccessibleName("Download workers")
        self.workers.valueChanged.connect(lambda v: self._set("workers", v))
        card.add(
            Field(
                "Download workers",
                self.workers,
                "Parallel chunk downloads. 16 saturates most connections; drop it if "
                "your router struggles or your link is metered.",
            )
        )
        return card

    def _integration(self) -> Card:
        card = Card()
        card.add(
            SectionHeader(
                "Desktop integration",
                "Make Neo behave like any other installed application.",
            )
        )
        card.add(hline())

        entry_row = QWidget()
        eh = QHBoxLayout(entry_row)
        eh.setContentsMargins(0, 0, 0, 0)
        eh.setSpacing(SPACE["sm"])
        self.entry_badge = Badge("", "muted", self.theme)
        eh.addWidget(self.entry_badge)
        self.install_entry_btn = Button(
            "Add to application menu", self.theme, "plus", on_click=self._install_entry
        )
        eh.addWidget(self.install_entry_btn)
        self.remove_entry_btn = Button(
            "Remove", self.theme, "trash", variant="ghost", on_click=self._remove_entry
        )
        eh.addWidget(self.remove_entry_btn)
        eh.addStretch(1)
        card.add(
            Field(
                "Application menu entry",
                entry_row,
                "Installs a .desktop file and icon into ~/.local/share, so Neo shows "
                "up in your launcher and can be pinned to a dock or taskbar.",
                stacked=True,
            )
        )

        handler_row = QWidget()
        hh = QHBoxLayout(handler_row)
        hh.setContentsMargins(0, 0, 0, 0)
        hh.setSpacing(SPACE["sm"])
        self.handler_badge = Badge("", "muted", self.theme)
        hh.addWidget(self.handler_badge)
        hh.addWidget(
            Button("Take over the link", self.theme, "link", on_click=self._register_handler)
        )
        hh.addStretch(1)
        card.add(
            Field(
                "Sign-in link handler",
                handler_row,
                "Lets the Discord redirect (neolauncher://) come straight back into "
                "this window instead of being pasted by hand.",
                stacked=True,
            )
        )

        self.session_label = label("", "small", wrap=True)
        card.add(self.session_label)
        return card

    def _advanced(self) -> Card:
        card = Card()
        self.advanced_card = card
        card.add(
            SectionHeader(
                "Advanced",
                "Paths, environment overrides and destructive actions. Read the "
                "description before changing anything here.",
            )
        )
        card.add(hline())

        self.paths_box = QVBoxLayout()
        self.paths_box.setSpacing(SPACE["sm"])
        card.add_layout(self.paths_box)
        card.add(hline())

        danger = QHBoxLayout()
        danger.setSpacing(SPACE["sm"])
        danger.addWidget(
            Button(
                "Reset settings to defaults",
                self.theme,
                "refresh",
                variant="danger",
                on_click=self._reset_settings,
            )
        )
        danger.addWidget(
            Button(
                "Sign out",
                self.theme,
                "logout",
                variant="danger",
                on_click=self.ctx.sign_out,
            )
        )
        danger.addStretch(1)
        card.add_layout(danger)
        return card

    # ------------------------------------------------------------------ load
    def on_first_show(self) -> None:
        self.load(self.state.config)

    def on_show(self) -> None:
        self.load(self.state.config)
        self.state.refresh_cache()

    def refresh(self) -> None:
        self.state.reload_config()
        self.state.refresh_cache()

    def load(self, cfg: dict) -> None:
        self._loading = True
        try:
            self.notify_toggle.setChecked(bool(cfg.get("gui_notify_on_finish", True)))
            self.tray_toggle.setChecked(bool(cfg.get("gui_minimise_to_tray")))
            self.confirm_toggle.setChecked(bool(cfg.get("gui_confirm_launch")))
            self.advanced_toggle.setChecked(bool(cfg.get("gui_advanced_mode")))

            mode = cfg.get("gui_theme", "system")
            index = self.theme_picker.findData(mode)
            self.theme_picker.setCurrentIndex(max(0, index))
            self._render_accents(cfg.get("gui_accent", "violet"))

            self.install_root.set_value(str(cfg.get("install_root", "")))
            self.cache_root.set_value(
                str(cfg.get("cache_dir", "") or self.service.neo.cache_dir())
            )
            self.proton.setCurrentText(str(cfg.get("proton", "") or ""))
            self.launch_options.setText(str(cfg.get("launch_options", "") or ""))
            self.workers.setValue(int(cfg.get("workers", 16) or 16))
        finally:
            self._loading = False

        self._render_cache(self.state.cache)
        self._render_integration()
        self._render_paths()
        self.advanced_card.setVisible(bool(cfg.get("gui_advanced_mode")))

        prefix = os.environ.get("WINEPREFIX")
        self.prefix_note.setText(
            f"Wine prefix: {prefix}" if prefix
            else "WINEPREFIX is not set, so umu creates and manages its own prefix. "
                 "Set it in your shell profile if you want the game to share an "
                 "existing prefix."
        )

    def _render_accents(self, active: str) -> None:
        for key, button in self.accent_buttons.items():
            colour = ACCENTS[key][0]
            border = self.theme.p.text if key == active else "transparent"
            button.setStyleSheet(
                f"background: {colour}; border-radius: 15px; border: 2px solid {border};"
            )

    def _render_cache(self, cache) -> None:
        if not cache or not cache.path:
            self.cache_note.setText("")
            return
        self.cache_note.setText(
            f"{cache.chunk_files} cached chunk(s) and {cache.manifest_files} manifest(s), "
            f"{self.service.human(cache.total_bytes)} in {cache.path}"
        )

    def _render_integration(self) -> None:
        installed = is_desktop_entry_installed()
        self.entry_badge.set_tone(
            "success" if installed else "muted", "INSTALLED" if installed else "NOT INSTALLED"
        )
        self.install_entry_btn.setText(
            "Reinstall entry" if installed else "Add to application menu"
        )
        self.remove_entry_btn.setVisible(installed)

        owner = scheme_handler_owner()
        mine = owner == f"{APP_ID}.desktop"
        self.handler_badge.set_tone(
            "success" if mine else "muted",
            "THIS APP" if mine else (owner.replace(".desktop", "").upper()[:18] or "UNCLAIMED"),
        )
        self.session_label.setText(f"Running on {session_summary()}.")

    def _render_paths(self) -> None:
        while self.paths_box.count():
            item = self.paths_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        n = self.service.neo
        for title, path in (
            ("Config file", self.service.config_path()),
            ("Data directory", n.data_dir()),
            ("Cache directory", n.cache_dir()),
            ("Launcher module", str(getattr(n, "__file__", "?"))),
            ("Desktop entry", str(__import__("neogui.platform_integration",
                                             fromlist=["x"]).desktop_entry_path())),
        ):
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(SPACE["md"])
            k = label(title, "caption")
            k.setMinimumWidth(140)
            h.addWidget(k, 0, Qt.AlignmentFlag.AlignTop)
            h.addWidget(selectable(label(path, "mono", wrap=True)), 1)
            copy = IconButton(self.theme, "copy", f"Copy {title.lower()}", size=14)
            copy.clicked.connect(
                lambda _=False, p=path: (
                    copy_to_clipboard(p),
                    self.ctx.toast("Path copied.", "info"),
                )
            )
            h.addWidget(copy, 0, Qt.AlignmentFlag.AlignTop)
            self.paths_box.addWidget(row)

    # --------------------------------------------------------------- writers
    def _set(self, key: str, value) -> None:
        if self._loading:
            return
        if self.state.config.get(key) == value:
            return
        self.state.set_config(key, value)

    def _set_advanced(self, value: bool) -> None:
        self._set("gui_advanced_mode", value)
        self.advanced_card.setVisible(value)

    def _set_theme(self, index: int) -> None:
        if self._loading:
            return
        mode = self.theme_picker.itemData(index)
        self._set("gui_theme", mode)
        self.ctx.apply_theme(mode=mode)

    def _set_accent(self, key: str) -> None:
        self._set("gui_accent", key)
        self.ctx.apply_theme(accent=key)
        self._render_accents(key)

    def _save_launch_options(self) -> None:
        text = self.launch_options.text()
        try:
            self.service.validate_launch_options(text)
        except NeoError as exc:
            self.ctx.show_error(exc)
            return
        self._set("launch_options", text)

    # --------------------------------------------------------------- actions
    def _clear_cache(self) -> None:
        cache = self.state.cache
        dialog = ConfirmDialog(
            self.ctx,
            title="Clear the download cache?",
            body=(
                f"This frees {self.service.human(cache.total_bytes)} in {cache.path}.\n\n"
                "Installed builds are not touched. A later repair may need to "
                "re-download chunks it would otherwise have reused."
            ),
            confirm_text="Clear cache",
            destructive=True,
            checkbox_text="Also clear cached manifests",
        )
        if not dialog.exec():
            return
        removed, freed = self.service.clear_cache(manifests=dialog.checkbox_checked)
        self.ctx.toast(
            f"Removed {removed} file(s), freed {self.service.human(freed)}.", "success"
        )
        self.state.refresh_cache()

    def _install_entry(self) -> None:
        try:
            path = install_desktop_entry()
        except OSError as exc:
            self.ctx.show_error(
                NeoError(
                    "Could not write the desktop entry.", str(exc), kind="permission"
                )
            )
            return
        self.ctx.toast(
            "Neo is now in your application menu — you can pin it to your dock.",
            "success",
        )
        self.state.log_activity(f"Installed desktop entry at {path}")
        self._render_integration()

    def _remove_entry(self) -> None:
        remove_desktop_entry()
        self.ctx.toast("Desktop entry removed.", "info")
        self._render_integration()

    def _register_handler(self) -> None:
        if register_scheme_handler(self.service):
            self.ctx.toast("Neo now handles neolauncher:// sign-in links.", "success")
        else:
            self.ctx.toast(
                "Could not register the handler — xdg-mime is not installed. You can "
                "still paste the callback URL when signing in.",
                "warning",
            )
        self._render_integration()

    def _reset_settings(self) -> None:
        dialog = ConfirmDialog(
            self.ctx,
            title="Reset all settings?",
            body=(
                "Install locations, launch options, modifiers and appearance go back "
                "to their defaults. Your account session and installed builds are "
                "not affected."
            ),
            confirm_text="Reset settings",
            destructive=True,
            require_phrase="RESET",
        )
        if not dialog.exec():
            return
        try:
            path = self.service.config_path()
            if os.path.exists(path):
                os.replace(path, path + ".bak")
        except OSError as exc:
            self.ctx.show_error(
                NeoError("Could not reset the settings file.", str(exc), kind="permission")
            )
            return
        self.state.reload_config()
        cfg = self.state.config
        self.ctx.apply_theme(mode=cfg.get("gui_theme", "system"),
                             accent=cfg.get("gui_accent", "violet"))
        self.ctx.toast("Settings reset. The old file was kept as config.json.bak.", "success")
