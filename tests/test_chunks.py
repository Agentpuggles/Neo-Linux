"""Chunk storage: the 62-byte header, the CDN round-trip and the resume cache.

The header offsets here are the ones that silently broke every download for a day
(sha-1 read at 32/33 instead of 40/41) — see docs/engineering-notes.md §4.
"""

import os
import pathlib
import unittest
import zlib
from unittest import mock

from tests import support
from tests.support import build_chunk, cache_chunk, neo

CDN = "https://cdn.invalid"


class TestParseChunk(unittest.TestCase):
    def test_zlib_chunk(self):
        payload = os.urandom(4096)
        raw, sha_hex = build_chunk(payload)
        data, sha = neo.parse_chunk(raw)
        self.assertEqual(data, payload)
        self.assertEqual(sha, sha_hex)

    def test_stored_chunk_is_not_decompressed(self):
        payload = b"\x78\x9c" + b"already raw bytes"
        raw, _ = build_chunk(payload, stored=False)
        data, _ = neo.parse_chunk(raw)
        self.assertEqual(data, payload)

    def test_truncated_input(self):
        with self.assertRaises(ValueError) as ctx:
            neo.parse_chunk(b"\x00" * 10)
        self.assertIn("too small", str(ctx.exception))

    def test_bad_magic_is_rejected(self):
        raw = bytearray(build_chunk(b"x")[0])
        raw[0:4] = b"NOPE"
        with self.assertRaises(ValueError) as ctx:
            neo.parse_chunk(bytes(raw))
        self.assertIn("magic", str(ctx.exception))

    def test_payload_starts_at_header_size_not_at_62(self):
        # v3+ headers are longer; trusting a fixed offset would corrupt the payload.
        payload = b"headroom" * 8
        raw, _ = build_chunk(payload, header_size=80)
        data, _ = neo.parse_chunk(raw)
        self.assertEqual(data, payload)
        self.assertEqual(zlib.decompress(raw[80:]), payload)

    def test_header_sha_matches_the_manifests_chunk_sha_list(self):
        manifest = neo.Manifest(support.manifest_dict())
        guid = next(iter(manifest.chunks))
        payload = b"cross-check me"
        _raw, _sha_hex = build_chunk(payload, sha1=bytes.fromhex(manifest.chunks[guid]["sha1"]))
        data, sha = neo.parse_chunk(_raw)
        self.assertEqual((data, sha), (payload, manifest.chunks[guid]["sha1"]))


class TestFetchChunk(unittest.TestCase):
    """The download path, with the CDN stubbed out.

    Retries sleep with backoff, so every test here also stubs ``time.sleep`` —
    otherwise a single failing-chunk assertion would spend ten real seconds
    waiting between attempts.
    """

    GUID = "1832294A440167B074AC75B6A842F82A"

    def setUp(self):
        self.manifest = neo.Manifest(support.manifest_dict())
        self.chunk_sha = self.manifest.chunks[self.GUID]["sha1"]
        self.stats = {"dl": 0, "reuse": 0}
        self._http = neo.http
        sleeper = mock.patch.object(neo.time, "sleep")
        sleeper.start()
        self.addCleanup(sleeper.stop)
        self.addCleanup(self._reset_cache)

    def tearDown(self):
        neo.http = self._http

    def _reset_cache(self):
        for path in pathlib.Path(neo.cache_dir()).glob("chunks/*"):
            path.unlink(missing_ok=True)

    def _chunk_of(self, payload, sha1=None):
        return build_chunk(payload, guid=self.GUID, sha1=bytes.fromhex(sha1 or self.chunk_sha))[0]

    def test_cached_chunk_is_reused_without_touching_the_network(self):
        payload = b"cached payload"
        cache_chunk(self.GUID, self._chunk_of(payload))

        def no_network(*args, **kwargs):
            self.fail("a cache hit must not hit the network")

        neo.http = no_network
        data = neo.fetch_chunk(CDN, self.manifest, self.GUID, self.stats)
        self.assertEqual(data, payload)
        self.assertEqual(self.stats, {"dl": 0, "reuse": 1})

    def test_download_is_verified_then_written_to_the_cache(self):
        payload = b"fresh from the cdn"
        raw = self._chunk_of(payload)
        calls = []

        def fake_http(method, url, **kwargs):
            calls.append(url)
            return 200, raw

        neo.http = fake_http
        self.assertEqual(neo.fetch_chunk(CDN, self.manifest, self.GUID, self.stats), payload)
        self.assertEqual(self.stats["dl"], 1)
        self.assertEqual(
            calls, [CDN + "/Builds/Fortnite/CloudDir/" + self.manifest.chunk_relpath(self.GUID)]
        )
        cached = pathlib.Path(neo.cache_dir(), "chunks", self.GUID).read_bytes()
        self.assertEqual(zlib.decompress(cached[62:]), payload)

    def test_corrupt_cache_entry_falls_back_to_a_redownload(self):
        cache_chunk(self.GUID, b"truncated garbage")
        payload = b"repaired"
        neo.http = lambda *args, **kwargs: (200, self._chunk_of(payload))
        self.assertEqual(neo.fetch_chunk(CDN, self.manifest, self.GUID, self.stats), payload)
        self.assertEqual(self.stats["reuse"], 0)

    def test_sha_mismatch_is_fatal_and_names_the_chunk(self):
        neo.http = lambda *args, **kwargs: (200, self._chunk_of(b"wrong bytes", sha1="11" * 20))
        with self.assertRaises(RuntimeError) as ctx:
            neo.fetch_chunk(CDN, self.manifest, self.GUID, self.stats)
        self.assertIn(self.GUID, str(ctx.exception))
        self.assertIn("sha1 mismatch", str(ctx.exception))

    def test_a_404_on_the_primary_url_falls_back_to_the_v4_layout(self):
        raw = self._chunk_of(b"served from the other layout")

        def fake_http(method, url, **kwargs):
            calls.append(url)
            return (200, raw) if "ChunksV4" in url else (404, b"")

        calls = []
        neo.http = fake_http
        self.assertEqual(
            neo.fetch_chunk(CDN, self.manifest, self.GUID, self.stats), b"served from the other layout"
        )
        self.assertEqual(
            calls[0], CDN + "/Builds/Fortnite/CloudDir/" + self.manifest.chunk_relpath(self.GUID)
        )
        self.assertIn("ChunksV4/18/", calls[-1])

    def test_hard_http_failure_names_the_chunk_and_the_reason(self):
        neo.http = lambda *args, **kwargs: (403, b"forbidden")
        with self.assertRaises(RuntimeError) as ctx:
            neo.fetch_chunk(CDN, self.manifest, self.GUID, self.stats)
        self.assertIn(self.GUID, str(ctx.exception))
        self.assertIn("HTTP 403", str(ctx.exception))


class TestProgress(unittest.TestCase):
    def test_counts_accumulate_and_the_thread_stops(self):
        import contextlib
        import io

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer), neo.Progress(10, "test") as progress:
            progress.add(4)
            progress.add(3)
        self.assertEqual(progress.done, 7)
        self.assertFalse(progress.thread.is_alive())
        self.assertIn("test", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
