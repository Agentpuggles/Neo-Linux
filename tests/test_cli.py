"""The command-line contract: exit codes, help text and config persistence.

These run `neo` as a subprocess against a throwaway NEO_HOME/XDG_CONFIG_HOME, so
they cover argument parsing and file layout — the parts a user sees first — without
ever reaching the network.
"""

import contextlib
import json
import pathlib
import shutil
import tempfile
import unittest

from tests import support
from tests.support import neo


class CliTestCase(unittest.TestCase):
    def setUp(self):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="cli-", dir=str(support.SANDBOX)))
        self.addCleanup(shutil.rmtree, tmp, True)
        stack = contextlib.ExitStack()
        stack.enter_context(
            support.environment(
                NEO_HOME=str(tmp / "share"),
                NEO_CACHE=str(tmp / "cache"),
                XDG_CONFIG_HOME=str(tmp / "config"),
            )
        )
        self.addCleanup(stack.close)
        self.home = tmp
        self.config_file = tmp / "config" / "neo" / "config.json"

    def read_config(self):
        return json.loads(self.config_file.read_text())


class TestInvocation(CliTestCase):
    def test_version_flag_matches_the_launcher_constant(self):
        self.assertEqual(support.run_cli("--version").strip(), neo.VERSION)

    def test_help_lists_the_command_groups(self):
        text = support.run_cli("--help")
        for command in (
            "login",
            "whoami",
            "setup",
            "status",
            "list",
            "install",
            "verify",
            "launch",
            "config",
        ):
            self.assertIn(command, text)

    def test_every_subcommand_has_its_own_help(self):
        for command in (
            "login",
            "whoami",
            "setup",
            "logout",
            "status",
            "list",
            "config",
            "install",
            "verify",
            "launch",
        ):
            with self.subTest(command=command):
                self.assertIn("usage:", support.run_cli(command, "--help"))

    def test_install_documents_its_flags(self):
        text = support.run_cli("install", "--help")
        for flag in ("-d", "-j", "--keep-cache"):
            self.assertIn(flag, text)

    def test_launch_documents_its_flags(self):
        text = support.run_cli("launch", "--help")
        self.assertIn("--dry-run", text)
        self.assertIn("--proton", text)

    def test_unknown_command_exits_2(self):
        support.run_cli("frobnicate", expect_rc=2)

    def test_bare_invocation_asks_for_a_command(self):
        text = support.run_cli(expect_rc=2)
        self.assertIn("the following arguments are required", text)


class TestGatedCommands(CliTestCase):
    """Commands must fail with an actionable message, not a traceback."""

    def test_whoami_without_a_session(self):
        text = support.run_cli("whoami", expect_rc=1)
        self.assertIn("not logged in", text)
        self.assertNotIn("Traceback", text)

    def test_verify_without_an_install(self):
        self.assertIn("nothing installed yet", support.run_cli("verify", expect_rc=1))

    def test_launch_without_an_install(self):
        self.assertIn("nothing installed yet", support.run_cli("launch", expect_rc=1))

    def test_logout_empties_the_session(self):
        self.assertIn("logged out", support.run_cli("logout"))
        self.assertEqual(json.loads((self.home / "share" / "auth.json").read_text()), {})


class TestLoginFallbacks(CliTestCase):
    def test_placeholder_callback_codes_are_rejected_before_any_request(self):
        for code in ("…", "...", "CODE"):
            with self.subTest(code=code):
                text = support.run_cli(
                    "login", "--callback", f"neolauncher://callback/auth?code={code}", expect_rc=1
                )
                self.assertIn("placeholder/truncated", text)
                self.assertIn("neo login", text)

    def test_truncated_code_is_rejected(self):
        text = support.run_cli(
            "login", "--callback", "neolauncher://callback/auth?code=tooshort", expect_rc=1
        )
        self.assertIn("placeholder/truncated", text)


class TestConfigCommand(CliTestCase):
    def test_defaults_when_no_file_exists(self):
        text = support.run_cli("config")
        home = str(pathlib.Path.home())
        self.assertIn("install_root = ~/Games/Neo", text.replace(home, "~"))
        self.assertIn("workers = 16", text)

    def test_set_then_get_persists_the_value(self):
        self.assertIn("workers = 8", support.run_cli("config", "workers", "8"))
        self.assertEqual(self.read_config()["workers"], 8)  # stored as an int
        self.assertIn("workers = 8", support.run_cli("config", "workers"))

    def test_paths_are_stored_verbatim(self):
        support.run_cli("config", "install_root", "/mnt/big/Games")
        self.assertEqual(self.read_config()["install_root"], "/mnt/big/Games")

    def test_unset_key_reports_instead_of_failing(self):
        self.assertIn("nonsense", support.run_cli("config", "nonsense"))
        self.assertIn("(unset)", support.run_cli("config", "nonsense"))

    def test_settings_survive_a_second_invocation(self):
        support.run_cli("config", "cache_dir", str(self.home / "bulk"))
        self.assertIn(str(self.home / "bulk"), support.run_cli("config"))


class TestKnownLimitations(CliTestCase):
    """Pins the behaviour recorded in CHANGELOG.md → Known issues.

    `neo launch <ver> -windowed` cannot reach the game yet: argparse rejects
    flag-shaped tokens after the subcommand. If this test starts failing, the
    limitation was fixed — update the changelog and the README table with it.
    """

    def test_extra_ue4_arguments_are_rejected_at_parse_time(self):
        text = support.run_cli("launch", "10.40", "-windowed", expect_rc=2)
        self.assertIn("unrecognized arguments", text)


if __name__ == "__main__":
    unittest.main()
