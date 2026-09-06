"""Tests for the GUI's backend layer.

These deliberately do NOT import Qt: `neogui.backend` is Qt-free by design, so
the whole service façade — error classification, config validation, redaction,
install/verify orchestration and the diagnostics report — is testable headlessly
on a machine with no display server and no PySide6 installed.

Everything runs offline: `neo`'s network functions are monkeypatched, and every
path is redirected into a scratch directory by `tests.support`.
"""

import json
import os
import pathlib
import sys
import unittest

from tests import support

GUI_ROOT = pathlib.Path(__file__).resolve().parents[1] / "gui"
if str(GUI_ROOT) not in sys.path:
    sys.path.insert(0, str(GUI_ROOT))

from neogui.backend import core  # noqa: E402
from neogui.backend.errors import NeoError, classify  # noqa: E402
from neogui.backend.service import (  # noqa: E402
    Cancelled,
    CancelToken,
    NeoService,
    redact,
)


class ServiceTestCase(unittest.TestCase):
    """Base: a scratch NEO_HOME and a fresh NeoService per test."""

    def setUp(self):
        self.home = support.scratch_home()
        os.environ["NEO_BIN"] = str(pathlib.Path(__file__).resolve().parents[1] / "neo")
        core._module = None
        self.service = NeoService()
        self.neo = self.service.neo

    def write_state(self, installs):
        path = os.path.join(self.neo.data_dir(), "state.json")
        with open(path, "w") as fh:
            json.dump({"installs": installs}, fh)

    def make_install(self, name="10.40", *, binaries=True, manifest=True):
        root = pathlib.Path(self.home) / "games" / name
        if binaries:
            (root / "FortniteGame" / "Binaries" / "Win64").mkdir(parents=True, exist_ok=True)
        else:
            root.mkdir(parents=True, exist_ok=True)
        if manifest:
            (root / ".neo-manifest.json").write_text("{}")
        return str(root)


# ------------------------------------------------------------------- errors
class TestErrorClassification(unittest.TestCase):
    def test_network_errors_get_a_hint(self):
        import urllib.error

        err = classify(urllib.error.URLError("no route to host"), action="Loading news")
        self.assertEqual(err.kind, "network")
        self.assertIn("Loading news failed", err.summary)
        self.assertTrue(err.hint, "a network failure must tell the user what to do")

    def test_http_401_is_an_auth_problem(self):
        import urllib.error

        err = classify(
            urllib.error.HTTPError("u", 401, "Unauthorized", {}, None), action="Launching"
        )
        self.assertEqual(err.kind, "auth")
        self.assertIn("sign in again", err.hint.lower())

    def test_permission_error_explains_itself(self):
        err = classify(PermissionError(13, "denied"), action="Installing")
        self.assertEqual(err.kind, "permission")
        self.assertIn("permission denied", err.summary.lower())

    def test_enospc_suggests_moving_the_cache(self):
        import errno

        err = classify(OSError(errno.ENOSPC, "no space"), action="Installing")
        self.assertIn("disk is full", err.summary)
        self.assertIn("Settings", err.hint)

    def test_checksum_failures_point_at_repair(self):
        err = classify(RuntimeError("sha1 mismatch (want abc… got def…)"), action="Installing")
        self.assertIn("Verify", err.hint)

    def test_neoerror_passes_through_unchanged(self):
        original = NeoError("already human", "detail", "hint")
        self.assertIs(classify(original), original)

    def test_text_joins_all_three_parts(self):
        err = NeoError("summary", "detail", "hint")
        self.assertIn("summary", err.text)
        self.assertIn("detail", err.text)
        self.assertIn("hint", err.text)


# ---------------------------------------------------------------- redaction
class TestRedaction(unittest.TestCase):
    def test_tokens_are_stripped(self):
        raw = (
            'access_token: "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9abc"\n'
            "-AUTH_PASSWORD=9f8e7d6c5b4a39281706\n"
            "Authorization: Bearer sk_live_0123456789abcdef\n"
        )
        cleaned = redact(raw)
        self.assertNotIn("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9abc", cleaned)
        self.assertNotIn("9f8e7d6c5b4a39281706", cleaned)
        self.assertNotIn("sk_live_0123456789abcdef", cleaned)
        self.assertIn("<redacted>", cleaned)

    def test_ordinary_text_survives(self):
        text = "Downloading 411 files from the CDN"
        self.assertEqual(redact(text), text)

    def test_none_is_safe(self):
        self.assertEqual(redact(None), "")


# ------------------------------------------------------------------- config
class TestConfig(ServiceTestCase):
    def test_defaults_include_gui_keys(self):
        cfg = self.service.config()
        self.assertIn("gui_theme", cfg)
        self.assertIn("install_root", cfg)

    def test_writing_a_setting_is_visible_to_the_cli(self):
        self.service.set_config("workers", 8)
        self.assertEqual(self.neo.load_config()["workers"], 8)

    def test_unknown_settings_are_rejected(self):
        with self.assertRaises(NeoError):
            self.service.set_config("rm -rf /", "yes")

    def test_int_settings_are_coerced_and_clamped(self):
        self.service.set_config("workers", "24")
        self.assertEqual(self.service.config()["workers"], 24)
        self.service.set_config("workers", 0)
        self.assertEqual(self.service.config()["workers"], 1)

    def test_non_numeric_worker_count_is_an_error(self):
        with self.assertRaises(NeoError):
            self.service.set_config("workers", "lots")

    def test_paths_are_expanded(self):
        self.service.set_config("install_root", "~/Games/Elsewhere")
        self.assertNotIn("~", self.service.config()["install_root"])

    def test_launch_options_parse_like_a_shell(self):
        parsed = self.service.validate_launch_options('-windowed -Name="My Rig"')
        self.assertEqual(parsed, ["-windowed", "-Name=My Rig"])

    def test_unbalanced_quotes_are_reported_not_raised_raw(self):
        with self.assertRaises(NeoError) as ctx:
            self.service.validate_launch_options('-Name="unclosed')
        self.assertIn("quote", ctx.exception.hint.lower())


# ------------------------------------------------------------------ session
class TestSession(ServiceTestCase):
    def test_signed_out_by_default(self):
        self.assertFalse(self.service.session().logged_in)

    def test_extract_code_from_a_full_callback_url(self):
        code = "a" * 40
        got = self.service.extract_code(f"neolauncher://callback/auth?code={code}&state=x")
        self.assertEqual(got, code)

    def test_extract_code_accepts_a_bare_code(self):
        code = "b" * 32
        self.assertEqual(self.service.extract_code(code), code)

    def test_truncated_codes_are_rejected_with_guidance(self):
        with self.assertRaises(NeoError) as ctx:
            self.service.extract_code("neolauncher://callback/auth?code=abc…")
        self.assertIn("complete", ctx.exception.hint.lower())

    def test_empty_input_is_rejected(self):
        with self.assertRaises(NeoError):
            self.service.extract_code("   ")

    def test_initials_come_from_the_display_name(self):
        from neogui.backend.models import Session

        self.assertEqual(Session(True, "id", "NeoPlayer").initials, "NE")
        self.assertEqual(Session(True, "id", "Shadow Blade").initials, "SB")
        self.assertEqual(Session(False).initials, "?")


# ----------------------------------------------------------------- installs
class TestInstalls(ServiceTestCase):
    def test_no_installs_by_default(self):
        self.assertEqual(self.service.installs(), [])

    def test_playable_flag_needs_the_win64_folder(self):
        good = self.make_install("10.40")
        bad = self.make_install("9.41", binaries=False)
        self.write_state(
            {"Fortnite/10.40-CL-2": {"path": good}, "Fortnite/9.41-CL-1": {"path": bad}}
        )
        by_version = {i.version: i for i in self.service.installs()}
        self.assertTrue(by_version["Fortnite/10.40-CL-2"].playable)
        self.assertFalse(by_version["Fortnite/9.41-CL-1"].playable)

    def test_a_deleted_folder_is_reported_not_hidden(self):
        self.write_state({"Fortnite/10.40-CL-2": {"path": "/nonexistent/build"}})
        install = self.service.installs()[0]
        self.assertFalse(install.exists)
        self.assertFalse(install.playable)

    def test_installs_are_sorted_newest_changelist_first(self):
        self.write_state(
            {
                "Fortnite/9.41-CL-8085900": {"path": self.make_install("9.41")},
                "Fortnite/10.40-CL-9603448": {"path": self.make_install("10.40")},
            }
        )
        self.assertEqual(self.service.installs()[0].short, "10.40")

    def test_short_name_strips_the_changelist(self):
        from neogui.backend.models import Install

        self.assertEqual(Install("Fortnite/10.40-CL-9603448", "/x").short, "10.40")

    def test_resolving_live_picks_the_newest(self):
        self.write_state(
            {
                "Fortnite/9.41-CL-1": {"path": self.make_install("9.41")},
                "Fortnite/10.40-CL-2": {"path": self.make_install("10.40")},
            }
        )
        version, _ = self.service._resolve_install("live")
        self.assertEqual(version, "Fortnite/10.40-CL-2")

    def test_resolving_with_nothing_installed_says_so(self):
        with self.assertRaises(NeoError) as ctx:
            self.service._resolve_install(None)
        self.assertEqual(ctx.exception.kind, "notfound")

    def test_resolving_an_unknown_version_is_notfound(self):
        self.write_state({"Fortnite/10.40-CL-2": {"path": self.make_install("10.40")}})
        with self.assertRaises(NeoError) as ctx:
            self.service._resolve_install("42.0")
        self.assertEqual(ctx.exception.kind, "notfound")


# -------------------------------------------------------------- destructive
class TestUninstall(ServiceTestCase):
    def test_removing_deletes_the_folder_and_the_entry(self):
        path = self.make_install("10.40")
        self.write_state({"Fortnite/10.40-CL-2": {"path": path}})
        self.service.uninstall("10.40")
        self.assertFalse(os.path.exists(path))
        self.assertEqual(self.service.installs(), [])

    def test_a_folder_without_a_manifest_is_never_deleted(self):
        """The CLI's safety guard must survive into the GUI."""
        path = self.make_install("10.40", manifest=False)
        self.write_state({"Fortnite/10.40-CL-2": {"path": path}})
        with self.assertRaises(NeoError) as ctx:
            self.service.uninstall("10.40")
        self.assertTrue(os.path.isdir(path), "refusing must not delete anything")
        self.assertEqual(ctx.exception.kind, "permission")
        self.assertEqual(self.service.installs(), [], "the stale entry is dropped")

    def test_keeping_files_only_forgets_the_entry(self):
        path = self.make_install("10.40")
        self.write_state({"Fortnite/10.40-CL-2": {"path": path}})
        self.service.uninstall("10.40", delete_files=False)
        self.assertTrue(os.path.isdir(path))
        self.assertEqual(self.service.installs(), [])


# ------------------------------------------------------------------- import
class TestImport(ServiceTestCase):
    def test_a_folder_that_is_not_a_build_root_is_rejected(self):
        empty = pathlib.Path(self.home) / "not-a-build"
        empty.mkdir()
        with self.assertRaises(NeoError) as ctx:
            self.service.import_build(str(empty), "10.40")
        self.assertEqual(ctx.exception.kind, "notfound")
        self.assertIn("FortniteGame", ctx.exception.hint)


# -------------------------------------------------------------------- cache
class TestCache(ServiceTestCase):
    def test_stats_count_files_and_bytes(self):
        chunks = pathlib.Path(self.neo.cache_dir()) / "chunks"
        chunks.mkdir(parents=True, exist_ok=True)
        (chunks / "abc").write_bytes(b"x" * 1024)
        stats = self.service.cache_stats()
        self.assertEqual(stats.chunk_files, 1)
        self.assertEqual(stats.chunk_bytes, 1024)

    def test_clearing_removes_chunks_but_keeps_manifests_by_default(self):
        cache = pathlib.Path(self.neo.cache_dir())
        (cache / "chunks").mkdir(parents=True, exist_ok=True)
        (cache / "manifests").mkdir(parents=True, exist_ok=True)
        (cache / "chunks" / "a").write_bytes(b"12345")
        (cache / "manifests" / "m.json").write_text("{}")
        removed, freed = self.service.clear_cache()
        self.assertEqual(removed, 1)
        self.assertEqual(freed, 5)
        self.assertTrue((cache / "manifests" / "m.json").exists())

    def test_clearing_everything_takes_manifests_too(self):
        cache = pathlib.Path(self.neo.cache_dir())
        (cache / "manifests").mkdir(parents=True, exist_ok=True)
        (cache / "manifests" / "m.json").write_text("{}")
        self.service.clear_cache(manifests=True)
        self.assertFalse((cache / "manifests" / "m.json").exists())


# ------------------------------------------------------------------- verify
class TestVerify(ServiceTestCase):
    def test_verifying_without_a_manifest_explains_why(self):
        path = self.make_install("10.40", manifest=False)
        self.write_state({"Fortnite/10.40-CL-2": {"path": path}})
        with self.assertRaises(NeoError) as ctx:
            self.service.verify_install("10.40")
        self.assertEqual(ctx.exception.kind, "notfound")
        self.assertIn("Import", ctx.exception.hint)

    def test_a_missing_file_is_reported(self):
        path = self.make_install("10.40")
        manifest = {
            "ManifestFileVersion": "0",
            "FileManifestList": [
                {
                    "Filename": "FortniteGame/Content/missing.pak",
                    "FileHash": "0" * 60,
                    "FileChunkParts": [],
                }
            ],
            "ChunkHashList": {},
            "DataGroupList": {},
            "ChunkFilesizeList": {},
        }
        (pathlib.Path(path) / ".neo-manifest.json").write_text(json.dumps(manifest))
        self.write_state({"Fortnite/10.40-CL-2": {"path": path}})
        report = self.service.verify_install("10.40")
        self.assertFalse(report.clean)
        self.assertEqual(len(report.missing), 1)

    def test_cancelling_stops_the_scan(self):
        path = self.make_install("10.40")
        (pathlib.Path(path) / ".neo-manifest.json").write_text(
            json.dumps(
                {
                    "FileManifestList": [
                        {"Filename": f"f{i}", "FileHash": "0" * 60, "FileChunkParts": []}
                        for i in range(50)
                    ],
                    "ChunkHashList": {},
                    "DataGroupList": {},
                    "ChunkFilesizeList": {},
                }
            )
        )
        self.write_state({"Fortnite/10.40-CL-2": {"path": path}})
        token = CancelToken()
        token.cancel()
        with self.assertRaises(Cancelled):
            self.service.verify_install("10.40", cancel=token)


# ------------------------------------------------------------------- launch
class TestLaunch(ServiceTestCase):
    def test_launching_signed_out_is_an_auth_error(self):
        with self.assertRaises(NeoError) as ctx:
            self.service.build_launch_plan()
        self.assertEqual(ctx.exception.kind, "auth")

    def test_launch_plan_masks_credentials_in_the_preview(self):
        from neogui.backend.models import LaunchPlan

        plan = LaunchPlan(
            executable="/tmp/exe",
            argv=[
                "-basedir=Z:\\game",
                "-AUTH_PASSWORD=supersecretcode",
                "-p=anothersecret",
                "-fltoken=abcdef",
                "-windowed",
            ],
        )
        shown = " ".join(plan.display_command())
        self.assertNotIn("supersecretcode", shown)
        self.assertNotIn("anothersecret", shown)
        self.assertIn("-AUTH_PASSWORD=***", shown)
        self.assertIn("-windowed", shown, "harmless args stay readable")

    def test_wine_abort_is_turned_into_actionable_advice(self):
        tail = "wine: Call to unimplemented function ntdll.dll.RtlFoo, aborting"
        err = self.service.launch_failure(1, tail)
        self.assertIn("GE-Proton", err.hint)

    def test_missing_umu_exit_code_is_explained(self):
        err = self.service.launch_failure(127, "sh: umu-run: not found")
        self.assertIn("umu", err.hint.lower())

    def test_launch_failure_detail_is_redacted(self):
        err = self.service.launch_failure(1, "-AUTH_PASSWORD=deadbeefdeadbeef failed")
        self.assertNotIn("deadbeefdeadbeef", err.detail)


# -------------------------------------------------------------- diagnostics
class TestDiagnostics(ServiceTestCase):
    def test_environment_names_the_display_server(self):
        env = self.service.environment()
        self.assertIn("display server", env)
        self.assertIn("distro", env)

    def test_report_never_contains_a_token(self):
        auth_path = os.path.join(self.neo.data_dir(), "auth.json")
        with open(auth_path, "w") as fh:
            json.dump(
                {
                    "account_id": "abc123",
                    "display_name": "Tester",
                    "access_token": "TOTALLYSECRETACCESSTOKEN12345",
                    "refresh_token": "TOTALLYSECRETREFRESHTOKEN6789",
                },
                fh,
            )
        report = self.service.diagnostics_report()
        self.assertNotIn("TOTALLYSECRETACCESSTOKEN12345", report)
        self.assertNotIn("TOTALLYSECRETREFRESHTOKEN6789", report)
        self.assertIn("abc123", report, "the account id IS wanted for support")

    def test_report_includes_extra_sections(self):
        report = self.service.diagnostics_report(extra_sections={"Notes": "hello there"})
        self.assertIn("## Notes", report)
        self.assertIn("hello there", report)

    def test_report_lists_installs(self):
        self.write_state({"Fortnite/10.40-CL-2": {"path": self.make_install("10.40")}})
        self.assertIn("Fortnite/10.40-CL-2", self.service.diagnostics_report())


# --------------------------------------------------------------- cancelling
class TestCancelToken(unittest.TestCase):
    def test_check_raises_only_after_cancelling(self):
        token = CancelToken()
        token.check()
        token.cancel()
        self.assertTrue(token.cancelled)
        with self.assertRaises(Cancelled):
            token.check()


# --------------------------------------------------------------- the loader
class TestLauncherLoader(unittest.TestCase):
    def test_the_repo_checkout_is_a_candidate(self):
        candidates = [str(p) for p in core.candidate_paths()]
        self.assertTrue(
            any(c.endswith("/neo") for c in candidates),
            f"the checkout's `neo` should be searched, got {candidates[:4]}",
        )

    def test_the_module_exposes_the_cli_primitives(self):
        os.environ["NEO_BIN"] = str(pathlib.Path(__file__).resolve().parents[1] / "neo")
        core._module = None
        module = core.neo_module()
        for symbol in (
            "Auth",
            "Manifest",
            "fetch_chunk",
            "assemble_file",
            "game_argv",
            "load_config",
            "wine_abort_hint",
        ):
            self.assertTrue(
                hasattr(module, symbol), f"the GUI relies on neo.{symbol} existing"
            )

    def test_the_gui_reuses_the_cli_argument_vector(self):
        """If the GUI ever built its own argv, this would drift from the CLI."""
        os.environ["NEO_BIN"] = str(pathlib.Path(__file__).resolve().parents[1] / "neo")
        core._module = None
        module = core.neo_module()
        argv = module.game_argv("Z:\\game", "c1", "c2", "tok")
        self.assertIn("-epicapp=Fortnite", argv)
        self.assertIn("-AUTH_PASSWORD=c1", argv)


# -------------------------------------------------------------- service status
class TestServiceStatus(ServiceTestCase):
    """Status mapping, including the tri-state play gate (protocol.md §11.2)."""

    def stub(self, *, access, logged_in=True, entitlements=None):
        neo = self.neo
        if logged_in:
            self.service.auth().d = {
                "account_id": "ACCOUNT", "access_token": "A", "refresh_token": "R",
                "display_name": "n", "access_expires_at": None,
            }

        def fake_jhttp(method, url, body=None, headers=None, timeout=60):
            if url.endswith("/token"):
                return {"access_token": "T"}
            if "lightswitch" in url:
                return {"status": "UP", "message": "up", "banned": False,
                        "allowedActions": ["PLAY"]}
            if "ban-status" in url:
                return {"banned": False}
            if url.endswith("/fortniteAccess"):
                if isinstance(access, Exception):
                    raise access
                return access
            if "entitlements" in url:
                return entitlements or {}
            if "onlinecount" in url:
                return {"fortnite": 240, "launcher": 402}
            return {}

        original = neo.jhttp
        neo.jhttp = fake_jhttp
        self.addCleanup(setattr, neo, "jhttp", original)
        return self.service.service_status()

    def test_a_retired_gate_is_open_and_never_blocks_play(self):
        status = self.stub(access=self.neo.HttpError("GET", "https://x", 404, b""))
        self.assertEqual(status.access_gate, "open")
        self.assertTrue(status.access_ok)
        self.assertFalse(status.access_denied)
        self.assertEqual(status.access_label, "Open")
        self.assertEqual(status.access_tone, "success")

    def test_granted_and_denied_still_map_through(self):
        self.assertEqual(self.stub(access=True).access_gate, "granted")
        denied = self.stub(access=False)
        self.assertEqual(denied.access_gate, "denied")
        self.assertTrue(denied.access_denied)

    def test_an_unreadable_gate_is_unknown_and_not_a_denial(self):
        status = self.stub(access=self.neo.HttpError("GET", "https://x", 500, b""))
        self.assertEqual(status.access_gate, "unknown")
        self.assertFalse(status.access_denied)
        self.assertFalse(status.access_ok)

    def test_signed_out_leaves_the_gate_unknown(self):
        status = self.stub(access=True, logged_in=False)
        self.assertEqual(status.access_gate, "unknown")

    def test_players_online_prefers_the_game_over_the_launcher(self):
        self.assertEqual(self.stub(access=True).players_online, 240)


if __name__ == "__main__":
    unittest.main()
