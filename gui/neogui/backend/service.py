"""The GUI's façade over the `neo` launcher.

Everything the UI can do goes through `NeoService`. It is deliberately Qt-free
so it can be exercised headlessly in tests, and it never re-implements protocol
work: manifests, chunk fetching, hashing, the auth dance, the launch argument
vector and the XMPP client all come straight from the launcher module.

The few loops that *are* re-expressed here (install, verify, repair) exist only
because the CLI versions render an ANSI progress bar to stdout and call
`sys.exit()`. They call the same primitives — `load_manifest`, `fetch_chunk`,
`assemble_file`, `install_path` — so there is one implementation of the format
work, with the orchestration parameterised over a progress callback instead of
a terminal.
"""

from __future__ import annotations

import concurrent.futures as cf
import contextlib
import glob
import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import threading
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from collections.abc import Iterable

from .core import neo_module
from .errors import NeoError, classify
from .models import (
    Build,
    CacheStats,
    Friend,
    Install,
    LaunchPlan,
    NewsItem,
    Progress,
    ServiceStatus,
    Session,
    VerifyReport,
)

ProgressFn = Callable[[Progress], None]
LogFn = Callable[[str], None]

# Two shapes to catch: `key: value` / `key=value` pairs (JSON, headers, config
# dumps) and the game's own command-line flags. `\b` does not match before the
# leading "-" of a flag, so the flag forms are listed with their own alternation
# rather than relying on a word boundary — the launch preview and any crash tail
# that echoes the argv must never carry a live exchange code.
TOKEN_RE = re.compile(
    r"(?i)"
    r"(-AUTH_PASSWORD=|-fltoken=|-p=|"
    r"\b(?:access_token|refresh_token|authorization_code|refreshtoken|accesstoken|"
    r"authorization|bearer|token|secret|password|code)\b[\"'\s:=]*)"
    r"([A-Za-z0-9._\-]{8,})"
)


def redact(text: str) -> str:
    """Blank anything token-shaped.

    Applied on every path where text leaves the process or reaches the screen:
    game stderr, the session log, saved logs and the diagnostics report. It is
    deliberately over-eager — a redacted false positive costs a support round
    trip, a leaked exchange code costs an account.
    """
    return TOKEN_RE.sub(lambda m: f"{m.group(1)}<redacted>", text or "")


class CancelToken:
    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def check(self) -> None:
        if self._event.is_set():
            raise Cancelled()


class Cancelled(Exception):
    """Raised inside a job when the user cancels it."""


# ------------------------------------------------------------------ settings
SETTING_SPECS = {
    "install_root": ("path", "Where builds are installed"),
    "cache_dir": ("path", "Where chunks and manifests are cached during a download"),
    "workers": ("int", "Parallel download workers"),
    "proton": ("text", "Proton build umu should use (name or path)"),
    "launch_options": ("text", "Extra UE4 arguments added to every launch"),
    "edit_on_release": ("bool", "Confirm edits when the edit button is released"),
    "instant_reset": ("bool", "Confirm a reset when the reset button is released"),
    "disable_pre_edit": ("bool", "Skip the pre-edit highlight"),
}

# GUI-only preferences. Kept in the same config file so there is one place to
# look, but namespaced so `neo config` never trips over them.
GUI_SETTING_DEFAULTS = {
    "gui_theme": "system",  # system | dark | light
    "gui_accent": "violet",
    "gui_minimise_to_tray": False,
    "gui_notify_on_finish": True,
    "gui_confirm_launch": False,
    "gui_advanced_mode": False,
}


class NeoService:
    def __init__(self) -> None:
        self._neo = neo_module()
        self._auth = None
        self._auth_lock = threading.Lock()

    # -------------------------------------------------------------- plumbing
    @property
    def neo(self):
        return self._neo

    @property
    def version(self) -> str:
        return getattr(self._neo, "VERSION", "?")

    def auth(self):
        with self._auth_lock:
            if self._auth is None:
                self._auth = self._neo.Auth()
            return self._auth

    def reload_auth(self):
        with self._auth_lock:
            self._auth = self._neo.Auth()
            return self._auth

    def human(self, n: float) -> str:
        return self._neo.human(n)

    # ---------------------------------------------------------------- config
    def config(self) -> dict:
        cfg = dict(GUI_SETTING_DEFAULTS)
        cfg.update(self._neo.load_config())
        return cfg

    def config_path(self) -> str:
        return self._neo.config_path()

    def set_config(self, key: str, value) -> None:
        if key in SETTING_SPECS or key in GUI_SETTING_DEFAULTS:
            pass
        else:
            raise NeoError(f"Unknown setting “{key}”.", kind="config")
        cfg = self._neo.load_config()
        kind = SETTING_SPECS.get(key, ("bool" if isinstance(value, bool) else "text", ""))[0]
        if kind == "int":
            try:
                value = max(1, int(value))
            except (TypeError, ValueError) as exc:
                raise NeoError(
                    f"“{key}” needs a whole number.", str(exc), kind="config"
                ) from exc
        elif kind == "bool":
            value = bool(value)
        elif kind == "path" and value:
            value = os.path.expanduser(str(value))
        cfg[key] = value
        path = self.config_path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w") as fh:
                json.dump(cfg, fh, indent=1)
            os.replace(tmp, path)
        except OSError as exc:
            raise classify(exc, action="Saving settings") from exc

    def validate_launch_options(self, text: str) -> list:
        try:
            return shlex.split(text or "", posix=True)
        except ValueError as exc:
            raise NeoError(
                "Those launch options can't be parsed.",
                str(exc),
                "Usually an unbalanced quote. Example: -windowed -ResX=1920",
                kind="config",
            ) from exc

    # --------------------------------------------------------------- session
    def session(self) -> Session:
        auth = self.reload_auth()
        d = auth.d or {}
        return Session(
            logged_in=bool(auth.logged_in),
            account_id=d.get("account_id", ""),
            display_name=d.get("display_name", ""),
            access_expires_at=d.get("access_expires_at", "") or "",
            refresh_expires_at=d.get("refresh_expires_at", "") or "",
        )

    def login_url(self) -> str:
        return self._neo.CHALLENGE

    def install_scheme_handler(self) -> None:
        with contextlib.suppress(Exception):
            self._neo.install_scheme_handler()

    def extract_code(self, pasted: str) -> str:
        """Accept either a bare code or the whole neolauncher:// callback URL."""
        text = (pasted or "").strip().strip("<>\"'")
        if not text:
            raise NeoError("Paste the code (or the whole callback URL) first.", kind="auth")
        if "://" in text or text.startswith("?") or "code=" in text:
            query = urllib.parse.urlparse(text).query or text.lstrip("?")
            found = urllib.parse.parse_qs(query).get("code", [""])[0]
            text = found or text
        text = text.strip()
        if "…" in text or "..." in text or len(text) < 16:
            raise NeoError(
                "That looks like a truncated code.",
                f"got {len(text)} characters",
                "Copy the complete neolauncher://callback/auth?code=… URL from the "
                "browser's address bar — the code is 30+ characters with no “…” in it.",
                kind="auth",
            )
        return text

    def login_with_code(self, pasted: str) -> Session:
        code = self.extract_code(pasted)
        auth = self.reload_auth()
        try:
            auth.login_code(code)
        except Exception as exc:
            raise NeoError(
                "Sign-in failed.",
                redact(f"{type(exc).__name__}: {exc}"),
                "The code may be wrong, already used, or expired. Start the sign-in "
                "again to get a fresh one.",
                kind="auth",
            ) from exc
        return self.session()

    def logout(self) -> Session:
        self.reload_auth().logout()
        return self.session()

    def account_details(self) -> Session:
        auth = self.auth()
        s = self.session()
        if not s.logged_in:
            return s
        n = self._neo
        try:
            r = n.jhttp(
                "GET",
                n.ACCOUNT + "/api/public/account/" + auth.d["account_id"],
                headers={"Authorization": "Bearer " + auth.access()},
            )
            s.display_name = r.get("displayName") or s.display_name
            s.email = r.get("email") or ""
        except Exception as exc:
            raise classify(exc, action="Loading your account") from exc
        with contextlib.suppress(Exception):
            st = n.jhttp(
                "GET",
                n.ACCOUNT + "/api/public/account/setup/status",
                headers={"Authorization": "Bearer " + auth.access()},
            )
            s.setup_completed = bool(st.get("setupCompleted"))
        return s

    def display_name_available(self, name: str) -> bool:
        n, auth = self._neo, self.auth()
        try:
            r = n.jhttp(
                "GET",
                n.ACCOUNT
                + "/api/public/account/displayName/"
                + urllib.parse.quote(name, safe="")
                + "/available",
                headers={"Authorization": "Bearer " + auth.access()},
            )
        except Exception as exc:
            raise classify(exc, action="Checking that name") from exc
        return bool(r.get("available"))

    def set_display_name(self, name: str) -> str:
        name = (name or "").strip()
        if not 3 <= len(name) <= 16:
            raise NeoError("Display names are 3–16 characters.", kind="config")
        n, auth = self._neo, self.auth()
        if not self.display_name_available(name):
            raise NeoError(f"“{name}” is already taken.", hint="Try another name.", kind="config")
        try:
            status, raw = n.http(
                "POST",
                n.ACCOUNT + "/api/public/account/setup",
                body=json.dumps({"displayName": name}).encode(),
                headers={
                    "Authorization": "Bearer " + auth.access(),
                    "Content-Type": "application/json",
                },
            )
        except Exception as exc:
            raise classify(exc, action="Setting your display name") from exc
        if status >= 400:
            raise NeoError(
                "NeoFN rejected that display name.",
                f"HTTP {status}: {raw[:200].decode('utf-8', 'replace')}",
                kind="config",
            )
        confirmed = json.loads(raw or b"{}").get("displayName", name)
        auth.d["display_name"] = confirmed
        auth.save()
        return confirmed

    # ---------------------------------------------------------------- status
    def service_status(self, *, deep: bool = True) -> ServiceStatus:
        n = self._neo
        out = ServiceStatus(checked_at=datetime.now(timezone.utc))
        try:
            ls = n.lightswitch(self.auth())
        except Exception as exc:
            out.error = classify(exc, action="Checking service status").summary
            return out
        out.reachable = True
        out.status = str(ls.get("status") or "UNKNOWN")
        out.message = str(ls.get("message") or "")
        out.banned = bool(ls.get("banned"))
        out.ban_reason = str(ls.get("banReason") or "")
        actions = ls.get("allowedActions") or []
        out.allowed_actions = list(actions) if isinstance(actions, list) else [str(actions)]

        with contextlib.suppress(Exception):
            oc = n.jhttp("GET", n.LAUNCHER + "/api/public/onlinecount")
            if isinstance(oc, dict):
                # a per-service map: {"fortnite": 240, "launcher": 402} — the
                # game's own number is the one worth showing.
                counts = {k: v for k, v in oc.items() if isinstance(v, int)}
                oc = counts.get("fortnite", next(iter(counts.values()), None))
            if isinstance(oc, int):
                out.players_online = oc

        if deep and self.auth().logged_in:
            with contextlib.suppress(Exception):
                b = n.prism_ban(self.auth())
                out.prism_banned = bool(b.get("banned"))
                out.prism_reason = str(b.get("reason") or "")
            with contextlib.suppress(Exception):
                state, _payload = n.fortnite_access_state(self.auth())
                out.access_gate = state
                out.fortnite_access = (
                    None if state == n.ACCESS_OPEN else state == n.ACCESS_GRANTED
                )
            with contextlib.suppress(Exception):
                out.entitlements = n.describe_entitlements(n.store_entitlements(self.auth()))
        return out

    # ---------------------------------------------------------------- builds
    def builds(self) -> list:
        try:
            rows = self._neo.get_builds(self.auth())
        except Exception as exc:
            raise classify(exc, action="Loading the build catalog") from exc
        out = []
        for b in rows or []:
            out.append(
                Build(
                    version=b.get("version", "?"),
                    size=int(b.get("fileSizeBytes") or 0),
                    release_date=str(b.get("releaseDate") or ""),
                    is_live=bool(b.get("isLive")),
                    manifest_path=b.get("manifestPath", ""),
                    raw=b,
                )
            )
        out.sort(key=lambda b: (not b.is_live, -self._neo.changelist_number(b.version)))
        return out

    # -------------------------------------------------------------- installs
    def state(self) -> dict:
        return self._neo.load_state()

    def installs(self) -> list:
        st = self.state()
        out = []
        for version, inst in (st.get("installs") or {}).items():
            path = inst.get("path", "")
            exists = bool(path) and os.path.isdir(path)
            playable = exists and os.path.isdir(
                os.path.join(path, "FortniteGame", "Binaries", "Win64")
            )
            out.append(
                Install(
                    version=version,
                    path=path,
                    imported=bool(inst.get("imported")),
                    exists=exists,
                    playable=playable,
                    build=inst.get("build") or {},
                    size=int((inst.get("build") or {}).get("fileSizeBytes") or 0),
                )
            )
        out.sort(key=lambda i: -self._neo.changelist_number(i.version))
        return out

    def newest_install(self) -> Install | None:
        rows = self.installs()
        return rows[0] if rows else None

    def install_dir_size(self, path: str) -> int:
        total = 0
        for root, _dirs, files in os.walk(path):
            for name in files:
                with contextlib.suppress(OSError):
                    total += os.path.getsize(os.path.join(root, name))
        return total

    def disk_free(self, path: str) -> int | None:
        probe = path
        while probe and not os.path.isdir(probe):
            parent = os.path.dirname(probe)
            if parent == probe:
                return None
            probe = parent
        try:
            return shutil.disk_usage(probe).free
        except OSError:
            return None

    # ------------------------------------------------------------ install job
    def install_build(
        self,
        version: str | None = None,
        *,
        target_dir: str | None = None,
        workers: int | None = None,
        keep_cache: bool = False,
        force: bool = False,
        progress: ProgressFn | None = None,
        log: LogFn | None = None,
        cancel: CancelToken | None = None,
    ) -> Install:
        n = self._neo
        cancel = cancel or CancelToken()
        emit = progress or (lambda p: None)
        say = log or (lambda s: None)

        def step(label, detail=""):
            emit(Progress(label=label, total=0, detail=detail))
            say(label + (f" — {detail}" if detail else ""))

        cfg = self.config()
        step("Reading the build catalog")
        builds = n.get_builds(self.auth())
        try:
            build = n.pick_build(builds, version)
        except RuntimeError as exc:
            raise NeoError(
                f"No build matches “{version}”.",
                str(exc),
                "Pick one from the Library list.",
                kind="notfound",
            ) from exc
        ver = build["version"]
        cancel.check()

        clouds = n.get_distribution_points()
        if not clouds:
            raise NeoError(
                "NeoFN listed no download servers.",
                hint="This is usually temporary — try again shortly.",
                kind="network",
            )
        cloud = clouds[0]

        step("Fetching the manifest", ver)
        m = n.load_manifest(ver, cloud + "/" + build["manifestPath"].lstrip("/"))
        cancel.check()

        root = os.path.abspath(os.path.expanduser(target_dir or cfg["install_root"]))
        inst_dir = os.path.join(root, n.version_dir_name(ver))
        try:
            os.makedirs(inst_dir, exist_ok=True)
        except OSError as exc:
            raise classify(exc, action="Creating the install folder") from exc

        needed = sorted({g for f in m.files for g, _, _ in f["parts"]})
        total = sum(m.chunks.get(g, {}).get("size", 0) for g in needed)
        total_raw = sum(size for f in m.files for _, _, size in f["parts"])

        if not force:
            short = n.free_space_shortages([(n.cache_dir(), total), (inst_dir, total_raw)])
            if short:
                lines = [
                    f"{os.path.dirname(p) or p}: {self.human(free)} free, "
                    f"{self.human(need)} needed"
                    for p, free, need in short
                ]
                raise NeoError(
                    "Not enough free disk space for this build.",
                    "\n".join(lines),
                    "Install somewhere else, or move the download cache in "
                    "Settings → Game. The compressed download and the extracted "
                    "build both need room.",
                )

        say(f"{len(m.files)} files, {len(needed)} chunks ({self.human(total)} to download)")
        stats = {"dl": 0, "reuse": 0}
        chunk_cache: dict = {}
        cache_lock = threading.Lock()
        done_bytes = {"n": 0}
        t0 = time.time()

        def get_chunk(guid):
            cancel.check()
            data = n.fetch_chunk(cloud, m, guid, stats)
            with cache_lock:
                if len(chunk_cache) > 96:
                    for k in list(chunk_cache)[:32]:
                        chunk_cache.pop(k, None)
                chunk_cache[guid] = data
            return guid

        pool = max(1, int(workers or cfg["workers"]))
        with cf.ThreadPoolExecutor(max_workers=pool) as ex:
            futs = {ex.submit(get_chunk, g): g for g in needed}
            try:
                for fut in cf.as_completed(futs):
                    guid = futs[fut]
                    done_bytes["n"] += m.chunks.get(guid, {}).get("size", 0)
                    elapsed = max(time.time() - t0, 0.001)
                    rate = done_bytes["n"] / elapsed
                    emit(
                        Progress(
                            label="Downloading",
                            done=done_bytes["n"],
                            total=total,
                            unit="bytes",
                            rate=rate,
                            eta=(total - done_bytes["n"]) / max(rate, 1.0),
                            detail=f"{stats['dl']} downloaded · {stats['reuse']} reused",
                        )
                    )
                    fut.result()
            except (Cancelled, KeyboardInterrupt):
                for f in futs:
                    f.cancel()
                raise
            except Exception as exc:
                for f in futs:
                    f.cancel()
                raise classify(exc, action="Downloading the build") from exc

        say(f"chunks: {stats['dl']} downloaded, {stats['reuse']} reused from cache")
        cancel.check()

        bad = []
        for i, f in enumerate(m.files, 1):
            cancel.check()
            try:
                n.assemble_file(inst_dir, f, chunk_cache, cloud, m)
            except Exception as exc:
                bad.append((f["name"], str(exc)))
            if i % 5 == 0 or i == len(m.files):
                emit(
                    Progress(
                        label="Assembling files",
                        done=i,
                        total=len(m.files),
                        unit="files",
                        detail=f["name"][-58:],
                    )
                )

        with open(os.path.join(inst_dir, ".neo-manifest.json"), "w") as fh:
            json.dump(m.d, fh)
        st = n.load_state()
        st.setdefault("installs", {})[ver] = {"path": inst_dir, "build": build}
        n.save_state(st)

        if bad:
            raise NeoError(
                f"{len(bad)} file(s) could not be written.",
                "\n".join(f"{name}: {msg}" for name, msg in bad[:12]),
                "Run Verify & Repair — only the broken files are re-fetched.",
                context={"version": ver},
            )

        if not keep_cache:
            purged = 0
            for g in needed:
                with contextlib.suppress(OSError):
                    os.remove(os.path.join(n.cache_dir(), "chunks", g))
                    purged += 1
            say(f"purged {purged} cached chunks")

        say(f"Installed {ver} → {inst_dir}")
        return Install(version=ver, path=inst_dir, exists=True, playable=True, build=build)

    # ------------------------------------------------------------ verify job
    def verify_install(
        self,
        version: str | None = None,
        *,
        repair: bool = False,
        progress: ProgressFn | None = None,
        log: LogFn | None = None,
        cancel: CancelToken | None = None,
    ) -> VerifyReport:
        n = self._neo
        cancel = cancel or CancelToken()
        emit = progress or (lambda p: None)
        say = log or (lambda s: None)

        ver, inst = self._resolve_install(version)
        manifest_file = os.path.join(inst["path"], ".neo-manifest.json")
        if not os.path.exists(manifest_file):
            raise NeoError(
                "That install has no Neo manifest, so it can't be verified.",
                manifest_file,
                "Re-register it from Library → Import, which downloads the manifest.",
                kind="notfound",
            )
        with open(manifest_file) as fh:
            m = n.Manifest(json.load(fh))

        report = VerifyReport(version=ver, checked=len(m.files))
        for i, f in enumerate(m.files, 1):
            cancel.check()
            p = os.path.join(inst["path"], f["name"])
            if f["symlink"]:
                if not os.path.islink(p):
                    report.missing.append(f)
            elif not os.path.exists(p):
                report.missing.append(f)
            else:
                h = hashlib.sha1()
                try:
                    with open(p, "rb") as fh:
                        for b in iter(lambda: fh.read(1 << 20), b""):
                            h.update(b)
                except OSError as exc:
                    raise classify(exc, action="Reading a game file") from exc
                if f["sha1"] and h.hexdigest() != f["sha1"]:
                    report.corrupt.append(f)
            if i % 10 == 0 or i == len(m.files):
                emit(
                    Progress(
                        label="Verifying",
                        done=i,
                        total=len(m.files),
                        unit="files",
                        detail=f"{len(report.missing)} missing · {len(report.corrupt)} corrupt",
                    )
                )

        if report.clean:
            say("All files verified.")
            return report
        say(f"{len(report.missing)} missing, {len(report.corrupt)} corrupt")
        if not repair:
            return report

        broken = report.missing + report.corrupt
        clouds = n.get_distribution_points()
        if not clouds:
            raise NeoError("No download servers available, so repair can't run.", kind="network")
        cloud = clouds[0]
        stats = {"dl": 0, "reuse": 0}
        cache_map: dict = {}
        for i, f in enumerate(broken, 1):
            cancel.check()
            try:
                for guid, _off, _size in f["parts"]:
                    if guid not in cache_map:
                        cache_map[guid] = n.fetch_chunk(cloud, m, guid, stats)
                n.assemble_file(inst["path"], f, cache_map, cloud, m)
                if not f["symlink"]:
                    h = hashlib.sha1()
                    with open(n.install_path(inst["path"], f["name"]), "rb") as fh:
                        for b in iter(lambda: fh.read(1 << 20), b""):
                            h.update(b)
                    if f["sha1"] and h.hexdigest() != f["sha1"]:
                        raise RuntimeError("sha1 still mismatched after rebuild")
                report.repaired += 1
            except Cancelled:
                raise
            except Exception as exc:
                report.failed.append((f["name"], str(exc)))
            emit(
                Progress(
                    label="Repairing",
                    done=i,
                    total=len(broken),
                    unit="files",
                    detail=f["name"][-58:],
                )
            )
        say(f"repaired {report.repaired}, {len(report.failed)} still failing")
        return report

    def _resolve_install(self, version: str | None):
        st = self._neo.load_state()
        installs = st.get("installs") or {}
        if not installs:
            raise NeoError(
                "No build is installed yet.",
                hint="Install one from the Library.",
                kind="notfound",
            )
        if not version or version == "live":
            ver = sorted(installs, key=self._neo.changelist_number)[-1]
        else:
            ver = next((v for v in installs if version in v), None)
            if not ver:
                raise NeoError(f"No install matches “{version}”.", kind="notfound")
        return ver, installs[ver]

    # ----------------------------------------------------------- import etc.
    def import_build(self, path: str, version: str) -> Install:
        n = self._neo
        path = os.path.abspath(os.path.expanduser(path))
        for sub in ("FortniteGame", "Engine"):
            if not os.path.isdir(os.path.join(path, sub)):
                raise NeoError(
                    "That folder is not a Fortnite build root.",
                    f"missing {sub}/ inside {path}",
                    "Pick the folder that directly contains FortniteGame/ and Engine/.",
                    kind="notfound",
                )
        try:
            builds = n.get_builds(self.auth())
            build = n.pick_build(builds, version)
            clouds = n.get_distribution_points()
            if not clouds:
                raise NeoError("No download servers available for the manifest.", kind="network")
            m = n.load_manifest(
                build["version"], clouds[0] + "/" + build["manifestPath"].lstrip("/")
            )
            with open(os.path.join(path, ".neo-manifest.json"), "w") as fh:
                json.dump(m.d, fh)
        except NeoError:
            raise
        except Exception as exc:
            raise classify(exc, action="Importing that build") from exc
        st = n.load_state()
        st.setdefault("installs", {})[build["version"]] = {
            "path": path,
            "build": build,
            "imported": True,
        }
        n.save_state(st)
        return Install(
            version=build["version"], path=path, imported=True, exists=True, playable=True,
            build=build,
        )

    def uninstall(self, version: str, *, delete_files: bool = True) -> None:
        n = self._neo
        ver, inst = self._resolve_install(version)
        path = inst.get("path", "")
        st = n.load_state()
        if delete_files and os.path.isdir(path):
            if not os.path.exists(os.path.join(path, ".neo-manifest.json")):
                st.get("installs", {}).pop(ver, None)
                n.save_state(st)
                raise NeoError(
                    "Refusing to delete that folder — it has no Neo manifest.",
                    path,
                    "The entry has been removed from Neo's list; delete the folder "
                    "yourself if you are sure it is a Neo install.",
                    kind="permission",
                )
            try:
                shutil.rmtree(path)
            except OSError as exc:
                raise classify(exc, action="Deleting the build") from exc
        st.get("installs", {}).pop(ver, None)
        n.save_state(st)

    # ----------------------------------------------------------------- cache
    def cache_stats(self) -> CacheStats:
        n = self._neo
        cache = n.cache_dir()
        out = CacheStats(path=cache)
        for sub, count_attr, byte_attr in (
            ("chunks", "chunk_files", "chunk_bytes"),
            ("manifests", "manifest_files", "manifest_bytes"),
        ):
            d = os.path.join(cache, sub)
            files = size = 0
            if os.path.isdir(d):
                for name in os.listdir(d):
                    with contextlib.suppress(OSError):
                        size += os.path.getsize(os.path.join(d, name))
                        files += 1
            setattr(out, count_attr, files)
            setattr(out, byte_attr, size)
        return out

    def clear_cache(self, *, manifests: bool = False) -> tuple:
        cache = self._neo.cache_dir()
        subs = ["chunks"] + (["manifests"] if manifests else [])
        removed = freed = 0
        for sub in subs:
            d = os.path.join(cache, sub)
            for name in os.listdir(d) if os.path.isdir(d) else []:
                p = os.path.join(d, name)
                try:
                    freed += os.path.getsize(p)
                    os.remove(p)
                    removed += 1
                except OSError:
                    pass
        return removed, freed

    # ---------------------------------------------------------------- launch
    def build_launch_plan(
        self,
        version: str | None = None,
        *,
        extra_args: Iterable[str] | None = None,
        modifiers: dict | None = None,
        proton: str | None = None,
        progress: ProgressFn | None = None,
        log: LogFn | None = None,
        cancel: CancelToken | None = None,
    ) -> LaunchPlan:
        """Do everything up to (not including) spawning the game.

        Same order as the CLI: preflight → prism assets → exchange codes → argv.
        """
        n = self._neo
        cancel = cancel or CancelToken()
        emit = progress or (lambda p: None)
        say = log or (lambda s: None)
        cfg = self.config()

        if not self.auth().logged_in:
            raise NeoError(
                "You need to be signed in to launch.",
                hint="Sign in with Discord from the account panel.",
                kind="auth",
            )

        ver, inst = self._resolve_install(version)
        win64 = os.path.join(inst["path"], "FortniteGame", "Binaries", "Win64")
        if not os.path.isdir(win64):
            raise NeoError(
                "The game binaries are missing from that install.",
                win64,
                "Run Verify & Repair, or reinstall the build.",
                kind="notfound",
            )

        emit(Progress(label="Checking service status"))
        ls = n.lightswitch(self.auth())
        if ls.get("banned"):
            raise NeoError(
                "Your account is banned from the service.",
                str(ls.get("banReason") or ""),
                kind="auth",
            )
        if ls.get("status") != "UP":
            say(f"service status: {ls.get('status')} — {ls.get('message', '')}")
        with contextlib.suppress(Exception):
            ban = n.prism_ban(self.auth())
            if ban.get("banned"):
                raise NeoError(
                    "Your account is banned (Prism).", str(ban.get("reason") or ""), kind="auth"
                )
        cancel.check()

        emit(Progress(label="Updating the patched client"))
        try:
            assets = n.prism_assets(self.auth())
        except Exception as exc:
            raise classify(exc, action="Fetching the patched client") from exc
        prism_dir = os.path.join(n.data_dir(), "prism")
        exe = None
        assets = assets or []
        for i, a in enumerate(assets, 1):
            cancel.check()
            dest = os.path.join(prism_dir, a["filename"])
            emit(
                Progress(
                    label="Updating the patched client",
                    done=i,
                    total=len(assets),
                    unit="files",
                    detail=a["filename"],
                )
            )
            try:
                good = False
                if os.path.exists(dest):
                    h = hashlib.sha256()
                    with open(dest, "rb") as fh:
                        for b in iter(lambda: fh.read(1 << 20), b""):
                            h.update(b)
                    good = h.hexdigest().lower() == a["hash256"].lower()
                if not good:
                    say(f"prism: downloading {a['filename']}")
                    status, raw = n.http("GET", a["url"], timeout=600)
                    if status != 200:
                        raise RuntimeError(f"HTTP {status}")
                    if hashlib.sha256(raw).hexdigest().lower() != a["hash256"].lower():
                        raise RuntimeError("sha256 mismatch")
                    with open(dest + ".tmp", "wb") as fh:
                        fh.write(raw)
                    os.replace(dest + ".tmp", dest)
                if a["filename"] == n.GAME_EXE_NAME:
                    exe = dest
            except Cancelled:
                raise
            except Exception as exc:
                if a["filename"] == n.GAME_EXE_NAME:
                    raise NeoError(
                        "The patched game client could not be downloaded.",
                        f"{a['filename']}: {exc}",
                        "Check your connection and try again; the file is verified by "
                        "SHA-256, so a partial download is rejected on purpose.",
                        kind="network",
                    ) from exc
                say(f"prism asset {a['filename']} failed ({exc}) — continuing")
        if not exe:
            exe = os.path.join(prism_dir, n.GAME_EXE_NAME)
            if not os.path.exists(exe):
                raise NeoError(
                    "NeoFN did not provide the patched game client.",
                    n.GAME_EXE_NAME,
                    "This usually clears up on its own — try again shortly.",
                    kind="network",
                )

        emit(Progress(label="Requesting exchange codes"))
        try:
            code1, exp1 = self.auth().exchange_code()
            code2, _ = self.auth().exchange_code()
        except Exception as exc:
            raise classify(exc, action="Requesting sign-in codes") from exc
        if exp1:
            say(f"exchange codes valid for ~{exp1}s")

        mods = dict(modifiers or {})
        resolved_mods = {
            json_key: bool(mods.get(json_key, cfg.get(cfg_key)))
            for cfg_key, json_key in n.MODIFIER_CONFIG_KEYS
        }
        extra = list(extra_args or [])
        stored = str(cfg.get("launch_options") or "").strip()
        argv_extra = (self.validate_launch_options(stored) if stored else []) + extra

        argv = n.game_argv(
            n.to_winpath(win64), code1, code2, n.fl_token(), argv_extra, modifiers=resolved_mods
        )
        env = dict(os.environ)
        chosen_proton = proton or cfg.get("proton") or ""
        if chosen_proton:
            env["PROTONPATH"] = chosen_proton
        return LaunchPlan(
            version=ver,
            executable=exe,
            working_dir=win64,
            argv=argv,
            env=env,
            umu=os.environ.get("NEO_UMU", "umu-run"),
            proton=chosen_proton,
            wine_prefix=os.environ.get("WINEPREFIX", ""),
        )

    def umu_available(self) -> bool:
        return shutil.which(os.environ.get("NEO_UMU", "umu-run")) is not None

    def run_launch(
        self,
        plan: LaunchPlan,
        *,
        log: LogFn | None = None,
        on_started: Callable[[subprocess.Popen], None] | None = None,
    ) -> int:
        """Spawn the game and stream stderr. Never uses a shell."""
        say = log or (lambda s: None)
        cmd = [plan.umu, plan.executable, *plan.argv]
        if shutil.which(plan.umu) is None and not os.path.isabs(plan.umu):
            raise NeoError(
                f"“{plan.umu}” is not installed.",
                "umu-run was not found on PATH.",
                "Install umu-launcher (Open-Wine-Components/umu-launcher) — it is what "
                "runs the Windows build through Proton.",
                kind="notfound",
            )
        say("Launching " + " ".join(shlex.quote(a) for a in plan.display_command()))
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=plan.working_dir,
                env=plan.env,
                stderr=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as exc:
            raise classify(exc, action="Starting the game") from exc
        if on_started:
            on_started(proc)
        captured = []
        assert proc.stderr is not None
        with proc.stderr:
            for chunk in proc.stderr:
                text = chunk.decode("utf-8", "replace").rstrip("\n")
                captured.append(text)
                say(redact(text))
        rc = proc.wait()
        if rc != 0:
            hint = self._neo.wine_abort_hint("\n".join(captured[-400:]))
            if hint:
                say(hint)
        return rc

    def launch_failure(self, rc: int, tail: str) -> NeoError:
        """Turn a non-zero exit into something a human can act on."""
        hint = self._neo.wine_abort_hint(tail) or ""
        low = (tail or "").lower()
        if not hint:
            if "wineprefix" in low and ("denied" in low or "cannot" in low):
                hint = (
                    "The Wine prefix could not be written. Set WINEPREFIX to a folder "
                    "you own, or clear it to let umu create its own."
                )
            elif "exchange" in low or "auth_password" in low:
                hint = "The sign-in codes expired before the game redeemed them. Launch again."
            elif rc == 127:
                hint = "umu-run could not be executed — check that umu-launcher is installed."
        return NeoError(
            f"The game exited with code {rc}.",
            redact(tail[-4000:]),
            hint,
        )

    # ----------------------------------------------------------------- misc
    def news(self) -> list:
        try:
            payload = self._neo.get_news()
        except Exception as exc:
            raise classify(exc, action="Loading news") from exc
        return [
            NewsItem(date=d, title=t, body=b) for d, t, b in self._neo.format_news(payload) or []
        ]

    def friends(self, *, wait: float = 3.0) -> tuple:
        """(friends, transport). Falls back to REST exactly like `neo friends`."""
        n = self._neo
        if not self.auth().logged_in:
            raise NeoError("Sign in to see your friends.", kind="auth")
        presence, transport, items = {}, "xmpp", []
        sess = None
        try:
            sess = n.XmppSession(self.auth().d["account_id"], self.auth().access())
            sess.connect()
            sess.auth()
            sess.bind()
            items = n.parse_roster(sess.roster())
            presence = sess.presence_snapshot(wait)
        except Exception:
            transport = "http"
            try:
                items = n.friends_http(self.auth())
            except Exception as exc:
                raise classify(exc, action="Loading your friends list") from exc
        finally:
            if sess is not None and getattr(sess, "ws", None):
                with contextlib.suppress(Exception):
                    sess.ws.close()

        ids = [i["jid"].split("@")[0].split("/")[0] for i in items]
        names = {}
        with contextlib.suppress(Exception):
            names = n.resolve_names(self.auth(), ids)
        out = []
        for it in items:
            fid = it["jid"].split("@")[0].split("/")[0]
            pres = next(
                (p for k, p in presence.items() if k.split("@")[0].split("/")[0] == fid), None
            )
            online = bool(pres and pres.get("type") != "unavailable")
            out.append(
                Friend(
                    account_id=fid,
                    name=it.get("name") or names.get(fid) or "",
                    subscription=it.get("subscription") or "",
                    online=online,
                    show=(pres or {}).get("show") or "",
                    status=(pres or {}).get("status") or "",
                )
            )
        out.sort(key=lambda f: (not f.online, f.label.lower()))
        return out, transport

    # ------------------------------------------------------------------ logs
    def game_log_path(self, explicit: str | None = None) -> str | None:
        found = self._neo.find_game_log(explicit)
        if found:
            return found
        # Also look inside umu's default prefix, which the CLI does not know about.
        for pattern in (
            "~/Games/umu/*/pfx/drive_c/users/*/AppData/Local/FortniteGame/Saved/Logs/FortniteGame.log",
            "~/.local/share/umu/*/drive_c/users/*/AppData/Local/FortniteGame/Saved/Logs/FortniteGame.log",
        ):
            hits = glob.glob(os.path.expanduser(pattern))
            if hits:
                return max(hits, key=os.path.getmtime)
        return None

    def read_log(self, path: str, *, max_lines: int = 4000) -> list:
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
        except OSError as exc:
            raise classify(exc, action="Reading the log") from exc
        return [line.rstrip("\n") for line in lines[-max_lines:]]

    def log_is_interesting(self, line: str) -> bool:
        return bool(self._neo.LOG_HIGHLIGHT.search(line))

    # ----------------------------------------------------------- diagnostics
    def environment(self) -> dict:
        n = self._neo
        wayland = bool(os.environ.get("WAYLAND_DISPLAY"))
        env = {
            "neo version": self.version,
            "neo path": str(getattr(n, "__file__", "?")),
            "python": platform.python_version(),
            "system": f"{platform.system()} {platform.release()}",
            "machine": platform.machine(),
            "distro": self._distro(),
            "desktop": os.environ.get("XDG_CURRENT_DESKTOP") or "unknown",
            "session type": os.environ.get("XDG_SESSION_TYPE")
            or ("wayland" if wayland else "x11"),
            "display server": "Wayland" if wayland else ("X11" if os.environ.get("DISPLAY") else "none"),
            "data dir": n.data_dir(),
            "cache dir": n.cache_dir(),
            "config file": n.config_path(),
            "umu-run": shutil.which(os.environ.get("NEO_UMU", "umu-run")) or "not found",
            "WINEPREFIX": os.environ.get("WINEPREFIX") or "(unset — umu picks its own)",
            "PROTONPATH": os.environ.get("PROTONPATH") or "(unset)",
        }
        return env

    def _distro(self) -> str:
        try:
            with open("/etc/os-release") as fh:
                data = dict(
                    line.strip().split("=", 1)
                    for line in fh
                    if "=" in line and not line.startswith("#")
                )
            return data.get("PRETTY_NAME", "").strip('"') or data.get("NAME", "").strip('"')
        except OSError:
            return "unknown"

    def diagnostics_report(self, *, extra_sections: dict | None = None) -> str:
        """A paste-ready report. Everything token-shaped is redacted."""
        lines = [
            "# Neo diagnostics",
            f"generated {datetime.now().astimezone().isoformat(timespec='seconds')}",
            "",
            "## Environment",
        ]
        for k, v in self.environment().items():
            lines.append(f"{k:<16} {v}")

        lines += ["", "## Account"]
        s = self.session()
        lines.append(f"signed in       {'yes' if s.logged_in else 'no'}")
        if s.logged_in:
            lines.append(f"display name    {s.display_name or '(none set)'}")
            lines.append(f"account id      {s.account_id}")
            lines.append("tokens          present (not included in this report)")

        lines += ["", "## Settings"]
        for k, v in sorted(self.config().items()):
            lines.append(f"{k:<20} {v}")

        lines += ["", "## Installs"]
        rows = self.installs()
        if not rows:
            lines.append("(none)")
        for inst in rows:
            flags = []
            if inst.imported:
                flags.append("imported")
            if not inst.exists:
                flags.append("MISSING FROM DISK")
            elif not inst.playable:
                flags.append("no Win64 binaries")
            lines.append(f"{inst.version}  {inst.path}  {' '.join(flags)}")

        cache = self.cache_stats()
        lines += [
            "",
            "## Cache",
            f"chunks     {cache.chunk_files} files, {self.human(cache.chunk_bytes)}",
            f"manifests  {cache.manifest_files} files, {self.human(cache.manifest_bytes)}",
            f"path       {cache.path}",
        ]

        for title, body in (extra_sections or {}).items():
            lines += ["", f"## {title}", body.strip()]
        return redact("\n".join(lines)) + "\n"


def find_wine_prefixes() -> list:
    """Candidate Wine prefixes, for the prefix picker. Best-effort, never raises."""
    out = []
    seen = set()
    candidates = [os.environ.get("WINEPREFIX", "")]
    candidates += glob.glob(os.path.expanduser("~/Games/umu/*"))
    candidates += glob.glob(os.path.expanduser("~/.local/share/umu/*"))
    candidates += [os.path.expanduser("~/.wine")]
    for c in candidates:
        if not c:
            continue
        p = Path(c)
        if (p / "drive_c").is_dir() and str(p) not in seen:
            seen.add(str(p))
            out.append(str(p))
    return out
