"""Signing in to job-finder.space with Google from the desktop app.

The app listens on a free port of this computer only (127.0.0.1), opens the website's Google login in the browser, and waits
for the browser to come back to that port with a one-time code. It trades the code and a secret it made itself (PKCE) for a
session token. The secret never leaves this computer except in that one trade, so a code seen by anything else is useless."""
from __future__ import annotations

import base64
import hashlib
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Callable, Dict, Optional
from urllib.parse import parse_qs, urlparse

DONE_PAGE = (b"<!doctype html><meta charset='utf-8'><title>Job Finder</title>"
             b"<body style='font:16px -apple-system,Segoe UI,sans-serif;text-align:center;margin-top:18vh'>"
             b"<h2>You are signed in</h2><p>You can close this tab and go back to Job Finder.</p></body>")
FAILED_PAGE = (b"<!doctype html><meta charset='utf-8'><title>Job Finder</title>"
               b"<body style='font:16px -apple-system,Segoe UI,sans-serif;text-align:center;margin-top:18vh'>"
               b"<h2>That did not work</h2><p>Go back to Job Finder and click Sign in again.</p></body>")


def make_pkce() -> Dict[str, str]:
    """A random verifier and its challenge (the URL-safe SHA-256 of the verifier, no padding)."""
    verifier = secrets.token_urlsafe(32)            # 43 characters
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return {"verifier": verifier, "challenge": challenge, "state": secrets.token_urlsafe(24)}


class LoopbackReceiver:
    """A one-shot web server on 127.0.0.1 that catches the browser's return trip."""

    def __init__(self, expected_state: str) -> None:
        self.expected_state = expected_state
        self.code: Optional[str] = None
        self.error: Optional[str] = None
        self._done = threading.Event()
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                pass

            def _page(self, status: int, body: bytes) -> None:
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:
                parsed = urlparse(self.path)
                if parsed.path != "/callback":
                    return self._page(404, FAILED_PAGE)
                query = parse_qs(parsed.query)
                code = (query.get("code") or [""])[0]
                state = (query.get("state") or [""])[0]
                if receiver.code is not None or not code or not secrets.compare_digest(state, receiver.expected_state):
                    return self._page(400, FAILED_PAGE)   # a stray request, a repeat, or someone else's state: ignored
                receiver.code = code
                self._page(200, DONE_PAGE)
                receiver._done.set()

        self.server = HTTPServer(("127.0.0.1", 0), Handler)   # port 0: the system picks a free one
        self.server.timeout = 0.25
        self.port = self.server.server_address[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def _serve(self) -> None:
        while not self._done.is_set() and not self._stop.is_set():
            self.server.handle_request()

    def start(self) -> "LoopbackReceiver":
        self._stop = threading.Event()
        self._thread.start()
        return self

    def wait(self, timeout: float) -> Optional[str]:
        self._done.wait(timeout)
        return self.code

    def close(self) -> None:
        self._stop.set()
        self._done.set()
        self._thread.join(timeout=2)
        try:
            self.server.server_close()
        except OSError:
            pass


class SignInCancelled(Exception):
    pass


def run_google_sign_in(post_json: Callable[[str, Dict[str, Any]], Dict[str, Any]], open_browser: Callable[[str], Any] = webbrowser.open,
                       timeout: float = 180.0, cancelled: Optional[threading.Event] = None) -> Dict[str, str]:
    """The whole round trip. `post_json(path, body)` talks to the server. Returns {"token", "email"} or raises with a message the
    user can read."""
    pkce = make_pkce()
    receiver = LoopbackReceiver(pkce["state"]).start()
    try:
        begun = post_json("/auth/app/begin", {"challenge": pkce["challenge"], "port": receiver.port, "state": pkce["state"]})
        url = str(begun.get("login_url") or "")
        if not url.startswith(("https://", "http://localhost", "http://127.0.0.1")):
            raise RuntimeError("The server did not return a sign-in address.")
        open_browser(url)
        deadline = time.time() + timeout
        code = None
        while time.time() < deadline:
            code = receiver.wait(0.25)
            if code:
                break
            if cancelled is not None and cancelled.is_set():
                raise SignInCancelled()
        if not code:
            raise RuntimeError("Signing in took too long. Click Sign in with Google to try again.")
        done = post_json("/auth/app/exchange", {"code": code, "verifier": pkce["verifier"]})
        token, email = str(done.get("token") or ""), str(done.get("email") or "")
        if not token:
            raise RuntimeError("The server did not accept the sign-in. Try again.")
        return {"token": token, "email": email}
    finally:
        receiver.close()
