"""Build selection, file assembly and install bookkeeping."""

import contextlib
import hashlib
import io
import json
import os
import pathlib
import shutil
import stat
import tempfile
import unittest
import unittest.mock

from tests import support
from tests.support import build_chunk, manifest_dict, neo


@contextlib.contextmanager
def quiet():
    """Swallow the launcher's own progress/`✔` output so test logs stay readable."""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
        yield buffer


def build_entry(version, live=False, size=1 << 30):
    return {
        "version": version,
        "isLive": live,
        "fileSizeBytes": size,
        "manifestPath": "Builds/Fortnite/CloudDir/x.manifest",
        "releaseDate": "2026-08-01",
    }


def sample_builds():
    return [
        build_entry("++Fortnite+Release-10.40-CL-9380822"),
        build_entry("++Fortnite+Release-10.32-CL-9200000", live=True),
        build_entry("++Fortnite+Release-9.00-CL-8000000"),
    ]


class TestBuildSelection(unittest.TestCase):
    def test_live_is_the_default(self):
        self.assertEqual(
            neo.pick_build(sample_builds(), None)["version"], "++Fortnite+Release-10.32-CL-9200000"
        )
        self.assertTrue(neo.pick_build(sample_builds(), "live")["isLive"])

    def test_version_is_a_substring_match(self):
        self.assertEqual(neo.pick_build(sample_builds(), "10.40")["fileSizeBytes"], 1 << 30)
        self.assertEqual(
            neo.pick_build(sample_builds(), "9.00")["version"], "++Fortnite+Release-9.00-CL-8000000"
        )

    def test_unmatched_selections_explain_themselves(self):
        with self.assertRaises(RuntimeError) as ctx:
            neo.pick_build(sample_builds(), "11.00")
        self.assertIn("neo list", str(ctx.exception))
        with self.assertRaises(RuntimeError):
            neo.pick_build([build_entry("x")], "live")  # nothing flagged live


class TestInstallState(unittest.TestCase):
    def test_changelist_number(self):
        self.assertEqual(neo.changelist_number("++Fortnite+Release-10.40-CL-9380822"), 9380822)
        self.assertEqual(neo.changelist_number("++Fortnite+Release-10.40"), 0)

    def test_live_means_highest_changelist_not_last_installed(self):
        st = {
            "installs": {
                "++Fortnite+Release-9.00-CL-8000000": {"path": "/old"},
                "++Fortnite+Release-10.40-CL-9380822": {"path": "/new"},
            }
        }
        with quiet():
            self.assertEqual(neo.select_install(None, st)[0], "++Fortnite+Release-10.40-CL-9380822")
            self.assertEqual(neo.select_install("live", st)[0], "++Fortnite+Release-10.40-CL-9380822")
            self.assertEqual(neo.select_install("9.00", st)[1], {"path": "/old"})

    def test_no_installs_and_no_match_exit_with_a_hint(self):
        with quiet() as out, self.assertRaises(SystemExit) as ctx:
            neo.select_install(None, {"installs": {}})
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("neo install", out.getvalue())
        with quiet(), self.assertRaises(SystemExit):
            neo.select_install("7.00", {"installs": {"10.40-CL-1": {}}})

    def test_install_directories_are_named_after_the_build(self):
        self.assertEqual(
            neo.version_dir_name("++Fortnite+Release-10.40-CL-9380822"),
            "++Fortnite+Release-10.40-CL-9380822",
        )


class TestAssembleFile(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="assemble-", dir=str(support.SANDBOX)))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def assemble(self, spec, chunk_cache, manifest=None):
        with quiet():
            neo.assemble_file(str(self.tmp), spec, chunk_cache, "https://cdn.invalid", manifest)

    def spec_for(self, name, payload, parts=None, **overrides):
        spec = {
            "name": name,
            "sha1": hashlib.sha1(payload).hexdigest(),
            "parts": parts or [("G1", 0, len(payload))],
            "exec": False,
            "symlink": None,
        }
        spec.update(overrides)
        return spec

    def test_chunks_are_concatenated_in_order(self):
        first, second = b"AAAA" * 4, b"BBBB" * 4
        self.assemble(
            self.spec_for("dir/file.bin", first + second, parts=[("G1", 0, 16), ("G2", 0, 16)]),
            {"G1": first, "G2": second},
        )
        self.assertEqual((self.tmp / "dir" / "file.bin").read_bytes(), first + second)

    def test_slices_are_taken_at_offset_and_size(self):
        chunk = b"0123456789abcdef"
        spec = self.spec_for("cut.bin", b"456789ab", parts=[("G1", 4, 8)])
        self.assemble(spec, {"G1": chunk})
        self.assertEqual((self.tmp / "cut.bin").read_bytes(), b"456789ab")

    def test_executable_flag_becomes_mode_0755(self):
        payload = b"#!/bin/sh\n"
        self.assemble(self.spec_for("run.sh", payload, exec=True), {"G1": payload})
        self.assertEqual(stat.S_IMODE(os.stat(self.tmp / "run.sh").st_mode), 0o755)

    def test_symlink_entries_are_links_not_files(self):
        spec = {
            "name": "libsettings.so",
            "sha1": "",
            "parts": [],
            "exec": False,
            "symlink": "../libsettings.conf",
        }
        self.assemble(spec, {})
        link = self.tmp / "libsettings.so"
        self.assertTrue(link.is_symlink())
        self.assertEqual(os.readlink(link), "../libsettings.conf")

    def test_a_hash_mismatch_leaves_no_partial_file_behind(self):
        spec = self.spec_for("bad.bin", b"data")
        spec["sha1"] = "0" * 40
        with quiet(), self.assertRaises(RuntimeError) as ctx:
            neo.assemble_file(str(self.tmp), spec, {"G1": b"data"}, "", None)
        self.assertIn("sha1 mismatch", str(ctx.exception))
        self.assertFalse((self.tmp / "bad.bin").exists())
        self.assertFalse((self.tmp / "bad.bin.tmp").exists())

    def test_missing_from_the_in_memory_cache_reads_the_bulk_cache(self):
        payload = b"from disk"
        raw, sha_hex = build_chunk(payload)
        guid = "A" * 32
        support.cache_chunk(guid, raw)
        spec = {
            "name": "disk.bin",
            "sha1": sha_hex,
            "parts": [(guid, 0, len(payload))],
            "exec": False,
            "symlink": None,
        }
        self.assemble(spec, {})
        self.assertEqual((self.tmp / "disk.bin").read_bytes(), payload)

    def test_manifest_paths_cannot_escape_the_install_directory(self):
        payload = b"nope"
        spec = self.spec_for("../../escaped.bin", payload)
        with self.assertRaises(RuntimeError) as ctx:
            self.assemble(spec, {"G1": payload})
        self.assertIn("outside", str(ctx.exception))
        self.assertFalse((support.SANDBOX / "escaped.bin").exists())
        spec["name"] = "/etc/escaped.bin"
        with self.assertRaises(RuntimeError):
            self.assemble(spec, {"G1": payload})


class TestHuman(unittest.TestCase):
    def test_sizes(self):
        cases = {
            0: "0 B",
            999: "999 B",
            1024: "1.0 KiB",
            1536: "1.5 KiB",
            int(61.9 * 1024**3): "61.9 GiB",
            1024**4: "1.0 TiB",
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(neo.human(value), expected)


if __name__ == "__main__":
    unittest.main()


class TestFreeSpacePreflight(unittest.TestCase):
    """Engineering note 9, turned into a guard: both bulk paths are checked first."""

    def test_short_and_ok_volumes(self):
        from unittest import mock

        fake = {"full": 100, "fine": 1 << 40}

        def disk_usage(path):
            class U:
                pass

            u = U()
            u.free = fake[path]
            return u

        with mock.patch.object(neo.shutil, "disk_usage", disk_usage):
            self.assertEqual(neo.free_space_shortages([("full", 200), ("fine", 500)]),
                             [("full", 100, 200)])
            self.assertEqual(neo.free_space_shortages([("fine", 500)]), [])

    def test_unstatable_paths_are_skipped(self):
        from unittest import mock

        with mock.patch.object(neo.shutil, "disk_usage",
                               side_effect=OSError("no such volume")):
            self.assertEqual(neo.free_space_shortages([("/gone", 1)]), [])


class TestImport(unittest.TestCase):
    def setUp(self):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="import-", dir=str(support.SANDBOX)))
        self.addCleanup(shutil.rmtree, tmp, True)
        stack = contextlib.ExitStack()
        stack.enter_context(support.environment(NEO_HOME=str(tmp / "share"),
                                                NEO_CACHE=str(tmp / "cache")))
        self.addCleanup(stack.close)
        self.home = tmp

    def make_build_root(self, complete=True):
        root = self.home / "build"
        (root / "FortniteGame" / "Binaries").mkdir(parents=True)
        if complete:
            (root / "Engine").mkdir()
        return root

    def test_import_registers_state_and_writes_manifest(self):
        import argparse

        root = self.make_build_root()
        with quiet(), unittest.mock.patch.object(neo, "get_builds", lambda a: sample_builds()), \
                 unittest.mock.patch.object(neo, "get_distribution_points",
                                        lambda: ["https://cdn.example"]), \
                 unittest.mock.patch.object(neo, "load_manifest",
                                        lambda v, u: neo.Manifest(manifest_dict())):
            neo.cmd_import(argparse.Namespace(path=str(root), version="10.40"), None)
        state = json.loads((self.home / "share" / "state.json").read_text())
        (version, entry), = state["installs"].items()
        self.assertIn("10.40", version)
        self.assertTrue(entry["imported"])
        self.assertEqual(entry["path"], str(root))
        self.assertTrue((root / ".neo-manifest.json").exists())

    def test_import_rejects_dirs_that_are_not_build_roots(self):
        import argparse

        root = self.make_build_root(complete=False)
        with quiet(), self.assertRaises(SystemExit):
            neo.cmd_import(argparse.Namespace(path=str(root), version="10.40"), None)


class TestVerifyRepair(unittest.TestCase):
    def setUp(self):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="repair-", dir=str(support.SANDBOX)))
        self.addCleanup(shutil.rmtree, tmp, True)
        stack = contextlib.ExitStack()
        stack.enter_context(support.environment(NEO_HOME=str(tmp / "share"),
                                                NEO_CACHE=str(tmp / "cache")))
        self.addCleanup(stack.close)
        self.home = tmp
        self.m = neo.Manifest(manifest_dict())
        self.inst_dir = tmp / "inst"
        self.inst_dir.mkdir()
        payload = b"neo test payload"
        guid = next(iter(self.m.chunks))
        with quiet():
            neo.assemble_file(str(self.inst_dir), self.m.files[0], {guid: payload},
                              "https://cdn.example", self.m)
        with open(self.inst_dir / ".neo-manifest.json", "w") as fh:
            json.dump(self.m.d, fh)
        state = {"installs": {"++Fortnite+Release-10.40-CL-9380822":
                              {"path": str(self.inst_dir)}}}
        (self.home / "share").mkdir()
        (self.home / "share" / "state.json").write_text(json.dumps(state))

    def target(self):
        return self.inst_dir / "FortniteGame" / "Binaries" / "Win64" / \
            "FortniteClient-Win64-Shipping.exe"

    def test_corrupt_file_is_repaired_from_cached_chunks(self):
        import argparse

        raw, _sha = build_chunk(b"neo test payload",
                                guid=next(iter(self.m.chunks)),
                                rolling_hash=0x487A33F0F2E5F569)
        support.cache_chunk(next(iter(self.m.chunks)), raw)
        self.target().write_bytes(b"corrupted!")  # sha1 no longer matches

        with quiet(), unittest.mock.patch.object(neo, "get_distribution_points",
                                        lambda: ["https://cdn.example"]):
            neo.cmd_verify(argparse.Namespace(version=None, repair=True), None)

        digest = hashlib.sha1(self.target().read_bytes()).hexdigest()
        self.assertEqual(digest, self.m.files[0]["sha1"])

    def test_without_repair_it_only_suggests(self):
        import argparse

        self.target().unlink()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            neo.cmd_verify(argparse.Namespace(version=None, repair=False), None)
        self.assertFalse(self.target().exists())  # nothing was fetched
        self.assertIn("--repair", buf.getvalue())
