"""Export and delete for one account."""
from starlette.testclient import TestClient

import routes.auth_routes as auth_routes
import services.account_data as account_data
from main import app

client = TestClient(app)
USER = {"id": 7, "email": "Me@Example.com", "sync_code": "ABC123", "gemini_api_key": "enc:secret", "send_tailored_email": True}
H = {"Authorization": "Bearer ABC123"}


def _as(monkeypatch, user):
    async def fake(token):
        return user
    monkeypatch.setattr(auth_routes, "async_get_user_by_token", fake)


def test_export_needs_a_real_account(monkeypatch):
    _as(monkeypatch, None)
    assert client.get("/user/export", headers=H).status_code == 401
    _as(monkeypatch, {"id": "guest_1"})
    assert client.get("/user/export", headers=H).status_code == 401


def test_export_never_contains_the_saved_key(monkeypatch):
    _as(monkeypatch, USER)
    monkeypatch.setattr(account_data, "supabase_request", lambda path, method="GET", data=None: [{"job_url": "u"}] if path.startswith("applications") else [])
    body = client.get("/user/export", headers=H).json()
    assert body["account"]["has_saved_api_key"] is True
    assert "enc:secret" not in str(body)
    assert body["applications"] == [{"job_url": "u"}]


def test_delete_requires_matching_email(monkeypatch):
    _as(monkeypatch, USER)
    calls = []
    monkeypatch.setattr(account_data, "supabase_request", lambda path, method="GET", data=None: calls.append((method, path)) or [])
    assert client.request("DELETE", "/user/account", json={"confirm_email": "other@example.com"}, headers=H).status_code == 400
    assert calls == []


def test_delete_removes_rows_in_order_and_confirms(monkeypatch):
    _as(monkeypatch, USER)
    calls = []
    monkeypatch.setattr(account_data, "supabase_request", lambda path, method="GET", data=None: calls.append((method, path)) or [])
    r = client.request("DELETE", "/user/account", json={"confirm_email": " me@example.com "}, headers=H)
    assert r.status_code == 200 and r.json() == {"status": "deleted"}
    deletes = [p for m, p in calls if m == "DELETE"]
    assert deletes == ["applications?user_id=eq.7", "user_resumes?user_id=eq.7", "sessions?user_id=eq.7", "users?id=eq.7"]


def test_delete_reports_failure_when_rows_remain(monkeypatch):
    _as(monkeypatch, USER)
    monkeypatch.setattr(account_data, "supabase_request", lambda path, method="GET", data=None: [{"id": 7}] if method == "GET" else [])
    r = client.request("DELETE", "/user/account", json={"confirm_email": "me@example.com"}, headers=H)
    assert r.status_code == 502
