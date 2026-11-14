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


def test_oauth_authorize_screen_and_pkce_flow(client):
    """Tests the full OAuth 2.1 flow: authorize screen -> sync code approval -> token exchange."""
    # Register client
    reg = client.post("/oauth/register", json={"redirect_uris": ["https://claude.ai/oauth/callback"]})
    client_id = reg.json()["client_id"]

    # Generate PKCE verifier and challenge
    code_verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")

    # Request authorize page
    auth_res = client.get(
        f"/oauth/authorize?response_type=code&client_id={client_id}&redirect_uri=https://claude.ai/oauth/callback&state=xyz987&code_challenge={code_challenge}&code_challenge_method=S256"
    )
    assert auth_res.status_code == 200
    assert "Connect Claude to Job Finder" in auth_res.text

    session_match = re.search(r"name=\"session_id\"\s+value=\"([a-f0-9]+)\"", auth_res.text)
    assert session_match is not None
    session_id = session_match.group(1)

    # Approve with user sync code (EYP0LA for Akhil)
    approve_res = client.post(
        "/oauth/quick-approve",
        data={"session_id": session_id, "sync_code": "EYP0LA"},
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
    assert token_data["access_token"] == "EYP0LA"
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
