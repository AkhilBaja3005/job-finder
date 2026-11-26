"""
The logic behind the Job Finder Mac app: a control panel for the job scanner and the auto-apply agent.

The app never re-implements scanning. It builds a `job-finder scan ...` command from the form, runs it as a child
process, and shows the output and the tracker. Everything here works without a window, so it can be tested.
"""
from __future__ import annotations

import csv
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
import webbrowser
from collections import deque
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional

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
    return Path(override) if override else Path.home() / "Library" / "Application Support" / APP_NAME


def load_app_config() -> Dict[str, Any]:
    try:
        return json.loads((app_support_dir() / "app.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_app_config(config: Dict[str, Any]) -> None:
    home = app_support_dir()
    home.mkdir(parents=True, exist_ok=True)
    (home / "app.json").write_text(json.dumps(config, indent=2), encoding="utf-8")


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
                self._proc = subprocess.Popen(
                    self._launcher + args, cwd=str(cwd), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1, errors="replace", start_new_session=True,
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
                with self._lock:
                    if len(self._lines) == self._lines.maxlen:
                        self._dropped += 1
                    self._lines.append(line)
        self._exit_code = proc.wait()

    def stop(self) -> Dict[str, Any]:
        proc = self._proc
        if proc is None or proc.poll() is not None:
            return {"ok": True, "message": "Nothing is running."}
        try:
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


# ── results ──────────────────────────────────────────────────────────────────────
def read_tracker(ws: Path, limit: int = 300) -> List[Dict[str, str]]:
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


# ── what the window calls ────────────────────────────────────────────────────────
class Api:
    """Methods the window's JavaScript can call. Only simple values go in and out."""

    def __init__(self, launcher: List[str]):
        self._runner = ScanRunner(launcher)
        self._window: Any = None

    def _bind(self, window: Any) -> None:
        self._window = window

    def get_state(self) -> Dict[str, Any]:
        ws = workspace_dir()
        return {
            "workspace": str(ws), "prefs": read_preferences(ws), "keys": key_status(ws),
            "running": self._runner.running, "version": _app_version(),
        }

    def save_prefs(self, form: Dict[str, Any]) -> Dict[str, Any]:
        write_preferences(workspace_dir(), form)
        return {"ok": True}

    def start_scan(self, form: Dict[str, Any]) -> Dict[str, Any]:
        ws = workspace_dir()
        if not read_preferences(ws)["profile_exists"]:
            return {"ok": False, "error": "No profile yet. Open Settings and build or choose a profile first."}
        write_preferences(ws, form)
        return self._runner.start(build_scan_args(form), build_run_env(form, ws), ws, "scan")

    def run_command(self, name: str, extra: Optional[List[str]] = None) -> Dict[str, Any]:
        """Runs a short CLI command (doctor, profile sync) and shows its output in the log."""
        if name not in ("doctor", "profile"):
            return {"ok": False, "error": "Unknown command."}
        ws = workspace_dir()
        return self._runner.start([name] + list(extra or []), build_run_env({}, ws), ws, name)

    def stop_scan(self) -> Dict[str, Any]:
        return self._runner.stop()

    def poll(self, offset: int = 0) -> Dict[str, Any]:
        return self._runner.poll(int(offset))

    def get_results(self) -> List[Dict[str, str]]:
        return read_tracker(workspace_dir())

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

    def open_path(self, what: str) -> Dict[str, Any]:
        ws = workspace_dir()
        targets = {
            "workspace": ["open", str(ws)],
            "profile": ["open", "-t", str(profile_path(ws))],
            "env": ["open", "-t", str(ws / ".env")],
            "tracker": ["open", str(ws / "applications_tracker")],
        }
        if what not in targets:
            return {"ok": False}
        subprocess.run(targets[what], check=False)
        return {"ok": True}

    def open_url(self, url: str) -> Dict[str, Any]:
        if url.startswith(("http://", "https://")):
            webbrowser.open(url)
            return {"ok": True}
        return {"ok": False}


def _app_version() -> str:
    try:
        from job_finder import __version__
        return str(__version__)
    except Exception:
        return ""
