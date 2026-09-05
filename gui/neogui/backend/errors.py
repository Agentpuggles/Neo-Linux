"""One error type for the whole GUI.

Every failure the user can see is a `NeoError`: a short human sentence, the raw
technical detail (kept out of the way but never thrown away) and, when we can
work it out, a concrete next step. Views render the three parts differently —
headline, expandable "Details", and a highlighted hint — so an error is always
readable *and* diagnosable.
"""

from __future__ import annotations

import errno
import socket
import ssl
import urllib.error
from dataclasses import dataclass, field


@dataclass
class NeoError(Exception):
    summary: str
    detail: str = ""
    hint: str = ""
    kind: str = "error"  # error | network | auth | permission | notfound | config
    context: dict = field(default_factory=dict)

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.summary

    @property
    def text(self) -> str:
        bits = [self.summary]
        if self.hint:
            bits.append(self.hint)
        if self.detail:
            bits.append(self.detail)
        return "\n\n".join(bits)


_NETWORK_HINT = (
    "Check your internet connection. If you are online, NeoFN's services may be "
    "down — the Play page shows service status."
)


def classify(exc: BaseException, *, action: str = "") -> NeoError:
    """Map any backend exception onto a NeoError the UI can present."""
    if isinstance(exc, NeoError):
        return exc

    prefix = f"{action} failed" if action else "Something went wrong"
    detail = f"{type(exc).__name__}: {exc}"
    text = str(exc)

    if isinstance(exc, urllib.error.HTTPError):
        code = exc.code
        if code in (401, 403):
            return NeoError(
                f"{prefix}: not authorised",
                detail,
                "Your session may have expired. Sign out and sign in again.",
                kind="auth",
            )
        if code == 404:
            return NeoError(f"{prefix}: the server has no such resource", detail, kind="notfound")
        if code >= 500:
            return NeoError(
                f"{prefix}: NeoFN returned a server error ({code})",
                detail,
                "This is on NeoFN's side. Try again in a few minutes.",
                kind="network",
            )
        return NeoError(f"{prefix}: HTTP {code}", detail, kind="network")

    if isinstance(exc, (urllib.error.URLError, socket.timeout, socket.gaierror, ssl.SSLError)):
        return NeoError(f"{prefix}: could not reach NeoFN", detail, _NETWORK_HINT, kind="network")

    if isinstance(exc, PermissionError):
        return NeoError(
            f"{prefix}: permission denied",
            detail,
            "Neo cannot read or write that path. Check the folder's ownership and "
            "permissions, or choose a different location in Settings.",
            kind="permission",
        )

    if isinstance(exc, FileNotFoundError):
        return NeoError(f"{prefix}: a required file is missing", detail, kind="notfound")

    if isinstance(exc, OSError):
        if exc.errno == errno.ENOSPC:
            return NeoError(
                f"{prefix}: the disk is full",
                detail,
                "Free some space, or move the install/cache location in Settings → Game.",
                kind="error",
            )
        if exc.errno == errno.EROFS:
            return NeoError(f"{prefix}: that filesystem is read-only", detail, kind="permission")

    low = text.lower()
    if "not logged in" in low or "unauthor" in low:
        return NeoError(
            f"{prefix}: you are not signed in",
            detail,
            "Sign in with Discord from the account panel.",
            kind="auth",
        )
    if "http 4" in low or "http 5" in low or ("failed:" in low and "urlopen" in low):
        return NeoError(f"{prefix}: could not reach NeoFN", detail, _NETWORK_HINT, kind="network")
    if "sha1" in low or "sha256" in low or "mismatch" in low:
        return NeoError(
            f"{prefix}: a downloaded file did not match its checksum",
            detail,
            "Run Verify & Repair on the build — only the broken files are re-fetched.",
        )

    # Plain RuntimeErrors from `neo` are already written for humans.
    if isinstance(exc, RuntimeError) and text:
        return NeoError(text if action == "" else f"{prefix}: {text}", detail)

    return NeoError(prefix, detail)
