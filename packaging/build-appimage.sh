#!/usr/bin/env bash
# Release build: Ubuntu 22.04 x86-64 + CPython 3.11. See docs/appimage.md.
# Nothing is installed into the user's Python, shell profile or application menu.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
BUILD="$ROOT/build/appimage"
APPDIR="$BUILD/Neo.AppDir"
PYTHON=${PYTHON:-python3}

if [[ ${1:-} == --help ]]; then
    echo "Usage: packaging/build-appimage.sh"
    echo "Builds build/Neo-v<VERSION>-x86_64.AppImage, its SHA-256 checksum and build-info.json."
    echo "Requires Linux x86-64, Python 3.11 + venv, gh, and the Qt host libraries in docs/appimage.md."
    exit 0
fi
[[ $# == 0 ]] || { echo "Unexpected arguments; use --help" >&2; exit 2; }
[[ $(uname -s) == Linux && $(uname -m) == x86_64 ]] || {
    echo "The first AppImage release targets Linux x86-64; cross-compilation is not supported." >&2
    exit 1
}
"$PYTHON" -c 'import sys; assert sys.version_info[:2] == (3, 11), "Build with CPython 3.11"'
for tool in gh git sha256sum desktop-file-validate; do
    command -v "$tool" >/dev/null || { echo "Missing $tool; see docs/appimage.md" >&2; exit 1; }
done

# Keep only the pinned dependency/tool cache. Always regenerate the payload.
mkdir -p "$BUILD"
if [[ ! -x "$BUILD/venv/bin/python" ]]; then
    "$PYTHON" -m venv "$BUILD/venv"
fi
PY="$BUILD/venv/bin/python"
"$PY" -m pip install --disable-pip-version-check --only-binary=:all: --require-hashes \
    -r "$ROOT/packaging/appimage-requirements.txt"
"$PY" -c 'from PySide6.QtWidgets import QApplication; from PySide6.QtSvg import QSvgRenderer'
"$PY" "$ROOT/packaging/appimage.py" tools

export SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH:-$(git -C "$ROOT" log -1 --format=%ct)}
export PYTHONHASHSEED=0
VERSION=$("$PY" "$ROOT/packaging/appimage.py" version)
OUTPUT="$ROOT/build/Neo-v$VERSION-x86_64.AppImage"
# No stale, apparently successful output after a failed rebuild.
rm -f "$OUTPUT" "$OUTPUT.sha256" "$OUTPUT.build-info.json"
trap 'rm -f "$OUTPUT" "$OUTPUT.sha256" "$OUTPUT.build-info.json"' ERR
rm -rf "$APPDIR" "$BUILD/dist" "$BUILD/work"
mkdir -p "$APPDIR/usr/bin"
"$PY" -m PyInstaller --clean --noconfirm --distpath "$BUILD/dist" \
    --workpath "$BUILD/work" "$ROOT/packaging/neo-gui.spec"
cp -a "$BUILD/dist/neo-gui/." "$APPDIR/usr/bin/"
"$PY" "$ROOT/packaging/appimage.py" prepare
# The backend must remain private, readable, and present in the frozen payload.
test -f "$APPDIR/usr/bin/_internal/neo"
chmod 0644 "$APPDIR/usr/bin/_internal/neo"
test ! -e "$APPDIR/usr/bin/neo"
desktop-file-validate "$APPDIR/dev.neofn.NeoLauncher.desktop"

# Force a reviewed runtime: appimagetool must not silently download 'continuous'.
# Extract-and-run works on CI without a FUSE device or administrator privileges.
export ARCH=x86_64
APPIMAGE_EXTRACT_AND_RUN=1 "$BUILD/tools/appimagetool-x86_64.AppImage" \
    --no-appstream --runtime-file "$BUILD/tools/runtime-x86_64" \
    --mksquashfs-opt -processors --mksquashfs-opt 2 \
    "$APPDIR" "$OUTPUT"
chmod 0755 "$OUTPUT"
if ! "$PY" "$ROOT/packaging/smoke-appimage.py" "$OUTPUT"; then
    rm -f "$OUTPUT"
    exit 1
fi
cp "$APPDIR/usr/share/doc/neo/build-info.json" "$OUTPUT.build-info.json"
(cd "$ROOT/build" && sha256sum "$(basename "$OUTPUT")" > "$(basename "$OUTPUT").sha256")
trap - ERR
printf '\nBuilt and smoke-tested: %s\n' "$OUTPUT"
echo "No release has been published. Review docs/appimage.md before publishing."
