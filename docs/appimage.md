# AppImage builds and releases

The AppImage is a portable **GUI-first** launcher: it includes Python, PySide6,
the UI and its private backend. It does **not** include game downloads,
umu-launcher, Proton, drivers or user credentials. The public CLI remains an
optional first-run/Settings installation.

## Download and run

When a [release](https://github.com/Agentpuggles/Neo-Linux/releases) includes an
AppImage, download `Neo-v<version>-x86_64.AppImage` and its `.sha256` file. During
release preparation, successful **AppImage** workflow runs provide the same files
in the `neo-appimage-x86_64` artifact; these are test builds, not published releases.

1. Verify the download in its folder: `sha256sum -c Neo-v*.AppImage.sha256`.
2. Move the image somewhere permanent, such as `~/Applications`. You can give it
   a stable name like `Neo.AppImage` **after** verifying the original filename.
3. Mark it executable in your file manager's **Properties → Permissions**, then
   double-click it. Alternatively: `chmod +x Neo.AppImage && ./Neo.AppImage`.
4. Install [umu-launcher](https://github.com/Open-Wine-Components/umu-launcher#installation)
   separately to run Fortnite. The GUI checks whether `umu-run` is available.

The release target is **Linux x86-64 with glibc 2.35+**, using Ubuntu 22.04 as the
build baseline. You still need a working Wayland/X11 desktop and graphics drivers.
Alpine/musl and ARM are not supported by this build. The optional standalone CLI
requires host Python 3.9+; the bundled GUI does not require host Python or Qt.

If mounting fails (for example, FUSE is unavailable):

```sh
./Neo.AppImage --appimage-extract-and-run
```

As a last resort, `./Neo.AppImage --appimage-extract` creates `squashfs-root/`;
run `squashfs-root/AppRun` and keep that entire folder together. Do not run as root.

**Desktop integration and sign-in:** Settings can install the app-menu entry and
register `neolauncher://`. Opening the Discord sign-in browser also registers the
GUI callback. These entries point at the original AppImage, not its temporary
mount. Re-register after moving it. Pasting the callback URL remains a fallback.

**Updating/removing:** close Neo before replacing/deleting its AppImage. Accounts,
settings and game downloads live outside it, so they are retained. A CLI previously
copied into `~/.local/bin/neo` is retained too; it is not silently overwritten or
auto-updated. See [desktop setup](desktop-setup.md#optional-command-line-tool).

## Build locally

Use **Ubuntu 22.04 x86-64 and CPython 3.11** for release builds. A newer build host
can raise the required glibc version: merely wrapping binaries in an AppImage does
not make them compatible with older Linux systems. Other local hosts are for
experimentation, not equivalent release artifacts.

Install Git, Make, Python 3.11 with venv support, and the GitHub CLI (`gh`). Native
build dependencies on Ubuntu 22.04 are:

```sh
sudo apt-get install binutils desktop-file-utils file patchelf \
  libgl1 libegl1 libdbus-1-3 libglib2.0-0 libfontconfig1 libfreetype6 \
  libxkbcommon0 libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 \
  libxcb-image0 libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 \
  libxcb-shape0 libxcb-xinerama0 libxcb-xfixes0 libxcb-sync1 \
  libsm6 libice6 fonts-dejavu-core
```

Then, from the checkout:

```sh
make appimage PYTHON=python3.11
```

The builder creates its own `build/appimage/venv`. It **never uses sudo, installs
into system Python, edits shell profiles, or installs the application for you**.
GitHub Actions provides `gh` authentication automatically; local builders can use
an existing `gh` login. Do not put credentials in scripts or version control.

Build inputs are deliberately reviewed and version/hash-pinned:

- `packaging/appimage-requirements.txt`: Python build dependencies and wheel hashes.
- `packaging/appimage-tools.json`: appimagetool **1.9.1** and type-2 runtime
  **20251108**, with SHA-256 verification **before use**. No floating `continuous`
  runtime download. Cached tools are verified on every build.
- `packaging/neo-gui.spec`: GUI modules plus all imports from the dynamically
  loaded backend; the backend remains private data for optional CLI installation.
- `packaging/AppRun`: argument forwarding without putting bundled executables on
  the host's PATH. Host processes get their original library search paths back.

The build uses the Git commit timestamp for `SOURCE_DATE_EPOCH`, records dependency
versions and the source commit, and runs the **actual AppImage** with an isolated
HOME/XDG environment. The smoke check needs no FUSE and exercises every GUI page,
the optional CLI dialog, themes, command-line forwarding and desktop-entry
registration after relocation. Self-checks block Python network connections and
do not hand off to, or replace the socket of, a running Neo instance.

Outputs (ignored by Git):

```text
build/Neo-v<version>-x86_64.AppImage
build/Neo-v<version>-x86_64.AppImage.sha256
build/Neo-v<version>-x86_64.AppImage.build-info.json
```

These are pinned-input builds, not a claim of bit-for-bit reproducibility across
different operating systems or Python patch releases. Preserve the recorded
build information when investigating a packaging regression. Dependency updates
need regenerated hashes, matching Qt license/source references, tests and review.

## GitHub Actions and publishing

[AppImage workflow](../.github/workflows/appimage.yml):

- Relevant branch pushes/PRs and manual runs build and test the image, run lint,
  the offline suite and Qt widget tests, then upload an artifact for **14 days**.
- A pushed `vX.Y.Z` tag must exactly match `VERSION` in `neo`. Only a successful
  tag build may prepare a **draft GitHub release** with the image, checksum and
  build information. Branch builds never create releases.
- Published release assets are never overwritten by the workflow. Re-running a
  tag build can refresh its **draft**, not a public release. Only the draft job
  has repository write permission; build/PR jobs are read-only.

Before publishing, follow [Contributing → Releasing](../CONTRIBUTING.md#releasing),
review the generated notes, and test real Discord callbacks and umu/Proton gameplay
on X11/Wayland with real GPU drivers. Offscreen tests cannot establish those work.
Review the bundled license notices and exact corresponding-source availability.
Then explicitly publish the draft in GitHub. No unattended public release or
automatic AppImage updater is configured.
