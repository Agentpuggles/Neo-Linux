"""Offline release/runtime regressions. No Qt, network, FUSE or real user data."""

import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest import mock

from tests import support

GUI = support.REPO_ROOT / "gui"
if str(GUI) not in sys.path:
    sys.path.insert(0, str(GUI))

from neogui import runtime  # noqa: E402
from neogui.backend import core  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "appimage_build_test", support.REPO_ROOT / "packaging/appimage.py"
)
packaging = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(packaging)


class TestHostEnvironment(unittest.TestCase):
    def test_source_installs_leave_the_environment_untouched(self):
        original = {"LD_LIBRARY_PATH": "/my/libs", "QT_PLUGIN_PATH": "/my/qt", "WINEPREFIX": "/games"}
        with mock.patch.object(runtime.sys, "frozen", False, create=True):
            result = runtime.host_environment(original)
        self.assertEqual(result, original)
        self.assertIsNot(result, original)

    def test_frozen_children_restore_host_libraries_and_keep_game_overrides(self):
        original = {
            "APPDIR": "/tmp/.mount_Neo",
            "APPIMAGE": "/home/me/Neo.AppImage",
            "LD_LIBRARY_PATH": "/tmp/.mount_Neo/usr/bin/_internal:/custom/libs",
            "LD_LIBRARY_PATH_ORIG": "/custom/libs",
            "QT_PLUGIN_PATH": "/tmp/.mount_Neo/usr/bin/_internal/PySide6/plugins:/my/qt",
            "QML2_IMPORT_PATH": "/tmp/.mount_Neo/qml",
            "NEO_BIN": "/tmp/.mount_Neo/usr/bin/_internal/neo",
            "_PYI_APPLICATION_HOME_DIR": "/tmp/.mount_Neo/usr/bin/_internal",
            "PROTONPATH": "GE-Proton",
            "WINEPREFIX": "/games/prefix",
            "NEO_HOME": "/games/neo",
            "PATH": "/home/me/bin:/usr/bin",
            "WAYLAND_DISPLAY": "wayland-0",
        }
        before = dict(original)
        with (
            mock.patch.object(runtime.sys, "frozen", True, create=True),
            mock.patch.object(runtime.sys, "_MEIPASS", "/tmp/.mount_Neo/usr/bin/_internal", create=True),
        ):
            result = runtime.host_environment(original)
        self.assertEqual(result["LD_LIBRARY_PATH"], "/custom/libs")
        self.assertEqual(result["QT_PLUGIN_PATH"], "/my/qt")
        for key in (
            "APPIMAGE",
            "APPDIR",
            "_PYI_APPLICATION_HOME_DIR",
            "NEO_BIN",
            "QML2_IMPORT_PATH",
            "LD_LIBRARY_PATH_ORIG",
        ):
            self.assertNotIn(key, result)
        for key in ("PROTONPATH", "WINEPREFIX", "NEO_HOME", "PATH", "WAYLAND_DISPLAY"):
            self.assertEqual(result[key], original[key])
        self.assertEqual(original, before, "never mutate the GUI or LaunchPlan environment")

    def test_game_launch_uses_the_clean_host_environment(self):
        from neogui.backend.models import LaunchPlan
        from neogui.backend.service import NeoService

        plan = LaunchPlan(
            version="10.40",
            executable="Fortnite.exe",
            working_dir="/tmp",
            argv=[],
            umu="/usr/bin/umu-run",
            env={
                "LD_LIBRARY_PATH": "/bundle/libs",
                "LD_LIBRARY_PATH_ORIG": "/host/libs",
                "WINEPREFIX": "/my/games/prefix",
            },
        )
        process = mock.Mock()
        process.stderr = io.BytesIO(b"")
        process.wait.return_value = 0
        with (
            mock.patch.object(runtime.sys, "frozen", True, create=True),
            mock.patch("neogui.backend.service.subprocess.Popen", return_value=process) as popen,
        ):
            self.assertEqual(NeoService().run_launch(plan), 0)
        env = popen.call_args.kwargs["env"]
        self.assertEqual(env["LD_LIBRARY_PATH"], "/host/libs")
        self.assertEqual(env["WINEPREFIX"], "/my/games/prefix")
        self.assertEqual(plan.env["LD_LIBRARY_PATH"], "/bundle/libs")

    def test_an_originally_unset_library_path_is_removed(self):
        with mock.patch.object(runtime.sys, "frozen", True, create=True):
            for extra in ({}, {"LD_LIBRARY_PATH_ORIG": ""}):
                self.assertNotIn(
                    "LD_LIBRARY_PATH", runtime.host_environment({"LD_LIBRARY_PATH": "/bundle", **extra})
                )

    def test_similarly_named_host_directories_are_not_removed(self):
        with (
            mock.patch.object(runtime.sys, "frozen", True, create=True),
            mock.patch.object(runtime.sys, "_MEIPASS", "/tmp/bundle", create=True),
        ):
            result = runtime.host_environment({"QT_PLUGIN_PATH": "/tmp/bundle-other/qt"})
        self.assertEqual(result["QT_PLUGIN_PATH"], "/tmp/bundle-other/qt")


class TestDurableDesktopCommand(unittest.TestCase):
    def test_the_original_appimage_wins_over_the_mount_or_an_old_install(self):
        path = "/home/gamer/My apps/Neo 100%.AppImage"
        with (
            support.environment(APPIMAGE=path, NEO_GUI_EXEC=None),
            mock.patch.object(runtime.sys, "frozen", True, create=True),
            mock.patch.object(runtime.sys, "executable", "/tmp/.mount_Neo/usr/bin/neo-gui"),
            mock.patch.object(runtime.shutil, "which", return_value="/old/bin/neo-gui"),
        ):
            self.assertEqual(runtime.launch_argv(), [path])

    def test_an_extracted_payload_pins_its_own_frozen_executable(self):
        with (
            support.environment(APPIMAGE=None, NEO_GUI_EXEC=None),
            mock.patch.object(runtime.sys, "frozen", True, create=True),
            mock.patch.object(runtime.sys, "executable", "/apps/Neo/usr/bin/neo-gui"),
        ):
            self.assertEqual(runtime.launch_argv(), ["/apps/Neo/usr/bin/neo-gui"])

    def test_a_source_launcher_keeps_its_virtualenv_interpreter(self):
        with (
            support.environment(NEO_GUI_EXEC=None),
            mock.patch.object(runtime.sys, "frozen", False, create=True),
            mock.patch.object(runtime.sys, "executable", "/my venv/bin/python"),
            mock.patch.object(runtime.sys, "argv", [str(GUI / "neo-gui")]),
        ):
            self.assertEqual(runtime.launch_argv(), ["/my venv/bin/python", str(GUI / "neo-gui")])

    def test_explicit_commands_are_parsed_as_arguments_not_executed_by_a_shell(self):
        with support.environment(NEO_GUI_EXEC='"/my apps/Neo.AppImage" --theme dark'):
            self.assertEqual(runtime.launch_argv(), ["/my apps/Neo.AppImage", "--theme", "dark"])

    def test_desktop_arguments_escape_both_layers_and_literal_percent_signs(self):
        self.assertEqual(
            runtime.desktop_argument("/my apps/Neo 100%.AppImage"), '"/my apps/Neo 100%%.AppImage"'
        )
        argument = runtime.desktop_argument('"$`\\')
        self.assertTrue(argument.startswith('"'))
        self.assertIn('\\\\"', argument)
        self.assertIn("\\\\$", argument)
        self.assertIn("\\\\`", argument)
        self.assertIn("\\\\\\\\", argument)
        self.assertEqual(runtime.desktop_value("line\nnext"), "line\\nnext")

    def test_the_loader_prefers_the_frozen_resource(self):
        with (
            support.environment(NEO_BIN=None),
            mock.patch.object(core.sys, "frozen", True, create=True),
            mock.patch.object(core.sys, "_MEIPASS", "/tmp/Neo/usr/bin/_internal", create=True),
        ):
            self.assertEqual(core.candidate_paths()[0], Path("/tmp/Neo/usr/bin/_internal/neo"))


class TestReleaseInputs(unittest.TestCase):
    def test_release_version_is_the_actual_backend_version(self):
        self.assertEqual(packaging.version(), support.neo.VERSION)

    def test_version_is_parsed_without_executing_the_source(self):
        with support.temp_dir() as tmp:
            source = tmp / "neo"
            source.write_text('raise RuntimeError("must not execute")\nVERSION = "1.2.3-rc.1"\n')
            self.assertEqual(packaging.version(source), "1.2.3-rc.1")
            for invalid in ('"../bad"', '"1.2.3; echo bad"', "str(1)"):
                source.write_text(f"VERSION = {invalid}\n")
                with self.assertRaises(ValueError):
                    packaging.version(source)

    def test_all_dynamic_backend_imports_are_collected(self):
        modules = packaging.backend_imports()
        for name in (
            "xml.etree.ElementTree",
            "concurrent.futures",
            "urllib.request",
            "ssl",
            "zlib",
            "secrets",
        ):
            self.assertIn(name, modules)
        self.assertNotIn("cf", modules)
        self.assertNotIn("__future__", modules)

    def test_reviewed_tools_have_fixed_tags_and_sha256_pins(self):
        pins = json.loads((support.REPO_ROOT / "packaging/appimage-tools.json").read_text())
        self.assertEqual(set(pins), {"runtime", "appimagetool"})
        for pin in pins.values():
            self.assertNotIn(pin["tag"], ("continuous", "latest", ""))
            self.assertRegex(pin["sha256"], r"^[0-9a-f]{64}$")
            self.assertIn("x86_64", pin["asset"])

    def test_checksums_refuse_unreviewed_tool_content(self):
        with support.temp_dir() as tmp:
            tool = tmp / "tool"
            tool.write_bytes(b"known input")
            expected = hashlib.sha256(b"known input").hexdigest()
            packaging.verify(tool, expected)
            tool.write_bytes(b"changed input")
            with self.assertRaisesRegex(ValueError, "refusing"):
                packaging.verify(tool, expected)

    def test_cached_tools_are_still_verified_before_use(self):
        with support.temp_dir() as tmp:
            (tmp / "packaging").mkdir()
            tool_dir = tmp / "build/tools"
            tool_dir.mkdir(parents=True)
            payload = b"a verified build tool"
            pins = {
                "tool": {
                    "repository": "example/tool",
                    "tag": "1.0",
                    "asset": "tool.AppImage",
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            }
            (tmp / "packaging/appimage-tools.json").write_text(json.dumps(pins))
            target = tool_dir / "tool.AppImage"
            target.write_bytes(payload)
            with (
                mock.patch.object(packaging, "ROOT", tmp),
                mock.patch.object(packaging, "BUILD", tmp / "build"),
                mock.patch.object(packaging.subprocess, "run") as download,
            ):
                packaging.fetch_tools()
                download.assert_not_called()
                self.assertTrue(os.access(target, os.X_OK))
                target.write_bytes(b"untrusted replacement")

                def corrupt_download(argv, **kwargs):
                    Path(argv[argv.index("--output") + 1]).write_bytes(b"wrong download")

                download.side_effect = corrupt_download
                with self.assertRaisesRegex(ValueError, "SHA-256"):
                    packaging.fetch_tools()
                download.assert_called_once()
                self.assertFalse(list(tool_dir.glob("*.download")))

    def test_qt_license_version_matches_the_pinned_binding(self):
        requirements = (support.REPO_ROOT / "packaging/appimage-requirements.txt").read_text()
        self.assertIn(f"PySide6=={packaging.QT_VERSION}", requirements)
        self.assertIn("--hash=sha256:", requirements)


class TestAppRun(unittest.TestCase):
    def test_spaces_callback_arguments_private_core_and_host_path(self):
        with support.temp_dir() as tmp:
            appdir = tmp / "Neo portable directory"
            binary = appdir / "usr/bin/neo-gui"
            binary.parent.mkdir(parents=True)
            binary.write_text(
                "#!/usr/bin/env python3\nimport json, os, sys\n"
                'print(json.dumps({"argv": sys.argv[1:], "path": os.environ["PATH"], '
                '"backend": os.environ["NEO_BIN"], "appdir": os.environ["APPDIR"], '
                '"certs": os.environ.get("SSL_CERT_FILE")}))\n'
            )
            binary.chmod(0o755)
            app_run = appdir / "AppRun"
            shutil.copy2(support.REPO_ROOT / "packaging/AppRun", app_run)
            app_run.chmod(0o755)
            env = {**os.environ, "PATH": "/usr/bin:/bin"}
            env.pop("NEO_BIN", None)
            url = "neolauncher://callback?code=not-a-real-code&state=a%20b"
            result = subprocess.run(
                [str(app_run), url], cwd=tmp, env=env, capture_output=True, text=True, check=True
            )
            data = json.loads(result.stdout)
            self.assertEqual(data["argv"], [url])
            self.assertEqual(data["path"], env["PATH"])
            self.assertEqual(data["appdir"], str(appdir))
            self.assertEqual(data["backend"], str(appdir / "usr/bin/_internal/neo"))
            self.assertFalse((appdir / "usr/bin/neo").exists())
            env["SSL_CERT_FILE"] = "/custom/company-trust.pem"
            result = subprocess.run(
                [str(app_run)], cwd=tmp, env=env, capture_output=True, text=True, check=True
            )
            self.assertEqual(json.loads(result.stdout)["certs"], env["SSL_CERT_FILE"])

    def test_build_script_has_safe_help_and_valid_shell_syntax(self):
        script = support.REPO_ROOT / "packaging/build-appimage.sh"
        subprocess.run(["bash", "-n", str(script)], check=True)
        result = subprocess.run(["bash", str(script), "--help"], capture_output=True, text=True, check=True)
        self.assertIn("x86_64.AppImage", result.stdout)
        self.assertIn("Python 3.11", result.stdout)


if __name__ == "__main__":
    unittest.main()
