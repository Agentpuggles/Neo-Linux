"""Manifest numerics and URL derivation — the parts of the format that are easy
to misread, pinned straight from the verified table in ``docs/protocol.md`` §5.1.
"""

import unittest

from tests import support
from tests.support import blob, neo, num_le


class TestBlobCodec(unittest.TestCase):
    def test_blob_to_bytes_roundtrips(self):
        for payload in (b"\x00", b"\x01\x02\x03", bytes(range(256))):
            self.assertEqual(neo.blob_to_bytes(blob(payload)), payload)

    def test_three_digits_per_byte(self):
        self.assertEqual(neo.blob_to_bytes("001002003"), b"\x01\x02\x03")


class TestParseNum(unittest.TestCase):
    """Every row of the protocol doc's "Verified against ``neo.parse_num``" table."""

    def test_documented_cases(self):
        cases = [
            ("031", 31),  # exactly 3 digits -> a plain group number, not a blob
            ("00000000063", 63),  # 11 digits: not a multiple of 3 -> plain int
            ("000001", 256),  # 6 digits -> 2-byte little-endian blob
            (63, 63),  # already numeric
            ("1048576", 1048576),  # 7 digits, not a multiple of 3 -> plain
        ]
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(neo.parse_num(value), expected)

    def test_little_endian_blob_widths(self):
        self.assertEqual(neo.parse_num(num_le(1, 4)), 1)
        self.assertEqual(neo.parse_num(num_le(0xDEADBEEF, 8)), 0xDEADBEEF)

    def test_unparseable_input_degrades_to_zero(self):
        # A manifest field we cannot read must not take the whole install down.
        self.assertEqual(neo.parse_num("not a number"), 0)
        self.assertEqual(neo.parse_num(""), 0)


class TestParseHashHex(unittest.TestCase):
    def test_sha1_blob_decodes_to_hex(self):
        digest = "2f2d0e0e4a1c9b3f5d6e7f8091a2b3c4d5e6f708"
        self.assertEqual(neo.parse_hash_hex(blob(bytes.fromhex(digest))), digest)

    def test_0x_prefix_stripped_and_lowercased(self):
        self.assertEqual(neo.parse_hash_hex("0xAABBCC"), "aabbcc")
        self.assertEqual(neo.parse_hash_hex("AABBCC"), "aabbcc")

    def test_non_string_is_empty_not_an_error(self):
        self.assertEqual(neo.parse_hash_hex(None), "")
        self.assertEqual(neo.parse_hash_hex(1234), "")


class TestManifest(unittest.TestCase):
    def test_parses_one_file_one_chunk(self):
        m = neo.Manifest(support.manifest_dict())
        self.assertEqual(m.chunk_subdir, "ChunksV3")  # feature level 13
        self.assertEqual(len(m.files), 1)
        guid = next(iter(m.chunks))
        chunk = m.chunks[guid]
        self.assertEqual(chunk["hash"], 0x487A33F0F2E5F569)
        self.assertEqual(chunk["group"], 31)
        self.assertEqual(len(chunk["sha1"]), 40)
        self.assertEqual(m.files[0]["name"].rsplit("/", 1)[-1], "FortniteClient-Win64-Shipping.exe")
        self.assertTrue(m.files[0]["exec"])
        self.assertIsNone(m.files[0]["symlink"])
        self.assertEqual(m.files[0]["parts"], [(guid, 0, 16)])

    def test_version_drops_the_platform_suffix(self):
        m = neo.Manifest(support.manifest_dict())
        self.assertEqual(m.version(), "++Fortnite+Release-10.40-CL-9380822")

    def test_chunk_relpath_is_the_decompiled_dll_formula(self):
        # ChunksV3/{group:02d}/{rollingHash:016X}_{GUID}.chunk  (protocol.md §6.1)
        m = neo.Manifest(support.manifest_dict())
        guid = "1832294A440167B074AC75B6A842F82A"
        self.assertEqual(
            m.chunk_relpath(guid), "ChunksV3/31/487A33F0F2E5F569_1832294A440167B074AC75B6A842F82A.chunk"
        )

    def test_unknown_chunk_falls_back_to_group_zero(self):
        m = neo.Manifest(support.manifest_dict())
        self.assertTrue(m.chunk_relpath("F" * 32).startswith("ChunksV3/00/"))

    def test_feature_level_15_switches_to_the_v4_layout(self):
        m = neo.Manifest(support.manifest_dict(ManifestFileVersion="015000000000"))
        self.assertEqual(m.chunk_subdir, "ChunksV4")
        guid = "1832294A440167B074AC75B6A842F82A"
        self.assertEqual(m.chunk_relpath(guid), f"ChunksV4/18/{guid}.chunk")

    def test_symlink_entries_are_preserved(self):
        entry = support.manifest_dict()["FileManifestList"][0]
        entry.update(
            {
                "Filename": "libsettings.so",
                "SymlinkTarget": "../libsettings.conf",
                "bIsUnixExecutable": False,
                "FileChunkParts": [],
            }
        )
        m = neo.Manifest(support.manifest_dict(FileManifestList=[entry]))
        self.assertEqual(m.files[0]["symlink"], "../libsettings.conf")
        self.assertFalse(m.files[0]["exec"])


if __name__ == "__main__":
    unittest.main()
