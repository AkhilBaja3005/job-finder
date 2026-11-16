"""Regression tests for /auth/google and /auth/callback behavior used by the MCP consent flow."""

import pytest
from fastapi.testclient import TestClient
from backend.main import app
from routes import auth_routes


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(auth_routes, "get_google_auth_url", lambda redirect_uri, state: "https://accounts.google.com/o/oauth2/v2/auth?x=1")
    return TestClient(app)


def test_auth_google_redirects_browser_navigation(client):
    res = client.get("/auth/google?redirect_to=/oauth/consent%3Fsession%3Dabc", headers={"Accept": "text/html"}, follow_redirects=False)
    assert res.status_code == 302
    assert res.headers["location"].startswith("https://accounts.google.com/")


def test_auth_google_returns_json_for_fetch(client):
    res = client.get("/auth/google", headers={"Accept": "application/json"})
    assert res.status_code == 200
    assert res.json()["url"].startswith("https://accounts.google.com/")


def test_callback_joins_token_and_uses_backend_for_oauth_paths(client, monkeypatch):
    monkeypatch.setenv("FRONTEND_URL", "http://localhost:5173")
    monkeypatch.setattr(auth_routes, "exchange_google_code_for_email", lambda code, redirect_uri: ("u@example.com", None))
    monkeypatch.setattr(auth_routes, "create_or_get_user", lambda email, pic: {"id": 1})
    monkeypatch.setattr(auth_routes, "create_session", lambda uid: "tok123")
    res = client.get("/auth/callback", params={"code": "c", "state": "/oauth/consent?session=abc"}, follow_redirects=False)
    loc = res.headers["location"]
    assert "localhost:5173" not in loc
    assert loc.endswith("/oauth/consent?session=abc&token=tok123")
    res = client.get("/auth/callback", params={"code": "c", "state": "/platform"}, follow_redirects=False)
    assert res.headers["location"] == "http://localhost:5173/platform?token=tok123"
