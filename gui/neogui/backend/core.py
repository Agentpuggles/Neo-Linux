"""Locate and import the `neo` launcher as a module.

`neo` is a single executable file with no `.py` suffix, so a plain import will
not find it. This mirrors the loader the test-suite uses (tests/support.py) and
is the *only* place the GUI loads the shared implementation. Installed GUIs
prefer their private backend; the optional public CLI is not a GUI dependency.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import shutil
import sys
from pathlib import Path


class LauncherNotFound(RuntimeError):
    """The `neo` launcher file could not be located on this system."""


_module = None


def candidate_paths() -> list[Path]:
    """Every place `neo` might live, best first."""
    here = Path(__file__).resolve()
    out: list[Path] = []

    env = os.environ.get("NEO_BIN")
    if env:
        out.append(Path(env).expanduser())

    if getattr(sys, "frozen", False) and getattr(sys, "_MEIPASS", None):
        out.append(Path(sys._MEIPASS) / "neo")

    # Private installed backend (or PyInstaller data), not the optional CLI.
    out.append(here.parents[2] / "neo")
    # gui/neogui/backend/core.py -> repo root
    out.append(here.parents[3] / "neo")
    # Installed package: <prefix>/share/neo/neogui/backend/core.py.
    # Resolve the matching CLI even when <prefix>/bin is absent from PATH.
    out.append(here.parents[4] / "bin" / "neo")

    found = shutil.which("neo")
    if found:
        out.append(Path(found))

    for extra in (
        Path("~/.local/bin/neo"),
        Path("~/.local/share/neo-gui/neo"),
        Path("/usr/lib/neo/neo"),
        Path("/usr/share/neo/neo"),
        Path("/usr/local/bin/neo"),
        Path("/usr/bin/neo"),
        Path("/app/bin/neo"),  # flatpak
    ):
        out.append(extra.expanduser())

    seen: set[Path] = set()
    unique = []
    for p in out:
        try:
            rp = p.resolve()
        except OSError:
            continue
        if rp not in seen:
            seen.add(rp)
            unique.append(p)
    return unique


def launcher_path() -> Path:
    for path in candidate_paths():
        try:
            if path.is_file() and os.access(path, os.R_OK):
                return path
        except OSError:
            continue
    raise LauncherNotFound(
        "could not find Neo's shared backend. Reinstall the desktop app (`make install`) or point "
        "NEO_BIN at the file."
    )


def neo_module():
    """Import `neo` once and cache it."""
    global _module
    if _module is not None:
        return _module

    path = launcher_path()
    name = "neo_launcher"
    if name in sys.modules:
        _module = sys.modules[name]
        return _module

    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    if spec is None:  # pragma: no cover - defensive
        raise LauncherNotFound(f"{path} is not importable as Python source")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        loader.exec_module(module)
    except Exception:
        sys.modules.pop(name, None)
        raise
    _module = module
    return module
