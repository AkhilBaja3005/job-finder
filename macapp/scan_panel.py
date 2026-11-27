"""
The logic behind the Job Finder Mac app: a control panel for the job scanner and the auto-apply agent.

The app never re-implements scanning. It builds a `job-finder scan ...` command from the form, runs it as a child
process, and shows the output and the tracker. Everything here works without a window, so it can be tested.
"""
from __future__ import annotations

import csv
import functools
import json
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from collections import deque
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional

import platform_support

APP_NAME = "Job Finder"
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07")
PROGRESS_RE = re.compile(r"\[(\d+)/(\d+)\]")

API_KEYS = {"gemini": "GEMINI_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}
PROVIDER_ORDERS = {
    "auto": None,
    "gemini": "gemini,anthropic,openai",
    "anthropic": "anthropic,gemini,openai",
    "openai": "openai,gemini,anthropic",
}


# ── folders ──────────────────────────────────────────────────────────────────────
def app_support_dir() -> Path:
    override = os.environ.get("JOB_FINDER_APP_HOME")
    return Path(override) if override else platform_support.app_support_dir(APP_NAME)


def load_app_config() -> Dict[str, Any]:
    try:
        return json.loads((app_support_dir() / "app.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_app_config(config: Dict[str, Any]) -> None:
    home = app_support_dir()
    home.mkdir(parents=True, exist_ok=True)
    (home / "app.json").write_text(json.dumps(config, indent=2), encoding="utf-8")


def logs_dir() -> Path:
    """Where the app and each run write their logs: ~/Library/Logs/Job Finder (inside the app folder when that is overridden)."""
    override = os.environ.get("JOB_FINDER_APP_HOME")
    return Path(override) / "logs" if override else platform_support.logs_base(APP_NAME)


APP_PREF_KEYS = ("primary_ai", "headless", "tour_done")


def load_app_prefs() -> Dict[str, Any]:
    cfg = load_app_config()
    return {"primary_ai": cfg.get("primary_ai", "auto"), "headless": bool(cfg.get("headless", False)),
            "tour_done": bool(cfg.get("tour_done")) or os.environ.get("JOB_FINDER_APP_SELFTEST") == "1"}


def workspace_dir() -> Path:
    """Where the profile, .env, tracker and outputs live. Defaults to the app's own folder; can point at an existing
    Job Finder folder, for example the one the command line tool already uses."""
    chosen = load_app_config().get("workspace")
    if chosen and Path(chosen).is_dir():
        return Path(chosen)
    return app_support_dir()


# ── profile and preferences ─────────────────────────────────────────────────────
def profile_path(ws: Path) -> Path:
    nested = ws / "backend" / "config" / "candidate_profile.json"
    return nested if nested.exists() else ws / "candidate_profile.json"


def _split(text: Any) -> List[str]:
    if isinstance(text, list):
        return [str(t).strip() for t in text if str(t).strip()]
    return [t.strip() for t in re.split(r"[,\n]", str(text or "")) if t.strip()]


def read_preferences(ws: Path) -> Dict[str, Any]:
    path = profile_path(ws)
    data: Dict[str, Any] = {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    prefs = data.get("search_preferences") or {}
    candidate = data.get("candidate") or {}
    locations = _split(prefs.get("target_locations"))
    return {
        "profile_exists": bool(data),
        "profile_path": str(path),
        "candidate_name": candidate.get("name") or "",
        "roles": _split(prefs.get("target_roles")),
        "location": locations[0] if locations else "",
        "timeframe": str(prefs.get("timeframe") or "24h"),
        "min_ats": prefs.get("min_ats_score_threshold", 65),
        "title_keywords": _split(prefs.get("required_title_keywords")),
        "skip_portals": _split(prefs.get("skip_portals")),
    }


def write_preferences(ws: Path, form: Dict[str, Any]) -> None:
    """Saves the scan settings into the profile's search_preferences, leaving everything else in the file as it is."""
    path = profile_path(ws)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    prefs = data.setdefault("search_preferences", {})
    roles = _split(form.get("roles"))
    if roles:
        prefs["target_roles"] = roles
    location = str(form.get("location") or "").strip()
    if location:
        rest = [loc for loc in _split(prefs.get("target_locations"))[1:]]
        prefs["target_locations"] = [location] + rest
    if form.get("timeframe"):
        prefs["timeframe"] = str(form["timeframe"])
    try:
        prefs["min_ats_score_threshold"] = int(form.get("min_ats"))
    except (TypeError, ValueError):
        pass
    prefs["required_title_keywords"] = _split(form.get("title_keywords"))
    prefs["skip_portals"] = _split(form.get("skip_portals"))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)


# ── .env ─────────────────────────────────────────────────────────────────────────
def read_env(ws: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    try:
        for line in (ws / ".env").read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip().strip("\"'")
    except OSError:
        pass
    return values


def write_env_value(ws: Path, key: str, value: str) -> None:
    path = ws / ".env"
    lines: List[str] = []
    if path.exists():
        lines = [ln for ln in path.read_text(encoding="utf-8").splitlines(keepends=True) if not re.match(rf"\s*{re.escape(key)}\s*=", ln)]
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    lines.append(f'{key}="{value}"\n')
    ws.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(lines), encoding="utf-8")
    os.chmod(path, 0o600)


def key_status(ws: Path) -> Dict[str, Dict[str, Any]]:
    env = read_env(ws)
    status = {}
    for name, var in API_KEYS.items():
        value = env.get(var, "")
        status[name] = {"set": bool(value), "hint": value[-4:] if len(value) > 8 else ""}
    return status


# ── the scan command ─────────────────────────────────────────────────────────────
def build_scan_args(options: Dict[str, Any]) -> List[str]:
    """The arguments after `job-finder` for one run. Always says explicitly whether to submit."""
    args = ["scan", "--auto-apply" if options.get("mode") == "auto_apply" else "--dry-run"]
    for flag, key in (("--limit", "limit"), ("--min-ats", "min_ats")):
        try:
            value = int(options.get(key))
            if key == "min_ats" or value > 0:
                args += [flag, str(value)]
        except (TypeError, ValueError):
            pass
    for flag, key in (("--timeframe", "timeframe"), ("--location", "location")):
        if str(options.get(key) or "").strip():
            args += [flag, str(options[key]).strip()]
    skip = ",".join(_split(options.get("skip_portals")))
    if skip:
        args += ["--skip-portals", skip]
    if options.get("headless"):
        args.append("--headless")
    return args


def build_run_env(options: Dict[str, Any], workspace: Path, base: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    env = dict(base if base is not None else os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    env["JOB_FINDER_ROOT"] = str(workspace)
    order = PROVIDER_ORDERS.get(str(options.get("primary_ai") or "auto"))
    if order:
        env["BROWSER_USE_PROVIDERS"] = order
    return env


def count_progress(lines: List[str]) -> Dict[str, int]:
    """Totals shown above the log, read from the scanner's own messages."""
    counts = {"found": 0, "position": 0, "submitted": 0, "needs_review": 0, "skipped": 0}
    for line in lines:
        m = PROGRESS_RE.search(line)
        if m:
            counts["position"], counts["found"] = int(m.group(1)), int(m.group(2))
        if "verified & submitted successfully" in line:
            counts["submitted"] += 1
        elif "Submission verification failed" in line:
            counts["needs_review"] += 1
        elif "Skipping" in line:
            counts["skipped"] += 1
    return counts


# ── the page scraper's browser ───────────────────────────────────────────────────
def browsers_dir() -> Path:
    return Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or app_support_dir() / "browsers")


def browser_ready() -> bool:
    """True once Playwright has finished installing its Chromium. It writes INSTALLATION_COMPLETE in each finished folder."""
    root = browsers_dir()
    return any(root.glob("chromium*/INSTALLATION_COMPLETE")) if root.is_dir() else False


# ── running a scan ───────────────────────────────────────────────────────────────
class ScanRunner:
    """One child process at a time, with its output kept in memory for the window to read."""

    def __init__(self, launcher: List[str]):
        self._launcher = launcher
        self._lines: Deque[str] = deque(maxlen=5000)
        self._dropped = 0
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._exit_code: Optional[int] = None
        self._title = ""
        self._logfile: Any = None

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self, args: List[str], env: Dict[str, str], cwd: Path, title: str = "scan") -> Dict[str, Any]:
        with self._lock:
            if self.running:
                return {"ok": False, "error": "A run is already in progress."}
            self._lines.clear()
            self._dropped = 0
            self._exit_code = None
            self._title = title
            try:
                directory = logs_dir()
                directory.mkdir(parents=True, exist_ok=True)
                prune_logs(directory)
                self._logfile = open(directory / f"scan-{time.strftime('%Y%m%d-%H%M%S')}-{title}.log", "w", encoding="utf-8")
            except OSError:
                self._logfile = None
            try:
                group = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW} if platform_support.IS_WINDOWS else {"start_new_session": True}
                self._proc = subprocess.Popen(
                    self._launcher + args, cwd=str(cwd), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1, errors="replace", **group,
                )
            except OSError as exc:
                return {"ok": False, "error": f"Could not start: {exc}"}
            threading.Thread(target=self._pump, args=(self._proc,), daemon=True).start()
        return {"ok": True}

    def _pump(self, proc: subprocess.Popen) -> None:
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = ANSI_RE.sub("", raw.rstrip("\n")).replace("\r", "")
            if line.strip():
                if self._logfile:
                    try:
                        self._logfile.write(line + "\n")
                        self._logfile.flush()
                    except (OSError, ValueError):
                        pass
                with self._lock:
                    if len(self._lines) == self._lines.maxlen:
                        self._dropped += 1
                    self._lines.append(line)
        self._exit_code = proc.wait()
        if self._logfile:
            try:
                self._logfile.close()
            except OSError:
                pass

    def add_line(self, text: str) -> None:
        with self._lock:
            self._lines.append(text)

    def stop(self) -> Dict[str, Any]:
        proc = self._proc
        if proc is None or proc.poll() is not None:
            return {"ok": True, "message": "Nothing is running."}
        try:
            if platform_support.IS_WINDOWS:  # kills the process and everything it started
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], check=False, capture_output=True)
            else:
                os.killpg(proc.pid, signal.SIGTERM)
                for _ in range(50):
                    if proc.poll() is not None:
                        break
                    time.sleep(0.1)
                if proc.poll() is None:
                    os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        with self._lock:
            self._lines.append("— Stopped. The browser window the agent opened stays open; close it when you are done. —")
        return {"ok": True}

    def poll(self, offset: int = 0) -> Dict[str, Any]:
        with self._lock:
            lines = list(self._lines)
            dropped = self._dropped
        start = max(0, offset - dropped)
        return {
            "lines": lines[start:], "next": dropped + len(lines), "running": self.running,
            "exit_code": self._exit_code, "counts": count_progress(lines), "title": self._title,
        }


# ── profile: what is missing, and importing a ready-made file ───────────────────
# (section, field, label, why it matters, needed for a good first run)
PROFILE_FIELDS = (
    ("candidate", "name", "Full name", "Goes on every application.", True),
    ("candidate", "email", "Email", "Used for the application and the confirmation email.", True),
    ("candidate", "phone", "Phone", "Most forms require it.", True),
    ("candidate", "location", "Location", "City and country. Forms ask where you live.", True),
    ("candidate", "work_authorization", "Work authorisation", "Right-to-work questions are on almost every form. The agent will not guess.", True),
    ("candidate", "requires_sponsorship", "Needs visa sponsorship", "Yes or no. Asked on most forms.", True),
    ("candidate", "experience_summary", "Short summary", "Used for cover letters and 'tell us about yourself' boxes.", True),
    ("candidate", "work_experience", "Work experience", "Roles, companies and dates.", True),
    ("candidate", "education", "Education", "Degrees, schools and dates.", True),
    ("candidate", "core_skills", "Skills", "Used to score jobs and fill skill boxes.", True),
    ("candidate", "linkedin", "LinkedIn link", "Many forms have a LinkedIn field.", False),
    ("candidate", "github", "GitHub link", "Asked on engineering roles.", False),
    ("search_preferences", "target_roles", "Roles to search", "What the scan looks for. You can also set it on the Run page.", True),
    ("search_preferences", "target_locations", "Locations to search", "Where the scan looks.", True),
)


def _filled(value: Any) -> bool:
    if isinstance(value, bool):
        return True  # False is a real answer for "needs sponsorship"
    if isinstance(value, (list, dict, str)):
        return bool(value) and not (isinstance(value, str) and not value.strip())
    return value is not None


def profile_check(ws: Path) -> Dict[str, Any]:
    """Which profile fields are still empty. Needed ones first."""
    try:
        data = json.loads(profile_path(ws).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"exists": False, "missing": [], "filled": 0, "total": len(PROFILE_FIELDS)}
    missing = []
    for section, field, label, why, needed in PROFILE_FIELDS:
        if not _filled((data.get(section) or {}).get(field)):
            missing.append({"section": section, "field": field, "label": label, "why": why, "needed": needed})
    missing.sort(key=lambda m: not m["needed"])
    return {"exists": True, "missing": missing, "filled": len(PROFILE_FIELDS) - len(missing), "total": len(PROFILE_FIELDS)}


def import_profile_file(ws: Path, source: Path) -> Dict[str, Any]:
    """Copies a candidate_profile.json into the folder. Checks it first and keeps the old one as a backup."""
    try:
        if source.stat().st_size > 2_000_000:
            return {"ok": False, "error": "That file is too large to be a profile."}
        data = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"ok": False, "error": "That file is not valid JSON."}
    if not isinstance(data, dict) or not isinstance(data.get("candidate"), dict):
        return {"ok": False, "error": "This does not look like a Job Finder profile. It needs a \"candidate\" section."}
    if not isinstance(data.get("search_preferences", {}), dict):
        return {"ok": False, "error": "The \"search_preferences\" section must be an object."}
    target = profile_path(ws)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.copy2(target, target.with_name(target.name + ".bak"))
    target.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(target, 0o600)
    except OSError:
        pass
    return {"ok": True, "name": str((data.get("candidate") or {}).get("name") or ""), "check": profile_check(ws)}


# ── job-finder.space (sync code) ─────────────────────────────────────────────────
DEFAULT_SERVER = "https://abaja-job-finder.hf.space"
SYNC_CODE_VAR = "JOB_FINDER_SYNC_CODE"
_cloud_cache: Dict[str, Any] = {}


def server_url(ws: Path) -> str:
    url = (read_env(ws).get("JOB_FINDER_SERVER_URL") or DEFAULT_SERVER).rstrip("/")
    parsed = urllib.parse.urlparse(url)
    local = parsed.hostname in ("localhost", "127.0.0.1")
    return url if parsed.scheme == "https" or (parsed.scheme == "http" and local) else DEFAULT_SERVER  # never send the code in clear text


def sync_code(ws: Path) -> str:
    return read_env(ws).get(SYNC_CODE_VAR, "").strip().upper()


def _server_request(ws: Path, code: str, path: str, method: str = "GET", body: Any = None, timeout: float = 20.0) -> Any:
    request = urllib.request.Request(
        server_url(ws) + path, method=method, data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {code}", "Content-Type": "application/json", "User-Agent": "Job-Finder-App"},
    )
    with urllib.request.urlopen(request, timeout=timeout, context=_ssl_context()) as resp:
        raw = resp.read()
    return json.loads(raw) if raw else None


def _explain(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code == 401:
            return "That sync code was not recognised."
        if exc.code == 429:
            return "Too many attempts. Wait a few minutes and try again."
        return f"The server answered with an error ({exc.code})."
    return "Could not reach job-finder.space. Check your connection."


def cloud_status(ws: Path, fresh: bool = False) -> Dict[str, Any]:
    """Whether a sync code is saved and still accepted. The answer is kept for a minute so the window stays quick."""
    code = sync_code(ws)
    if not code:
        return {"configured": False, "connected": False}
    cached = _cloud_cache.get("status")
    if cached and not fresh and cached[0] == (code, server_url(ws)) and time.time() - cached[1] < 60:
        return cached[2]
    try:
        me = _server_request(ws, code, "/user/me", timeout=8) or {}
        result = {"configured": True, "connected": True, "email": str(me.get("email") or "")}
    except Exception as exc:
        result = {"configured": True, "connected": False, "error": _explain(exc)}
    _cloud_cache["status"] = ((code, server_url(ws)), time.time(), result)
    return result


def save_sync_code(ws: Path, raw: str) -> Dict[str, Any]:
    code = re.sub(r"[^A-Za-z0-9]", "", raw or "").upper()
    if not 4 <= len(code) <= 16:
        return {"ok": False, "error": "A sync code is 6 to 10 letters and numbers. Find it on job-finder.space under your account."}
    try:
        me = _server_request(ws, code, "/user/me", timeout=10) or {}
    except Exception as exc:
        return {"ok": False, "error": _explain(exc)}
    write_env_value(ws, SYNC_CODE_VAR, code)
    _cloud_cache.clear()
    return {"ok": True, "email": str(me.get("email") or "")}


def disconnect_sync(ws: Path) -> Dict[str, Any]:
    write_env_value(ws, SYNC_CODE_VAR, "")
    _cloud_cache.clear()
    return {"ok": True}


def sync_to_cloud(ws: Path) -> Dict[str, Any]:
    """Uploads the applications in the local tracker to the account. The server skips URLs it already has."""
    code = sync_code(ws)
    if not code:
        return {"ok": False, "error": "Add your sync code in Settings first."}
    rows, seen = [], set()
    for row in _csv_all(ws):
        url = (row.get("Job URL") or "").strip()
        if len(url) < 8 or url in seen:
            continue
        seen.add(url)
        try:
            score = int(re.sub(r"[^0-9]", "", row.get("Overall ATS") or "") or 0)
        except ValueError:
            score = 0
        rows.append({"job_title": (row.get("Job Title") or "Role")[:300], "company": (row.get("Company") or "Company")[:300], "job_url": url[:2000],
                     "score": min(score, 100), "status": (row.get("Status") or "saved")[:60], "source_mode": (row.get("Platform") or "desktop")[:60]})
    added = already = 0
    try:
        for i in range(0, len(rows), 200):
            out = _server_request(ws, code, "/applications/sync", "POST", {"applications": rows[i:i + 200]}, timeout=60) or {}
            added += int(out.get("added", 0))
            already += int(out.get("already", 0))
    except Exception as exc:
        return {"ok": False, "error": _explain(exc), "pushed": added}
    return {"ok": True, "pushed": added, "already": already}


# ── updates, Chrome, notifications ───────────────────────────────────────────────
RELEASES_URL = "https://api.github.com/repos/AkhilBaja3005/job-finder/releases/latest"


def _ssl_context():
    """A built Mac app has no system certificate list of its own, so use the one that ships with certifi."""
    import ssl
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _version_tuple(text: str) -> tuple:
    return tuple(int(n) for n in re.findall(r"\d+", text)[:3])


def check_for_update(current: str, fetch: Any = None) -> Dict[str, Any]:
    """Asks GitHub for the latest release. Sends nothing about you; it is a plain request for a public page."""
    try:
        if fetch is None:
            request = urllib.request.Request(RELEASES_URL, headers={"Accept": "application/vnd.github+json", "User-Agent": "Job-Finder-App"})
            with urllib.request.urlopen(request, timeout=6, context=_ssl_context()) as resp:
                data = json.load(resp)
        else:
            data = fetch()
        latest = str(data.get("tag_name", "")).lstrip("v")
        return {"ok": True, "current": current, "latest": latest, "newer": bool(latest) and _version_tuple(latest) > _version_tuple(current),
                "url": data.get("html_url") or "https://github.com/AkhilBaja3005/job-finder/releases"}
    except Exception as exc:
        return {"ok": False, "error": "Could not check for updates: " + str(exc)[:80]}


def chrome_found() -> bool:
    return platform_support.chrome_found()


def notify(title: str, message: str) -> None:
    """A system notification where the platform makes it easy. Failure is ignored: it is a nicety."""
    platform_support.notify(title, message)


def prune_logs(directory: Path, keep: int = 25) -> None:
    files = sorted(directory.glob("scan-*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[keep:]:
        try:
            old.unlink()
        except OSError:
            pass


# ── Supabase (optional) ──────────────────────────────────────────────────────────
def supabase_settings(ws: Path) -> Optional[Dict[str, str]]:
    """The project URL and key from the .env, or None when Supabase is not set up. The secret key wins if both exist."""
    env = read_env(ws)
    url = env.get("SUPABASE_URL", "").rstrip("/")
    key = env.get("SUPABASE_SERVICE_KEY") or env.get("SUPABASE_SECRET_KEY") or env.get("SUPABASE_KEY", "")
    return {"url": url, "key": key} if url and key else None


def _supabase_request(cfg: Dict[str, str], path: str, method: str = "GET", body: Any = None, headers: Optional[Dict[str, str]] = None, timeout: float = 20.0) -> Any:
    request = urllib.request.Request(
        f"{cfg['url']}/rest/v1/{path}", method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"apikey": cfg["key"], "Authorization": f"Bearer {cfg['key']}", "Content-Type": "application/json", **(headers or {})},
    )
    with urllib.request.urlopen(request, timeout=timeout, context=_ssl_context()) as resp:
        raw = resp.read()
    return json.loads(raw) if raw else None


def cloud_user_id(ws: Path) -> int:
    """The account id the scanner records applications under (the same rule the scanner uses)."""
    try:
        data = json.loads(profile_path(ws).read_text(encoding="utf-8"))
        return int((data.get("candidate") or {}).get("user_id") or 34)
    except (OSError, ValueError, TypeError):
        return 34


def supabase_status(ws: Path) -> Dict[str, Any]:
    cfg = supabase_settings(ws)
    if not cfg:
        return {"configured": False, "reachable": False}
    try:
        _supabase_request(cfg, f"applications?select=id&limit=1&user_id=eq.{cloud_user_id(ws)}", timeout=6)
        return {"configured": True, "reachable": True, "host": urllib.parse.urlparse(cfg["url"]).hostname or ""}
    except urllib.error.HTTPError as exc:
        host = urllib.parse.urlparse(cfg["url"]).hostname or ""
        if exc.code in (401, 403):  # the project answered but will not let this key read the table
            return {"configured": True, "reachable": False, "host": host, "denied": True,
                    "error": "The project is locked and this key is not allowed to read it. Use the secret key (SUPABASE_SERVICE_KEY) in the .env, or connect with a sync code below instead."}
        return {"configured": True, "reachable": False, "host": host, "error": f"The project answered with an error ({exc.code})."}
    except Exception as exc:
        return {"configured": True, "reachable": False, "host": urllib.parse.urlparse(cfg["url"]).hostname or "", "error": str(exc)[:120]}


def read_cloud_applications(ws: Path, limit: int = 300) -> List[Dict[str, str]]:
    cfg = supabase_settings(ws)
    if not cfg:
        return []
    rows = _supabase_request(
        cfg, f"applications?select=job_title,company,job_url,score,status,source_mode&user_id=eq.{cloud_user_id(ws)}&order=id.desc&limit={limit}",
    ) or []
    return [{
        "company": r.get("company") or "", "title": r.get("job_title") or "", "status": r.get("status") or "",
        "ats": f"{r['score']}%" if r.get("score") not in (None, "") else "", "platform": r.get("source_mode") or "", "url": r.get("job_url") or "",
    } for r in rows]


def read_account_applications(ws: Path, limit: int = 20000) -> List[Dict[str, str]]:
    """The applications saved to the job-finder.space account behind the sync code (website, extension and other computers).
    The answer is kept for 30 seconds so switching screens does not ask the server every time."""
    code = sync_code(ws)
    if not code:
        return []
    key = (code, server_url(ws))
    cached = _cloud_cache.get("applications")
    if cached and cached[0] == key and time.time() - cached[1] < 30:
        return cached[2]
    try:
        data = _server_request(ws, code, "/applications", timeout=30) or {}
    except Exception:
        log.debug("could not read the account's applications", exc_info=True)
        return cached[2] if cached and cached[0] == key else []
    rows = []
    for r in (data.get("applications") or [])[:limit]:
        if not isinstance(r, dict) or not r.get("job_url"):
            continue
        score = r.get("score")
        rows.append({
            "company": r.get("company") or "", "title": r.get("job_title") or "", "status": r.get("status") or "",
            "ats": f"{score}%" if score not in (None, "") else "", "platform": r.get("source_mode") or "", "url": r.get("job_url") or "",
        })
    _cloud_cache["applications"] = (key, time.time(), rows)
    return rows


def _cloud_urls(cfg: Dict[str, str], user_id: int) -> set:
    """Every job URL already stored for this account (paged, because the server caps one response)."""
    urls: set = set()
    start, page = 0, 1000
    while True:
        rows = _supabase_request(
            cfg, f"applications?select=job_url&user_id=eq.{user_id}&order=id.asc", headers={"Range-Unit": "items", "Range": f"{start}-{start + page - 1}"},
        ) or []
        urls.update(r.get("job_url") for r in rows if r.get("job_url"))
        if len(rows) < page:
            return urls
        start += page


def _csv_all(ws: Path) -> List[Dict[str, str]]:
    path = ws / "applications_tracker" / "job_applications_tracker.csv"
    try:
        with path.open(newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except OSError:
        return []


def sync_missing_to_supabase(ws: Path) -> Dict[str, Any]:
    """Adds the applications that are in the local tracker but not yet in the Supabase project. Never changes or deletes rows."""
    cfg = supabase_settings(ws)
    if not cfg:
        return {"ok": False, "error": "Supabase is not set up in this folder's .env."}
    user_id = cloud_user_id(ws)
    try:
        known = _cloud_urls(cfg, user_id)
        missing, seen = [], set()
        for row in _csv_all(ws):
            url = (row.get("Job URL") or "").strip()
            if not url or url in known or url in seen:
                continue
            seen.add(url)
            try:
                score = int(re.sub(r"[^0-9]", "", row.get("Overall ATS") or "") or 0)
            except ValueError:
                score = 0
            missing.append({"user_id": user_id, "job_title": row.get("Job Title") or "Role", "company": row.get("Company") or "Company",
                            "job_url": url, "score": score, "status": row.get("Status") or "saved", "source_mode": row.get("Platform") or "scanner"})
        for i in range(0, len(missing), 50):
            _supabase_request(cfg, "applications", "POST", missing[i:i + 50], headers={"Prefer": "return=minimal"})
        return {"ok": True, "pushed": len(missing), "already": len(known)}
    except Exception as exc:
        return {"ok": False, "error": f"Sync failed: {str(exc)[:160]}"}


def merge_results(local: List[Dict[str, str]], cloud: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    """One list for the Results table. A job in both shows the cloud status; `synced` says which rows are in the project."""
    cloud_by_url = {r["url"]: r for r in cloud if r.get("url")}
    out: List[Dict[str, Any]] = []
    seen = set()
    for row in local:
        url = row.get("url", "")
        match = cloud_by_url.get(url)
        out.append({**row, "status": (match or row).get("status", ""), "synced": bool(match)})
        seen.add(url)
    for row in cloud:
        if row.get("url") not in seen:
            out.append({**row, "synced": True})
    return out


# ── results ──────────────────────────────────────────────────────────────────────
def read_tracker(ws: Path, limit: int = 20000) -> List[Dict[str, str]]:
    path = ws / "applications_tracker" / "job_applications_tracker.csv"
    try:
        with path.open(newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    except OSError:
        return []
    out = []
    for row in reversed(rows[-limit:]):
        out.append({
            "company": row.get("Company", ""), "title": row.get("Job Title", ""), "status": row.get("Status", ""),
            "ats": row.get("Overall ATS", ""), "platform": row.get("Platform", ""), "url": row.get("Job URL", ""),
        })
    return out


def usage_today_for(ws: Path) -> Dict[str, Any]:
    try:
        from applications_tracker.outcomes import usage_today
        return usage_today(str(ws))
    except Exception:
        return {"tokens": 0, "cost": 0}


# ── moving an application along: submitted by hand, reply, interview ────────────
STAGES = {
    "applied": "Applied (manual)", "replied": "Replied", "interview": "Interview", "offer": "Offer",
    "rejected": "Rejected", "skipped": "Skipped",
}


def set_application_stage(ws: Path, url: str, stage: str) -> Dict[str, Any]:
    """Changes the Status of the tracker row with this job URL. Only the Status cell is touched; the file is replaced in one step."""
    label = STAGES.get(stage)
    if not label:
        return {"ok": False, "error": "Unknown status."}
    path = ws / "applications_tracker" / "job_applications_tracker.csv"
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fields = list(reader.fieldnames or [])
            rows = list(reader)
    except OSError:
        return {"ok": False, "error": "The tracker file was not found."}
    if "Status" not in fields or "Job URL" not in fields:
        return {"ok": False, "error": "The tracker file has no Status column."}
    changed = 0
    for row in rows:
        if (row.get("Job URL") or "").strip() == url.strip():
            row["Status"] = label
            changed += 1
    if not changed:
        return {"ok": False, "error": "That application is not in the tracker."}
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp, path)
    cfg = supabase_settings(ws)
    if cfg:  # best effort: the local file is the record, so a failure here is not an error
        try:
            quoted = urllib.parse.quote(url.strip(), safe="")
            _supabase_request(cfg, f"applications?user_id=eq.{cloud_user_id(ws)}&job_url=eq.{quoted}", "PATCH", {"status": label}, headers={"Prefer": "return=minimal"}, timeout=8)
        except Exception:
            log.debug("could not update the status in Supabase", exc_info=True)
    code = sync_code(ws)
    if code:  # best effort: the account on job-finder.space follows along
        try:
            _server_request(ws, code, "/applications/status", "POST", {"job_url": url.strip(), "status": label}, timeout=8)
        except Exception:
            log.debug("could not update the status on job-finder.space", exc_info=True)
    return {"ok": True, "status": label}


def stage_counts(rows: List[Dict[str, str]]) -> Dict[str, int]:
    counts = {k: 0 for k in STAGES}
    for row in rows:
        status = (row.get("status") or row.get("Status") or "").lower()
        for key, label in STAGES.items():
            if status == label.lower():
                counts[key] += 1
    return counts


def last_attempt(ws: Path, url: str) -> Dict[str, Any]:
    """The most recent line in the run ledger for this job: why it stopped, and the final screenshot if there is one."""
    try:
        from applications_tracker.outcomes import read_outcomes
    except Exception:
        return {}
    for row in reversed(read_outcomes(str(ws))):
        if (row.get("url") or "").strip() == url.strip():
            shot = str(row.get("screenshot") or "")
            inside = bool(shot) and Path(shot).resolve().is_relative_to(ws.resolve()) and Path(shot).is_file()
            return {"reason": str(row.get("final_result") or row.get("reason") or ""), "outcome": row.get("outcome", ""), "screenshot": shot if inside else ""}
    return {}


# ── replies from employers (opt-in mailbox check) ───────────────────────────────
MAILBOX_VARS = ("REPLY_IMAP_USER", "REPLY_IMAP_PASSWORD", "REPLY_IMAP_HOST")


def mailbox_status(ws: Path) -> Dict[str, Any]:
    env = read_env(ws)
    return {"configured": bool(env.get("REPLY_IMAP_USER") and env.get("REPLY_IMAP_PASSWORD")), "user": env.get("REPLY_IMAP_USER", "")}


def save_mailbox(ws: Path, user: str, password: str, host: str = "") -> Dict[str, Any]:
    """Checks that the mailbox login works, then keeps it in the .env. The password never leaves this Mac except to log in."""
    import imaplib
    user, password, host = (user or "").strip(), re.sub(r"\s+", "", password or ""), (host or "").strip() or "imap.gmail.com"
    if "@" not in user or len(password) < 8:
        return {"ok": False, "error": "Enter your email address and an app password (not your normal password)."}
    try:
        conn = imaplib.IMAP4_SSL(host, timeout=20)
        conn.login(user, password)
        conn.logout()
    except imaplib.IMAP4.error:
        return {"ok": False, "error": "The mailbox refused the login. For Gmail, create an app password (Google account, Security, 2-Step Verification, App passwords)."}
    except Exception as exc:
        return {"ok": False, "error": f"Could not reach {host}: {str(exc)[:80]}"}
    write_env_value(ws, "REPLY_IMAP_USER", user)
    write_env_value(ws, "REPLY_IMAP_PASSWORD", password)
    write_env_value(ws, "REPLY_IMAP_HOST", host)
    return {"ok": True}


def disconnect_mailbox(ws: Path) -> Dict[str, Any]:
    for var in MAILBOX_VARS:
        write_env_value(ws, var, "")
    return {"ok": True}


def check_replies(ws: Path) -> Dict[str, Any]:
    """Reads the last 30 days of the inbox, and moves matching applications to Replied, Interview, Rejected or Offer."""
    env = read_env(ws)
    user, password = env.get("REPLY_IMAP_USER", ""), env.get("REPLY_IMAP_PASSWORD", "")
    if not (user and password):
        return {"ok": False, "error": "Connect a mailbox in Settings first."}
    try:
        from applications_tracker.replies import fetch_messages, find_updates
        messages = fetch_messages(env.get("REPLY_IMAP_HOST") or "imap.gmail.com", user, password)
        changes = find_updates(read_tracker(ws, 5000), messages)
    except Exception as exc:
        return {"ok": False, "error": f"Could not read the mailbox: {str(exc)[:100]}"}
    applied = [c for c in changes if set_application_stage(ws, c["url"], c["stage"]).get("ok")]
    return {"ok": True, "checked": len(messages), "updated": len(applied), "changes": [{"company": c["company"], "stage": c["stage"]} for c in applied]}


# ── problem report (nothing is sent; the user copies it into an email) ──────────
_SECRET_RE = re.compile(r"(sk-[A-Za-z0-9_\-]{8,}|AIza[0-9A-Za-z_\-]{20,}|sb_(?:secret|publishable)_[A-Za-z0-9_\-]{8,}|eyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,})")


def redact(text: str) -> str:
    """Removes API keys, tokens and the user's home folder from text that is about to be shared."""
    text = _SECRET_RE.sub("[removed]", text)
    return text.replace(str(Path.home()), "~")


def diagnostics_report(ws: Path) -> str:
    import platform
    lines = [f"Job Finder {_app_version()}", f"macOS {platform.mac_ver()[0]} {platform.machine()}",
             f"Chrome found: {chrome_found()}", f"Scraper browser ready: {browser_ready()}",
             "Keys set: " + ", ".join(name for name, v in key_status(ws).items() if v["set"]) ,
             f"Sync code saved: {bool(sync_code(ws))}", f"Supabase configured: {bool(supabase_settings(ws))}", "", "--- app.log (last 60 lines) ---"]
    try:
        lines += (logs_dir() / "app.log").read_text(encoding="utf-8", errors="replace").splitlines()[-60:]
    except OSError:
        lines.append("(no log yet)")
    return redact("\n".join(lines))


# ── what the window calls ────────────────────────────────────────────────────────
log = logging.getLogger("job_finder_app")


def _guarded(method):
    """A failure inside an Api call is logged and returned as {ok: False, error}, never raised into the window."""
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            log.exception("Api.%s failed", method.__name__)
            return {"ok": False, "error": f"{method.__name__.replace('_', ' ').capitalize()} failed: {str(exc)[:140]}"}
    return wrapper


class Api:
    """Methods the window's JavaScript can call. Only simple values go in and out."""

    def __init__(self, launcher: List[str]):
        self._runner = ScanRunner(launcher)
        self._window: Any = None
        self._synced_after_run = True  # nothing to sync until a run has been started
        self._notified = True
        self._browser: Dict[str, Any] = {"installing": False, "error": ""}
        self._launcher = launcher

    def _bind(self, window: Any) -> None:
        self._window = window

    def get_state(self) -> Dict[str, Any]:
        ws = workspace_dir()
        return {
            "workspace": str(ws), "prefs": read_preferences(ws), "keys": key_status(ws),
            "running": self._runner.running, "version": _app_version(), "platform": platform_support.NAME, "mailbox": mailbox_status(ws), "stages": stage_counts(read_tracker(ws, 5000)), "usage_today": usage_today_for(ws), "supabase": supabase_status(ws), "cloud": cloud_status(ws), "profile_check": profile_check(ws),
            "browser": {"ready": browser_ready(), **self._browser},
            "app_prefs": load_app_prefs(), "chrome_found": chrome_found(),
        }

    def ensure_browser(self) -> Dict[str, Any]:
        """Downloads the page scraper's Chromium if it is missing (about 150 MB, once). Safe to call again."""
        if browser_ready() or self._browser["installing"] or os.environ.get("JOB_FINDER_SKIP_BROWSER_INSTALL") == "1":
            return {"ok": True}
        self._browser.update(installing=True, error="")
        threading.Thread(target=self._install_browser, daemon=True).start()
        return {"ok": True}

    def _install_browser(self) -> None:
        tail = ""
        try:
            proc = subprocess.run([a for a in self._launcher if a != "--cli"] + ["--install-browser"], capture_output=True, text=True, timeout=1200,
                                  env={**os.environ, "PLAYWRIGHT_BROWSERS_PATH": str(browsers_dir())})
            tail = ANSI_RE.sub("", (proc.stdout + proc.stderr).strip()).splitlines()[-1] if (proc.stdout + proc.stderr).strip() else ""
            if proc.returncode != 0 or not browser_ready():
                self._browser["error"] = tail or f"The browser download ended with code {proc.returncode}."
        except Exception as exc:
            self._browser["error"] = str(exc)[:200]
        finally:
            self._browser["installing"] = False

    def save_app_prefs(self, values: Dict[str, Any]) -> Dict[str, Any]:
        config = load_app_config()
        for key in APP_PREF_KEYS:
            if key in values:
                config[key] = values[key]
        save_app_config(config)
        return {"ok": True}

    def set_theme(self, dark: bool) -> Dict[str, Any]:
        """Lets the window's title bar match the page colours."""
        try:
            if not platform_support.IS_MAC:
                return {"ok": True}
            import native
            native.set_titlebar_theme(self._window, bool(dark))
        except Exception:
            log.debug("theme not applied", exc_info=True)
        return {"ok": True}

    def check_update(self) -> Dict[str, Any]:
        return check_for_update(_app_version())

    def save_prefs(self, form: Dict[str, Any]) -> Dict[str, Any]:
        write_preferences(workspace_dir(), form)
        return {"ok": True}

    def start_scan(self, form: Dict[str, Any]) -> Dict[str, Any]:
        ws = workspace_dir()
        if not read_preferences(ws)["profile_exists"]:
            return {"ok": False, "error": "No profile yet. Open Settings and build or choose a profile first."}
        write_preferences(ws, form)
        result = self._runner.start(build_scan_args(form), build_run_env(form, ws), ws, "scan")
        self._synced_after_run = not result.get("ok")
        self._notified = not result.get("ok")
        return result

    def run_command(self, name: str, extra: Optional[List[str]] = None) -> Dict[str, Any]:
        """Runs a short CLI command (doctor, profile sync) and shows its output in the log."""
        if name not in ("doctor", "profile"):
            return {"ok": False, "error": "Unknown command."}
        ws = workspace_dir()
        return self._runner.start([name] + list(extra or []), build_run_env({}, ws), ws, name)

    def stop_scan(self) -> Dict[str, Any]:
        return self._runner.stop()

    def poll(self, offset: int = 0) -> Dict[str, Any]:
        result = self._runner.poll(int(offset))
        if not result["running"] and not self._notified and result.get("title") == "scan":
            self._notified = True
            counts = result["counts"]
            notify("Job Finder", f"Run finished: {counts['submitted']} submitted, {counts['needs_review']} to review." if result["exit_code"] in (0, None) else "The run ended with an error.")
        if not result["running"] and not self._synced_after_run:
            self._synced_after_run = True  # once per run
            if (supabase_settings(workspace_dir()) or sync_code(workspace_dir()) or mailbox_status(workspace_dir())["configured"]) and result.get("title") == "scan":
                threading.Thread(target=self._sync_and_report, daemon=True).start()
        return result

    def _sync_and_report(self) -> None:
        ws = workspace_dir()
        if supabase_settings(ws):
            outcome = sync_missing_to_supabase(ws)
            self._runner.add_line(f"Synced with your Supabase project: {outcome['pushed']} new application(s) added." if outcome.get("ok") else outcome.get("error", "Sync failed."))
        if mailbox_status(ws)["configured"]:
            found = check_replies(ws)
            if found.get("ok") and found.get("updated"):
                self._runner.add_line(f"Mailbox: {found['updated']} application(s) moved forward after replies.")
        if sync_code(ws):
            outcome = sync_to_cloud(ws)
            self._runner.add_line(f"Synced with job-finder.space: {outcome['pushed']} new application(s) added." if outcome.get("ok") else outcome.get("error", "Sync failed."))

    def get_results(self) -> List[Dict[str, Any]]:
        ws = workspace_dir()
        local = read_tracker(ws)
        cloud: List[Dict[str, str]] = []
        if supabase_settings(ws):
            try:
                cloud = read_cloud_applications(ws)
            except Exception:
                cloud = []  # offline or key rejected: show the local list
        cloud = cloud + [r for r in read_account_applications(ws) if r["url"] not in {c["url"] for c in cloud}]
        return merge_results(local, cloud)

    def sync_now(self) -> Dict[str, Any]:
        return sync_missing_to_supabase(workspace_dir())

    def save_sync_code(self, code: str) -> Dict[str, Any]:
        return save_sync_code(workspace_dir(), code)

    def disconnect_sync(self) -> Dict[str, Any]:
        return disconnect_sync(workspace_dir())

    def sync_cloud_now(self) -> Dict[str, Any]:
        outcome = sync_to_cloud(workspace_dir())
        _cloud_cache.clear()
        return outcome

    def save_key(self, provider: str, value: str) -> Dict[str, Any]:
        var = API_KEYS.get(provider)
        if not var or not value.strip():
            return {"ok": False, "error": "Paste a key first."}
        write_env_value(workspace_dir(), var, value.strip())
        return {"ok": True, "keys": key_status(workspace_dir())}

    def choose_workspace(self) -> Dict[str, Any]:
        import webview
        picked = self._window.create_file_dialog(webview.FOLDER_DIALOG) if self._window else None
        if not picked:
            return {"ok": False}
        config = load_app_config()
        config["workspace"] = picked[0]
        save_app_config(config)
        return {"ok": True, "state": self.get_state()}

    def use_default_workspace(self) -> Dict[str, Any]:
        config = load_app_config()
        config.pop("workspace", None)
        save_app_config(config)
        return {"ok": True, "state": self.get_state()}

    def choose_resume_and_build_profile(self) -> Dict[str, Any]:
        import webview
        picked = self._window.create_file_dialog(webview.OPEN_DIALOG, file_types=("Resume (*.pdf;*.docx;*.tex)",)) if self._window else None
        if not picked:
            return {"ok": False}
        write_env_value(workspace_dir(), "MASTER_RESUME_PATH", picked[0])
        return self.run_command("profile", ["--sync", picked[0]])

    def open_signin(self) -> Dict[str, Any]:
        """Opens the agent's Chrome so the user can sign in to LinkedIn, Indeed and Reed once."""
        if self._runner.running:
            return {"ok": False, "error": "A run is in progress. Stop it first, then sign in."}
        if not chrome_found():
            return {"ok": False, "error": "Google Chrome was not found. Install it first."}
        try:
            proc = subprocess.run([a for a in self._launcher if a != "--cli"] + ["--signin"], capture_output=True, text=True, timeout=60)
        except Exception as exc:
            return {"ok": False, "error": str(exc)[:160]}
        return {"ok": proc.returncode == 0, "error": "" if proc.returncode == 0 else "Chrome did not start. See the log files."}

    def set_status(self, url: str, stage: str) -> Dict[str, Any]:
        return set_application_stage(workspace_dir(), url, stage)

    def review_info(self, url: str) -> Dict[str, Any]:
        return {"ok": True, **last_attempt(workspace_dir(), url)}

    def open_screenshot(self, url: str) -> Dict[str, Any]:
        shot = last_attempt(workspace_dir(), url).get("screenshot")
        if not shot:
            return {"ok": False, "error": "There is no screenshot for this job."}
        platform_support.open_path(shot)
        return {"ok": True}

    def review_in_chrome(self, url: str) -> Dict[str, Any]:
        """Opens the job in the agent's signed-in Chrome so the user can check the form and submit it by hand."""
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            return {"ok": False, "error": "That is not a web address."}
        if self._runner.running:
            return {"ok": False, "error": "A run is in progress. Stop it first, or open the job from the Open button."}
        try:
            proc = subprocess.run([a for a in self._launcher if a != "--cli"] + ["--open", url], capture_output=True, text=True, timeout=60)
        except Exception as exc:
            return {"ok": False, "error": str(exc)[:160]}
        return {"ok": proc.returncode == 0, "error": "" if proc.returncode == 0 else "Chrome did not open the page. See the log files."}

    def save_mailbox(self, user: str, password: str, host: str = "") -> Dict[str, Any]:
        return save_mailbox(workspace_dir(), user, password, host)

    def disconnect_mailbox(self) -> Dict[str, Any]:
        return disconnect_mailbox(workspace_dir())

    def check_replies_now(self) -> Dict[str, Any]:
        return check_replies(workspace_dir())

    def schedule_status(self) -> Dict[str, Any]:
        import scheduler
        return {"ok": True, **scheduler.status(workspace=workspace_dir())}

    def set_schedule(self, enabled: bool, hour: int = 8, minute: int = 0, real: bool = False) -> Dict[str, Any]:
        """Turns the daily run on or off. A real (submitting) run is only scheduled when `real` is True."""
        import scheduler
        if not enabled:
            return scheduler.remove(workspace=workspace_dir())
        ws = workspace_dir()
        prefs = load_app_prefs()
        options = {"mode": "auto_apply" if real else "dry_run", "primary_ai": prefs.get("primary_ai"), "headless": True}
        program = list(self._launcher) + build_scan_args(options)
        env = build_run_env(options, ws, base={})
        env["PLAYWRIGHT_BROWSERS_PATH"] = str(browsers_dir())
        env["HOME"] = str(Path.home())
        return scheduler.install(int(hour), int(minute), program, ws, logs_dir() / "scheduled.log", env)

    def get_saved_answers(self) -> Dict[str, Any]:
        from services.saved_answers import SUGGESTIONS, MAX_ENTRIES, MAX_CHARS, load_saved_answers
        return {"ok": True, "items": load_saved_answers(str(workspace_dir())), "suggestions": SUGGESTIONS, "max_entries": MAX_ENTRIES, "max_chars": MAX_CHARS}

    def save_saved_answers(self, items: List[Dict[str, str]]) -> Dict[str, Any]:
        from services.saved_answers import save_saved_answers
        return {"ok": True, **save_saved_answers(str(workspace_dir()), items)}

    # Moving the window by its top bar. The page reports how far the pointer has moved since the press.
    def drag_start(self) -> Dict[str, Any]:
        w = self._window
        self._drag_origin = (int(w.x), int(w.y)) if w is not None else None
        return {"ok": self._drag_origin is not None}

    def drag_to(self, dx: float, dy: float) -> Dict[str, Any]:
        origin = getattr(self, "_drag_origin", None)
        if origin is None or self._window is None:
            return {"ok": False}
        self._window.move(origin[0] + int(dx), origin[1] + int(dy))
        return {"ok": True}

    def zoom_window(self) -> Dict[str, Any]:
        if platform_support.IS_MAC:
            import native
            native.toggle_zoom(self._window)
        elif self._window is not None:
            self._window.toggle_fullscreen()
        return {"ok": True}

    def problem_report(self) -> Dict[str, Any]:
        return {"ok": True, "text": diagnostics_report(workspace_dir())}

    def choose_profile_and_import(self) -> Dict[str, Any]:
        import webview
        picked = self._window.create_file_dialog(webview.OPEN_DIALOG, file_types=("Profile (*.json)",)) if self._window else None
        if not picked:
            return {"ok": False}
        return import_profile_file(workspace_dir(), Path(picked[0]))

    def open_path(self, what: str) -> Dict[str, Any]:
        ws = workspace_dir()
        targets = {  # name -> (path, open as a text file)
            "workspace": (str(ws), False), "profile": (str(profile_path(ws)), True), "env": (str(ws / ".env"), True),
            "tracker": (str(ws / "applications_tracker"), False), "logs": (str(logs_dir()), False),
        }
        if what == "logs":
            logs_dir().mkdir(parents=True, exist_ok=True)
        if what == "answers":
            from services.saved_answers import ensure_template
            targets["answers"] = (ensure_template(str(ws)), True)
        if what not in targets:
            return {"ok": False}
        path, as_text = targets[what]
        platform_support.open_path(path, as_text)
        return {"ok": True}

    def open_url(self, url: str) -> Dict[str, Any]:
        if url.startswith(("http://", "https://", "mailto:hello@job-finder.space")):
            webbrowser.open(url)
            return {"ok": True}
        return {"ok": False}


for _name in [n for n in vars(Api) if not n.startswith("_") and callable(vars(Api)[n])]:
    setattr(Api, _name, _guarded(vars(Api)[_name]))


def _app_version() -> str:
    # Built app: the version baked in from pyproject.toml at build time.
    try:
        baked = Path(getattr(sys, "_MEIPASS", "")) / "VERSION"
        if getattr(sys, "_MEIPASS", None) and baked.is_file():
            return baked.read_text().strip()
    except Exception:
        pass
    try:
        from job_finder import __version__
        return str(__version__)
    except Exception:
        return ""
