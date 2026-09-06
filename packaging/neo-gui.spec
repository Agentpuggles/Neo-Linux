# Run via packaging/build-appimage.sh (isolated, pinned build environment).
# SPECPATH is supplied by PyInstaller; do not depend on the caller's cwd.
import pathlib
import sys

ROOT = pathlib.Path(SPECPATH).resolve().parent
sys.path.insert(0, str(ROOT / "packaging"))
from appimage import backend_imports, system_licenses

a = Analysis(
    [str(ROOT / "gui" / "neo-gui")],
    pathex=[str(ROOT / "gui")],
    # Keep the source as private data: the GUI can copy it to ~/.local/bin/neo
    # on explicit consent. Never expose an unconditional CLI in usr/bin.
    datas=[(str(ROOT / "neo"), ".")],
    # Analysis cannot see imports in an extensionless file loaded at runtime.
    hiddenimports=["neogui.app", *backend_imports()],
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
              "PySide6.QtQuick", "PySide6.QtQml", "PySide6.Qt3DCore"],
    noarchive=False,
)
a.datas += system_licenses(a.binaries)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="neo-gui",
          console=True, strip=False, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="neo-gui")
