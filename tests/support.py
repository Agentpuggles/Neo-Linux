"""Shared scaffolding for the test suite.

Two things the tests need that a normal ``import`` does not give them:

1. ``neo`` is a single executable file with no ``.py`` suffix, so it has to be
   loaded through an explicit source loader.
2. Every path the launcher touches is resolved from ``NEO_HOME`` / ``NEO_CACHE`` /
   ``XDG_CONFIG_HOME`` *at call time*, so pointing those three at a scratch
   directory keeps the suite from reading or writing a real ``~/.local/share/neo``
   — and keeps it entirely offline.

The fixtures here (``blob``, ``build_chunk``, ``manifest_dict``) reproduce the
on-the-wire formats exactly as documented in ``docs/protocol.md`` §5–§6, so a test
that passes here is evidence the implementation still agrees with the docs.
"""

import atexit
import contextlib
import hashlib
import importlib.machinery
import importlib.util
import os
import pathlib
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

SANDBOX = pathlib.Path(tempfile.mkdtemp(prefix="neo-tests-"))
os.environ["NEO_HOME"] = str(SANDBOX / "share")
os.environ["NEO_CACHE"] = str(SANDBOX / "cache")
os.environ["XDG_CONFIG_HOME"] = str(SANDBOX / "config")
atexit.register(shutil.rmtree, SANDBOX, ignore_errors=True)


def _import_launcher():
    """Load ``<repo>/neo`` as the module ``neo``."""
    path = REPO_ROOT / "neo"
    loader = importlib.machinery.SourceFileLoader("neo", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    loader.exec_module(module)
    return module


neo = _import_launcher()


# ------------------------------------------------------------------ env helpers
@contextlib.contextmanager
def environment(**values):
    """Set environment variables for the duration of a block (None deletes)."""
    saved = {}
    for key, value in values.items():
        saved[key] = os.environ.get(key)
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def scratch_home():
    """Point NEO_HOME / NEO_CACHE / XDG_CONFIG_HOME at a fresh directory.

    Used by the GUI backend tests, which need a clean state.json and config per
    test rather than the module-wide sandbox. The directory is inside SANDBOX,
    so it is cleaned up with everything else at exit.
    """
    root = pathlib.Path(tempfile.mkdtemp(prefix="neo-case-", dir=str(SANDBOX)))
    os.environ["NEO_HOME"] = str(root / "share")
    os.environ["NEO_CACHE"] = str(root / "cache")
    os.environ["XDG_CONFIG_HOME"] = str(root / "config")
    for sub in ("share", "cache", "config"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return str(root)


@contextlib.contextmanager
def temp_dir():
    """A scratch directory, removed afterwards."""
    path = pathlib.Path(tempfile.mkdtemp(prefix="neo-test-", dir=str(SANDBOX)))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def run_cli(*args, expect_rc=0, env=None):
    """Run the launcher as a real program (what a user's shell does)."""
    run_env = dict(os.environ)
    run_env.update(env or {})
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "neo"), *args],
        cwd=str(REPO_ROOT),
        env=run_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=60,
    )
    if proc.returncode != expect_rc:
        raise AssertionError(
            f"neo {' '.join(args)}: expected exit {expect_rc}, got {proc.returncode}\n"
            f"--- output ---\n{proc.stdout}"
        )
    return proc.stdout


# ------------------------------------------------------------- protocol fixtures
def blob(data):
    """``bytes`` -> Epic's fixed-width decimal encoding: three digits per byte."""
    return "".join(f"{byte:03d}" for byte in data)


def num_le(value, nbytes):
    """A little-endian integer, as the blob string a manifest would store it in."""
    return blob(int(value).to_bytes(nbytes, "little"))


def build_chunk(
    payload=b"", *, sha1=None, rolling_hash=0, guid=None, stored=True, header_version=2, header_size=62
):
    """Synthesise a chunk file with a v2 header. Returns ``(raw_bytes, sha1_hex)``.

    ``stored`` mirrors the real ``storedAs & 1`` flag: payload zlib-compressed.
    """
    digest = hashlib.sha1(payload).digest() if sha1 is None else sha1
    body = zlib.compress(payload) if stored else payload
    header = struct.pack("<IIII", neo.CHUNK_MAGIC, header_version, header_size, len(body))
    header += bytes.fromhex(guid or "0" * 32)
    header += int(rolling_hash).to_bytes(8, "little")
    header += bytes([1 if stored else 0]) + digest + b"\x01"  # storedAs, sha1, hashType
    if header_size > len(header):
        header += b"\x00" * (header_size - len(header))  # v3+ headers are longer
    return header + body, digest.hex()


def cache_chunk(guid, raw):
    """Drop a raw chunk into the bulk cache, as a resumed install would find it."""
    path = pathlib.Path(neo.cache_dir()) / "chunks" / guid
    path.write_bytes(raw)
    return path


def manifest_dict(**overrides):
    """A minimal but format-accurate manifest (one file, one chunk)."""
    payload = b"neo test payload"
    raw, sha_hex = build_chunk(
        payload, rolling_hash=0x487A33F0F2E5F569, guid="1832294A440167B074AC75B6A842F82A"
    )
    guid = "1832294A440167B074AC75B6A842F82A"
    base = {
        "ManifestFileVersion": "013000000000",  # feature level 13 -> ChunksV3
        "BuildVersionString": "++Fortnite+Release-10.40-CL-9380822-Windows",
        "ChunkHashList": {guid: num_le(0x487A33F0F2E5F569, 8)},
        "ChunkShaList": {guid: blob(bytes.fromhex(sha_hex))},
        "DataGroupList": {guid: 31},
        "ChunkFilesizeList": {guid: len(raw)},
        "FileManifestList": [
            {
                "Filename": "FortniteGame/Binaries/Win64/FortniteClient-Win64-Shipping.exe",
                "FileHash": blob(bytes.fromhex(sha_hex)),
                "FileChunkParts": [{"Guid": guid, "Offset": 0, "Size": len(payload)}],
                "bIsUnixExecutable": True,
                "SymlinkTarget": None,
            }
        ],
    }
    base.update(overrides)
    return base
