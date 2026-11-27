"""Sign-in for the desktop app with a Google account, without pasting a code.

The flow is the standard one for native apps (OAuth with PKCE and a loopback address):

1. The app makes a random secret (the verifier) and sends only its SHA-256 hash (the challenge) with a free local port.
   `begin()` stores that and returns an id.
2. The app opens the browser at the normal Google login with that id in the state.
3. After Google, `complete()` turns the new session into a one-time code and sends the browser back to
   http://127.0.0.1:<port>/callback, where only the app is listening.
4. The app trades the code plus its verifier for the session token with `exchange()`. A stolen code is useless without the
   verifier, and a code works once and for two minutes.

Pending sign-ins live in memory: they last minutes, and a restart only means the user clicks Sign in again."""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import threading
import time
from typing import Any, Dict, Optional
from urllib.parse import urlencode

BEGIN_TTL = 600        # seconds the user has to finish Google's login page
CODE_TTL = 120         # seconds the one-time code can be traded
MAX_PENDING = 2000
_B64URL = re.compile(r"^[A-Za-z0-9_-]{43,128}$")
_STATE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")

_lock = threading.Lock()
_pending: Dict[str, Dict[str, Any]] = {}   # sign-in id -> {challenge, port, state, expires}
_codes: Dict[str, Dict[str, Any]] = {}     # one-time code -> {token, challenge, expires}


class AppLoginError(ValueError):
    """The request was malformed or expired. The message is safe to show."""


def challenge_for(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def _sweep(now: float) -> None:
    for table in (_pending, _codes):
        for key in [k for k, v in table.items() if v["expires"] < now]:
            table.pop(key, None)


def begin(challenge: str, port: int, state: str, now: Optional[float] = None) -> str:
    """Remembers a sign-in the app started. Only a loopback port and a well-formed challenge are accepted."""
    now = time.time() if now is None else now
    if not isinstance(challenge, str) or not _B64URL.match(challenge):
        raise AppLoginError("The sign-in request is not valid.")
    if not isinstance(state, str) or not _STATE.match(state):
        raise AppLoginError("The sign-in request is not valid.")
    if not isinstance(port, int) or isinstance(port, bool) or not 1024 <= port <= 65535:
        raise AppLoginError("The sign-in request is not valid.")
    with _lock:
        _sweep(now)
        if len(_pending) >= MAX_PENDING:
            raise AppLoginError("Too many sign-ins are waiting. Try again in a few minutes.")
        login_id = secrets.token_urlsafe(24)
        _pending[login_id] = {"challenge": challenge, "port": port, "state": state, "expires": now + BEGIN_TTL}
    return login_id


def complete(login_id: str, session_token: str, now: Optional[float] = None) -> Optional[str]:
    """After Google: returns the loopback address to send the browser to, or None when the sign-in is unknown or expired."""
    now = time.time() if now is None else now
    with _lock:
        _sweep(now)
        entry = _pending.pop(login_id, None)
        if entry is None:
            return None
        code = secrets.token_urlsafe(32)
        _codes[code] = {"token": session_token, "challenge": entry["challenge"], "expires": now + CODE_TTL}
    return "http://127.0.0.1:%d/callback?%s" % (entry["port"], urlencode({"code": code, "state": entry["state"]}))


def exchange(code: str, verifier: str, now: Optional[float] = None) -> Optional[str]:
    """Trades a one-time code and the app's verifier for the session token. The code is used up even when the verifier is wrong."""
    now = time.time() if now is None else now
    if not isinstance(code, str) or not isinstance(verifier, str) or not _B64URL.match(verifier):
        return None
    with _lock:
        _sweep(now)
        entry = _codes.pop(code, None)
    if entry is None:
        return None
    if not hmac.compare_digest(challenge_for(verifier), entry["challenge"]):
        return None
    return entry["token"]


def reset_for_tests() -> None:
    with _lock:
        _pending.clear()
        _codes.clear()
