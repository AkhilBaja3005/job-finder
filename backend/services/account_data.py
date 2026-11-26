"""Export and deletion of everything the server keeps about one account.

Tables, in the order they can be removed: applications, user_resumes, sessions, then the user row itself.
Saved API keys are never part of an export (they are only shown as "set" in the account page)."""
from __future__ import annotations

import os
import shutil
from typing import Any, Dict, Optional

from config.constants import get_output_dir
from services.auth import supabase_request

TABLES_BY_USER = ("applications", "user_resumes", "sessions")
EXPORT_LIMIT = 5000


def export_user_data(user: Dict[str, Any]) -> Dict[str, Any]:
    uid = user["id"]
    rows = lambda table: supabase_request(f"{table}?user_id=eq.{uid}&limit={EXPORT_LIMIT}", "GET") or []  # noqa: E731
    resumes = rows("user_resumes")
    return {
        "account": {"email": user.get("email"), "sync_code": user.get("sync_code"), "send_tailored_email": user.get("send_tailored_email"),
                    "has_saved_api_key": bool(user.get("gemini_api_key"))},
        "applications": rows("applications"),
        "resumes": resumes,
    }


def _local_dir(token: Optional[str]) -> Optional[str]:
    from services.application_tracker import _safe_key
    root = os.path.realpath(get_output_dir())
    path = os.path.realpath(os.path.join(root, _safe_key(token)))
    return path if path.startswith(root + os.sep) and os.path.isdir(path) else None


def delete_user_data(user: Dict[str, Any], token: Optional[str] = None) -> Dict[str, Any]:
    """Removes the account's rows and this token's local files. Reports what remains; never claims more than it checked."""
    uid = user["id"]
    for table in TABLES_BY_USER:
        supabase_request(f"{table}?user_id=eq.{uid}", "DELETE")
    supabase_request(f"users?id=eq.{uid}", "DELETE")
    remaining = {t: len(supabase_request(f"{t}?user_id=eq.{uid}&select=user_id&limit=1", "GET") or []) for t in TABLES_BY_USER}
    remaining["users"] = len(supabase_request(f"users?id=eq.{uid}&select=id&limit=1", "GET") or [])
    local = _local_dir(token)
    if local:
        shutil.rmtree(local, ignore_errors=True)
    return {"deleted": all(v == 0 for v in remaining.values()), "remaining": remaining}
