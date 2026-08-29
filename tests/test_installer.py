"""Build selection, file assembly and install bookkeeping."""

import contextlib
import hashlib
import io
import os
import pathlib
import shutil
import stat
import tempfile
import unittest

from tests import support
from tests.support import build_chunk, neo


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
