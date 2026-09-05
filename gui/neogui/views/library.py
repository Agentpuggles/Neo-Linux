"""Library — installed builds, the catalog, and per-build configuration.

Left: your installs plus everything NeoFN offers. Right: the selected build's
detail panel — location, size, integrity, launch options, modifiers, and the
destructive actions, each behind a confirmation.
"""

from __future__ import annotations


from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from ..backend.errors import NeoError
from ..platform_integration import open_path
from ..theme import RADIUS, SPACE
from ..widgets.common import (
    Badge,
    Button,
    Card,
    EmptyState,
    Field,
    IconButton,
    FlowLayout,
    SectionHeader,
    StatusDot,
    Toggle,
    hline,
    label,
    selectable,
)
from ..widgets.dialogs import ConfirmDialog, TextPromptDialog
from .base import View


class BuildRow(QFrame):
    """One selectable row in the build list."""

    def __init__(self, ctx, *, version: str, primary: str, secondary: str,
                 badges: list, installed: bool, tone: str, parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.version = version
        self.installed = installed
        self._selected = False
        self._theme = ctx.theme
        self.setObjectName("BuildRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(f"{primary}, {secondary}")

        row = QHBoxLayout(self)
        row.setContentsMargins(SPACE["md"], SPACE["sm"] + 2, SPACE["md"], SPACE["sm"] + 2)
        row.setSpacing(SPACE["md"])

        self.dot = StatusDot(ctx.theme, tone, size=8)
        row.addWidget(self.dot, 0, Qt.AlignmentFlag.AlignVCenter)

        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(1)
        self.primary = label(primary, "body")
        col.addWidget(self.primary)
        self.secondary = label(secondary, "small")
        col.addWidget(self.secondary)
        row.addLayout(col, 1)

        for text, btone in badges:
            row.addWidget(Badge(text, btone, ctx.theme), 0, Qt.AlignmentFlag.AlignVCenter)

        self.retheme()
        ctx.theme.changed.connect(self.retheme)

    def set_selected(self, value: bool) -> None:
        self._selected = value
        self.retheme()

    def retheme(self) -> None:
        p = self._theme.p
        if self._selected:
            bg, border = p.accent_soft, p.accent
        else:
            bg, border = "transparent", "transparent"
        hover = "rgba(255,255,255,0.05)" if p.is_dark else "rgba(10,14,24,0.045)"
        self.setStyleSheet(
            f"#BuildRow {{ background: {bg}; border: 1px solid {border};"
            f"border-radius: {RADIUS['md']}px; }}"
            f"#BuildRow:hover {{ background: {bg if self._selected else hover}; }}"
            f"#BuildRow:focus {{ border: 1px solid {p.accent}; }}"
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.ctx.library_select(self.version)
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.ctx.library_select(self.version)
            return
        super().keyPressEvent(event)


class InfoGrid(QWidget):
    """key → value pairs, aligned, with selectable values."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(SPACE["xl"])
        self.grid.setVerticalSpacing(SPACE["sm"])
        self.grid.setColumnStretch(1, 1)
        self._rows: dict = {}

    def set(self, key: str, value: str, *, mono: bool = False) -> None:
        if key not in self._rows:
            r = self.grid.rowCount()
            k = label(key, "caption")
            k.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            v = selectable(label(value, "mono" if mono else "body", wrap=True))
            self.grid.addWidget(k, r, 0, Qt.AlignmentFlag.AlignTop)
            self.grid.addWidget(v, r, 1)
            self._rows[key] = v
        else:
            self._rows[key].setText(value)

    def clear_values(self) -> None:
        for v in self._rows.values():
            v.setText("—")


class LibraryView(View):
    title = "Library"
    subtitle = "Installed builds and everything NeoFN publishes."

    def __init__(self, ctx, parent=None) -> None:
        super().__init__(ctx, parent)
        self.selected: str | None = None
        self._rows: dict = {}

        self.install_btn = Button(
            "Install build", self.theme, "download", variant="primary",
            on_click=lambda: self.ctx.start_install(),
            tooltip="Download and install a build from the catalog",
        )
        self.import_btn = Button(
            "Import folder", self.theme, "import",
            on_click=self._import_build,
            tooltip="Register a build you already have on disk — no download",
        )
        self.refresh_btn = IconButton(self.theme, "refresh", "Reload the catalog  (F5)")
        self.refresh_btn.clicked.connect(self.refresh)
        self.add_header_action(self.import_btn)
        self.add_header_action(self.install_btn)
        self.add_header_action(self.refresh_btn)

        split = QHBoxLayout()
        split.setSpacing(SPACE["lg"])

        # ------------------------------------------------------------- list
        list_card = Card(padding=SPACE["md"])
        list_card.setMinimumWidth(330)
        list_card.setMaximumWidth(430)
        head = SectionHeader("Builds")
        list_card.add(head)

        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter builds…")
        self.filter.setClearButtonEnabled(True)
        self.filter.setAccessibleName("Filter builds")
        self.filter.textChanged.connect(self._rebuild_list)
        list_card.add(self.filter)

        self.installed_caption = label("INSTALLED", "caption")
        list_card.add(self.installed_caption)
        self.installed_box = QVBoxLayout()
        self.installed_box.setSpacing(2)
        list_card.add_layout(self.installed_box)
        self.no_installs = label("Nothing installed yet.", "small")
        list_card.add(self.no_installs)

        list_card.add(hline())
        self.catalog_caption = label("AVAILABLE", "caption")
        list_card.add(self.catalog_caption)
        self.catalog_box = QVBoxLayout()
        self.catalog_box.setSpacing(2)
        list_card.add_layout(self.catalog_box)
        self.catalog_note = label("Loading the catalog…", "small")
        list_card.add(self.catalog_note)
        list_card.add_stretch()
        split.addWidget(list_card, 2)

        # ----------------------------------------------------------- detail
        detail_col = QVBoxLayout()
        detail_col.setSpacing(SPACE["lg"])

        self.detail_card = Card()
        head_row = QHBoxLayout()
        head_row.setSpacing(SPACE["md"])
        self.detail_title = label("Select a build", "title")
        head_row.addWidget(self.detail_title)
        self.detail_badge = Badge("", "muted", self.theme)
        self.detail_badge.setVisible(False)
        head_row.addWidget(self.detail_badge, 0, Qt.AlignmentFlag.AlignVCenter)
        head_row.addStretch(1)
        self.detail_card.add_layout(head_row)
        self.detail_sub = label("", "small", wrap=True)
        self.detail_card.add(self.detail_sub)
        self.detail_card.add(hline())

        self.info = InfoGrid()
        self.detail_card.add(self.info)

        actions = FlowLayout()
        self.play_btn = Button("Launch", self.theme, "play", variant="primary",
                               on_click=lambda: self.ctx.launch(self.selected))
        self.verify_btn = Button("Verify", self.theme, "shield-check",
                                 on_click=lambda: self._verify(repair=False),
                                 tooltip="Hash every file against the manifest")
        self.repair_btn = Button("Verify & repair", self.theme, "wrench",
                                 on_click=lambda: self._verify(repair=True),
                                 tooltip="Re-download only the files that are broken")
        self.folder_btn = Button("Open folder", self.theme, "folder",
                                 on_click=self._open_folder)
        self.install_this_btn = Button("Install this build", self.theme, "download",
                                       variant="primary",
                                       on_click=self._install_selected)
        self.remove_btn = Button("Remove", self.theme, "trash", variant="danger",
                                 on_click=self._uninstall)
        for btn in (self.play_btn, self.verify_btn, self.repair_btn, self.folder_btn,
                    self.install_this_btn, self.remove_btn):
            actions.addWidget(btn)
        self.detail_card.add_layout(actions)
        detail_col.addWidget(self.detail_card)

        # --------------------------------------------------- launch settings
        self.launch_card = Card()
        self.launch_card.add(
            SectionHeader(
                "Launch options",
                "These apply to every launch. Per-launch overrides live in the Play page.",
            )
        )
        self.launch_card.add(hline())

        self.launch_options = QLineEdit()
        self.launch_options.setPlaceholderText("-windowed -ResX=1920 -ResY=1080")
        self.launch_options.setAccessibleName("Extra launch arguments")
        self.launch_options.editingFinished.connect(self._save_launch_options)
        self.launch_card.add(
            Field(
                "Extra arguments",
                self.launch_options,
                "Passed to the game after Neo's own arguments. Quoted like a shell.",
                stacked=True,
            )
        )

        self.proton = QComboBox()
        self.proton.setEditable(True)
        self.proton.setAccessibleName("Proton build")
        self.proton.addItems(["", "GE-Proton", "Proton-Experimental", "UMU-Latest"])
        self.proton.lineEdit().setPlaceholderText("Leave empty for umu's default")
        self.proton.currentTextChanged.connect(self._save_proton)
        self.launch_card.add(
            Field(
                "Proton build",
                self.proton,
                "Passed to umu as PROTONPATH. GE-Proton is the safest choice if a "
                "launch dies on “unimplemented function”.",
            )
        )
        detail_col.addWidget(self.launch_card)

        # --------------------------------------------------------- modifiers
        self.mods_card = Card()
        self.mods_card.add(
            SectionHeader(
                "Game modifiers",
                "The same options the official launcher sends, encoded into "
                "-NeoModifiers on launch.",
            )
        )
        self.mods_card.add(hline())
        self.mod_toggles = {}
        for key, title, desc in (
            ("edit_on_release", "Edit on release",
             "Confirm the edit as soon as the edit button is released."),
            ("instant_reset", "Instant reset",
             "Confirm a reset when the reset button is released."),
            ("disable_pre_edit", "Disable pre-edit",
             "Skip the pre-edit highlight so edits apply without a confirm step."),
        ):
            toggle = Toggle(self.theme)
            toggle.toggled.connect(lambda v, k=key: self.state.set_config(k, v))
            self.mod_toggles[key] = toggle
            self.mods_card.add(Field(title, toggle, desc))
        detail_col.addWidget(self.mods_card)

        self.empty = EmptyState(
            self.theme,
            "gamepad",
            "Nothing selected",
            "Pick a build on the left to see its details, or install one to get started.",
        )
        detail_col.addWidget(self.empty)
        detail_col.addStretch(1)
        split.addLayout(detail_col, 3)
        self.body.addLayout(split, 1)

        self.state.installs_changed.connect(lambda _l: self._rebuild_list())
        self.state.builds_changed.connect(lambda _l: self._rebuild_list())
        self.state.config_changed.connect(self._load_config)

    # ---------------------------------------------------------------- events
    def on_first_show(self) -> None:
        self._load_config(self.state.config)
        self._rebuild_list()

    def on_show(self) -> None:
        if not self.state.builds:
            self.state.refresh_builds(quiet=True)
        self._rebuild_list()

    def refresh(self) -> None:
        self.state.refresh_installs()
        self.state.refresh_builds()

    def select(self, version: str | None) -> None:
        self.selected = version
        for ver, row in self._rows.items():
            row.set_selected(ver == version)
        self._render_detail()

    # ------------------------------------------------------------ list build
    def _rebuild_list(self) -> None:
        needle = self.filter.text().strip().lower()
        self._rows.clear()
        for box in (self.installed_box, self.catalog_box):
            while box.count():
                item = box.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()

        installs = self.state.installs
        shown_installs = [i for i in installs if needle in i.version.lower()]
        for inst in shown_installs:
            badges = []
            if inst.imported:
                badges.append(("IMPORTED", "info"))
            if not inst.exists:
                badges.append(("MISSING", "danger"))
            elif not inst.playable:
                badges.append(("INCOMPLETE", "warning"))
            tone = "success" if inst.playable else ("danger" if not inst.exists else "warning")
            secondary = inst.path if inst.exists else "folder no longer exists"
            row = BuildRow(
                self.ctx,
                version=inst.version,
                primary=f"Fortnite {inst.short}",
                secondary=self._ellipsis(secondary, 46),
                badges=badges,
                installed=True,
                tone=tone,
            )
            self._rows[inst.version] = row
            self.installed_box.addWidget(row)
        self.no_installs.setVisible(not shown_installs)
        self.installed_caption.setVisible(bool(installs) or not needle)

        installed_versions = {i.version for i in installs}
        catalog = [
            b
            for b in self.state.builds
            if b.version not in installed_versions and needle in b.version.lower()
        ]
        for build in catalog:
            badges = [("LIVE", "accent")] if build.is_live else []
            row = BuildRow(
                self.ctx,
                version=build.version,
                primary=f"Fortnite {build.short}",
                secondary=f"{self.service.human(build.size)}"
                + (f" · {build.release_date[:10]}" if build.release_date else ""),
                badges=badges,
                installed=False,
                tone="muted",
            )
            self._rows[build.version] = row
            self.catalog_box.addWidget(row)
        if self.state.builds:
            self.catalog_note.setVisible(not catalog)
            self.catalog_note.setText(
                "No other builds match that filter."
                if needle
                else "Everything in the catalog is installed."
            )
        else:
            self.catalog_note.setVisible(True)
            self.catalog_note.setText(
                "Catalog unavailable — check your connection, then refresh."
                if self.state.status.reachable is False
                else "Loading the catalog…"
            )

        if self.selected not in self._rows:
            self.selected = None
        self.select(self.selected)

    @staticmethod
    def _ellipsis(text: str, limit: int) -> str:
        return text if len(text) <= limit else "…" + text[-(limit - 1):]

    # --------------------------------------------------------------- detail
    def _render_detail(self) -> None:
        version = self.selected
        install = next((i for i in self.state.installs if i.version == version), None)
        build = next((b for b in self.state.builds if b.version == version), None)
        has_selection = bool(version)

        self.detail_card.setVisible(has_selection)
        self.launch_card.setVisible(bool(install))
        self.mods_card.setVisible(bool(install))
        self.empty.setVisible(not has_selection)
        if not has_selection:
            return

        short = (install or build).short
        self.detail_title.setText(f"Fortnite {short}")
        self.detail_sub.setText(version)

        self.info.set("Version", version, mono=True)
        cl = version.split("-CL-")[-1] if "-CL-" in version else "—"
        self.info.set("Changelist", cl)

        if install:
            self.detail_badge.setVisible(True)
            if not install.exists:
                self.detail_badge.set_tone("danger", "MISSING")
            elif not install.playable:
                self.detail_badge.set_tone("warning", "INCOMPLETE")
            elif install.imported:
                self.detail_badge.set_tone("info", "IMPORTED")
            else:
                self.detail_badge.set_tone("success", "INSTALLED")
            self.info.set("Location", install.path, mono=True)
            size = install.size or (build.size if build else 0)
            self.info.set("Download size", self.service.human(size) if size else "—")
            free = self.service.disk_free(install.path)
            self.info.set(
                "Free on that disk", self.service.human(free) if free is not None else "—"
            )
            if install.exists:
                status = (
                    "Ready to launch"
                    if install.playable
                    else "Game binaries missing — run Verify & repair"
                )
            else:
                status = "The install folder no longer exists on disk"
            self.info.set("Status", status)
        else:
            self.detail_badge.setVisible(bool(build and build.is_live))
            if build and build.is_live:
                self.detail_badge.set_tone("accent", "LIVE")
            self.info.set("Location", "Not installed")
            self.info.set(
                "Download size", self.service.human(build.size) if build else "—"
            )
            free = self.service.disk_free(self.state.config.get("install_root", "~"))
            self.info.set(
                "Free on install disk",
                self.service.human(free) if free is not None else "—",
            )
            self.info.set("Released", (build.release_date[:10] if build else "") or "—")
            self.info.set("Status", "Available to download")

        for btn in (self.play_btn, self.verify_btn, self.repair_btn, self.folder_btn,
                    self.remove_btn):
            btn.setVisible(bool(install))
        self.install_this_btn.setVisible(not install)
        if install:
            self.play_btn.setEnabled(install.playable and self.state.session.logged_in)
            self.play_btn.setToolTip(
                "Launch this build"
                if install.playable
                else "This install is incomplete — verify and repair it first"
            )
            self.verify_btn.setEnabled(install.exists)
            self.repair_btn.setEnabled(install.exists)
            self.folder_btn.setEnabled(install.exists)

    # ------------------------------------------------------------- actions
    def _install_selected(self) -> None:
        self.ctx.start_install(self.selected)

    def _open_folder(self) -> None:
        install = next((i for i in self.state.installs if i.version == self.selected), None)
        if install and not open_path(install.path):
            self.ctx.toast("Could not open the file manager.", "warning")

    def _verify(self, *, repair: bool) -> None:
        self.ctx.start_verify(self.selected, repair=repair)

    def _uninstall(self) -> None:
        install = next((i for i in self.state.installs if i.version == self.selected), None)
        if not install:
            return
        dialog = ConfirmDialog(
            self.ctx,
            title=f"Remove Fortnite {install.short}?",
            body=(
                f"This deletes the build from disk:\n{install.path}\n\n"
                "Type REMOVE to confirm. Your account and settings are untouched."
            ),
            confirm_text="Remove build",
            destructive=True,
            require_phrase="REMOVE" if install.exists else "",
            checkbox_text="Also delete the files from disk" if install.exists else "",
            checkbox_default=True,
        )
        if not dialog.exec():
            return
        delete_files = dialog.checkbox_checked if install.exists else False
        try:
            self.service.uninstall(install.version, delete_files=delete_files)
        except NeoError as exc:
            self.ctx.show_error(exc)
        else:
            self.ctx.toast(f"Removed Fortnite {install.short}.", "success")
            self.state.log_activity(f"Removed build {install.short}")
        self.state.refresh_installs()

    def _import_build(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            "Choose the build folder (the one containing FortniteGame and Engine)",
            self.state.config.get("install_root", ""),
        )
        if not folder:
            return
        versions = [b.version for b in self.state.builds]
        dialog = TextPromptDialog(
            self.ctx,
            title="Which build is this?",
            body=f"{folder}\n\nNeo downloads that build's manifest so the folder can be "
            "verified later. Nothing is re-downloaded.",
            placeholder="10.40",
            options=versions,
        )
        if not dialog.exec():
            return
        chosen = dialog.value().strip()
        if not chosen:
            return
        self.tasks.run(
            self.service.import_build,
            folder,
            chosen,
            action="Importing that build",
            key="import",
            on_result=self._imported,
            on_error=self.ctx.show_error,
        )
        self.ctx.toast("Importing… fetching the manifest.", "info")

    def _imported(self, install) -> None:
        self.ctx.toast(f"Imported Fortnite {install.short}.", "success")
        self.state.log_activity(f"Imported build {install.short} from {install.path}")
        self.state.refresh_installs()
        self.select(install.version)

    # -------------------------------------------------------------- settings
    def _load_config(self, cfg: dict) -> None:
        self.launch_options.blockSignals(True)
        self.launch_options.setText(str(cfg.get("launch_options") or ""))
        self.launch_options.blockSignals(False)
        self.proton.blockSignals(True)
        self.proton.setCurrentText(str(cfg.get("proton") or ""))
        self.proton.blockSignals(False)
        for key, toggle in self.mod_toggles.items():
            toggle.setChecked(bool(cfg.get(key)))

    def _save_launch_options(self) -> None:
        text = self.launch_options.text()
        try:
            self.service.validate_launch_options(text)
        except NeoError as exc:
            self.launch_options.setProperty("invalid", "true")
            self.launch_options.style().polish(self.launch_options)
            self.ctx.show_error(exc)
            return
        self.launch_options.setProperty("invalid", "false")
        self.launch_options.style().polish(self.launch_options)
        if self.state.config.get("launch_options", "") != text:
            self.state.set_config("launch_options", text)

    def _save_proton(self, text: str) -> None:
        if self.state.config.get("proton", "") != text:
            self.state.set_config("proton", text.strip())
