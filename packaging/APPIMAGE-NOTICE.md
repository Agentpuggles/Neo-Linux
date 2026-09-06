# Neo AppImage — third-party notices

Neo's source is MIT-licensed; see `LICENSE.Neo`. No Fortnite or NeoFN game files,
account credentials, Proton builds, umu runtime, graphics drivers or game patches
are included in this launcher package.

The AppImage additionally contains these independently licensed components:

- **CPython**, under the Python Software Foundation license and its included
  notices. See `licenses/LICENSE.Python`; source is available from
  <https://www.python.org/downloads/source/>. `build-info.json` records its version.
- **Qt 6.11.2 / PySide6 6.11.2 / shiboken6 6.11.2**, using the open-source
  LGPLv3 terms where offered. The Qt LGPL, GPL and other upstream license texts
  are in `licenses/Qt`. Qt Widgets, Core, Gui, Network, SVG and their platform
  dependencies are used; the application does not use Qt WebEngine or Qt Quick.
  Corresponding source is available from the Qt 6.11.2 and Qt for Python 6.11.2
  release directories at <https://download.qt.io/official_releases/qt/6.11/6.11.2/>
  and <https://download.qt.io/official_releases/QtForPython/pyside6/>.
  The source of the license texts is <https://github.com/qt/qtbase/tree/v6.11.2/LICENSES>.
- **PyInstaller's bootloader**, with its GPL exception allowing bundled
  applications to retain their own licenses. Its notices are under
  `licenses/PyInstaller`; source: <https://github.com/pyinstaller/pyinstaller>.
- **AppImage type-2 runtime (20251108)** and its FUSE dependencies, under their
  upstream MIT/LGPL terms; see `licenses/LICENSE.AppImage-runtime` and
  `licenses/Qt/LGPL-2.1-or-later.txt`. Source and notices:
  <https://github.com/AppImage/type2-runtime/tree/20251108>.
- System libraries collected from the build distribution retain their original
  licenses and copyright notices. Copies are in
  `usr/bin/_internal/licenses/system/` inside the extracted image.

Qt libraries remain dynamically linked, not statically embedded into Neo.
`./Neo.AppImage --appimage-extract` exposes the payload in `squashfs-root/`;
compatible modified libraries may be substituted under
`usr/bin/_internal/PySide6/Qt/lib/`, then launched using `squashfs-root/AppRun`.
Neo imposes no restriction on reverse engineering necessary to debug such
modifications. The optional CLI is the MIT-licensed, standard-library-only `neo`
source, not a copy of Qt or the frozen interpreter.

Maintainers should preserve these notices, provide access to the corresponding
source for the exact versions being distributed, and review dependency-license
changes before publishing. Build information and reviewed tool hashes are
included in `build-info.json` alongside this file.
