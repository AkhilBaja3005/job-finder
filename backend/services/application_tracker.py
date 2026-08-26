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
import hashlib
from datetime import datetime, timezone
from typing import Optional

from services.auth import supabase_request, get_user_by_token

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HF_DATA_DIR = "/data"
if os.path.exists(HF_DATA_DIR) and os.access(HF_DATA_DIR, os.W_OK):
    OUTPUT_DIR = os.path.join(HF_DATA_DIR, "output")
else:
    OUTPUT_DIR = os.path.join(BASE_DIR, "output")

# Cap on entries kept in the local JSON fallback file, so a long-running guest
# session can't grow this file without bound.
MAX_LOCAL_HISTORY_ENTRIES = 200


def _safe_key(token: Any) -> str:
    """Mirrors session_store's _safe_key(): filesystem-safe per-user cache key."""
    if token is None:
        return "guest"
    key = str(token).strip()
    key = re.sub(r'[^a-zA-Z0-9_-]', '', key)[:40]
    return key or "guest"


def _local_history_path(token: Optional[str]) -> str:
    key = _safe_key(token)
    user_out_dir = os.path.join(OUTPUT_DIR, key)
    os.makedirs(user_out_dir, exist_ok=True)
    return os.path.join(user_out_dir, f"application_history_{key}.json")


def _read_local_history(token: Optional[str]) -> list[dict]:
    path = _local_history_path(token)
    if not os.path.exists(path):
        # Fallback check flat OUTPUT_DIR for backward compatibility
        flat_path = os.path.join(OUTPUT_DIR, f"application_history_{_safe_key(token)}.json")
        if os.path.exists(flat_path):
            path = flat_path
        else:
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
        os.makedirs(os.path.dirname(path), exist_ok=True)
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
        supa_payload = {
            "user_id": user["id"],
            "job_title": record.get("job_title", "") or "Target Role",
            "company": record.get("company", "") or "Hiring Company",
            "job_url": record.get("job_url", ""),
            "score": record.get("score"),
            "status": record.get("status", "tailored"),
            "created_at": datetime.fromtimestamp(record["timestamp"], tz=timezone.utc).isoformat(),
        }
        if record.get("source_mode"):
            supa_payload["source_mode"] = record.get("source_mode")
        if record.get("recruiter_name"):
            supa_payload["recruiter_name"] = record.get("recruiter_name")
        if record.get("recruiter_profile_url"):
            supa_payload["recruiter_profile_url"] = record.get("recruiter_profile_url")
        if record.get("overleaf_url"):
            supa_payload["overleaf_url"] = record.get("overleaf_url")
        if record.get("pdf_url"):
            supa_payload["pdf_url"] = record.get("pdf_url")

        result = supabase_request("applications", "POST", supa_payload)
        if result:
            return
        print("[application_tracker] Supabase write returned no rows, falling back to local file")

    # Local snapshot persistence
    if record.get("pdf_path") and os.path.exists(record.get("pdf_path")):
        try:
            snapshot_dir = os.path.join(OUTPUT_DIR, _safe_key(token), "snapshots")
            os.makedirs(snapshot_dir, exist_ok=True)
            app_id = f"{int(record['timestamp'])}_{hashlib.md5(record.get('job_title', '').encode('utf-8')).hexdigest()[:6]}"
            snap_pdf = os.path.join(snapshot_dir, f"tailored_{app_id}.pdf")
            import shutil
            shutil.copy2(record["pdf_path"], snap_pdf)
            record["snapshot_pdf_path"] = snap_pdf
        except Exception as snap_err:
            print(f"[application_tracker] Warning: Could not create PDF snapshot: {snap_err}")

    entries = _read_local_history(token)
    entries.append(record)
    _write_local_history(token, entries)


def update_application_status(token: Optional[str], job_url: str, new_status: str) -> bool:
    """Updates status ('applied'|'autofilled'|'tailored') for a job URL."""
    user = get_user_by_token(token) if token else None
    if user and user.get("id"):
        result = supabase_request(
            f"applications?user_id=eq.{user['id']}&job_url=eq.{job_url}",
            "PATCH",
            {"status": new_status}
        )
        if result:
            return True

    # Fallback to local JSON file
    entries = _read_local_history(token)
    updated = False
    for entry in entries:
        if entry.get("job_url") == job_url:
            entry["status"] = new_status
            updated = True
    if updated:
        _write_local_history(token, entries)
    return updated


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
                    "recruiter_name": r.get("recruiter_name"),
                    "recruiter_profile_url": r.get("recruiter_profile_url"),
                    "overleaf_url": r.get("overleaf_url"),
                    "pdf_url": r.get("pdf_url"),
                    "source_mode": r.get("source_mode", "website"),
                    "timestamp": datetime.fromisoformat(r["created_at"]).timestamp() if r.get("created_at") else None,
                }
                for r in rows
            ]

    entries = _read_local_history(token)
    return sorted(entries, key=lambda e: e.get("timestamp", 0), reverse=True)
