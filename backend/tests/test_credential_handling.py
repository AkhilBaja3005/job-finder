"""Portal password handling and token lookups during a Supabase outage."""
import json
import os
import stat

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routes import mcp_routes
from services import auth


def test_template_ships_no_password():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "candidate_profile.example.json")
    with open(path, encoding="utf-8") as f:
        assert json.load(f)["candidate"]["portals_password"] == ""


def test_setup_stores_password_in_owner_only_env(tmp_path):
    from job_finder.commands.setup import _write_env_value
    env = tmp_path / ".env"
    env.write_text('GEMINI_API_KEY="k"\nPORTALS_PASSWORD="old"')
    _write_env_value(str(env), "PORTALS_PASSWORD", "new-secret")
    text = env.read_text()
    assert text.count("PORTALS_PASSWORD=") == 1 and 'PORTALS_PASSWORD="new-secret"' in text
    assert 'GEMINI_API_KEY="k"' in text
    assert stat.S_IMODE(os.stat(env).st_mode) == 0o600


def test_saved_profile_file_is_owner_only(tmp_path, monkeypatch):
    import asyncio
    from job_finder_mcp.tools import profile_tools as pt
    target = tmp_path / "candidate_profile.json"
    monkeypatch.setenv("CANDIDATE_PROFILE_PATH", str(target))
    monkeypatch.delenv("SPACE_ID", raising=False)
    asyncio.run(pt.handle_save_candidate_profile({"name": "A", "email": "a@example.com"}))
    assert stat.S_IMODE(os.stat(target).st_mode) == 0o600


def test_outage_is_not_cached_as_guest_and_mcp_answers_503(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    auth._token_cache.clear() if hasattr(auth._token_cache, "clear") else None

    def failing(path, method="GET", data=None):
        auth._lookup_state.failed = True
        return []

    monkeypatch.setattr(auth, "supabase_request", failing)
    user = auth.get_user_by_token("ABC123")
    assert user["is_guest"] and user["lookup_failed"]
    assert auth._token_cache.get("ABC123") is None  # a later, healthy lookup is not poisoned

    monkeypatch.setattr(mcp_routes, "_is_local_deployment", lambda: False)
    monkeypatch.setattr(mcp_routes, "get_user_by_token", lambda t: user)
    app = FastAPI()
    app.include_router(mcp_routes.router)
    r = TestClient(app).post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
                             headers={"Authorization": "Bearer ABC123"})
    assert r.status_code == 503 and r.headers["retry-after"] == "10"


def test_unknown_token_with_healthy_supabase_is_cached_as_guest(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(auth, "supabase_request", lambda *a, **k: [])
    user = auth.get_user_by_token("totally-unknown-token")
    assert user is not None
    assert user["is_guest"] and not user.get("lookup_failed")
