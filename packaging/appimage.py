"""Small, testable AppImage build helpers. Never import/execute `neo` to version it."""

from __future__ import annotations

import argparse
import ast
import base64
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import sysconfig
from datetime import datetime, timezone
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build" / "appimage"
APP_ID = "dev.neofn.NeoLauncher"
QT_VERSION = "6.11.2"


def version(source: Path = ROOT / "neo") -> str:
    for node in ast.parse(source.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "VERSION" for target in node.targets
        ):
            value = ast.literal_eval(node.value)
            if isinstance(value, str) and re.fullmatch(
                r"[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?", value
            ):
                return value
    raise ValueError("neo must declare a literal, filename-safe VERSION")


def backend_imports(source: Path = ROOT / "neo") -> list[str]:
    """The dynamically loaded, extensionless backend is invisible to Analysis."""
    modules = set()
    for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            modules.add(node.module)
    modules.discard("__future__")
    return sorted(modules)


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def verify(path: Path, expected: str) -> None:
    if digest(path) != expected:
        raise ValueError(f"SHA-256 mismatch for {path.name}; refusing to use it. Review the tool pins.")


def fetch_tools() -> None:
    tools = BUILD / "tools"
    tools.mkdir(parents=True, exist_ok=True)
    pins = json.loads((ROOT / "packaging/appimage-tools.json").read_text())
    for pin in pins.values():
        target = tools / pin["asset"]
        if not target.is_file() or digest(target) != pin["sha256"]:
            temporary = target.with_suffix(target.suffix + ".download")
            try:
                subprocess.run(
                    [
                        "gh",
                        "release",
                        "download",
                        pin["tag"],
                        "--repo",
                        pin["repository"],
                        "--pattern",
                        pin["asset"],
                        "--output",
                        str(temporary),
                        "--clobber",
                    ],
                    check=True,
                )
                verify(temporary, pin["sha256"])
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
        verify(target, pin["sha256"])
        target.chmod(0o755)


def qt_licenses(destination: Path) -> None:
    """Ship the upstream license texts, not just a link to LGPL/GPL terms."""
    destination.mkdir(parents=True, exist_ok=True)
    raw = subprocess.check_output(
        [
            "gh",
            "api",
            f"repos/qt/qtbase/contents/LICENSES?ref=v{QT_VERSION}",
        ],
        text=True,
    )
    for entry in json.loads(raw):
        if entry["type"] != "file" or not re.fullmatch(r"[A-Za-z0-9.+_-]+\.txt", entry["name"]):
            raise ValueError("Unexpected entry in Qt's LICENSES directory")
        path = destination / entry["name"]
        if path.is_file():
            content = path.read_bytes()
            header = f"blob {len(content)}\0".encode()
            if hashlib.sha1(header + content).hexdigest() == entry["sha"]:
                continue
        blob = json.loads(
            subprocess.check_output(
                [
                    "gh",
                    "api",
                    f"repos/qt/qtbase/git/blobs/{entry['sha']}",
                ],
                text=True,
            )
        )
        content = base64.b64decode(blob["content"])
        header = f"blob {len(content)}\0".encode()
        if hashlib.sha1(header + content).hexdigest() != entry["sha"]:
            raise ValueError("Qt license blob did not match its Git object ID")
        path.write_bytes(content)


def bundle_licenses(appdir: Path) -> None:
    destination = appdir / "usr/share/doc/neo"
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "LICENSE", destination / "LICENSE.Neo")
    shutil.copy2(ROOT / "packaging/APPIMAGE-NOTICE.md", destination / "THIRD-PARTY-NOTICES.md")
    qt_licenses(destination / "licenses/Qt")
    runtime_license = json.loads(
        subprocess.check_output(
            [
                "gh",
                "api",
                "repos/AppImage/type2-runtime/contents/LICENSE?ref=20251108",
            ],
            text=True,
        )
    )
    (destination / "licenses/LICENSE.AppImage-runtime").write_bytes(
        base64.b64decode(runtime_license["content"])
    )
    python_license = Path(sysconfig.get_path("stdlib")) / "LICENSE.txt"
    if not python_license.is_file():
        python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if not python_license.is_file():
        raise FileNotFoundError("Python license missing from the build interpreter")
    shutil.copy2(python_license, destination / "licenses/LICENSE.Python")
    # Wheels place their notices in .dist-info (or package directories).
    for package in ("PyInstaller", "PySide6", "PySide6_Essentials", "PySide6_Addons", "shiboken6"):
        dist = importlib.metadata.distribution(package)
        for file in dist.files or []:
            if any(word in file.name.lower() for word in ("license", "copying", "copyright", "notice")):
                source = Path(dist.locate_file(file))
                if ".." not in file.parts and source.is_file() and not source.is_symlink():
                    target = destination / "licenses" / package / str(file)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)


def system_licenses(binaries: list) -> list[tuple]:
    """Collect copyright notices for distro libraries PyInstaller bundles."""
    if not shutil.which("dpkg-query"):
        raise RuntimeError("Build on the documented Debian/Ubuntu baseline to collect system licenses")
    packages = set()
    for _name, source, _kind in binaries:
        if not source.startswith(("/lib/", "/usr/lib/")):
            continue
        for path in (source, str(Path(source).resolve()), source.replace("/usr/lib/", "/lib/", 1)):
            result = subprocess.run(["dpkg-query", "-S", path], capture_output=True, text=True, check=False)
            if result.returncode == 0:
                packages.update(line.split(": ")[0].split(":")[0] for line in result.stdout.splitlines())
                break
    entries = []
    for package in sorted(packages):
        path = Path("/usr/share/doc") / package / "copyright"
        if path.is_file():
            entries.append((f"licenses/system/{package}.copyright", str(path.resolve()), "DATA"))
    return entries


def prepare(appdir: Path) -> None:
    appdir.mkdir(parents=True, exist_ok=True)
    for source, target in (
        ("AppRun", "AppRun"),
        (f"{APP_ID}.desktop", f"{APP_ID}.desktop"),
        (f"{APP_ID}.desktop", f"usr/share/applications/{APP_ID}.desktop"),
        (f"{APP_ID}.svg", f"{APP_ID}.svg"),
        (f"{APP_ID}.svg", ".DirIcon"),
        (f"{APP_ID}.svg", f"usr/share/icons/hicolor/scalable/apps/{APP_ID}.svg"),
    ):
        dest = appdir / target
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "packaging" / source, dest)
    (appdir / "AppRun").chmod(0o755)
    meta = ET.parse(ROOT / f"packaging/{APP_ID}.metainfo.xml")
    releases = meta.getroot().find("releases")
    releases.clear()
    epoch = int(os.environ["SOURCE_DATE_EPOCH"])
    release = ET.SubElement(
        releases,
        "release",
        {
            "version": version(),
            "date": datetime.fromtimestamp(epoch, timezone.utc).date().isoformat(),
        },
    )
    ET.SubElement(ET.SubElement(release, "description"), "p").text = "Neo desktop AppImage."
    target = appdir / f"usr/share/metainfo/{APP_ID}.metainfo.xml"
    target.parent.mkdir(parents=True, exist_ok=True)
    meta.write(target, encoding="utf-8", xml_declaration=True)
    info = {
        "version": version(),
        "architecture": "x86_64",
        "python": sys.version.split()[0],
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True)),
        "source_date_epoch": epoch,
        "dependencies": {
            p: importlib.metadata.version(p)
            for p in (
                "PyInstaller",
                "pyinstaller-hooks-contrib",
                "PySide6",
                "shiboken6",
            )
        },
        "tools": json.loads((ROOT / "packaging/appimage-tools.json").read_text()),
    }
    doc = appdir / "usr/share/doc/neo"
    doc.mkdir(parents=True, exist_ok=True)
    (doc / "build-info.json").write_text(json.dumps(info, indent=2) + "\n")
    bundle_licenses(appdir)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("version", "tools", "prepare"))
    args = parser.parse_args()
    if args.action == "version":
        print(version())
    elif args.action == "tools":
        fetch_tools()
    else:
        prepare(BUILD / "Neo.AppDir")


if __name__ == "__main__":
    main()
