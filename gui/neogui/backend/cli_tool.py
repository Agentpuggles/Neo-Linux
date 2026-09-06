"""Install the optional terminal command from the bundled core, never the network.

The GUI keeps its own backend regardless of this choice. Only a user-requested
install writes ~/.local/bin/neo. Existing commands (including symlinks) are never
overwritten, and files copied from an AppImage keep working after it unmounts.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
import os
from pathlib import Path
import shlex
import shutil
import tempfile

from .errors import NeoError, classify

RECOMMENDATION = (
    "The command-line tool (CLI) is highly recommended for troubleshooting and "
    "doing tasks manually, such as checking status, reading logs and repairing files. "
    "The desktop app works without it. You can install it later from "
    "Settings → Command-line tool."
)
# Identify our plain Python launcher without executing anything found on PATH.
_MARKER = "# neo — a native Linux launcher for NeoFN (neofn.dev)".encode()


@dataclass(frozen=True)
class CliStatus:
    path: Path
    installed: bool = False
    on_path: bool = False
    conflict: bool = False

    @property
    def help_command(self) -> str:
        command = "neo" if self.on_path else shlex.quote(str(self.path))
        return f"{command} --help"


def user_cli_path() -> Path:
    return Path.home() / ".local" / "bin" / "neo"


def is_neo_cli(path: Path) -> bool:
    try:
        if path.is_file() and os.access(path, os.X_OK):
            with path.open("rb") as source:
                return _MARKER in source.read(512)
    except OSError:
        pass
    return False


def cli_status(source: Path) -> CliStatus:
    target = user_cli_path()
    found = shutil.which("neo")
    resolved = Path(found) if found else None
    candidates = [target]
    if resolved is not None:
        candidates.append(resolved)
    # Also recognise a legacy/custom-prefix install outside the session's PATH.
    if source.parent.name == "neo" and source.parent.parent.name in ("share", "lib"):
        candidates.append(source.parents[2] / "bin" / "neo")
    for path in candidates:
        if is_neo_cli(path):
            on_path = False
            if resolved is not None:
                with contextlib.suppress(OSError):
                    on_path = path.samefile(resolved)
            return CliStatus(path, installed=True, on_path=on_path)
    return CliStatus(target, conflict=os.path.lexists(target))


def install_cli(source: Path) -> CliStatus:
    """Copy the stdlib CLI into the user's bin directory, without replacing files."""
    status = cli_status(source)
    if status.installed:
        return status
    target = user_cli_path()
    if status.conflict:
        raise NeoError(
            "The CLI could not be installed because that path is already in use.",
            str(target),
            "Nothing was overwritten. Check the existing file, then try again from "
            "Settings → Command-line tool. You can keep using the GUI without the CLI.",
            kind="conflict",
        )

    temporary = None
    try:
        data = source.read_bytes()
        if _MARKER not in data[:512]:
            raise NeoError(
                "The bundled CLI source could not be recognised.", str(source),
                "Reinstall Neo from a full checkout, or run make install-cli from it.",
                kind="notfound",
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".neo-cli-", dir=target.parent)
        with os.fdopen(fd, "wb") as file:
            file.write(data)
            file.flush()
            os.fchmod(file.fileno(), 0o755)
        # Publish the finished file atomically. Unlike replace(), link() refuses
        # even a dangling symlink at the destination if it appeared meanwhile.
        os.link(temporary, target)
    except OSError as exc:
        raise classify(exc, action="Installing the command-line tool") from exc
    finally:
        if temporary:
            with contextlib.suppress(OSError):
                os.unlink(temporary)
    return cli_status(source)
