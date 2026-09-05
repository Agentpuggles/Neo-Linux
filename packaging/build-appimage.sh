#!/usr/bin/env sh
# Build a portable AppImage of the Neo desktop app.
#
# Needs: python3, pip, and appimagetool on PATH. Run from the repo root.
# The AppImage bundles PySide6 and the `neo` CLI, so it runs on any glibc-based
# distro without installing anything.
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
BUILD="$ROOT/build/appimage"
APPDIR="$BUILD/Neo.AppDir"

command -v appimagetool >/dev/null 2>&1 || {
    echo "appimagetool not found — see https://github.com/AppImage/AppImageKit" >&2
    exit 1
}

rm -rf "$BUILD"
mkdir -p "$APPDIR/usr/bin"

python3 -m pip install --quiet --upgrade pyinstaller PySide6
( cd "$ROOT" && python3 -m PyInstaller --noconfirm --distpath "$BUILD/dist" \
    --workpath "$BUILD/work" packaging/neo-gui.spec )

cp -a "$BUILD/dist/neo-gui/." "$APPDIR/usr/bin/"
install -Dm755 "$ROOT/neo" "$APPDIR/usr/bin/neo"
install -Dm644 "$ROOT/packaging/dev.neofn.NeoLauncher.svg" \
    "$APPDIR/usr/share/icons/hicolor/scalable/apps/dev.neofn.NeoLauncher.svg"
install -Dm644 "$ROOT/packaging/dev.neofn.NeoLauncher.metainfo.xml" \
    "$APPDIR/usr/share/metainfo/dev.neofn.NeoLauncher.metainfo.xml"
install -Dm755 "$ROOT/packaging/dev.neofn.NeoLauncher.desktop" \
    "$APPDIR/dev.neofn.NeoLauncher.desktop"
cp "$ROOT/packaging/dev.neofn.NeoLauncher.svg" "$APPDIR/dev.neofn.NeoLauncher.svg"

cat > "$APPDIR/AppRun" <<'RUN'
#!/usr/bin/env sh
HERE=$(dirname "$(readlink -f "$0")")
export PATH="$HERE/usr/bin:$PATH"
export NEO_BIN="${NEO_BIN:-$HERE/usr/bin/neo}"
exec "$HERE/usr/bin/neo-gui" "$@"
RUN
chmod +x "$APPDIR/AppRun"

ARCH=$(uname -m) appimagetool "$APPDIR" "$ROOT/build/Neo-$(uname -m).AppImage"
echo "built: build/Neo-$(uname -m).AppImage"
