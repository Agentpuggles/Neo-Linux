"""Qt-free boundary between a frozen launcher and the host desktop.

PyInstaller adjusts library/plugin search paths for its own interpreter. Never
pass those adjustments to umu, Proton, the browser or desktop utilities.
"""

from __future__ import annotations

import os
import shlex
import shutil
import sys
from pathlib import Path


def host_environment(environ: dict | None = None) -> dict:
    """Return a copy suitable for host programs, preserving game/user overrides."""
    env = dict(os.environ if environ is None else environ)
    if not getattr(sys, "frozen", False):
        return env

    original = env.pop("LD_LIBRARY_PATH_ORIG", None)
    if original:
        env["LD_LIBRARY_PATH"] = original
    else:
        env.pop("LD_LIBRARY_PATH", None)

    roots = [str(getattr(sys, "_MEIPASS", "")), env.get("APPDIR", "")]
    roots = [os.path.abspath(root) for root in roots if root]

    def bundled(path: str) -> bool:
        path = os.path.abspath(path)
        return any(path == root or path.startswith(root + os.sep) for root in roots)

    for key in ("QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "QML2_IMPORT_PATH", "QML_IMPORT_PATH"):
        if key in env:
            paths = [p for p in env[key].split(os.pathsep) if p and not bundled(p)]
            if paths:
                env[key] = os.pathsep.join(paths)
            else:
                env.pop(key)
    if env.get("NEO_BIN") and bundled(env["NEO_BIN"]):
        env.pop("NEO_BIN")
    for key in list(env):
        if key.startswith("_PYI_") or key in ("_MEIPASS2", "APPIMAGE", "APPDIR", "ARGV0", "OWD"):
            env.pop(key)
    return env


def launch_argv() -> list[str]:
    """A durable desktop command, not an AppImage's temporary mount path."""
    override = os.environ.get("NEO_GUI_EXEC")
    if override:
        return shlex.split(override)
    if getattr(sys, "frozen", False):
        image = os.environ.get("APPIMAGE")
        return [str(Path(image).absolute())] if image else [sys.executable]

    main = Path(sys.argv[0]).resolve()
    if main.name in ("neo-gui", "neo-gui.py") and main.is_file():
        return [sys.executable, str(main)]
    package_root = Path(__file__).resolve().parents[1]
    script = package_root / "neo-gui"
    if script.is_file():
        return [sys.executable, str(script)]
    found = shutil.which("neo-gui")
    if found:
        return [found]
    return ["env", f"PYTHONPATH={package_root}", sys.executable, "-m", "neogui"]


def desktop_value(value: str) -> str:
    """Escape a freedesktop string value (not shell syntax)."""
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")


def desktop_argument(value: str) -> str:
    """Quote an Exec argument, including literal percent signs and backslashes."""
    value = value.replace("%", "%%")
    value = "".join("\\" + char if char in '\\"`$' else char for char in value)
    return desktop_value('"' + value + '"')
