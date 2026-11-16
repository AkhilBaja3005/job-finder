"""
Comprehensive Test Suite for MCP OAuth 2.1 & Multi-Tenant Authentication Flow.
Covers:
- RFC 9728 Protected Resource Metadata
- RFC 8414 Authorization Server Metadata Discovery
- RFC 7591 Dynamic Client Registration (DCR)
- OAuth Authorize Consent Page rendering & PKCE S256 parameters
- Quick Sync Code Approval
- OAuth /token exchange with PKCE verification
- Authenticated vs Unauthenticated MCP Profile Resolution
"""

import re
import pytest
import hashlib
import base64
from fastapi.testclient import TestClient
from backend.main import app
try:
    from services.session_store import set_session_data
except ImportError:
    from backend.services.session_store import set_session_data


@pytest.fixture
def client():
    return TestClient(app)


def test_rfc9728_protected_resource_metadata(client):
    """Validates that RFC 9728 endpoint advertises MCP resource and authorization server."""
    res = client.get("/.well-known/oauth-protected-resource")
    assert res.status_code == 200
    data = res.json()
    assert "/mcp" in data["resource"]
    assert len(data["authorization_servers"]) >= 1
    assert "mcp:tools" in data["scopes_supported"]
    assert "header" in data["bearer_methods_supported"]


def test_rfc8414_authorization_server_metadata(client):
    """Validates that RFC 8414 endpoint advertises endpoints, PKCE S256, and DCR."""
    res = client.get("/.well-known/oauth-authorization-server")
    assert res.status_code == 200
    data = res.json()
    assert data["authorization_endpoint"].endswith("/oauth/authorize")
    assert data["token_endpoint"].endswith("/oauth/token")
    assert data["registration_endpoint"].endswith("/oauth/register")
    assert "S256" in data["code_challenge_methods_supported"]
    assert "code" in data["response_types_supported"]


def test_rfc7591_dynamic_client_registration(client):
    """Validates that Claude or MCP clients can dynamically register via RFC 7591."""
    payload = {
        "client_name": "Claude Desktop / Web Connector",
        "redirect_uris": ["https://claude.ai/oauth/callback"]
    }
    res = client.post("/oauth/register", json=payload)
    assert res.status_code == 201
    data = res.json()
    assert data["client_id"].startswith("claude_client_")
    assert data["redirect_uris"] == ["https://claude.ai/oauth/callback"]


def test_oauth_authorize_screen_and_pkce_flow(client, monkeypatch):
    """Tests the full OAuth 2.1 flow: authorize screen -> sync code approval -> token exchange."""
    # Register client
    reg = client.post("/oauth/register", json={"redirect_uris": ["https://claude.ai/oauth/callback"]})
    client_id = reg.json()["client_id"]

    # Generate PKCE verifier and challenge
    code_verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")

    # Mock a real (non-guest) user so the test does not depend on Supabase or a real sync code
    from routes import oauth_routes
    monkeypatch.setattr(
        oauth_routes, "get_user_by_token",
        lambda token: {"id": 42, "email": "user@example.com"} if token == "TESTCODE" else {"id": "guest_x", "is_guest": True},
    )
    monkeypatch.setattr(oauth_routes, "create_session", lambda user_id: "session-token-for-test")

    # Request authorize page
    auth_res = client.get(
        f"/oauth/authorize?response_type=code&client_id={client_id}&redirect_uri=https://claude.ai/oauth/callback&state=xyz987&code_challenge={code_challenge}&code_challenge_method=S256"
    )
    assert auth_res.status_code == 200
    assert "Connect Claude to Job Finder" in auth_res.text

    session_match = re.search(r"name=\"session_id\"\s+value=\"([a-f0-9]+)\"", auth_res.text)
    assert session_match is not None
    session_id = session_match.group(1)

    # Approve with the mocked user sync code
    approve_res = client.post(
        "/oauth/quick-approve",
        data={"session_id": session_id, "sync_code": "TESTCODE"},
        follow_redirects=False
    )
    assert approve_res.status_code == 302
    location = approve_res.headers["location"]
    assert "https://claude.ai/oauth/callback" in location
    assert "code=mcp_code_" in location
    assert "state=xyz987" in location

    code_match = re.search(r"code=([^&]+)", location)
    assert code_match is not None
    auth_code = code_match.group(1)

    # Exchange code for token with PKCE verifier
    token_res = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": auth_code,
            "client_id": client_id,
            "redirect_uri": "https://claude.ai/oauth/callback",
            "code_verifier": code_verifier
        }
    )
    assert token_res.status_code == 200
    token_data = token_res.json()
    assert token_data["token_type"] == "Bearer"
    # A dedicated session token is issued; the sync code is never the bearer token
    assert token_data["access_token"] == "session-token-for-test"
    assert token_data["scope"] == "mcp:tools"


def test_mcp_profile_token_isolation(client):
    """Validates that MCP profile resolution isolates candidate data per user token."""
    # Seed mock user session
    set_session_data("usr_bob_777", {
        "name": "Bob Vance",
        "email": "bob@vancerefrigeration.com",
        "skills": ["HVAC", "Sales"],
        "education": [{"degree": "B.A."}]
    }, "")

    # Query with Bob's Bearer token
    res = client.post(
        "/mcp",
        headers={"Authorization": "Bearer usr_bob_777"},
        json={
            "jsonrpc": "2.0",
            "id": 10,
            "method": "tools/call",
            "params": {"name": "get_candidate_profile", "arguments": {}}
        }
    )
    assert res.status_code == 200
    body = res.json()
    import json
    data = json.loads(body["result"]["content"][0]["text"])
    assert data["found"] is True
    assert data["profile"]["candidate"]["name"] == "Bob Vance"
    assert data["profile"]["candidate"]["email"] == "bob@vancerefrigeration.com"


def _register(client, uri="https://claude.ai/oauth/callback"):
    return client.post("/oauth/register", json={"redirect_uris": [uri]}).json()["client_id"]


def test_authorize_rejects_unknown_client(client):
    res = client.get("/oauth/authorize?response_type=code&client_id=nope&redirect_uri=https://evil.example/cb&code_challenge=abc&code_challenge_method=S256")
    assert res.status_code == 400


def test_authorize_rejects_unregistered_redirect_uri(client):
    cid = _register(client)
    res = client.get(f"/oauth/authorize?response_type=code&client_id={cid}&redirect_uri=https://evil.example/cb&code_challenge=abc&code_challenge_method=S256")
    assert res.status_code == 400


def test_authorize_requires_pkce(client):
    cid = _register(client)
    res = client.get(f"/oauth/authorize?response_type=code&client_id={cid}&redirect_uri=https://claude.ai/oauth/callback")
    assert res.status_code == 400


def test_token_rejects_refresh_grant_and_garbage(client):
    res = client.post("/oauth/token", data={"grant_type": "refresh_token", "code": "anything"})
    assert res.status_code == 400
    res = client.post("/oauth/token", data={"grant_type": "authorization_code", "code": "bogus"})
    assert res.status_code == 400


def test_token_requires_code_verifier(client):
    from routes import oauth_routes
    oauth_routes._AUTH_CODES["mcp_code_test"] = {
        "auth_code": "mcp_code_test", "user_id": 1, "user_token": "tok",
        "client_id": "c", "redirect_uri": "https://x/cb",
        "code_challenge": "abc", "code_challenge_method": "S256", "created_at": __import__("time").time(),
    }
    res = client.post("/oauth/token", data={"grant_type": "authorization_code", "code": "mcp_code_test", "client_id": "c", "redirect_uri": "https://x/cb"})
    assert res.status_code == 400


def test_expired_auth_code_rejected(client):
    from routes import oauth_routes
    oauth_routes._AUTH_CODES["mcp_code_old"] = {
        "auth_code": "mcp_code_old", "user_token": "tok", "client_id": "c",
        "redirect_uri": "https://x/cb", "code_challenge": "abc", "created_at": 0,
    }
    res = client.post("/oauth/token", data={"grant_type": "authorization_code", "code": "mcp_code_old", "code_verifier": "v"})
    assert res.status_code == 400


def test_quick_approve_rate_limited(client):
    from routes import oauth_routes
    oauth_routes._SYNC_FAILURES.clear()
    cid = _register(client)
    page = client.get(f"/oauth/authorize?response_type=code&client_id={cid}&redirect_uri=https://claude.ai/oauth/callback&code_challenge=abc&code_challenge_method=S256")
    sid_match = re.search(r"name=\"session_id\"\s+value=\"([a-f0-9]+)\"", page.text)
    assert sid_match is not None
    sid = sid_match.group(1)
    codes = []
    for _ in range(oauth_routes.SYNC_CODE_MAX_FAILURES + 1):
        codes.append(client.post("/oauth/quick-approve", data={"session_id": sid, "sync_code": "ZZZZZZ"}).status_code)
    assert codes[-1] == 429, codes
    oauth_routes._SYNC_FAILURES.clear()


def test_client_registration_survives_restart(client):
    """A registered client_id must stay valid after in-memory state is lost (restart / other worker)."""
    from routes import oauth_routes
    cid = _register(client)
    oauth_routes._OAUTH_CLIENTS.clear()
    res = client.get(f"/oauth/authorize?response_type=code&client_id={cid}&redirect_uri=https://claude.ai/oauth/callback&code_challenge=abc&code_challenge_method=S256")
    assert res.status_code == 200


def test_tampered_client_id_rejected_with_invalid_client(client):
    cid = _register(client)
    # Always change the last signature character (a fixed "0" would be a no-op 1 time in 16)
    tampered = cid[:-1] + ("1" if cid[-1] == "0" else "0")
    res = client.get(f"/oauth/authorize?response_type=code&client_id={tampered}&redirect_uri=https://claude.ai/oauth/callback&code_challenge=abc&code_challenge_method=S256")
    assert res.status_code == 400
    assert res.json()["error"] == "invalid_client"
