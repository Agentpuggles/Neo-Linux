"""Plain dataclasses the UI renders. No Qt, no launcher types leak past here."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Session:
    logged_in: bool = False
    account_id: str = ""
    display_name: str = ""
    email: str = ""
    access_expires_at: str = ""
    refresh_expires_at: str = ""
    setup_completed: bool | None = None

    @property
    def label(self) -> str:
        return self.display_name or (self.account_id[:12] if self.account_id else "Signed out")

    @property
    def initials(self) -> str:
        name = self.display_name.strip()
        if not name:
            return "?"
        parts = [p for p in name.replace("_", " ").replace("-", " ").split() if p]
        if len(parts) >= 2:
            return (parts[0][0] + parts[1][0]).upper()
        return name[:2].upper()


@dataclass
class ServiceStatus:
    reachable: bool = False
    status: str = "UNKNOWN"
    message: str = ""
    banned: bool = False
    ban_reason: str = ""
    allowed_actions: list = field(default_factory=list)
    players_online: int | None = None
    prism_banned: bool | None = None
    prism_reason: str = ""
    fortnite_access: bool | None = None
    # granted | denied | open | unknown — "open" is the post-launch service no
    # longer publishing a per-account gate (the endpoint 404s), which is not a
    # denial and must not gray out Play. See neo.ACCESS_* / protocol.md §11.2.
    access_gate: str = "unknown"
    entitlements: str = ""
    checked_at: datetime | None = None
    error: str = ""

    @property
    def up(self) -> bool:
        return self.status.upper() == "UP"

    @property
    def access_denied(self) -> bool:
        """Only an explicit `false` from the gate blocks play."""
        return self.access_gate == "denied"

    @property
    def access_ok(self) -> bool:
        return self.access_gate in ("granted", "open")

    @property
    def access_label(self) -> str:
        return {"granted": "Granted", "denied": "Not granted",
                "open": "Open"}.get(self.access_gate, "Unknown")

    @property
    def access_tone(self) -> str:
        return {"granted": "success", "open": "success",
                "denied": "warning"}.get(self.access_gate, "muted")

    @property
    def access_note(self) -> str:
        return {
            "denied": "NeoFN has not enabled play for this account yet.",
            "open": "Play is no longer gated per account.",
        }.get(self.access_gate, "")

    @property
    def tone(self) -> str:
        if not self.reachable:
            return "muted"
        if self.banned:
            return "danger"
        return "success" if self.up else "warning"


@dataclass
class Build:
    version: str
    size: int = 0
    release_date: str = ""
    is_live: bool = False
    manifest_path: str = ""
    raw: dict = field(default_factory=dict)

    @property
    def short(self) -> str:
        """`Fortnite/10.40-CL-9603448` → `10.40`."""
        tail = self.version.split("/")[-1]
        return tail.split("-CL-")[0] or tail

    @property
    def changelist(self) -> str:
        _, sep, cl = self.version.partition("-CL-")
        return cl if sep else ""


@dataclass
class Install:
    version: str
    path: str
    size: int = 0
    imported: bool = False
    exists: bool = True
    playable: bool = False
    build: dict = field(default_factory=dict)

    @property
    def short(self) -> str:
        tail = self.version.split("/")[-1]
        return tail.split("-CL-")[0] or tail


@dataclass
class Friend:
    account_id: str
    name: str = ""
    subscription: str = ""
    online: bool = False
    show: str = ""
    status: str = ""

    @property
    def label(self) -> str:
        return self.name or self.account_id[:12]

    @property
    def state(self) -> str:
        if self.online:
            return {"dnd": "Do not disturb", "away": "Away", "xa": "Away"}.get(
                self.show.lower(), "Online"
            )
        return (self.subscription or "offline").capitalize()


@dataclass
class NewsItem:
    date: str = ""
    title: str = ""
    body: str = ""


@dataclass
class CacheStats:
    chunk_files: int = 0
    chunk_bytes: int = 0
    manifest_files: int = 0
    manifest_bytes: int = 0
    path: str = ""

    @property
    def total_bytes(self) -> int:
        return self.chunk_bytes + self.manifest_bytes


@dataclass
class Progress:
    """One progress report from a long-running job."""

    label: str = ""
    done: int = 0
    total: int = 0
    unit: str = "bytes"  # bytes | files | chunks
    rate: float = 0.0
    eta: float = 0.0
    detail: str = ""

    @property
    def fraction(self) -> float:
        return min(1.0, self.done / self.total) if self.total else 0.0

    @property
    def percent(self) -> int:
        return round(self.fraction * 100)


@dataclass
class VerifyReport:
    version: str
    checked: int = 0
    missing: list = field(default_factory=list)
    corrupt: list = field(default_factory=list)
    repaired: int = 0
    failed: list = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.missing and not self.corrupt


@dataclass
class LaunchPlan:
    """Everything about a launch, resolved but not yet run."""

    version: str = ""
    executable: str = ""
    working_dir: str = ""
    argv: list = field(default_factory=list)
    env: dict = field(default_factory=dict)
    umu: str = "umu-run"
    proton: str = ""
    wine_prefix: str = ""

    def display_command(self) -> list:
        """The command line with the exchange codes masked, like the CLI prints it."""
        out = [self.umu, self.executable]
        for arg in self.argv:
            if arg.startswith(("-AUTH_PASSWORD=", "-p=", "-fltoken=")):
                out.append(arg.split("=", 1)[0] + "=***")
            else:
                out.append(arg)
        return out
