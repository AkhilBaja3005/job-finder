"""Sign-in for the desktop app (OAuth with PKCE and a loopback address) and the email check for sync codes."""
import re
from urllib.parse import parse_qs, urlparse

import pytest
from starlette.testclient import TestClient

import routes.auth_routes as auth_routes
import routes.job_routes as job_routes
import services.app_auth as app_auth
from main import app
from services import app_login

client = TestClient(app, follow_redirects=False)
VERIFIER = "v" * 43
CHALLENGE = app_login.challenge_for(VERIFIER)
STATE = "s" * 24


@pytest.fixture(autouse=True)
def fresh():
    app_login.reset_for_tests()
    auth_routes._APP_LOGIN_RATE.clear()
    yield
    app_login.reset_for_tests()


# ── the module ───────────────────────────────────────────────────────────────────
def test_challenge_is_the_url_safe_sha256_of_the_verifier():
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", CHALLENGE)
    assert app_login.challenge_for(VERIFIER) == CHALLENGE != app_login.challenge_for("w" * 43)


@pytest.mark.parametrize("challenge,port,state", [
    ("short", 50000, STATE), (CHALLENGE, 80, STATE), (CHALLENGE, 70000, STATE), (CHALLENGE, True, STATE),
    (CHALLENGE, "50000", STATE), (CHALLENGE, 50000, "no spaces allowed here!!"), (CHALLENGE, 50000, "x"),
    ("a/b" * 20, 50000, STATE),
])
def test_begin_rejects_malformed_requests(challenge, port, state):
    with pytest.raises(app_login.AppLoginError):
        app_login.begin(challenge, port, state)


def test_full_flow_returns_the_token_once():
    login_id = app_login.begin(CHALLENGE, 51234, STATE)
    target = app_login.complete(login_id, "session-token")
    parsed = urlparse(target)
    assert (parsed.scheme, parsed.hostname, parsed.port, parsed.path) == ("http", "127.0.0.1", 51234, "/callback")
    query = parse_qs(parsed.query)
    assert query["state"] == [STATE]
    code = query["code"][0]
    assert app_login.exchange(code, VERIFIER) == "session-token"
    assert app_login.exchange(code, VERIFIER) is None                      # a code works once


def test_a_wrong_verifier_fails_and_burns_the_code():
    code = parse_qs(urlparse(app_login.complete(app_login.begin(CHALLENGE, 51234, STATE), "t")).query)["code"][0]
    assert app_login.exchange(code, "x" * 43) is None
    assert app_login.exchange(code, VERIFIER) is None                      # the guess used the code up


def test_sign_in_id_works_once_and_expires():
    login_id = app_login.begin(CHALLENGE, 51234, STATE, now=1000.0)
    assert app_login.complete(login_id, "t", now=1000.0 + app_login.BEGIN_TTL + 1) is None
    login_id = app_login.begin(CHALLENGE, 51234, STATE, now=1000.0)
    assert app_login.complete(login_id, "t", now=1001.0)
    assert app_login.complete(login_id, "t", now=1002.0) is None
    assert app_login.complete("unknown", "t") is None


def test_code_expires_after_two_minutes():
    login_id = app_login.begin(CHALLENGE, 51234, STATE, now=1000.0)
    code = parse_qs(urlparse(app_login.complete(login_id, "t", now=1000.0)).query)["code"][0]
    assert app_login.exchange(code, VERIFIER, now=1000.0 + app_login.CODE_TTL + 1) is None


def test_the_waiting_list_has_a_limit():
    for _ in range(app_login.MAX_PENDING):
        app_login.begin(CHALLENGE, 51234, STATE)
    with pytest.raises(app_login.AppLoginError):
        app_login.begin(CHALLENGE, 51234, STATE)


# ── the routes ───────────────────────────────────────────────────────────────────
def _begin():
    r = client.post("/auth/app/begin", json={"challenge": CHALLENGE, "port": 51234, "state": STATE})
    return r


def test_begin_returns_a_google_login_address_with_the_sign_in_id():
    r = _begin()
    assert r.status_code == 200
    url = r.json()["login_url"]
    assert "/auth/url?redirect_to=" in url and "%2Fapp%2Flogin-done%3Fcid%3D" in url
    assert CHALLENGE not in url and VERIFIER not in url                    # nothing secret goes through the browser


def test_begin_refuses_a_bad_port_and_too_many_attempts():
    assert client.post("/auth/app/begin", json={"challenge": CHALLENGE, "port": 22, "state": STATE}).status_code == 400
    for _ in range(25):
        status = _begin().status_code
    assert status == 429


def test_google_callback_sends_the_browser_back_to_the_app_and_the_app_gets_a_token(monkeypatch):
    monkeypatch.setattr(auth_routes, "exchange_google_code_for_email", lambda code, redirect_uri: ("me@example.com", None))
    monkeypatch.setattr(auth_routes, "create_or_get_user", lambda email, picture: {"id": 7, "email": email})
    monkeypatch.setattr(auth_routes, "create_session", lambda uid: "11111111-2222-3333-4444-555555555555")

    async def fake_user(token):
        return {"id": 7, "email": "me@example.com"} if token == "11111111-2222-3333-4444-555555555555" else None

    monkeypatch.setattr(auth_routes, "async_get_user_by_token", fake_user)
    cid = parse_qs(urlparse(_begin().json()["login_url"]).query)["redirect_to"][0].split("cid=")[1]
    back = client.get("/auth/callback", params={"code": "google-code", "state": f"/app/login-done?cid={cid}"})
    assert back.status_code == 302
    location = urlparse(back.headers["location"])
    assert (location.hostname, location.port, location.path) == ("127.0.0.1", 51234, "/callback")
    assert "token=" not in back.headers["location"]                         # the session token never rides in the URL
    code = parse_qs(location.query)["code"][0]
    done = client.post("/auth/app/exchange", json={"code": code, "verifier": VERIFIER})
    assert done.status_code == 200 and done.json() == {"token": "11111111-2222-3333-4444-555555555555", "email": "me@example.com"}
    assert client.post("/auth/app/exchange", json={"code": code, "verifier": VERIFIER}).status_code == 401


def test_callback_for_an_unknown_sign_in_shows_an_expired_page(monkeypatch):
    monkeypatch.setattr(auth_routes, "exchange_google_code_for_email", lambda code, redirect_uri: ("me@example.com", None))
    monkeypatch.setattr(auth_routes, "create_or_get_user", lambda email, picture: {"id": 7, "email": email})
    monkeypatch.setattr(auth_routes, "create_session", lambda uid: "tok")
    r = client.get("/auth/callback", params={"code": "g", "state": "/app/login-done?cid=nope"})
    assert r.status_code == 400 and "expired" in r.text


def test_exchange_refuses_a_wrong_verifier():
    login_id = app_login.begin(CHALLENGE, 51234, STATE)
    code = parse_qs(urlparse(app_login.complete(login_id, "tok")).query)["code"][0]
    assert client.post("/auth/app/exchange", json={"code": code, "verifier": "z" * 43}).status_code == 401


def test_revoke_deletes_a_session_but_refuses_sync_codes(monkeypatch):
    calls = []
    import services.auth as auth_service
    monkeypatch.setattr(auth_service, "supabase_request", lambda path, method="GET", data=None: calls.append((method, path)) or [])
    ok = client.post("/auth/app/revoke", headers={"Authorization": "Bearer 11111111-2222-3333-4444-555555555555"})
    assert ok.status_code == 200 and calls == [("DELETE", "sessions?token=eq.11111111-2222-3333-4444-555555555555")]
    assert client.post("/auth/app/revoke", headers={"Authorization": "Bearer ABC123"}).status_code == 401
    assert client.post("/auth/app/revoke").status_code == 401


# ── the email check ──────────────────────────────────────────────────────────────
def _as(monkeypatch, user):
    async def fake(token):
        return user
    monkeypatch.setattr(app_auth, "async_get_user_by_token", fake)
    monkeypatch.setattr(job_routes, "async_get_user_by_token", fake)


ROW = {"job_title": "AI Engineer", "company": "Acme", "job_url": "https://boards.greenhouse.io/acme/jobs/1", "score": 80, "status": "applied"}


def test_sync_code_needs_the_matching_email_on_the_app_endpoints(monkeypatch):
    _as(monkeypatch, {"id": 7, "email": "Me@Example.com"})
    monkeypatch.setattr(job_routes, "list_applications", lambda token=None: [])
    monkeypatch.setattr(job_routes, "record_application", lambda token, entry: None)
    body = {"applications": [ROW]}
    code = {"Authorization": "Bearer ABC123XYZ9"}
    assert client.post("/applications/sync", json=body, headers=code).status_code == 401                              # no email
    assert client.post("/applications/sync", json=body, headers={**code, "X-Account-Email": "other@example.com"}).status_code == 401
    ok = client.post("/applications/sync", json=body, headers={**code, "X-Account-Email": " me@example.com "})
    assert ok.status_code == 200 and ok.json()["added"] == 1


def test_a_google_session_token_needs_no_email(monkeypatch):
    _as(monkeypatch, {"id": 7, "email": "me@example.com"})
    monkeypatch.setattr(job_routes, "list_applications", lambda token=None: [])
    monkeypatch.setattr(job_routes, "record_application", lambda token, entry: None)
    r = client.post("/applications/sync", json={"applications": [ROW]}, headers={"Authorization": "Bearer 11111111-2222-3333-4444-555555555555"})
    assert r.status_code == 200


def test_shared_endpoints_check_the_email_only_when_it_is_sent(monkeypatch):
    _as(monkeypatch, {"id": 7, "email": "me@example.com"})
    monkeypatch.setattr(job_routes, "list_applications", lambda token=None: [])
    code = {"Authorization": "Bearer ABC123XYZ9"}
    assert client.get("/applications", headers=code).status_code == 200                                                # the extension: code only
    assert client.get("/applications", headers={**code, "X-Account-Email": "me@example.com"}).status_code == 200
    assert client.get("/applications", headers={**code, "X-Account-Email": "other@example.com"}).status_code == 401
    monkeypatch.setenv("REQUIRE_SYNC_EMAIL", "1")                                                                       # once the extension sends the email too
    assert client.get("/applications", headers=code).status_code == 401
    assert client.get("/applications", headers={**code, "X-Account-Email": "me@example.com"}).status_code == 200
    assert client.get("/applications", headers={"Authorization": "Bearer 11111111-2222-3333-4444-555555555555"}).status_code == 200


def test_guests_are_refused_even_with_an_email(monkeypatch):
    _as(monkeypatch, {"id": "guest_abc", "email": "guest@job-finder.space"})
    r = client.post("/applications/sync", json={"applications": [ROW]}, headers={"Authorization": "Bearer ABC123XYZ9", "X-Account-Email": "guest@job-finder.space"})
    assert r.status_code == 401


def test_sync_code_detection():
    assert app_auth.is_sync_code("ABC123") and app_auth.is_sync_code("abc123xyz9") and app_auth.is_sync_code("ABCDEFGHIJKL")
    assert not app_auth.is_sync_code("ABC12") and not app_auth.is_sync_code("A" * 13)
    assert not app_auth.is_sync_code("11111111-2222-3333-4444-555555555555") and not app_auth.is_sync_code(None)
    assert app_auth.email_matches({"email": "A@b.co"}, " a@B.co ") and not app_auth.email_matches({"email": ""}, "") and not app_auth.email_matches({"email": "a@b.co"}, None)
