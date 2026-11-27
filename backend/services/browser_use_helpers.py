"""Pure helpers for the browser-use autofill runner (no browser-use import, easy to unit test)."""

import base64
import hashlib
import os
import re
from typing import Any, List, Optional

CAPTCHA_MARKERS = (
    "captcha", "recaptcha", "hcaptcha", "turnstile", "verify you are human",
    "i am human", "i'm not a robot", "security check", "bot detection",
)
LOGIN_MARKERS = (
    "login required", "sign in to continue", "sign in required", "log in to continue",
    "please log in", "please sign in", "authentication required", "create an account to apply",
    "verification code", "one-time code", "two-factor", "2fa",
)


def detect_blocker(text: str) -> Optional[str]:
    """Return 'captcha' or 'login' when a run result describes a human-only obstacle, else None."""
    lowered = (text or "").lower()
    if any(m in lowered for m in CAPTCHA_MARKERS):
        return "captcha"
    if any(m in lowered for m in LOGIN_MARKERS):
        return "login"
    return None


_QUESTIONS_LINE = re.compile(r"(?im)^\s*QUESTIONS:\s*(.+)$")


def extract_questions(text: str, limit: int = 25) -> List[str]:
    """The screening questions the agent reports on its last "QUESTIONS: a | b | c" line. Short, no answers, never raises."""
    found = _QUESTIONS_LINE.findall(text or "")
    if not found:
        return []
    out: List[str] = []
    for part in found[-1].split("|"):
        question = re.sub(r"\s+", " ", part).strip(" .;:-*")[:140]
        if len(question) >= 4 and question.lower() not in {q.lower() for q in out}:
            out.append(question)
        if len(out) >= limit:
            break
    return out


def get_run_timeout(default: float = 600.0) -> float:
    """Total wall-clock budget for one application (BROWSER_USE_TIMEOUT, seconds)."""
    raw = os.getenv("BROWSER_USE_TIMEOUT", "").strip()
    try:
        value = float(raw) if raw else default
    except ValueError:
        value = default
    return value if value > 0 else default


def save_review_screenshot(history: Any, job_url: str, out_dir: str) -> Optional[str]:
    """Save the last screenshot of a run so the final form state can be audited. Never raises."""
    try:
        data = None
        paths: Any = getattr(history, "screenshot_paths", None)
        if callable(paths):
            raw_paths: Any = paths()
            existing = [p for p in (raw_paths or []) if p and os.path.exists(p)]
            if existing:
                return existing[-1]
        shots: Any = getattr(history, "screenshots", None)
        if callable(shots):
            raw_shots: Any = shots()
            items = [s for s in (raw_shots or []) if s]
            if items:
                data = items[-1]
        if not data:
            return None
        os.makedirs(out_dir, exist_ok=True)
        name = hashlib.sha1(job_url.encode("utf-8")).hexdigest()[:12] + ".png"
        path = os.path.join(out_dir, name)
        with open(path, "wb") as fh:
            fh.write(base64.b64decode(data))
        return path
    except Exception:
        return None
