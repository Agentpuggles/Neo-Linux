# PyInstaller spec used to produce the AppImage payload.
#   pyinstaller packaging/neo-gui.spec
# The result is a self-contained directory; packaging/build-appimage.sh wraps it.
import pathlib

ROOT = pathlib.Path.cwd()

a = Analysis(
    [str(ROOT / "gui" / "neo-gui")],
    pathex=[str(ROOT / "gui")],
    datas=[(str(ROOT / "neo"), ".")],
    hiddenimports=["neogui.app"],
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtQuick", "PySide6.Qt3DCore"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="neo-gui",
          console=False, strip=False, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="neo-gui")
