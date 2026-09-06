"""Finish a source install's GUI entry points (stdlib only, no display needed).

User installs pin the selected GUI interpreter, so a PySide6 virtualenv works
from the application menu as well as the terminal. Staged distro packages keep
the portable shebang; neither entry point may contain the build's DESTDIR.
"""

import argparse
import os
from pathlib import Path
import shlex
import sys


def desktop_value(value):
    """Escape the string-value layer of the Desktop Entry specification."""
    return (value.replace("\\", "\\\\").replace("\n", "\\n")
            .replace("\r", "\\r").replace("\t", "\\t"))


def desktop_argument(value):
    """Quote one Exec argument, then escape the enclosing desktop-file value."""
    # Exec has its own quoting rules, not shell quoting. Literal percent signs
    # must not be mistaken for field codes such as %u.
    value = value.replace("%", "%%")
    value = "".join("\\" + char if char in '\\"`$' else char for char in value)
    return desktop_value('"' + value + '"')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--destdir", default="")
    args = parser.parse_args()
    prefix = Path(os.path.abspath(os.path.expanduser(args.prefix)))
    root = Path(args.destdir) / str(prefix).lstrip("/") if args.destdir else prefix

    script = root / "bin" / "neo-gui"
    if not args.destdir:
        # env -S handles interpreter paths containing spaces. Do not resolve a
        # virtualenv's Python symlink: that would lose the virtualenv itself.
        body = script.read_text(encoding="utf-8").split("\n", 1)[1]
        script.write_text(
            f"#!/usr/bin/env -S {shlex.quote(sys.executable)}\n{body}", encoding="utf-8"
        )

    # Desktop sessions often lack ~/.local/bin on PATH even when a terminal
    # has it. Point at the installed launcher, never the checkout or DESTDIR.
    executable = str(prefix / "bin" / "neo-gui")
    template = Path(__file__).with_name("dev.neofn.NeoLauncher.desktop").read_text(encoding="utf-8")
    entry = template.replace("Exec=neo-gui %u", f"Exec={desktop_argument(executable)} %u")
    entry = entry.replace("TryExec=neo-gui", f"TryExec={desktop_value(executable)}")
    (root / "share" / "applications" / "dev.neofn.NeoLauncher.desktop").write_text(
        entry, encoding="utf-8"
    )


if __name__ == "__main__":
    main()
