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


class TestLaunchArgumentForwarding(CliTestCase):
    """Fixed in 0.4.0: flag-shaped UE4 arguments reach the game (CHANGELOG → Added).

    `extra` is an argparse REMAINDER: options (--dry-run, --proton) must come
    before the first UE4 argument, and a leading `--` separator is stripped.
    """

    def test_flag_shaped_arguments_are_kept(self):
        args = neo.make_parser().parse_args(["launch", "--dry-run", "10.40", "-windowed", "-log"])
        self.assertEqual(args.extra, ["-windowed", "-log"])
        self.assertTrue(args.dry_run)
        self.assertEqual(args.version, "10.40")

    def test_double_dash_separator_is_accepted_and_stripped(self):
        args = neo.make_parser().parse_args(["launch", "10.40", "--", "-windowed"])
        self.assertEqual(args.extra, ["-windowed"])  # argparse drops the separator


if __name__ == "__main__":
    unittest.main()


class TestStatusWatch(CliTestCase):
    """--watch polls fortniteAccess and exits with a notification once granted."""

    def run_status_watch(self, access_value):
        import io
        from unittest import mock

        auth = neo.Auth()
        auth.d = {"account_id": "ACCOUNT", "refresh_token": "R", "access_token": "A",
                  "display_name": "n", "access_expires_at": None}

        def fake_jhttp(method, url, body=None, headers=None, timeout=60):
            if url.endswith("/token"):
                return {"access_token": "T"}
            if "lightswitch" in url:
                return {"status": "UP", "banned": False, "allowedActions": []}
            if "ban-status" in url:
                return {"banned": False}
            if url.endswith("/fortniteAccess"):
                return access_value
            if "entitlements" in url:
                return {"ownedOfferIds": ["5"]}
            if "onlinecount" in url:
                return {"count": 3}
            return {}

        with mock.patch.object(neo, "jhttp", fake_jhttp), \
                mock.patch.object(neo, "notify") as notified, \
                contextlib.redirect_stdout(io.StringIO()) as out:
            neo.cmd_status(
                __import__("argparse").Namespace(watch=True, interval=10), auth)
        return out.getvalue(), notified

    def test_watch_exits_and_notifies_once_access_is_granted(self):
        output, notified = self.run_status_watch(True)
        self.assertIn("granted", output)
        notified.assert_called_once()
        self.assertIn("neo launch", notified.call_args[0][1])

    def test_watch_reports_deny_without_notifying(self):
        # watching while denied is endless by design — stop the clock at the
        # first sleep and check what had been printed by then
        class ClockStopped(Exception):
            pass

        def stop_the_clock(_seconds):
            raise ClockStopped

        import io
        from unittest import mock

        auth = neo.Auth()
        auth.d = {"account_id": "ACCOUNT", "refresh_token": "R", "access_token": "A",
                  "display_name": "n", "access_expires_at": None}

        def fake_jhttp(method, url, body=None, headers=None, timeout=60):
            if url.endswith("/token"):
                return {"access_token": "T"}
            if "lightswitch" in url:
                return {"status": "UP", "banned": False}
            if "ban-status" in url:
                return {"banned": False}
            if url.endswith("/fortniteAccess"):
                return False
            if "entitlements" in url:
                return {}
            if "onlinecount" in url:
                return {}
            return {}

        import argparse

        with mock.patch.object(neo, "jhttp", fake_jhttp), \
                mock.patch.object(neo, "notify") as notified, \
                mock.patch.object(neo.time, "sleep", stop_the_clock), \
                contextlib.redirect_stdout(io.StringIO()) as out, self.assertRaises(ClockStopped):
            neo.cmd_status(argparse.Namespace(watch=True, interval=10), auth)
        self.assertIn("fortniteAccess: False", out.getvalue())
        notified.assert_not_called()


class TestUninstall(CliTestCase):
    def make_install(self):
        root = self.home / "game"
        inst = root / "++Fortnite+Release-10.40-CL-9380822"
        (inst / "FortniteGame").mkdir(parents=True)
        (inst / ".neo-manifest.json").write_text("{}")
        (inst / "FortniteGame" / "x.bin").write_bytes(b"payload")
        state = {"installs": {"++Fortnite+Release-10.40-CL-9380822": {"path": str(inst)}}}
        (self.home / "share").mkdir(exist_ok=True)
        (self.home / "share" / "state.json").write_text(json.dumps(state))
        return inst

    def test_uninstall_with_yes_removes_files_and_state(self):
        import argparse
        import io

        inst = self.make_install()
        with contextlib.redirect_stdout(io.StringIO()):
            neo.cmd_uninstall(argparse.Namespace(version=None, yes=True))
        self.assertFalse(inst.exists())
        self.assertEqual(json.loads((self.home / "share" / "state.json").read_text()),
                         {"installs": {}})

    def test_uninstall_refuses_dirs_without_our_manifest(self):
        import argparse
        import io

        inst = self.make_install()
        (inst / ".neo-manifest.json").unlink()
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
            neo.cmd_uninstall(argparse.Namespace(version=None, yes=True))
        self.assertTrue(inst.exists())  # nothing deleted
        # the stale state entry was dropped anyway
        self.assertEqual(json.loads((self.home / "share" / "state.json").read_text()),
                         {"installs": {}})


class TestCacheCommand(CliTestCase):
    def test_stats_then_clear(self):
        import argparse
        import io

        chunks = pathlib.Path(neo.cache_dir()) / "chunks"
        chunks.mkdir(parents=True, exist_ok=True)
        (chunks / "abc").write_bytes(b"0" * 2048)
        (chunks / "def").write_bytes(b"0" * 1024)
        manifests = pathlib.Path(neo.cache_dir()) / "manifests"
        manifests.mkdir(parents=True, exist_ok=True)
        (manifests / "10.40.json").write_text("{}")

        with contextlib.redirect_stdout(io.StringIO()) as out:
            neo.cmd_cache(argparse.Namespace(action="stats", all=False))
        self.assertIn("2 file(s)", out.getvalue())

        with contextlib.redirect_stdout(io.StringIO()):
            neo.cmd_cache(argparse.Namespace(action="clear", all=False))
        self.assertFalse((chunks / "abc").exists())
        self.assertTrue((manifests / "10.40.json").exists())  # kept unless --all


class TestNewsFormatter(unittest.TestCase):
    def test_list_payload_and_dict_wrapping_list(self):
        direct = neo.format_news(
            [{"title": "Season X", "message": "Soon.", "date": "2026-08-30"}])
        self.assertEqual(direct, [("2026-08-30", "Season X", "Soon.")])
        wrapped = neo.format_news({"news": [{"title": "Hi", "body": "Body"}],
                                   "hash": "x"})
        self.assertEqual(wrapped, [("", "Hi", "Body")])

    def test_items_without_any_text_are_dropped(self):
        self.assertEqual(neo.format_news([{"id": 1}, "junk", {}]), [])


class TestLogCommand(CliTestCase):
    def test_find_and_print_with_highlight(self):
        import argparse
        import io

        prefix = self.home / "prefix"
        log_dir = prefix / "drive_c" / "users" / "steamuser" / "AppData" / \
            "Local" / "FortniteGame" / "Saved" / "Logs"
        log_dir.mkdir(parents=True)
        log = log_dir / "FortniteGame.log"
        log.write_text(" mundane line\nCheckEntitledToPlay → 403\n")

        with support.environment(WINEPREFIX=str(prefix)):
            self.assertEqual(neo.find_game_log(), str(log))
            with contextlib.redirect_stdout(io.StringIO()) as out:
                neo.cmd_log(argparse.Namespace(follow=False, path=None))
        text = out.getvalue()
        self.assertIn("403", text)
        self.assertIn("\033[33m", text)   # the entitlement line is highlighted
        self.assertNotIn("\033[33m" + " mundane", text)




class TestSourceHygiene(CliTestCase):
    """Invalid escape sequences warn on newer Pythons and become errors eventually.

    Found in the wild: running `neo` on Python 3.12 surfaced a SyntaxWarning
    from a docstring containing a Windows path. This tokenizes `neo` and fails
    on any invalid escape in any non-raw string, on every Python in the CI
    matrix (the interpreter's own warning only appears on 3.12+).
    """

    def test_no_invalid_escape_sequences(self):
        import io as _io
        import tokenize

        backslash = chr(92)
        # everything a backslash may legally precede inside a non-raw string
        valid = set("'\"" + backslash + "abfnrtv01234567xNuU" + chr(10))
        source = (support.REPO_ROOT / "neo").read_text(encoding="utf-8")
        offenders = []
        for tok in tokenize.generate_tokens(_io.StringIO(source).readline):
            if tok.type != tokenize.STRING:
                continue
            text = tok.string
            i, raw = 0, False
            while i < len(text) and text[i] in "bBfFuUrR":
                if text[i] in "rR":
                    raw = True
                i += 1
            if raw:
                continue
            body = text[i:]
            j = body.find(backslash)
            while j != -1:
                follower = body[j + 1] if j + 1 < len(body) else ""
                if follower not in valid:
                    offenders.append(f"line {tok.start[0]}: {text[:60]}")
                    break
                j = body.find(backslash, j + 2)
        self.assertEqual(offenders, [])



class TestLaunchArgVector(CliTestCase):
    """The launch command line, pinned to the decompiled official client.

    Golden copy below is transcribed from GameLauncher.LaunchAsync in
    NeoLauncher.dll 1.0.7 (IL 0x12AE79-0x12AF5C). If either side changes,
    this test is the tripwire — update it only with a new DLL reading.
    """

    DLL_FLAGS = ("-epicapp=Fortnite", "-epicenv=Prod", "-epicportal",
                 "-skippatchcheck", "-nobe", "-fromfl=eac",
                 "-AUTH_LOGIN=unused", "-AUTH_TYPE=exchangecode")

    def test_vector_matches_the_dll(self):
        argv = neo.game_argv("C:\\g\\Win64", "CODE1", "CODE2", "tok123", ["-windowed"])
        self.assertEqual(argv[0], "-basedir=C:\\g\\Win64")  # bare: see protocol 8.1
        self.assertEqual(argv[1:9], list(self.DLL_FLAGS))
        self.assertEqual(argv[9:12], ["-AUTH_PASSWORD=CODE1", "-p=CODE2",
                                      "-fltoken=tok123"])
        self.assertEqual(argv[12:], ["-windowed"])

    def test_module_constants_agree_with_the_golden_copy(self):
        self.assertEqual(list(neo.OFFICIAL_ARGS), list(self.DLL_FLAGS))

    def test_fltoken_shape_matches_randomnumbergenerator_getstring(self):
        import string

        token = neo.fl_token()
        self.assertEqual(len(token), 24)
        self.assertTrue(set(token) <= set(string.ascii_lowercase + string.digits))
        self.assertNotEqual(token, neo.fl_token())
