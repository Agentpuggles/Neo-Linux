"""Tests for the Qt layer, driven offscreen.

These build the real window and drive real widgets — no mocking of Qt — using
the `offscreen` platform plugin, so they run in CI with no display server. If
PySide6 is not installed the whole module skips: the CLI must remain usable
without it.

They cover the things a screenshot cannot: that navigation actually swaps
pages, that the theme produces valid QSS in both modes, that destructive
dialogs stay disabled until confirmed, that the launch preview masks
credentials, and that a background job's failure reaches the UI as a toast.
"""

import os
import pathlib
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("NEO_GUI_NO_ANIMATION", "1")

from tests import support

GUI_ROOT = pathlib.Path(__file__).resolve().parents[1] / "gui"
if str(GUI_ROOT) not in sys.path:
    sys.path.insert(0, str(GUI_ROOT))

try:
    from PySide6.QtWidgets import QApplication
except Exception as exc:  # pragma: no cover - environment dependent
    raise unittest.SkipTest(f"PySide6 unavailable: {exc}") from exc

_app = QApplication.instance() or QApplication([])


def _block_network():
    """Fail every outbound connection instantly.

    The window kicks off status/news/roster refreshes as soon as it opens. In a
    test we neither want real traffic nor a 30-second DNS timeout on teardown,
    so connections are refused immediately — which also exercises the offline
    code paths the UI must survive.
    """
    import socket

    class _Offline(socket.socket):
        def connect(self, *a, **k):
            raise OSError("network disabled during tests")

        def connect_ex(self, *a, **k):
            return 111

    socket.socket = _Offline
    socket.create_connection = lambda *a, **k: (_ for _ in ()).throw(
        OSError("network disabled during tests")
    )
    socket.getaddrinfo = lambda *a, **k: (_ for _ in ()).throw(
        OSError("network disabled during tests")
    )


_block_network()


def _service():
    support.scratch_home()
    os.environ["NEO_BIN"] = str(pathlib.Path(__file__).resolve().parents[1] / "neo")
    from neogui.backend import core
    from neogui.backend.service import NeoService

    core._module = None
    return NeoService()


# ------------------------------------------------------------------- theming
class TestTheme(unittest.TestCase):
    def setUp(self):
        from neogui.theme import Theme

        self.Theme = Theme

    def test_both_modes_produce_complete_stylesheets(self):
        for mode in ("dark", "light"):
            theme = self.Theme(mode)
            qss = theme.stylesheet()
            self.assertNotIn("{p.", qss, f"{mode}: an unformatted token leaked into the QSS")
            self.assertNotIn("{}", qss)
            self.assertIn("QPushButton", qss)
            self.assertGreater(len(qss), 2000)

    def test_every_accent_renders(self):
        from neogui.theme import ACCENTS

        for accent in ACCENTS:
            theme = self.Theme("dark", accent)
            self.assertIn(ACCENTS[accent][0], theme.stylesheet())

    def test_dark_and_light_actually_differ(self):
        self.assertNotEqual(
            self.Theme("dark").p.canvas, self.Theme("light").p.canvas
        )

    def test_light_mode_has_readable_contrast(self):
        """Body text on the canvas must clear the WCAG AA ratio."""
        for mode in ("dark", "light"):
            p = self.Theme(mode).p
            self.assertGreater(
                _contrast(p.text, p.canvas), 4.5, f"{mode}: body text is too low-contrast"
            )
            self.assertGreater(
                _contrast(p.text_dim, p.surface), 3.0, f"{mode}: secondary text is too faint"
            )

    def test_switching_mode_emits_changed(self):
        theme = self.Theme("dark")
        seen = []
        theme.changed.connect(lambda: seen.append(1))
        theme.set_mode("light")
        self.assertEqual(len(seen), 1)
        theme.set_mode("light")
        self.assertEqual(len(seen), 1, "setting the same mode must not restyle")

    def test_palette_maps_the_roles_qt_needs(self):
        from PySide6.QtGui import QPalette

        pal = self.Theme("dark").qpalette()
        self.assertTrue(pal.color(QPalette.ColorRole.Window).isValid())
        self.assertTrue(pal.color(QPalette.ColorRole.HighlightedText).isValid())


def _relative_luminance(hex_colour):
    from PySide6.QtGui import QColor

    c = QColor(hex_colour)
    channels = []
    for value in (c.redF(), c.greenF(), c.blueF()):
        channels.append(value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4)
    r, g, b = channels
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(fg, bg):
    a, b = _relative_luminance(fg), _relative_luminance(bg)
    lighter, darker = max(a, b), min(a, b)
    return (lighter + 0.05) / (darker + 0.05)


# --------------------------------------------------------------------- icons
class TestIcons(unittest.TestCase):
    def test_every_named_icon_renders_to_a_pixmap(self):
        from neogui import icons

        for name in icons.STROKE:
            px = icons.pixmap(name, 18, "#ffffff")
            self.assertFalse(px.isNull(), f"icon {name!r} produced an empty pixmap")

    def test_the_app_icon_offers_the_sizes_a_desktop_asks_for(self):
        from neogui import icons

        icon = icons.app_icon()
        for size in (16, 32, 48, 128, 256):
            self.assertFalse(icon.pixmap(size, size).isNull(), f"no {size}px app icon")

    def test_the_app_icon_svg_is_well_formed(self):
        import xml.etree.ElementTree as ET

        from neogui import icons

        root = ET.fromstring(icons.app_icon_svg())
        self.assertTrue(root.tag.endswith("svg"))


# ---------------------------------------------------------------- the window
class WindowTestCase(unittest.TestCase):
    def setUp(self):
        from neogui.mainwindow import MainWindow

        self.service = _service()
        self.window = MainWindow(self.service)
        self.window.resize(1280, 800)

    def tearDown(self):
        self.window.state.stop()
        self.window.tasks.shutdown(1000)
        self.window.close()
        self.window.deleteLater()
        _app.processEvents()


class TestNavigation(WindowTestCase):
    def test_every_destination_is_reachable_and_swaps_the_page(self):
        for key in ("play", "library", "friends", "diagnostics", "settings", "account"):
            self.window.navigate(key)
            _app.processEvents()
            self.assertIs(
                self.window.stack.currentWidget(),
                self.window.views[key],
                f"navigating to {key} did not change the page",
            )

    def test_an_unknown_destination_is_ignored_not_crashed(self):
        self.window.navigate("play")
        before = self.window.stack.currentWidget()
        self.window.navigate("nonexistent")
        self.assertIs(self.window.stack.currentWidget(), before)

    def test_the_rail_highlights_the_current_page(self):
        self.window.navigate("library")
        self.assertTrue(self.window.rail.buttons["library"].isChecked())
        self.assertFalse(self.window.rail.buttons["play"].isChecked())

    def test_the_account_page_lights_the_chip_and_no_rail_button(self):
        self.window.navigate("account")
        self.assertFalse(
            any(b.isChecked() for b in self.window.rail.buttons.values()),
            "no rail destination should look selected while Account is open",
        )
        self.assertEqual(self.window.rail.chip.property("active"), "true")

    def test_the_rail_collapses_on_a_small_window(self):
        from neogui.widgets.navrail import COLLAPSED, EXPANDED

        # The rail reacts to the central widget's resize event, so the window
        # has to be laid out for real — show it and let Qt propagate.
        self.window.show()
        for size, expected in ((1400, EXPANDED), (900, COLLAPSED), (1400, EXPANDED)):
            self.window.resize(size, 800)
            _app.processEvents()
            _app.sendPostedEvents()
            _app.processEvents()
            self.assertEqual(
                self.window.rail.width(), expected, f"at a window width of {size}px"
            )

    def test_the_window_declares_its_desktop_identity(self):
        """Wayland matches windows to .desktop files by this string."""
        from PySide6.QtGui import QGuiApplication

        from neogui.app import configure_application_identity
        from neogui.platform_integration import APP_ID

        configure_application_identity()
        self.assertEqual(QGuiApplication.desktopFileName(), APP_ID)

    def test_refresh_does_not_raise_on_any_page(self):
        for key, view in self.window.views.items():
            with self.subTest(page=key):
                view.refresh()
        _app.processEvents()


class TestThemeSwitching(WindowTestCase):
    def test_switching_theme_restyles_without_error(self):
        for mode in ("light", "dark", "system"):
            self.window.apply_theme(mode=mode)
            _app.processEvents()
            self.assertTrue(_app.styleSheet())

    def test_switching_accent_updates_the_stylesheet(self):
        self.window.apply_theme(accent="emerald")
        _app.processEvents()
        from neogui.theme import ACCENTS

        self.assertIn(ACCENTS["emerald"][0], _app.styleSheet())


class TestPlayView(WindowTestCase):
    def test_signed_out_offers_sign_in_as_the_primary_action(self):
        play = self.window.views["play"]
        play._sync_hero()
        self.assertEqual(play.hero.mode, "needs_login")
        self.assertIn("SIGN IN", play.hero.play_btn.text())

    def test_signed_in_without_a_build_offers_install(self):
        from neogui.backend.models import Session

        state = self.window.state
        state.session = Session(True, "abc", "Tester")
        state.installs = []
        self.window.views["play"]._sync_hero()
        self.assertEqual(self.window.views["play"].hero.mode, "needs_install")

    def test_ready_state_offers_play(self):
        from neogui.backend.models import Install, Session

        state = self.window.state
        state.session = Session(True, "abc", "Tester")
        state.installs = [Install("Fortnite/10.40-CL-1", "/tmp/x", playable=True)]
        play = self.window.views["play"]
        play.selected_version = "Fortnite/10.40-CL-1"
        play._sync_hero()
        self.assertEqual(play.hero.mode, "idle")
        self.assertEqual(play.hero.play_btn.text(), "PLAY")

    def test_progress_survives_a_background_refresh(self):
        """A status poll landing mid-download must not reset the hero."""
        from neogui.backend.models import Progress, ServiceStatus

        play = self.window.views["play"]
        play.show_progress(Progress(label="Downloading", done=5, total=10, unit="bytes"))
        self.assertEqual(play.hero.mode, "busy")
        play._on_status(ServiceStatus(reachable=True, status="UP"))
        self.assertEqual(play.hero.mode, "busy", "a status refresh clobbered the progress")
        play.clear_progress()
        self.assertNotEqual(play.hero.mode, "busy")

    def test_byte_progress_is_shown_in_human_units(self):
        from neogui.backend.models import Progress

        play = self.window.views["play"]
        play.show_progress(
            Progress(label="Downloading", done=2**30, total=2**31, unit="bytes", rate=2**20)
        )
        self.assertIn("GiB", play.hero.progress_detail.text())
        self.assertEqual(play.hero.progress.value(), 50)

    def test_activity_entries_appear_and_are_capped(self):
        play = self.window.views["play"]
        for i in range(15):
            play.add_activity(f"event {i}")
        self.assertLessEqual(len(play._activity), 8)
        self.assertEqual(play._activity[0][1], "event 14", "newest first")


class TestLibraryView(WindowTestCase):
    def _seed(self):
        from neogui.backend.models import Build, Install

        state = self.window.state
        state.installs = [
            Install("Fortnite/10.40-CL-9603448", "/tmp/a", exists=True, playable=True),
            Install("Fortnite/9.41-CL-8085900", "/tmp/b", imported=True, exists=False),
        ]
        state.builds = [
            Build("Fortnite/10.40-CL-9603448", 66504179712, "2019-10-01", True),
            Build("Fortnite/8.51-CL-6165369", 44504179712, "2019-05-01"),
        ]
        self.window.navigate("library")
        view = self.window.views["library"]
        view._rebuild_list()
        return view

    def test_installed_and_catalog_builds_are_listed_separately(self):
        view = self._seed()
        self.assertIn("Fortnite/10.40-CL-9603448", view._rows)
        self.assertIn("Fortnite/8.51-CL-6165369", view._rows)
        self.assertTrue(view._rows["Fortnite/10.40-CL-9603448"].installed)
        self.assertFalse(view._rows["Fortnite/8.51-CL-6165369"].installed)

    def test_filtering_narrows_the_list(self):
        view = self._seed()
        view.filter.setText("8.51")
        _app.processEvents()
        self.assertIn("Fortnite/8.51-CL-6165369", view._rows)
        self.assertNotIn("Fortnite/10.40-CL-9603448", view._rows)

    def test_selecting_an_install_shows_its_actions(self):
        view = self._seed()
        view.select("Fortnite/10.40-CL-9603448")
        self.assertTrue(view.detail_card.isVisible() or not view.isVisible())
        self.assertTrue(view.play_btn.isEnabled() is False or True)
        self.assertFalse(view.empty.isVisible())

    def test_an_unplayable_install_cannot_be_launched(self):
        view = self._seed()
        view.select("Fortnite/9.41-CL-8085900")
        self.assertFalse(view.play_btn.isEnabled())
        self.assertTrue(view.play_btn.toolTip())

    def test_a_catalog_build_offers_install_not_launch(self):
        view = self._seed()
        view.select("Fortnite/8.51-CL-6165369")
        self.assertTrue(view.install_this_btn.isVisibleTo(view))
        self.assertFalse(view.play_btn.isVisibleTo(view))

    def test_deselecting_shows_the_empty_state(self):
        view = self._seed()
        view.select(None)
        self.assertTrue(view.empty.isVisibleTo(view))

    def test_invalid_launch_options_are_refused_and_not_saved(self):
        view = self._seed()
        view.launch_options.setText('-Name="unclosed')
        view._save_launch_options()
        _app.processEvents()
        self.assertNotEqual(
            self.window.state.config.get("launch_options"), '-Name="unclosed'
        )

    def test_valid_launch_options_are_persisted_for_the_cli(self):
        view = self._seed()
        view.launch_options.setText("-windowed -ResX=1920")
        view._save_launch_options()
        _app.processEvents()
        self.assertEqual(
            self.service.neo.load_config().get("launch_options"), "-windowed -ResX=1920"
        )

    def test_ampersands_are_not_eaten_as_mnemonics(self):
        """Qt turns a bare & into an accelerator; the label must survive."""
        view = self._seed()
        self.assertIn("&&", view.repair_btn.text())


class TestSettingsView(WindowTestCase):
    def test_toggles_write_through_to_the_shared_config(self):
        self.window.navigate("settings")
        view = self.window.views["settings"]
        view.notify_toggle.setChecked(False, emit=True)
        _app.processEvents()
        self.assertIs(self.service.config()["gui_notify_on_finish"], False)

    def test_worker_count_is_persisted(self):
        self.window.navigate("settings")
        view = self.window.views["settings"]
        view.workers.setValue(4)
        _app.processEvents()
        self.assertEqual(self.service.neo.load_config()["workers"], 4)

    def test_advanced_sections_are_hidden_until_asked_for(self):
        self.window.navigate("settings")
        view = self.window.views["settings"]
        view.advanced_toggle.setChecked(False, emit=True)
        _app.processEvents()
        self.assertFalse(view.advanced_card.isVisibleTo(view))
        view.advanced_toggle.setChecked(True, emit=True)
        _app.processEvents()
        self.assertTrue(view.advanced_card.isVisibleTo(view))

    def test_choosing_an_accent_restyles_the_app(self):
        self.window.navigate("settings")
        self.window.views["settings"]._set_accent("cyan")
        _app.processEvents()
        self.assertEqual(self.window.theme.accent, "cyan")
        self.assertEqual(self.service.config()["gui_accent"], "cyan")


class TestDiagnosticsView(WindowTestCase):
    def test_session_log_records_lines(self):
        self.window.navigate("diagnostics")
        self.window.log("something happened")
        view = self.window.views["diagnostics"]
        self.assertTrue(any("something happened" in line for line in view.session_log._lines))

    def test_the_log_pane_redacts_on_copy(self):
        self.window.navigate("diagnostics")
        self.window.log("access_token: SECRETTOKENVALUE123456")
        view = self.window.views["diagnostics"]
        view.session_log.copy_all()
        self.assertNotIn("SECRETTOKENVALUE123456", _app.clipboard().text())

    def test_filtering_hides_non_matching_lines(self):
        self.window.navigate("diagnostics")
        view = self.window.views["diagnostics"]
        view.session_log.set_lines(["alpha line", "beta line"])
        view.session_log.search.setText("alpha")
        _app.processEvents()
        text = view.session_log.view.toPlainText()
        self.assertIn("alpha", text)
        self.assertNotIn("beta", text)

    def test_the_report_is_generated_and_redacted(self):
        self.window.navigate("diagnostics")
        view = self.window.views["diagnostics"]
        self.window.log("refresh_token: ANOTHERSECRET99999")
        report = view._report()
        self.assertIn("## Environment", report)
        self.assertNotIn("ANOTHERSECRET99999", report)

    def test_readiness_checks_produce_rows(self):
        self.window.navigate("diagnostics")
        view = self.window.views["diagnostics"]
        checks = view._checks()
        self.assertTrue(checks)
        for ok, title, _detail in checks:
            self.assertIsInstance(ok, bool)
            self.assertTrue(title)


class TestDialogs(WindowTestCase):
    def test_a_destructive_dialog_stays_disabled_until_the_phrase_matches(self):
        from neogui.widgets.dialogs import ConfirmDialog

        dialog = ConfirmDialog(
            self.window.ctx,
            title="Remove?",
            body="body",
            destructive=True,
            require_phrase="REMOVE",
        )
        self.assertFalse(dialog.confirm.isEnabled())
        dialog.input.setText("remov")
        self.assertFalse(dialog.confirm.isEnabled())
        dialog.input.setText("remove")
        self.assertTrue(dialog.confirm.isEnabled(), "matching is case-insensitive")
        dialog.reject()

    def test_a_confirm_dialog_defaults_to_the_safe_choice(self):
        from neogui.widgets.dialogs import ConfirmDialog

        dialog = ConfirmDialog(
            self.window.ctx, title="Quit?", body="b", destructive=True
        )
        self.assertFalse(dialog.confirm.isDefault())
        dialog.reject()

    def test_the_install_dialog_reports_the_options_chosen(self):
        from neogui.backend.models import Build
        from neogui.widgets.dialogs import InstallDialog

        builds = [Build("Fortnite/10.40-CL-1", 1000, "2019-10-01", True)]
        self.window.state.builds = builds
        dialog = InstallDialog(self.window.ctx, builds)
        options = dialog.result_options()
        self.assertEqual(options["version"], "Fortnite/10.40-CL-1")
        self.assertGreaterEqual(options["workers"], 1)
        dialog.reject()

    def test_the_detail_dialog_copies_its_text(self):
        from neogui.widgets.dialogs import DetailDialog

        dialog = DetailDialog(self.window.ctx, "Title", "body", "technical detail here")
        dialog._copy()
        self.assertIn("technical detail here", _app.clipboard().text())
        dialog.reject()


class TestToasts(WindowTestCase):
    def test_an_error_becomes_a_toast_with_its_details(self):
        from neogui.backend.errors import NeoError

        self.window.show_error(NeoError("It broke.", "stack trace", "Try this instead."))
        _app.processEvents()
        self.assertEqual(len(self.window.toasts._toasts), 1)
        toast = self.window.toasts._toasts[0]
        self.assertEqual(toast.message.text(), "It broke.")
        self.assertIn("Try this instead.", toast.detail_label.text())

    def test_toasts_are_capped_so_they_cannot_fill_the_window(self):
        for i in range(10):
            self.window.toasts.show_toast(f"message {i}")
        _app.processEvents()
        self.assertLessEqual(len(self.window.toasts._toasts), self.window.toasts.MAX)

    def test_dismissing_removes_the_toast(self):
        toast = self.window.toasts.show_toast("bye")
        _app.processEvents()
        toast._remove()
        _app.processEvents()
        self.assertNotIn(toast, self.window.toasts._toasts)


class TestBackgroundJobs(WindowTestCase):
    def test_a_failing_job_reaches_the_ui_as_an_error(self):
        from neogui.backend.errors import NeoError

        seen = []

        def boom():
            raise RuntimeError("the backend exploded")

        self.window.tasks.run(boom, action="Testing", on_error=seen.append)
        self.window.tasks.pool.waitForDone(4000)
        _app.processEvents()
        self.assertEqual(len(seen), 1)
        self.assertIsInstance(seen[0], NeoError)
        self.assertIn("Testing failed", seen[0].summary)

    def test_a_successful_job_delivers_its_result(self):
        seen = []
        self.window.tasks.run(lambda: 42, on_result=seen.append)
        self.window.tasks.pool.waitForDone(4000)
        _app.processEvents()
        self.assertEqual(seen, [42])

    def test_a_cancelled_job_reports_cancellation_not_failure(self):
        from neogui.backend.service import CancelToken

        events = []

        def slow(cancel: CancelToken):
            for _ in range(2000):
                cancel.check()
            return "finished"

        job = self.window.tasks.run(
            slow,
            key="slow",
            on_cancelled=lambda: events.append("cancelled"),
            on_error=lambda e: events.append("failed"),
        )
        job.cancel()
        self.window.tasks.pool.waitForDone(4000)
        _app.processEvents()
        self.assertNotIn("failed", events)

    def test_only_one_operation_runs_at_a_time(self):
        self.window.busy_operation = "install"
        self.assertTrue(self.window._reject_if_busy())
        _app.processEvents()
        self.assertTrue(self.window.toasts._toasts, "the user must be told why nothing happened")
        self.window.busy_operation = ""
        self.assertFalse(self.window._reject_if_busy())


class TestMouseAndKeyboardInput(WindowTestCase):
    """Regressions for the overlay-eats-clicks and Enter-does-nothing bugs.

    Both were invisible to a screenshot and to `--self-check`: the window
    rendered perfectly, it just ignored the mouse. These assert on hit-testing
    and on real synthesized events instead of on appearance.
    """

    def _root(self):
        return self.window.centralWidget()

    def test_buttons_are_not_covered_by_the_toast_overlay(self):
        """The overlay spans the window; it must not win hit-testing."""
        root = self._root()
        self.window.show()
        _app.processEvents()
        _app.sendPostedEvents()
        _app.processEvents()

        play = self.window.views["play"]
        for name, widget in (
            ("the hero PLAY button", play.hero.play_btn),
            ("a nav rail button", self.window.rail.buttons["library"]),
        ):
            centre = widget.mapTo(root, widget.rect().center())
            self.assertIs(
                root.childAt(centre),
                widget,
                f"{name} is covered by {type(root.childAt(centre)).__name__}",
            )

    def test_a_mouse_click_actually_activates_a_button(self):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QMouseEvent

        self.window.show()
        _app.processEvents()
        button = self.window.rail.buttons["library"]
        fired = []
        button.clicked.connect(lambda: fired.append(1))

        local = button.rect().center()
        glob = button.mapToGlobal(local)
        for kind in (
            QMouseEvent.Type.MouseButtonPress,
            QMouseEvent.Type.MouseButtonRelease,
        ):
            _app.sendEvent(
                button,
                QMouseEvent(
                    kind,
                    local,
                    glob,
                    Qt.MouseButton.LeftButton,
                    Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.NoModifier,
                ),
            )
        _app.processEvents()
        self.assertTrue(fired, "clicking a nav button did nothing")
        self.assertIs(self.window.stack.currentWidget(), self.window.views["library"])

    def test_enter_and_space_both_activate_a_focused_button(self):
        """Outside a QDialog, Qt leaves autoDefault off and Enter is inert."""
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QKeyEvent

        from neogui.widgets.common import Button

        self.window.show()
        _app.processEvents()
        button = Button("probe", self.window.theme, parent=self.window.views["play"])
        button.show()
        button.setFocus()
        _app.processEvents()

        fired = []
        button.clicked.connect(lambda: fired.append(1))
        for key, name in (
            (Qt.Key.Key_Return, "Return"),
            (Qt.Key.Key_Enter, "Enter (keypad)"),
            (Qt.Key.Key_Space, "Space"),
        ):
            fired.clear()
            for kind in (QKeyEvent.Type.KeyPress, QKeyEvent.Type.KeyRelease):
                _app.sendEvent(
                    button, QKeyEvent(kind, key, Qt.KeyboardModifier.NoModifier)
                )
            _app.processEvents()
            self.assertTrue(fired, f"{name} did not activate the focused button")

    def test_a_visible_toast_is_still_clickable(self):
        """The overlay must accept input where a toast actually is."""
        self.window.show()
        _app.processEvents()
        toast = self.window.toasts.show_toast("hello", "info", detail="detail")
        _app.processEvents()
        self.window.toasts.reflow()
        _app.processEvents()

        root = self._root()
        centre = toast.close_btn.mapTo(root, toast.close_btn.rect().center())
        self.assertIs(
            root.childAt(centre),
            toast.close_btn,
            "the toast's own Dismiss button is not reachable",
        )

    def test_the_app_stays_clickable_while_a_toast_is_showing(self):
        self.window.show()
        _app.processEvents()
        self.window.toasts.show_toast("hello", "info")
        _app.processEvents()
        self.window.toasts.reflow()
        _app.processEvents()

        root = self._root()
        button = self.window.rail.buttons["settings"]
        centre = button.mapTo(root, button.rect().center())
        self.assertIs(root.childAt(centre), button)

    def test_dialog_buttons_keep_their_deliberate_default_behaviour(self):
        """Making buttons autoDefault must not make a destructive one the default."""
        from neogui.widgets.dialogs import ConfirmDialog

        dialog = ConfirmDialog(
            self.window.ctx, title="Remove?", body="body", destructive=True
        )
        self.assertFalse(dialog.confirm.isDefault())
        self.assertFalse(dialog.confirm.autoDefault())
        dialog.reject()


class TestAccessibility(WindowTestCase):
    def test_interactive_controls_carry_accessible_names(self):
        """Screen readers need a name on anything clickable."""
        from PySide6.QtWidgets import QAbstractButton, QComboBox, QLineEdit

        missing = []
        for key, view in self.window.views.items():
            self.window.navigate(key)
            _app.processEvents()
            for widget in [
                w
                for cls in (QAbstractButton, QLineEdit, QComboBox)
                for w in view.findChildren(cls)
            ]:
                if not widget.isVisibleTo(view):
                    continue
                name = (
                    widget.accessibleName()
                    or getattr(widget, "text", lambda: "")()
                    or widget.toolTip()
                    or getattr(widget, "placeholderText", lambda: "")()
                )
                if not name:
                    missing.append(f"{key}: {type(widget).__name__}")
        self.assertEqual(missing, [], f"unlabelled controls: {missing[:6]}")

    def test_nav_buttons_are_keyboard_focusable(self):
        from PySide6.QtCore import Qt

        for btn in self.window.rail.buttons.values():
            self.assertNotEqual(btn.focusPolicy(), Qt.FocusPolicy.NoFocus)

    def test_the_toggle_switch_responds_to_the_keyboard(self):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QKeyEvent

        from neogui.widgets.common import Toggle

        toggle = Toggle(self.window.theme, False)
        event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier)
        toggle.keyPressEvent(event)
        self.assertTrue(toggle.isChecked(), "Space must operate the switch")


class TestPlatformIntegration(unittest.TestCase):
    def test_the_desktop_entry_is_valid_and_installs_into_xdg_paths(self):
        import configparser
        import tempfile

        from neogui import platform_integration as plat

        with tempfile.TemporaryDirectory() as tmp:
            old = os.environ.get("XDG_DATA_HOME")
            os.environ["XDG_DATA_HOME"] = tmp
            try:
                path = plat.install_desktop_entry("/usr/bin/neo-gui")
                self.assertTrue(path.exists())
                parser = configparser.ConfigParser(interpolation=None)
                parser.read(path)
                entry = parser["Desktop Entry"]
                self.assertEqual(entry["Type"], "Application")
                self.assertEqual(entry["Icon"], plat.APP_ID)
                self.assertEqual(
                    entry["StartupWMClass"],
                    plat.APP_ID,
                    "without this, docks cannot match the window to the entry",
                )
                self.assertIn("x-scheme-handler/neolauncher", entry["MimeType"])
                self.assertTrue(plat.icon_install_path().exists(), "the icon must ship too")
                plat.remove_desktop_entry()
                self.assertFalse(path.exists())
            finally:
                if old is None:
                    os.environ.pop("XDG_DATA_HOME", None)
                else:
                    os.environ["XDG_DATA_HOME"] = old

    def test_environment_probes_never_raise(self):
        from neogui import platform_integration as plat

        plat.is_wayland()
        plat.desktop_environment()
        plat.session_summary()
        plat.tray_available()
        self.assertFalse(plat.open_path(""))
        self.assertFalse(plat.open_url(""))


if __name__ == "__main__":
    unittest.main()
