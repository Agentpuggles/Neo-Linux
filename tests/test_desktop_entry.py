"""GUI-first entry points and source installs, without Qt or network access.

Subprocess tests replace only the installed app with a tiny stub. They exercise
the real launcher, shebang, package lookup and backend lookup away from the
checkout, with the install's bin directory deliberately absent from PATH.
"""

import configparser
import contextlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest import mock

from tests import support
from tests.support import neo


class TestGuiDispatch(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.root = self.stack.enter_context(support.temp_dir())
        self.stack.enter_context(
            support.environment(DISPLAY=":test", WAYLAND_DISPLAY=None, QT_QPA_PLATFORM=None, NEO_BIN=None)
        )
        self.stack.enter_context(mock.patch.object(neo, "__file__", str(self.root / "neo")))
        self.exec = self.stack.enter_context(mock.patch.object(neo.os, "execvpe"))
        self.which = self.stack.enter_context(mock.patch.object(neo.shutil, "which", return_value=None))

    def touch(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
        return str(path)

    def test_bare_invocation_dispatches_before_auth_or_argument_parsing(self):
        with (
            mock.patch.object(sys, "argv", ["neo"]),
            mock.patch.object(neo, "open_gui") as gui,
            mock.patch.object(neo, "Auth") as auth,
            mock.patch.object(neo, "make_parser") as parser,
        ):
            neo.main()
        gui.assert_called_once_with()
        auth.assert_not_called()
        parser.assert_not_called()

    def test_checkout_uses_the_running_python_without_a_local_venv(self):
        script = self.touch(self.root / "gui" / "neo-gui")
        neo.open_gui()
        program, command, env = self.exec.call_args.args
        self.assertEqual(program, sys.executable)
        self.assertEqual(command, [sys.executable, script])
        self.assertEqual(env["NEO_BIN"], str(self.root / "neo"))
        self.which.assert_not_called()

    def test_checkout_prefers_its_pyside_virtualenv(self):
        script = self.touch(self.root / "gui" / "neo-gui")
        python = self.touch(self.root / ".venv" / "bin" / "python")
        with mock.patch.object(sys, "prefix", sys.base_prefix):
            neo.open_gui()
        self.assertEqual(self.exec.call_args.args[:2], (python, [python, script]))

    def test_an_explicit_virtualenv_is_not_overridden(self):
        script = self.touch(self.root / "gui" / "neo-gui")
        self.touch(self.root / ".venv" / "bin" / "python")
        with mock.patch.object(sys, "prefix", "/another/venv"):
            neo.open_gui()
        self.assertEqual(self.exec.call_args.args[1], [sys.executable, script])

    def test_adjacent_install_precedes_path_and_preserves_backend_override(self):
        script = self.touch(self.root / "neo-gui")
        with support.environment(NEO_BIN="/custom/neo"):
            neo.open_gui()
        self.assertEqual(self.exec.call_args.args[:2], (script, [script]))
        self.assertEqual(self.exec.call_args.args[2]["NEO_BIN"], "/custom/neo")
        self.which.assert_not_called()

    def test_path_fallback_can_be_a_bundled_executable(self):
        self.which.return_value = "/opt/Neo/neo-gui"
        neo.open_gui()
        self.assertEqual(self.exec.call_args.args[:2], ("/opt/Neo/neo-gui", ["/opt/Neo/neo-gui"]))
        self.which.assert_called_once_with("neo-gui")

    def test_missing_gui_explains_installation_and_cli_usage(self):
        with self.assertRaisesRegex(RuntimeError, r"not installed.*\n.*make install.*\n.*neo --help"):
            neo.open_gui()
        self.exec.assert_not_called()

    def test_exec_failure_is_actionable(self):
        self.touch(self.root / "neo-gui")
        self.exec.side_effect = PermissionError("not executable")
        with self.assertRaisesRegex(RuntimeError, r"could not start.*\n.*make install.*neo --help"):
            neo.open_gui()

    def test_wayland_and_explicit_offscreen_platform_are_accepted(self):
        self.touch(self.root / "neo-gui")
        for session in ({"WAYLAND_DISPLAY": "wayland-0"}, {"QT_QPA_PLATFORM": "offscreen"}):
            with self.subTest(session=session), support.environment(DISPLAY=None, **session):
                self.exec.reset_mock()
                neo.open_gui()
                self.exec.assert_called_once()

    def test_missing_qt_does_not_break_terminal_commands(self):
        package = self.root / "PySide6"
        package.mkdir()
        (package / "__init__.py").write_text("raise ImportError(\"No module named 'PySide6'\")\n")
        env = {"PYTHONPATH": str(self.root)}
        self.assertEqual(support.run_cli("--version", env=env).strip(), neo.VERSION)
        self.assertIn("commands", support.run_cli("--help", env=env))
        self.assertIn("workers =", support.run_cli("config", env=env))
        text = support.run_cli(expect_rc=1, env=env)
        self.assertIn("needs PySide6", text)
        self.assertIn("make install", text)
        self.assertIn("neo --help", text)
        self.assertNotIn("pip install --user", text)
        self.assertNotIn("Traceback", text)


@unittest.skipUnless(shutil.which("make"), "source install tests need make")
class TestSourceInstall(unittest.TestCase):
    def setUp(self):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        self.root = stack.enter_context(support.temp_dir())
        self.stage = self.root / "stage"
        self.prefix = Path("/opt/Neo Test")
        self.installed = self.stage / str(self.prefix).lstrip("/")

    def make(self, target, *, staged=True, gui_python=None):
        result = subprocess.run(
            [
                "make",
                "--no-print-directory",
                target,
                f"DESTDIR={self.stage if staged else ''}",
                f"PREFIX={self.prefix if staged else self.installed}",
                f"GUI_PYTHON={gui_python or sys.executable}",
            ],
            cwd=support.REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def run_installed(self, name, *args, expected=0):
        env = dict(os.environ)
        for key in ("NEO_BIN", "NEO_GUI_ROOT", "PYTHONPATH"):
            env.pop(key, None)
        env.update(HOME=str(self.root), PATH="/usr/bin:/bin", DISPLAY=":test")
        result = subprocess.run(
            [str(self.installed / "bin" / name), *args],
            cwd=self.root,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result.stdout

    def stub_app(self):
        (self.installed / "share/neo/neogui/app.py").write_text(
            "import sys\n"
            "from neogui.backend.core import launcher_path, neo_module\n"
            "def main():\n"
            "    print('GUI opened')\n"
            "    print(launcher_path())\n"
            "    print(neo_module().VERSION)\n"
            "    print(repr(sys.argv[1:]))\n"
            "    return 23\n"
        )

    def desktop_entry(self):
        parser = configparser.ConfigParser(interpolation=None)
        parser.read(self.installed / "share/applications/dev.neofn.NeoLauncher.desktop")
        return parser["Desktop Entry"]

    def test_default_and_gui_installs_keep_the_backend_private(self):
        for target in ("install", "install-gui"):
            with self.subTest(target=target):
                self.stage = self.root / target
                self.installed = self.stage / str(self.prefix).lstrip("/")
                self.make(target)
                for path in (
                    "share/neo/neo",
                    "bin/neo-gui",
                    "share/neo/neogui/app.py",
                    "share/applications/dev.neofn.NeoLauncher.desktop",
                    "share/icons/hicolor/scalable/apps/dev.neofn.NeoLauncher.svg",
                    "share/metainfo/dev.neofn.NeoLauncher.metainfo.xml",
                ):
                    self.assertTrue((self.installed / path).is_file(), path)
                self.assertFalse((self.installed / "bin/neo").exists())
                self.assertFalse(os.access(self.installed / "share/neo/neo", os.X_OK))
                self.assertFalse(list(self.installed.rglob("*.pyc")))
                self.assertTrue(os.access(self.installed / "bin/neo-gui", os.X_OK))
                script = (self.installed / "bin/neo-gui").read_text()
                self.assertTrue(script.startswith("#!/usr/bin/env python3\n"))
                entry = self.desktop_entry()
                self.assertEqual(entry["Exec"], f'"{self.prefix}/bin/neo-gui" %u')
                self.assertEqual(entry["TryExec"], f"{self.prefix}/bin/neo-gui")
                self.assertEqual(entry["Terminal"], "false")
                self.assertIn("x-scheme-handler/neolauncher", entry["MimeType"])
                self.assertNotIn(str(self.stage), str(dict(entry)))

    def test_default_launch_and_direct_callback_work_outside_the_checkout(self):
        self.make("install")
        self.stub_app()
        for name, args in (("neo-gui", []), ("neo-gui", ["neolauncher://callback/auth?code=test"])):
            with self.subTest(name=name):
                text = self.run_installed(name, *args, expected=23)
                self.assertIn("GUI opened", text)
                self.assertIn(str(self.installed / "share/neo/neo"), text)
                self.assertIn(repr(args), text)
        self.assertFalse((self.installed / "bin/neo").exists())

    def test_explicit_install_all_includes_the_cli_and_keeps_gui_default(self):
        self.make("install-all")
        self.assertEqual(self.run_installed("neo", "--version").strip(), neo.VERSION)
        self.stub_app()
        text = self.run_installed("neo", expected=23)
        self.assertIn("GUI opened", text)
        self.assertIn(str(self.installed / "share/neo/neo"), text)

    def test_gui_install_preserves_an_existing_cli_and_uses_its_own_backend(self):
        self.make("install-cli")
        old_cli = self.installed / "bin/neo"
        old_cli.write_text("# existing user-managed command\n")
        self.make("install")
        self.assertEqual(old_cli.read_text(), "# existing user-managed command\n")
        self.stub_app()
        self.assertIn(neo.VERSION, self.run_installed("neo-gui", expected=23))

    def test_user_install_pins_the_selected_interpreter_and_menu_path(self):
        python = self.root / "Python with spaces" / "python"
        python.parent.mkdir()
        python.symlink_to(sys.executable)
        self.make("install", staged=False, gui_python=str(python))
        script = (self.installed / "bin/neo-gui").read_text()
        self.assertEqual(script.splitlines()[0], f"#!/usr/bin/env -S '{python}'")
        self.assertEqual(self.desktop_entry()["Exec"], f'"{self.installed}/bin/neo-gui" %u')
        self.stub_app()
        self.assertIn("GUI opened", self.run_installed("neo-gui", expected=23))
        self.assertIn(str(self.installed / "share/neo/neo"), self.run_installed("neo-gui", expected=23))

    def test_cli_only_install_needs_no_gui_files(self):
        self.make("install-cli")
        self.assertEqual(self.run_installed("neo", "--version").strip(), neo.VERSION)
        self.assertFalse((self.installed / "bin/neo-gui").exists())
        self.assertFalse((self.installed / "share").exists())
        self.make("uninstall-cli")
        self.assertFalse((self.installed / "bin/neo").exists())

    def test_uninstall_and_legacy_alias_preserve_user_data(self):
        for target in ("uninstall", "uninstall-all"):
            with self.subTest(target=target):
                self.make("install-all")
                kept = []
                for path in ("auth.json", "state.json", "cache/chunks/test", "prism/client"):
                    file = self.installed / "share/neo" / path
                    file.parent.mkdir(parents=True, exist_ok=True)
                    file.write_text("keep me")
                    kept.append(file)
                self.make(target)
                for file in kept:
                    self.assertEqual(file.read_text(), "keep me")
                for path in (
                    "bin/neo",
                    "bin/neo-gui",
                    "share/neo/neogui",
                    "share/neo/neo",
                    "share/applications/dev.neofn.NeoLauncher.desktop",
                    "share/icons/hicolor/scalable/apps/dev.neofn.NeoLauncher.svg",
                    "share/metainfo/dev.neofn.NeoLauncher.metainfo.xml",
                ):
                    self.assertFalse((self.installed / path).exists(), path)


if __name__ == "__main__":
    unittest.main()
