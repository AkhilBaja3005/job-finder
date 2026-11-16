"""`job-finder doctor`: environment health checks. Never prints secret values."""

import importlib.util
import json
import os
import shutil
import socket
import sys
from typing import Dict, List


def _env_set(*names: str) -> bool:
    placeholders = ("YOUR_", "ENTER_")
    for name in names:
        val = os.getenv(name, "").strip()
        if val and not val.upper().startswith(placeholders):
            return True
    return False


def _gemini_key_count() -> int:
    keys = []
    for name in ["GEMINI_API_KEY"] + [f"GEMINI_API_KEY_{i}" for i in range(2, 11)]:
        keys.append(os.getenv(name, ""))
    keys.extend(os.getenv("GEMINI_API_KEYS", "").split(","))
    return len({k.strip() for k in keys if k.strip() and not k.strip().upper().startswith(("YOUR_", "ENTER_"))})


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def collect_checks() -> List[Dict[str, str]]:
    checks: List[Dict[str, str]] = []

    def add(name: str, status: str, detail: str = "") -> None:
        checks.append({"check": name, "status": status, "detail": detail})

    ok = sys.version_info >= (3, 10)
    add("python", "ok" if ok else "fail", sys.version.split()[0] + ("" if ok else " (need 3.10+)"))

    n_keys = _gemini_key_count()
    add("gemini_keys", "ok" if n_keys else "fail", f"{n_keys} key(s) configured" if n_keys else "set GEMINI_API_KEY")

    for mod in ("playwright", "browser_use", "fastapi", "pypdf"):
        add(f"module:{mod}", "ok" if _has_module(mod) else "fail", "" if _has_module(mod) else "not installed")

    chrome = os.getenv("CHROME_PATH") or next(
        (p for p in (shutil.which("google-chrome"), shutil.which("chromium"), shutil.which("chrome"),
                     "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome") if p and os.path.exists(p)),
        None,
    )
    add("chrome", "ok" if chrome else "warn", "found" if chrome else "not found (Playwright Chromium may be used)")

    port = int(os.getenv("JOB_FINDER_CDP_PORT", "9223"))
    add("cdp_port", "ok" if _port_open(port) else "warn",
        f"{port} reachable" if _port_open(port) else f"{port} not listening (started on demand)")

    add("supabase", "ok" if _env_set("SUPABASE_URL") and _env_set("SUPABASE_KEY") else "warn",
        "configured" if _env_set("SUPABASE_URL") and _env_set("SUPABASE_KEY") else "not set; CSV fallback in use")

    mail = _env_set("BREVO_API_KEY") or _env_set("RESEND_API_KEY") or _env_set("SMTP_USER")
    add("email_provider", "ok" if mail else "warn", "configured" if mail else "no SMTP/Brevo/Resend; notifications disabled")
    add("notify_email", "ok" if _env_set("NOTIFY_EMAIL") else "warn",
        "set" if _env_set("NOTIFY_EMAIL") else "NOTIFY_EMAIL unset; candidate email is used")

    guard_off = _env_set("BROWSER_USE_DISABLE_GUARDRAILS", "JOB_FINDER_DISABLE_GUARDRAILS") and \
        os.getenv("BROWSER_USE_DISABLE_GUARDRAILS", os.getenv("JOB_FINDER_DISABLE_GUARDRAILS", "0")).strip() not in ("0", "false", "False", "no")
    add("guardrails", "warn" if guard_off else "ok",
        "OFF: applications are auto-submitted" if guard_off else "ON: runs stop at the review step")
    return checks


def run_doctor(as_json: bool = False) -> int:
    checks = collect_checks()
    if as_json:
        print(json.dumps(checks, indent=2))
    else:
        from job_finder import ui
        ui.print_table("Job Finder health check", ["Check", "Status", "Detail"],
                       [[c["check"], c["status"], c["detail"]] for c in checks], status_col=1)
        failed = [c for c in checks if c["status"] == "fail"]
        if failed:
            ui.error(f"{len(failed)} check(s) failed. Fix the items marked fail above.")
        else:
            ui.success("No blocking problems found.")
    return 1 if any(c["status"] == "fail" for c in checks) else 0
