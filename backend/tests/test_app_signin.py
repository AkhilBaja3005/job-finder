"""The desktop app's Google sign-in: PKCE, the loopback listener, and the whole round trip with a fake server and browser."""
import re
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "macapp"))
import account_login as al  # noqa: E402
from services import app_login  # noqa: E402


def _get(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def test_pkce_values_match_what_the_server_expects():
    a, b = al.make_pkce(), al.make_pkce()
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", a["verifier"]) and re.fullmatch(r"[A-Za-z0-9_-]{43}", a["challenge"])
    assert a["challenge"] == app_login.challenge_for(a["verifier"])          # the app and the server hash the same way
    assert a["verifier"] != b["verifier"] and a["state"] != b["state"]


def test_receiver_listens_on_this_computer_only_and_takes_one_good_callback():
    r = al.LoopbackReceiver("good-state").start()
    try:
        assert r.server.server_address[0] == "127.0.0.1" and r.port > 1023
        base = f"http://127.0.0.1:{r.port}"
        assert _get(base + "/other?code=x&state=good-state")[0] == 404
        assert _get(base + "/callback?code=abc&state=wrong")[0] == 400        # somebody else's state
        assert _get(base + "/callback?state=good-state")[0] == 400            # no code
        assert r.code is None
        status, body = _get(base + "/callback?code=abc&state=good-state")
        assert status == 200 and b"signed in" in body
        assert r.wait(1) == "abc"                                              # after one good callback the listener stops
    finally:
        r.close()


def test_receiver_wait_times_out():
    r = al.LoopbackReceiver("s").start()
    try:
        assert r.wait(0.2) is None
    finally:
        r.close()


class FakeServer:
    """Plays the website: begin remembers the loopback port, the 'browser' visits it with a code, exchange checks the verifier."""

    def __init__(self):
        self.calls, self.begun, self.codes = [], None, {}

    def post(self, path, body):
        self.calls.append(path)
        if path == "/auth/app/begin":
            self.begun = body
            return {"login_url": "https://www.job-finder.space/auth/url?redirect_to=%2Fapp%2Flogin-done%3Fcid%3Dabc"}
        if path == "/auth/app/exchange":
            if self.codes.get(body["code"]) != app_login.challenge_for(body["verifier"]):
                raise RuntimeError("rejected")
            return {"token": "11111111-2222-3333-4444-555555555555", "email": "me@example.com"}
        raise AssertionError(path)

    def browser(self, url):
        # Google finished: the website sends the browser to the app's own port with a code and the app's state.
        assert url.startswith("https://www.job-finder.space/auth/url")
        self.codes["one-time-code"] = self.begun["challenge"]
        threading.Thread(target=lambda: _get(f"http://127.0.0.1:{self.begun['port']}/callback?code=one-time-code&state={self.begun['state']}"), daemon=True).start()


def test_whole_sign_in_returns_the_token_and_email():
    fake = FakeServer()
    result = al.run_google_sign_in(fake.post, fake.browser, timeout=10)
    assert result == {"token": "11111111-2222-3333-4444-555555555555", "email": "me@example.com"}
    assert fake.calls == ["/auth/app/begin", "/auth/app/exchange"]
    assert fake.begun["port"] > 1023 and len(fake.begun["challenge"]) == 43 and "verifier" not in fake.begun   # the secret is not sent first


def test_sign_in_times_out_when_the_browser_never_comes_back():
    fake = FakeServer()
    with pytest.raises(RuntimeError, match="too long"):
        al.run_google_sign_in(fake.post, lambda url: None, timeout=0.6)
    assert fake.calls == ["/auth/app/begin"]


def test_sign_in_can_be_cancelled():
    fake, stop = FakeServer(), threading.Event()
    threading.Timer(0.3, stop.set).start()
    with pytest.raises(al.SignInCancelled):
        al.run_google_sign_in(fake.post, lambda url: None, timeout=10, cancelled=stop)


def test_an_unsafe_login_address_is_never_opened():
    opened = []

    def post(path, body):
        return {"login_url": "file:///etc/passwd"}

    with pytest.raises(RuntimeError, match="sign-in address"):
        al.run_google_sign_in(post, opened.append, timeout=1)
    assert opened == []


def test_a_server_error_on_begin_is_passed_up():
    def post(path, body):
        raise RuntimeError("Too many sign-in attempts. Try again in a few minutes.")

    with pytest.raises(RuntimeError, match="Too many"):
        al.run_google_sign_in(post, lambda u: None, timeout=1)
