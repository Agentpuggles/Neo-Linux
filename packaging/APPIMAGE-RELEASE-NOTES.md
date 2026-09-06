## Neo desktop AppImage — Linux x86-64

Download the `.AppImage` and matching `.sha256` file below. The JSON file records
the source commit, build interpreter, dependencies and tool versions.

1. Verify the download, if desired: `sha256sum -c Neo-v*-x86_64.AppImage.sha256`.
2. Move it to a permanent folder, such as `~/Applications`. Mark it executable in
   **Properties → Permissions**, or use `chmod +x Neo-v*-x86_64.AppImage`.
3. Double-click it. Python and Qt are bundled; you do not need a source checkout,
   a virtualenv, or a separate PySide6 installation to run the GUI.

The first run offers the optional CLI: highly recommended for troubleshooting
and doing tasks manually, but **Not now** is fine. Install it later from
**Settings → Command-line tool**. The separate CLI needs host Python 3.9+.

You still need **umu-launcher**, working graphics drivers and a NeoFN account to
play. No game files or Proton runtime are included. Target: glibc-based Linux
x86-64, built on Ubuntu 22.04 (glibc 2.35). Alpine/musl and ARM are not supported
by this build. Wayland/X11 and real gameplay still need on-hardware release QA.

If mounting is unavailable, run `./Neo-v*-x86_64.AppImage --appimage-extract-and-run`.
For application-menu integration, use **Settings → Desktop integration**. Keep
its file path stable, or re-register the entry after moving/updating the image.
Your account, settings and game downloads live outside the image and are kept
when it is replaced or deleted. An already-installed CLI is not auto-updated.

This is unofficial software, not affiliated with NeoFN or Epic Games. See the
repository's README, changelog and SECURITY.md for compatibility and account-risk
notes. Never attach session tokens or `auth.json` to a bug report.

---

**Maintainer draft checklist — complete before publishing:**
- Add the release's actual changelog highlights and known issues.
- Check clean GitHub Actions, the checksum and recorded source commit.
- Test opening the GUI, Discord sign-in/callbacks, optional CLI skip/install,
  download/import/repair and umu/Proton launch on real X11 and Wayland desktops.
- Check an older supported distro, a current gaming distro, and driver behaviour.
- Review bundled license notices and corresponding-source availability.
- Remove this checklist and publish only after the manual checks pass.
