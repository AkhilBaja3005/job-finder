"""
Application history tracking — records which jobs a user has tailored a
resume for or applied to, so that history survives a page refresh/browser
close (previously nothing persisted this at all).

Supabase-backed (an `applications` table) when configured, matching the
existing user_resumes persistence pattern in auth.py/main.py. Falls back to a
per-user JSON file under backend/output/ when Supabase isn't configured,
mirroring the existing resume_state.json guest-fallback pattern.
"""

import json
import os
import re
import time
from datetime import datetime, timezone
from typing import Optional

from services.auth import supabase_request, get_user_by_token

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

# Cap on entries kept in the local JSON fallback file, so a long-running guest
# session can't grow this file without bound.
MAX_LOCAL_HISTORY_ENTRIES = 200


def _safe_key(token: Optional[str]) -> str:
    """Mirrors main.py's _safe_key(): filesystem-safe per-user cache key."""
    key = token or "guest"
    key = re.sub(r'[^a-zA-Z0-9_-]', '', key)[:40]
    return key or "guest"


def _local_history_path(token: Optional[str]) -> str:
    return os.path.join(OUTPUT_DIR, f"application_history_{_safe_key(token)}.json")


def _read_local_history(token: Optional[str]) -> list[dict]:
    path = _local_history_path(token)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception as e:
        print(f"[application_tracker] Failed to read local history {path}: {e}")
        return []


def _write_local_history(token: Optional[str], entries: list[dict]) -> None:
    path = _local_history_path(token)
    try:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(entries[-MAX_LOCAL_HISTORY_ENTRIES:], f, indent=2)
    except Exception as e:
        print(f"[application_tracker] Failed to write local history {path}: {e}")


def record_application(token: Optional[str], entry: dict) -> None:
    """
    Records one history entry. `entry` is expected to have:
    job_title, company, job_url, score (optional), status ('tailored'|'applied').
    Adds a server-side timestamp so the client can't spoof ordering.
    """
    record = {**entry, "timestamp": time.time()}

    user = get_user_by_token(token) if token else None
    if user and user.get("id"):
        # supabase_request() never raises — it catches every exception itself
        # (auth.py) and returns []. So the only success signal available here
        # is a non-empty response (POST with Prefer: return=representation
        # returns the inserted row(s) on success). Treating "no exception" as
        # success meant a POST that silently failed (bad column type, RLS
        # rejection, etc.) never fell through to the local-file fallback below
        # — the write looked like it worked and the entry was just lost.
        result = supabase_request("applications", "POST", {
            "user_id": user["id"],
            "job_title": record.get("job_title", ""),
            "company": record.get("company", ""),
            "job_url": record.get("job_url", ""),
            "score": record.get("score"),
            "status": record.get("status", "tailored"),
            "created_at": datetime.fromtimestamp(record["timestamp"], tz=timezone.utc).isoformat(),
        })
        if result:
            return
        print("[application_tracker] Supabase write returned no rows, falling back to local file")

    entries = _read_local_history(token)
    entries.append(record)
    _write_local_history(token, entries)


def list_applications(token: Optional[str]) -> list[dict]:
    """Returns history entries newest-first."""
    user = get_user_by_token(token) if token else None
    if user and user.get("id"):
        rows = supabase_request(
            f"applications?user_id=eq.{user['id']}&order=created_at.desc&limit={MAX_LOCAL_HISTORY_ENTRIES}",
            "GET",
        )
        if rows:
            return [
                {
                    "job_title": r.get("job_title", ""),
                    "company": r.get("company", ""),
                    "job_url": r.get("job_url", ""),
                    "score": r.get("score"),
                    "status": r.get("status", "tailored"),
                    # created_at comes back from Supabase as an ISO 8601 string
                    # (timestamptz), but the frontend/local-file fallback both
                    # expect a Unix-epoch float (it does `timestamp * 1000` to
                    # build a JS Date) — normalize here so both sources produce
                    # the same shape.
                    "timestamp": datetime.fromisoformat(r["created_at"]).timestamp() if r.get("created_at") else None,
                }
                for r in rows
            ]

    entries = _read_local_history(token)
    return sorted(entries, key=lambda e: e.get("timestamp", 0), reverse=True)
