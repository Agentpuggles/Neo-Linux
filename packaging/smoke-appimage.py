"""Exercise the actual release file, offline, without FUSE or real user data."""

from __future__ import annotations

import argparse
import configparser
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def run(image: Path) -> None:
    # Spaces/percent signs catch desktop Exec quoting and temporary-mount bugs.
    with tempfile.TemporaryDirectory(prefix="neo-appimage-check-") as temporary:
        root = Path(temporary)
        moved = root / "Neo release 100%.AppImage"
        shutil.copy2(image, moved)
        moved.chmod(0o755)
        env = dict(os.environ)
        for key in (
            "NEO_BIN",
            "NEO_GUI_ROOT",
            "NEO_GUI_EXEC",
            "APPIMAGE",
            "APPDIR",
            "LD_LIBRARY_PATH",
            "LD_LIBRARY_PATH_ORIG",
            "PYTHONPATH",
            "PYTHONHOME",
        ):
            env.pop(key, None)
        for key, folder in (
            ("HOME", "home"),
            ("XDG_CONFIG_HOME", "config"),
            ("XDG_DATA_HOME", "data"),
            ("XDG_CACHE_HOME", "cache"),
            ("XDG_RUNTIME_DIR", "runtime"),
            ("NEO_HOME", "neo-data"),
            ("NEO_CACHE", "neo-cache"),
        ):
            path = root / folder
            path.mkdir(mode=0o700)
            env[key] = str(path)
        env.update({"QT_QPA_PLATFORM": "offscreen", "APPIMAGE_EXTRACT_AND_RUN": "1"})

        def invoke(*args: str) -> str:
            process = subprocess.run(
                [str(moved), *args],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                timeout=120,
            )
            print(process.stdout, end="")
            if process.returncode:
                raise RuntimeError(f"AppImage {' '.join(args)} failed:\n{process.stderr}")
            return process.stdout

        if "neo-gui" not in invoke("--version"):
            raise RuntimeError("The AppImage did not start the desktop entry point")
        if "--self-check" not in invoke("--help"):
            raise RuntimeError("Desktop arguments were not forwarded through AppRun")
        if "self-check: ok" not in invoke("--self-check"):
            raise RuntimeError("The actual bundled window did not pass its self-check")
        if (root / "home/.local/bin/neo").exists():
            raise RuntimeError("A CLI was installed without consent during smoke testing")
        invoke("--install-desktop-entry")
        entry = root / "data/applications/dev.neofn.NeoLauncher.desktop"
        parser = configparser.ConfigParser(interpolation=None)
        parser.read(entry)
        command = parser["Desktop Entry"]["Exec"]
        if (
            str(moved).replace("%", "%%") not in command
            or ".mount_" in command
            or "appimage_extracted" in command
        ):
            raise RuntimeError(f"Desktop callback does not point at the durable AppImage: {command}")
        if parser["Desktop Entry"]["TryExec"] != str(moved):
            raise RuntimeError("TryExec lost the AppImage's path or quoting")
        if not command.endswith(" %u"):
            raise RuntimeError("The desktop entry cannot forward Discord callback URLs")
        if shutil.which("desktop-file-validate"):
            subprocess.run(["desktop-file-validate", str(entry)], check=True, env=env)
    print("AppImage smoke: ok (bundled UI, offline, relocatable entry, CLI stays optional)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    run(parser.parse_args().image.resolve())
