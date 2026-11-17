"""Cloud /mcp must reject tokens that match no account; MCP server info carries the site icon."""
import asyncio
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from job_finder_mcp.server import process_mcp_request
from routes import mcp_routes
from services import auth


def _client(monkeypatch, user):
    monkeypatch.setattr(mcp_routes, "_is_local_deployment", lambda: False)
    monkeypatch.setattr(mcp_routes, "get_user_by_token", lambda token: user)
    app = FastAPI()
    app.include_router(mcp_routes.router)
    return TestClient(app)


PING = {"jsonrpc": "2.0", "id": 1, "method": "ping"}


def test_cloud_mcp_rejects_unknown_token_as_guest(monkeypatch):
    c = _client(monkeypatch, {"id": "guest_abc", "is_guest": True})
    r = c.post("/mcp", json=PING, headers={"Authorization": "Bearer not-a-real-token"})
    assert r.status_code == 401
    assert r.json()["error"] == "invalid_token"
    assert "resource_metadata" in r.headers["www-authenticate"]


def test_cloud_mcp_rejects_missing_user(monkeypatch):
    c = _client(monkeypatch, None)
    assert c.post("/mcp", json=PING, headers={"Authorization": "Bearer x"}).status_code == 401


def test_cloud_mcp_accepts_a_real_account(monkeypatch):
    c = _client(monkeypatch, {"id": "u1", "email": "a@example.com"})
    r = c.post("/mcp", json=PING, headers={"Authorization": "Bearer realtoken"})
    assert r.status_code == 200


def test_test_token_shortcut_is_off_outside_tests(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("ALLOW_TEST_TOKENS", raising=False)
    monkeypatch.setattr(auth, "supabase_request", lambda *a, **k: None)
    user = auth.get_user_by_token("test_anything")
    assert user.get("id") != "test_user_id"
    assert user.get("is_guest") is True


def test_initialize_returns_site_icons():
    res = asyncio.run(process_mcp_request({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                           "params": {"protocolVersion": "2025-06-18", "capabilities": {}}}))
    info = res["result"]["serverInfo"]
    assert info["title"] == "Job Finder"
    srcs = [i["src"] for i in info["icons"]]
    assert any(s.endswith("/favicon-192.png") for s in srcs)
    assert any(s.endswith("/favicon.svg") for s in srcs)


def test_favicon_ico_ships_as_a_real_icon():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "frontend", "public", "favicon.ico")
    with open(path, "rb") as f:
        assert f.read(4) == b"\x00\x00\x01\x00"


def test_user_profile_save_never_writes_the_shared_config(monkeypatch, tmp_path):
    """POST /user/profile on a deployed server must not put a user's details into the shared profile file."""
    import json
    from routes import auth_routes
    shared = tmp_path / "candidate_profile.json"
    shared.write_text(json.dumps({"candidate": {"name": "Template"}}))
    monkeypatch.setenv("CANDIDATE_PROFILE_PATH", str(shared))
    monkeypatch.setattr("services.auth._is_local_deployment", lambda: False)
    app = FastAPI()
    app.include_router(auth_routes.router)
    r = TestClient(app).post("/user/profile", headers={"Authorization": "Bearer someone"},
                             json={"name": "Someone Else", "email": "x@example.com"})
    assert r.status_code == 200
    assert json.loads(shared.read_text())["candidate"]["name"] == "Template"
