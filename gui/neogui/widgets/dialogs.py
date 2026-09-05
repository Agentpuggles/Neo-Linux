"""Modal dialogs: confirm, prompt, install options, sign-in, error detail.

All of them are real Qt dialogs — they get proper window decorations, are
positioned by the compositor, and are keyboard-complete (Escape cancels, Enter
confirms, Tab cycles, the initial focus is on the safe choice).
"""

from __future__ import annotations


from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..platform_integration import copy_to_clipboard, open_url
from ..theme import SPACE
from .common import Button, Card, Field, label


class BaseDialog(QDialog):
    def __init__(self, ctx, title: str, *, width: int = 480) -> None:
        super().__init__(ctx.window)
        self.ctx = ctx
        self.theme = ctx.theme
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(width)
        self.setStyleSheet(self.theme.stylesheet())

        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(SPACE["xl"], SPACE["xl"], SPACE["xl"], SPACE["lg"])
        self.root.setSpacing(SPACE["md"])

        self.heading = label(title, "title")
        self.heading.setWordWrap(True)
        self.root.addWidget(self.heading)

        self.body_label = label("", "dim", wrap=True)
        self.body_label.setVisible(False)
        self.root.addWidget(self.body_label)

        self.content = QVBoxLayout()
        self.content.setSpacing(SPACE["md"])
        self.root.addLayout(self.content)

        self.root.addStretch(1)
        self.buttons = QHBoxLayout()
        self.buttons.setSpacing(SPACE["sm"])
        self.buttons.addStretch(1)
        self.root.addLayout(self.buttons)

    def set_body(self, text: str) -> None:
        self.body_label.setText(text)
        self.body_label.setVisible(bool(text))

    def add_button(self, text: str, *, variant: str = "default", on_click=None,
                   default: bool = False) -> Button:
        btn = Button(text, self.theme, variant=variant)
        if on_click:
            btn.clicked.connect(on_click)
        btn.setDefault(default)
        btn.setAutoDefault(default)
        self.buttons.addWidget(btn)
        return btn


class ConfirmDialog(BaseDialog):
    """Yes/no, with optional typed confirmation for destructive actions."""

    def __init__(
        self,
        ctx,
        *,
        title: str,
        body: str = "",
        confirm_text: str = "Confirm",
        cancel_text: str = "Cancel",
        destructive: bool = False,
        require_phrase: str = "",
        checkbox_text: str = "",
        checkbox_default: bool = False,
    ) -> None:
        super().__init__(ctx, title)
        self.set_body(body)
        self._phrase = require_phrase
        self.checkbox: QCheckBox | None = None

        if checkbox_text:
            self.checkbox = QCheckBox(checkbox_text)
            self.checkbox.setChecked(checkbox_default)
            self.content.addWidget(self.checkbox)

        self.input: QLineEdit | None = None
        if require_phrase:
            self.input = QLineEdit()
            self.input.setPlaceholderText(require_phrase)
            self.input.setAccessibleName(f"Type {require_phrase} to confirm")
            self.input.textChanged.connect(self._validate)
            self.content.addWidget(self.input)

        cancel = self.add_button(cancel_text, on_click=self.reject, default=not require_phrase)
        self.confirm = self.add_button(
            confirm_text,
            variant="danger" if destructive else "primary",
            on_click=self.accept,
            default=not destructive,
        )
        if require_phrase:
            self.confirm.setEnabled(False)
        cancel.setFocus()

    def _validate(self, text: str) -> None:
        self.confirm.setEnabled(text.strip().upper() == self._phrase.upper())

    @property
    def checkbox_checked(self) -> bool:
        return bool(self.checkbox and self.checkbox.isChecked())


class TextPromptDialog(BaseDialog):
    def __init__(
        self,
        ctx,
        *,
        title: str,
        body: str = "",
        placeholder: str = "",
        initial: str = "",
        options: list | None = None,
    ) -> None:
        super().__init__(ctx, title)
        self.set_body(body)
        if options:
            self.field = QComboBox()
            self.field.setEditable(True)
            self.field.addItems(["", *list(options)])
            self.field.lineEdit().setPlaceholderText(placeholder)
            self.field.setCurrentText(initial)
        else:
            self.field = QLineEdit(initial)
            self.field.setPlaceholderText(placeholder)
            self.field.returnPressed.connect(self.accept)
        self.field.setAccessibleName(title)
        self.content.addWidget(self.field)
        self.add_button("Cancel", on_click=self.reject)
        self.add_button("Continue", variant="primary", on_click=self.accept, default=True)
        self.field.setFocus()

    def value(self) -> str:
        if isinstance(self.field, QComboBox):
            return self.field.currentText()
        return self.field.text()


class InstallDialog(BaseDialog):
    """Pick the build, the destination and the worker count before downloading."""

    def __init__(self, ctx, builds: list, preselect: str | None = None) -> None:
        super().__init__(ctx, "Install a build", width=560)
        cfg = ctx.state.config
        self.service = ctx.service
        self.set_body(
            "Neo downloads the build in chunks, verifies every one against the "
            "manifest, then assembles the files. You can cancel at any point — "
            "finished chunks are kept, so resuming does not start over."
        )

        self.build_picker = QComboBox()
        self.build_picker.setAccessibleName("Build to install")
        for build in builds:
            suffix = "  (live)" if build.is_live else ""
            self.build_picker.addItem(
                f"Fortnite {build.short}{suffix} — {self.service.human(build.size)}",
                build.version,
            )
        if preselect:
            index = self.build_picker.findData(preselect)
            if index >= 0:
                self.build_picker.setCurrentIndex(index)
        self.build_picker.currentIndexChanged.connect(self._update_space)
        self.content.addWidget(Field("Build", self.build_picker, "Live is the current season."))

        path_row = QWidget()
        ph = QHBoxLayout(path_row)
        ph.setContentsMargins(0, 0, 0, 0)
        ph.setSpacing(SPACE["sm"])
        self.path_field = QLineEdit(str(cfg.get("install_root", "")))
        self.path_field.setAccessibleName("Install location")
        self.path_field.textChanged.connect(self._update_space)
        ph.addWidget(self.path_field, 1)
        browse = Button("Browse", ctx.theme, "folder", on_click=self._browse)
        ph.addWidget(browse)
        self.content.addWidget(
            Field("Install to", path_row, "A folder per build is created inside this one.",
                  stacked=True)
        )

        self.workers = QSpinBox()
        self.workers.setRange(1, 64)
        self.workers.setValue(int(cfg.get("workers", 16) or 16))
        self.workers.setAccessibleName("Download workers")
        self.content.addWidget(
            Field(
                "Download workers",
                self.workers,
                "More workers saturate a fast link; fewer are kinder to a slow one.",
            )
        )

        self.keep_cache = QCheckBox("Keep downloaded chunks after installing")
        self.keep_cache.setToolTip(
            "Enables offline repair later, but uses roughly another build's worth of disk."
        )
        self.content.addWidget(self.keep_cache)

        self.space_note = label("", "small", wrap=True)
        self.content.addWidget(self.space_note)

        self.add_button("Cancel", on_click=self.reject)
        self.add_button("Start download", variant="primary", on_click=self.accept, default=True)
        self._update_space()

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Choose where builds are installed", self.path_field.text()
        )
        if folder:
            self.path_field.setText(folder)

    def _update_space(self) -> None:
        version = self.build_picker.currentData()
        build = next(
            (b for b in self.ctx.state.builds if b.version == version), None
        )
        target = self.path_field.text()
        free = self.service.disk_free(target)
        if not build or free is None:
            self.space_note.setText("")
            return
        needed = build.size
        peak = needed * 2
        ok = free > peak
        self.space_note.setText(
            f"{self.service.human(free)} free at that location. "
            f"This build needs about {self.service.human(needed)} downloaded and "
            f"{self.service.human(peak)} at peak while assembling."
            + ("" if ok else "  ⚠ That may not be enough.")
        )
        p = self.theme.p
        self.space_note.setStyleSheet(
            f"color: {p.text_dim if ok else p.warning}; font-size: 12px;"
        )

    def result_options(self) -> dict:
        return {
            "version": self.build_picker.currentData(),
            "target_dir": self.path_field.text().strip() or None,
            "workers": self.workers.value(),
            "keep_cache": self.keep_cache.isChecked(),
        }


class LoginDialog(BaseDialog):
    """Discord sign-in. The browser does the OAuth; we take the code back."""

    def __init__(self, ctx) -> None:
        super().__init__(ctx, "Sign in to NeoFN", width=560)
        self.service = ctx.service
        self.set_body(
            "Neo signs in through NeoFN's Discord flow in your normal browser. "
            "Approve the request there and Neo will pick up the result "
            "automatically. If your desktop can't hand the link back, paste the "
            "callback URL below instead."
        )

        step1 = Card(flat=True)
        step1.add(label("STEP 1", "caption"))
        step1.add(label("Open the Discord authorisation page", "body"))
        row = QHBoxLayout()
        row.setSpacing(SPACE["sm"])
        self.open_btn = Button(
            "Open in browser", ctx.theme, "external", variant="primary",
            on_click=self._open_browser,
        )
        row.addWidget(self.open_btn)
        copy_link = Button("Copy link", ctx.theme, "copy", on_click=self._copy_link)
        row.addWidget(copy_link)
        row.addStretch(1)
        step1.add_layout(row)
        self.content.addWidget(step1)

        step2 = Card(flat=True)
        step2.add(label("STEP 2", "caption"))
        step2.add(
            label(
                "Waiting for the browser… if nothing happens, paste the whole "
                "neolauncher://callback/auth?code=… URL here.",
                "small",
                wrap=True,
            )
        )
        self.code_field = QLineEdit()
        self.code_field.setPlaceholderText("neolauncher://callback/auth?code=…")
        self.code_field.setAccessibleName("Callback URL or code")
        self.code_field.returnPressed.connect(self._submit)
        step2.add(self.code_field)
        self.content.addWidget(step2)

        self.error_label = label("", "small", wrap=True)
        self.error_label.setVisible(False)
        self.content.addWidget(self.error_label)

        self.add_button("Cancel", on_click=self.reject)
        self.submit_btn = self.add_button(
            "Sign in", variant="primary", on_click=self._submit, default=True
        )
        self.code_field.setFocus()

    def _open_browser(self) -> None:
        self.service.install_scheme_handler()
        if not open_url(self.service.login_url()):
            self._fail("Could not open a browser. Use “Copy link” and paste it manually.")

    def _copy_link(self) -> None:
        copy_to_clipboard(self.service.login_url())
        self.ctx.toast("Authorisation link copied.", "info")

    def _fail(self, text: str) -> None:
        p = self.theme.p
        self.error_label.setText(text)
        self.error_label.setStyleSheet(f"color: {p.danger}; font-size: 12px;")
        self.error_label.setVisible(True)

    def _submit(self) -> None:
        text = self.code_field.text()
        self.submit_btn.setEnabled(False)
        self.submit_btn.setText("Signing in…")
        try:
            self.service.login_with_code(text)
        except Exception as exc:
            from ..backend.errors import classify

            err = classify(exc, action="Sign-in")
            self._fail("\n".join(x for x in (err.summary, err.hint) if x))
            self.submit_btn.setEnabled(True)
            self.submit_btn.setText("Sign in")
            return
        self.accept()

    def accept_code(self, url: str) -> None:
        """Called when the scheme handler delivers a callback while we're open."""
        self.code_field.setText(url)
        self._submit()


class DetailDialog(BaseDialog):
    """A long, copyable technical blob — errors, launch previews, diagnostics."""

    def __init__(self, ctx, title: str, body: str, text: str, *, tone: str = "danger") -> None:
        super().__init__(ctx, title, width=680)
        self.set_body(body)
        self.text = text
        self.view = QPlainTextEdit(text)
        self.view.setReadOnly(True)
        self.view.setMinimumHeight(260)
        self.view.setAccessibleName("Technical details")
        self.content.addWidget(self.view)
        self.add_button("Copy", on_click=self._copy)
        self.add_button("Close", variant="primary", on_click=self.accept, default=True)

    def _copy(self) -> None:
        copy_to_clipboard(self.view.toPlainText())
        self.ctx.toast("Copied to clipboard.", "success")
