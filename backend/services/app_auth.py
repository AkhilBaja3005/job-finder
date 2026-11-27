"""Who is calling, for the desktop app's endpoints.

A sync code is a short secret that links the extension and the app to an account. On its own it works like a password, so
the app endpoints also ask for the account's email (header X-Account-Email) and refuse a code whose account has another
email. A session token from Google sign-in is long and random and needs no email.

`REQUIRE_SYNC_EMAIL=1` makes every endpoint that accepts a sync code ask for the email. It is off by default only because the
published extension sends the code alone; turn it on once the extension sends the email too."""
from __future__ import annotations

import hmac
import os
from typing import Any, Dict, Optional, Tuple

from fastapi import HTTPException

from services.auth import SYNC_CODE_MAX_LEN, SYNC_CODE_MIN_LEN, async_get_user_by_token


def bearer_token(authorization: Optional[str]) -> Optional[str]:
    if authorization and authorization.startswith("Bearer "):
        parts = authorization.split(" ", 1)
        return parts[1].strip() or None
    return None


def is_sync_code(token: Optional[str]) -> bool:
    """Sync codes are 6 to 12 letters and digits. Session tokens are UUIDs with dashes, so they never look like one."""
    clean = (token or "").strip()
    return SYNC_CODE_MIN_LEN <= len(clean) <= SYNC_CODE_MAX_LEN and clean.isalnum()


def email_matches(user: Dict[str, Any], account_email: Optional[str]) -> bool:
    mine = str(user.get("email") or "").strip().lower()
    given = str(account_email or "").strip().lower()
    return bool(mine) and bool(given) and hmac.compare_digest(mine, given)


def check_email_for_sync_code(token: Optional[str], user: Dict[str, Any], account_email: Optional[str], strict: bool) -> None:
    """Raises 401 when a sync code is used with the wrong email, or with no email where one is required."""
    if not is_sync_code(token):
        return
    if account_email:
        if not email_matches(user, account_email):
            raise HTTPException(status_code=401, detail="That email and sync code do not belong together")
    elif strict or os.getenv("REQUIRE_SYNC_EMAIL") == "1":
        raise HTTPException(status_code=401, detail="Send your account email together with the sync code")


async def user_for_app(authorization: Optional[str], account_email: Optional[str], strict: bool = True) -> Tuple[str, Dict[str, Any]]:
    """The signed-in real account behind a request from the desktop app. Guests and unknown codes are refused."""
    token = bearer_token(authorization)
    user = await async_get_user_by_token(token) if token else None
    if not user or not user.get("id") or str(user["id"]).startswith("guest_"):
        raise HTTPException(status_code=401, detail="Invalid sync code")
    check_email_for_sync_code(token, user, account_email, strict)
    return token, user
