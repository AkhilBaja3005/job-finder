import pytest
from starlette.requests import Request

from services import auth, request_context as rc
from services import secret_store as ss


def _request(ip="9.9.9.9", xff=None):
    headers = [(b"x-forwarded-for", xff.encode())] if xff else []
    return Request({"type": "http", "method": "POST", "path": "/x", "headers": headers, "client": (ip, 1234)})


# ── real client IP ──────────────────────────────────────────────────────────────
def test_client_ip_uses_rightmost_forwarded_entry(monkeypatch):
    monkeypatch.delenv("TRUSTED_PROXY_COUNT", raising=False)
    # the left entry is client-controlled and must be ignored
    assert rc.get_client_ip("10.0.0.1", "6.6.6.6, 203.0.113.7") == "203.0.113.7"


def test_client_ip_two_proxies(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_COUNT", "2")
    assert rc.get_client_ip("10.0.0.1", "6.6.6.6, 203.0.113.7, 10.1.1.1") == "203.0.113.7"


def test_client_ip_falls_back_to_socket_peer(monkeypatch):
    monkeypatch.delenv("TRUSTED_PROXY_COUNT", raising=False)
    assert rc.get_client_ip("10.0.0.1", None) == "10.0.0.1"
    assert rc.get_client_ip(None, None) == "unknown"


# ── failed sync-code guesses ────────────────────────────────────────────────────
@pytest.fixture
def clean_limiter(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("SYNC_GUESS_MAX", "3")
    rc._MISSES.clear()
    auth._token_cache.clear() if hasattr(auth._token_cache, "clear") else None
    yield
    rc._MISSES.clear()


def test_repeated_wrong_sync_codes_are_blocked(clean_limiter, monkeypatch):
    monkeypatch.setattr(auth, "supabase_request", lambda *a, **k: [])
    tok = rc.client_ip_var.set("1.2.3.4")
    try:
        for i in range(3):
            auth.get_user_by_token(f"ABCD{i}Z")  # misses become guest users
        with pytest.raises(auth.TooManySyncGuesses):
            auth.get_user_by_token("ZZZZZ9")
    finally:
        rc.client_ip_var.reset(tok)


def test_other_ip_is_not_blocked(clean_limiter, monkeypatch):
    monkeypatch.setattr(auth, "supabase_request", lambda *a, **k: [])
    t1 = rc.client_ip_var.set("1.2.3.4")
    try:
        for i in range(3):
            auth.get_user_by_token(f"ABCD{i}Y")
    finally:
        rc.client_ip_var.reset(t1)
    t2 = rc.client_ip_var.set("5.6.7.8")
    try:
        assert auth.get_user_by_token("QQQQQ1")["is_guest"] is True
    finally:
        rc.client_ip_var.reset(t2)


def test_valid_code_still_works_and_is_not_counted(clean_limiter, monkeypatch):
    monkeypatch.setattr(auth, "supabase_request", lambda *a, **k: [{"id": "u1", "email": "a@b.c", "sync_code": "GOOD42"}])
    tok = rc.client_ip_var.set("1.2.3.4")
    try:
        for _ in range(10):
            auth._token_cache.clear() if hasattr(auth._token_cache, "clear") else None
            assert auth.get_user_by_token("GOOD42")["id"] == "u1"
    finally:
        rc.client_ip_var.reset(tok)


def test_new_sync_codes_are_long(monkeypatch):
    monkeypatch.setattr(auth, "supabase_request", lambda *a, **k: [])
    assert len(auth._generate_unique_sync_code()) == 10


# ── saved LLM keys ──────────────────────────────────────────────────────────────
def test_secret_roundtrip_and_passthrough(monkeypatch):
    monkeypatch.setenv("KEY_ENCRYPTION_SECRET", "unit-test-secret")
    enc = ss.encrypt_secret("sk-ant-abcdef123456")
    assert enc is not None
    assert enc.startswith("enc:v1:") and "sk-ant" not in enc
    assert ss.decrypt_secret(enc) == "sk-ant-abcdef123456"
    assert ss.decrypt_secret("AIzaOldPlainKey") == "AIzaOldPlainKey"  # saved before encryption existed


def test_secret_without_env_is_plaintext_and_encrypted_value_is_unreadable(monkeypatch):
    monkeypatch.setenv("KEY_ENCRYPTION_SECRET", "s1")
    enc = ss.encrypt_secret("sk-proj-xyz")
    monkeypatch.delenv("KEY_ENCRYPTION_SECRET")
    assert ss.encrypt_secret("sk-proj-xyz") == "sk-proj-xyz"
    assert ss.decrypt_secret(enc) is None


def test_wrong_secret_does_not_leak(monkeypatch):
    monkeypatch.setenv("KEY_ENCRYPTION_SECRET", "s1")
    enc = ss.encrypt_secret("sk-proj-xyz")
    monkeypatch.setenv("KEY_ENCRYPTION_SECRET", "s2")
    assert ss.decrypt_secret(enc) is None


def test_mask_shows_only_last_four():
    m = ss.mask_secret("sk-ant-abcdef123456")
    assert m == {"gemini_api_key_set": True, "gemini_api_key_hint": "3456"}
    assert ss.mask_secret(None) == {"gemini_api_key_set": False, "gemini_api_key_hint": ""}


def test_user_me_never_returns_the_key(monkeypatch):
    from fastapi.testclient import TestClient
    import main
    from routes import auth_routes

    async def fake_user(token):
        return {"id": "u1", "email": "a@b.c", "sync_code": "GOOD42", "gemini_api_key": "sk-ant-SECRETSECRET1234"}

    monkeypatch.setattr(auth_routes, "async_get_user_by_token", fake_user)
    monkeypatch.setattr(auth_routes, "supabase_request", lambda *a, **k: [])
    r = TestClient(main.app).get("/user/me", headers={"Authorization": "Bearer GOOD42"})
    assert r.status_code == 200
    assert "SECRETSECRET" not in r.text
    body = r.json()
    assert body["gemini_api_key_set"] is True and body["gemini_api_key_hint"] == "1234"
    assert "gemini_api_key" not in body


# ── LLM endpoint limits ─────────────────────────────────────────────────────────
def test_llm_endpoints_are_rate_limited_per_ip():
    from fastapi import HTTPException
    from routes import ai_routes, job_routes
    job_routes._rate_limits.clear()
    req = _request(ip="8.8.8.8")
    for _ in range(40):
        ai_routes._limit_llm_call(req, "answer_question", None)
    with pytest.raises(HTTPException) as e:
        ai_routes._limit_llm_call(req, "answer_question", None)
    assert e.value.status_code == 429
    job_routes._rate_limits.clear()


# ── API docs, CORS ──────────────────────────────────────────────────────────────
def test_api_docs_are_off_by_default():
    import main
    assert main.app.openapi_url is None and main.app.docs_url is None and main.app.redoc_url is None


def test_cors_does_not_allow_credentials():
    import main
    from starlette.middleware.cors import CORSMiddleware
    cors = [m for m in main.app.user_middleware if m.cls is CORSMiddleware][0]
    assert cors.kwargs["allow_credentials"] is False


# ── agent success detection ─────────────────────────────────────────────────────
@pytest.mark.parametrize("text", [
    "BLOCKED: On Workday sign-in ... the application was NOT submitted.",
    "Could not complete the application ... nothing was submitted.",
    "Application was not submitted because a required field was empty",
])
def test_negated_results_are_never_a_success(text):
    from services.browser_use_agent import _SUBMISSION_DENIED_MARKERS
    low = text.lower()
    assert any(m in low for m in _SUBMISSION_DENIED_MARKERS) or low.lstrip().startswith("blocked")


def test_real_confirmation_is_not_denied():
    from services.browser_use_agent import _SUBMISSION_DENIED_MARKERS
    low = "SUBMISSION_CONFIRMED: Application for Data Intern has been successfully submitted.".lower()
    assert not any(m in low for m in _SUBMISSION_DENIED_MARKERS)


def test_rotate_sync_code_endpoint(monkeypatch):
    from fastapi.testclient import TestClient
    import main
    from routes import auth_routes

    async def fake_user(token):
        return {"id": "u1", "email": "a@b.c", "sync_code": "GOOD42"}

    monkeypatch.setattr(auth_routes, "async_get_user_by_token", fake_user)
    monkeypatch.setattr(auth, "rotate_user_sync_code", lambda uid: "NEWCODE1234")
    c = TestClient(main.app)
    r = c.post("/user/rotate_sync_code", headers={"Authorization": "Bearer GOOD42"})
    assert r.status_code == 200 and r.json() == {"sync_code": "NEWCODE1234"}
    assert c.post("/user/rotate_sync_code").status_code == 401


# ── per-site portal passwords ──────────────────────────────────────────────────
def test_portal_passwords_differ_per_site_and_are_stable():
    from services.browser_use_agent import derive_portal_password as d
    a, b = d("seed", "greenhouse.io"), d("seed", "lever.co")
    assert a != b and a == d("seed", "greenhouse.io") and a != d("other-seed", "greenhouse.io")
    assert len(a) == 18 and any(c.isupper() for c in a) and any(c.islower() for c in a)
    assert any(c.isdigit() for c in a) and a.endswith("!")


def _prompt(monkeypatch, mode):
    from services.browser_use_agent import build_application_task_prompt
    monkeypatch.setenv("PORTALS_PASSWORD", "SharedSecret#1")
    if mode:
        monkeypatch.setenv("PORTALS_PASSWORD_MODE", mode)
    else:
        monkeypatch.delenv("PORTALS_PASSWORD_MODE", raising=False)
    return build_application_task_prompt("https://example.com/job", {"name": "A", "email": "a@b.c", "phone": "+447000000000", "location": "London, UK"}, None, True)


def test_default_mode_keeps_the_shared_password(monkeypatch):
    text = _prompt(monkeypatch, None)
    assert "SharedSecret#1" in text and "PASSWORD TABLE" not in text


def test_per_site_mode_hides_the_shared_password(monkeypatch):
    from services.browser_use_agent import derive_portal_password as d
    text = _prompt(monkeypatch, "per_site")
    assert "SharedSecret#1" not in text
    assert "PASSWORD TABLE" in text and d("SharedSecret#1", "greenhouse.io") in text
    assert d("SharedSecret#1", "other") in text


def test_prompt_has_security_rules(monkeypatch):
    assert "untrusted data" in _prompt(monkeypatch, None)
