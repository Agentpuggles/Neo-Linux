"""Optional CLI installation and first-run policy; no Qt, network or real HOME."""

import contextlib
import os
import stat
import subprocess
import sys
import unittest
from unittest import mock

from tests import support

GUI_ROOT = support.REPO_ROOT / "gui"
if str(GUI_ROOT) not in sys.path:
    sys.path.insert(0, str(GUI_ROOT))

from neogui.backend import cli_tool  # noqa: E402
from neogui.backend.errors import NeoError  # noqa: E402
from neogui.backend.service import NeoService  # noqa: E402


class CliToolTestCase(unittest.TestCase):
    def setUp(self):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        self.root = stack.enter_context(support.temp_dir())
        python_bin = self.root / "system-bin"
        python_bin.mkdir()
        (python_bin / "python3").symlink_to(sys.executable)
        stack.enter_context(
            support.environment(
                HOME=str(self.root),
                PATH=str(python_bin),
                NEO_HOME=str(self.root / "data"),
                NEO_CACHE=str(self.root / "cache"),
                XDG_CONFIG_HOME=str(self.root / "config"),
                NEO_BIN=str(support.REPO_ROOT / "neo"),
            )
        )
        self.source = self.root / "bundle" / "share" / "neo" / "neo"
        self.source.parent.mkdir(parents=True)
        self.payload = (support.REPO_ROOT / "neo").read_bytes()
        self.source.write_bytes(self.payload)
        self.source.chmod(0o644)  # the GUI's private backend is not a terminal command
        self.target = cli_tool.user_cli_path()


class TestCliInstallation(CliToolTestCase):
    def test_private_backend_is_not_mistaken_for_an_installed_cli(self):
        status = cli_tool.cli_status(self.source)
        self.assertFalse(status.installed)
        self.assertFalse(status.conflict)
        self.assertEqual(status.path, self.target)
        self.assertFalse(self.target.exists())

    def test_install_is_executable_and_survives_a_bundle_being_removed(self):
        result = cli_tool.install_cli(self.source)
        self.assertTrue(result.installed)
        self.assertFalse(result.on_path)
        self.assertEqual(result.path, self.target)
        self.assertEqual(self.target.read_bytes(), self.payload)
        self.assertEqual(stat.S_IMODE(self.target.stat().st_mode), 0o755)
        self.assertFalse(self.target.is_symlink())
        self.source.unlink()
        process = subprocess.run(
            [str(self.target), "--version"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stdout.strip(), support.neo.VERSION)
        self.assertFalse(list(self.target.parent.glob(".neo-cli-*")))

    def test_install_does_not_touch_accounts_settings_or_shell_profiles(self):
        files = [self.root / ".bashrc", self.root / ".profile", self.root / "data/auth.json"]
        for path in files:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("keep this content")
        cli_tool.install_cli(self.source)
        for path in files:
            self.assertEqual(path.read_text(), "keep this content")
        self.assertFalse((self.root / "config").exists())

    def test_install_is_idempotent_and_preserves_existing_cli_versions(self):
        cli_tool.install_cli(self.source)
        older = self.payload + b"\n# previously installed CLI\n"
        self.target.write_bytes(older)
        with mock.patch.object(cli_tool.os, "link") as link:
            self.assertTrue(cli_tool.install_cli(self.source).installed)
        link.assert_not_called()
        self.assertEqual(self.target.read_bytes(), older)

    def test_cli_on_path_is_recognised_without_running_it(self):
        other_bin = self.root / "existing-bin"
        other_bin.mkdir()
        existing = other_bin / "neo"
        existing.write_bytes(self.payload)
        existing.chmod(0o755)
        with support.environment(PATH=str(other_bin)):
            status = cli_tool.cli_status(self.source)
            self.assertEqual(status.path, existing)
            self.assertTrue(status.installed)
            self.assertTrue(status.on_path)
            self.assertEqual(status.help_command, "neo --help")
            cli_tool.install_cli(self.source)
        self.assertFalse(self.target.exists())

    def test_custom_prefix_cli_is_detected_even_outside_path(self):
        existing = self.source.parents[2] / "bin/neo"
        existing.parent.mkdir()
        existing.write_bytes(self.payload)
        existing.chmod(0o755)
        status = cli_tool.cli_status(self.source)
        self.assertTrue(status.installed)
        self.assertFalse(status.on_path)
        self.assertEqual(status.path, existing)

    def test_path_hint_uses_the_exact_installed_path_when_shadowed(self):
        cli_tool.install_cli(self.source)
        other_bin = self.root / "other-bin"
        other_bin.mkdir()
        other = other_bin / "neo"
        other.write_text("#!/bin/sh\nexit 42\n")
        other.chmod(0o755)
        with support.environment(PATH=f"{other_bin}:{self.target.parent}"):
            status = cli_tool.cli_status(self.source)
        self.assertTrue(status.installed)
        self.assertFalse(status.on_path)
        self.assertIn(str(self.target), status.help_command)
        with support.environment(PATH=str(self.target.parent)):
            self.assertEqual(cli_tool.cli_status(self.source).help_command, "neo --help")

    def test_unknown_files_directories_and_symlinks_are_never_replaced(self):
        self.target.parent.mkdir(parents=True)
        other = self.root / "some-other-tool"
        other.write_text("not Neo")
        for kind in ("file", "directory", "symlink", "broken-symlink", "non-executable-cli"):
            with self.subTest(kind=kind):
                if kind == "directory":
                    self.target.mkdir()
                elif kind == "symlink":
                    self.target.symlink_to(other)
                elif kind == "broken-symlink":
                    self.target.symlink_to(self.root / "missing")
                elif kind == "non-executable-cli":
                    self.target.write_bytes(self.payload)
                    self.target.chmod(0o644)
                else:
                    self.target.write_text("not Neo")
                self.assertTrue(cli_tool.cli_status(self.source).conflict)
                with self.assertRaisesRegex(NeoError, "already in use"):
                    cli_tool.install_cli(self.source)
                self.assertTrue(os.path.lexists(self.target))
                self.assertEqual(other.read_text(), "not Neo")
                if kind == "directory":
                    self.target.rmdir()
                else:
                    self.target.unlink()

    def test_a_destination_created_during_install_is_not_overwritten(self):
        def another_process(*args):
            self.target.write_text("another command won the race")
            raise FileExistsError(str(self.target))

        with (
            mock.patch.object(cli_tool.os, "link", side_effect=another_process),
            self.assertRaises(NeoError),
        ):
            cli_tool.install_cli(self.source)
        self.assertEqual(self.target.read_text(), "another command won the race")
        self.assertFalse(list(self.target.parent.glob(".neo-cli-*")))

    def test_permission_failure_leaves_no_partial_command_or_temporary_file(self):
        with (
            mock.patch.object(cli_tool.os, "link", side_effect=PermissionError("read-only")),
            self.assertRaises(NeoError) as caught,
        ):
            cli_tool.install_cli(self.source)
        self.assertEqual(caught.exception.kind, "permission")
        self.assertFalse(self.target.exists())
        self.assertFalse(list(self.target.parent.glob(".neo-cli-*")))

    def test_missing_or_unrecognised_source_fails_without_creating_a_command(self):
        for contents in (None, b"not the Neo source"):
            with self.subTest(contents=contents):
                if contents is None:
                    self.source.unlink()
                else:
                    self.source.write_bytes(contents)
                with self.assertRaises(NeoError):
                    cli_tool.install_cli(self.source)
                self.assertFalse(self.target.exists())


class TestCliOfferPolicy(CliToolTestCase):
    def test_new_users_are_offered_the_cli_without_installing_it_implicitly(self):
        service = NeoService()
        self.assertTrue(service.should_offer_cli())
        self.assertFalse(self.target.exists())
        self.assertFalse(service.config()["gui_cli_prompt_dismissed"])

    def test_not_now_is_remembered_across_service_instances(self):
        service = NeoService()
        service.set_config("gui_cli_prompt_dismissed", True)
        self.assertFalse(NeoService().should_offer_cli())
        self.assertFalse(self.target.exists())

    def test_already_installed_cli_is_not_offered_again(self):
        service = NeoService()
        service.install_cli()
        self.assertFalse(NeoService().should_offer_cli())
        self.assertTrue(service.cli_status().installed)

    def test_declining_does_not_prevent_installing_later(self):
        service = NeoService()
        service.set_config("gui_cli_prompt_dismissed", True)
        self.assertTrue(service.install_cli().installed)
        self.assertFalse(service.should_offer_cli())
        self.assertTrue(self.target.is_file())

    def test_prompt_copy_explains_recommendation_and_later_installation(self):
        for text in ("highly recommended", "troubleshooting", "manually", "works without it", "later"):
            self.assertIn(text, cli_tool.RECOMMENDATION)
        self.assertIn("Settings → Command-line tool", cli_tool.RECOMMENDATION)


if __name__ == "__main__":
    unittest.main()
