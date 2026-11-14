"""
Model Context Protocol (MCP) OAuth 2.1 Authorization Server Router.
Implements RFC 8414, RFC 9728, RFC 7591 (DCR), and PKCE S256 for Claude.ai Custom Connectors.
"""

import os
import time
import json
import uuid
import hashlib
import base64
import urllib.parse
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, Request, Response, HTTPException, Form
from fastapi.responses import RedirectResponse, JSONResponse, HTMLResponse
from pydantic import BaseModel

from services.auth import (
    create_or_get_user,
    create_session,
    get_user_by_token,
    supabase_request,
    _is_local_deployment
)

router = APIRouter(tags=["MCP OAuth 2.1 Authorization"])

# In-memory ephemeral storage for OAuth authorization requests & client registrations
_OAUTH_CLIENTS: Dict[str, Dict[str, Any]] = {}
_AUTH_CODES: Dict[str, Dict[str, Any]] = {}
_AUTH_SESSIONS: Dict[str, Dict[str, Any]] = {}


def _get_base_url(request: Request) -> str:
    """Returns canonical HTTPS base URL for OAuth metadata."""
    forwarded_host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
    if forwarded_host:
        return f"https://{forwarded_host}"
    base = str(request.base_url).rstrip("/")
    if base.startswith("http://") and not ("localhost" in base or "127.0.0.1" in base):
        base = "https://" + base[len("http://"):]
    return base


# ─── 1. RFC 9728 Protected Resource Metadata ──────────────────────────────────
@router.get("/.well-known/oauth-protected-resource")
@router.get("/.well-known/oauth-protected-resource/mcp")
@router.get("/mcp/.well-known/oauth-protected-resource")
async def oauth_protected_resource_metadata(request: Request):
    """
    RFC 9728 Protected Resource Metadata document.
    Informs Claude that this server is an MCP resource protected by OAuth 2.1.
    """
    base = _get_base_url(request)
    return {
        "resource": f"{base}/mcp",
        "authorization_servers": [base],
        "scopes_supported": ["mcp:tools"],
        "bearer_methods_supported": ["header"]
    }


# ─── 2. RFC 8414 Authorization Server Metadata ────────────────────────────────
@router.get("/.well-known/oauth-authorization-server")
@router.get("/.well-known/openid-configuration")
async def oauth_authorization_server_metadata(request: Request):
    """
    RFC 8414 Authorization Server Metadata.
    Advertises OAuth 2.1 endpoints, DCR support, and PKCE requirements to Claude.
    """
    base = _get_base_url(request)
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/oauth/authorize",
        "token_endpoint": f"{base}/oauth/token",
        "registration_endpoint": f"{base}/oauth/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none", "client_secret_post"],
        "scopes_supported": ["mcp:tools"],
        "client_id_metadata_document_supported": True
    }


# ─── 3. RFC 7591 Dynamic Client Registration (DCR) ────────────────────────────
class ClientRegistrationPayload(BaseModel):
    client_name: Optional[str] = "Claude MCP Client"
    redirect_uris: List[str]
    grant_types: Optional[List[str]] = ["authorization_code"]
    response_types: Optional[List[str]] = ["code"]
    token_endpoint_auth_method: Optional[str] = "none"


@router.post("/oauth/register")
async def oauth_register_client(payload: ClientRegistrationPayload):
    """
    RFC 7591 Dynamic Client Registration endpoint.
    Accepts Claude's registration and returns a client_id.
    """
    client_id = f"claude_client_{uuid.uuid4().hex[:16]}"
    _OAUTH_CLIENTS[client_id] = {
        "client_id": client_id,
        "client_name": payload.client_name,
        "redirect_uris": payload.redirect_uris,
        "created_at": time.time()
    }
    return JSONResponse(
        status_code=201,
        content={
            "client_id": client_id,
            "client_name": payload.client_name,
            "redirect_uris": payload.redirect_uris,
            "grant_types": payload.grant_types,
            "response_types": payload.response_types,
            "token_endpoint_auth_method": payload.token_endpoint_auth_method
        }
    )


# ─── 4. OAuth Authorize Endpoint (Prompt & Login) ─────────────────────────────
@router.get("/oauth/authorize")
async def oauth_authorize(
    request: Request,
    response_type: str = "code",
    client_id: str = "",
    redirect_uri: str = "",
    scope: str = "mcp:tools",
    state: str = "",
    code_challenge: str = "",
    code_challenge_method: str = "S256",
    resource: Optional[str] = None
):
    """
    OAuth 2.1 /authorize endpoint.
    Renders login & authorization consent screen where the user authenticates with Job Finder.
    """
    session_id = uuid.uuid4().hex
    _AUTH_SESSIONS[session_id] = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": code_challenge_method,
        "resource": resource,
        "created_at": time.time()
    }

    # Google OAuth Login deep-link with redirect back to consent approval
    base = _get_base_url(request)
    google_return_path = f"/oauth/consent?session={session_id}"
    google_login_url = f"{base}/auth/google?redirect_to={urllib.parse.quote(google_return_path)}"

    # Render branded consent page
    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8">
      <title>Sign in with Job Finder</title>
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <style>
        body {{
          font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
          background: #0f172a;
          color: #f8fafc;
          display: flex;
          justify-content: center;
          align-items: center;
          height: 100vh;
          margin: 0;
        }}
        .card {{
          background: #1e293b;
          border: 1px solid #334155;
          border-radius: 16px;
          padding: 32px;
          width: 100%;
          max-width: 420px;
          box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.5);
          text-align: center;
        }}
        .logo {{ font-size: 36px; margin-bottom: 8px; }}
        h2 {{ margin: 0 0 8px 0; font-size: 22px; color: #ffffff; }}
        p {{ color: #94a3b8; font-size: 14px; line-height: 1.5; margin-bottom: 24px; }}
        .btn {{
          display: block;
          width: 100%;
          box-sizing: border-box;
          padding: 12px 20px;
          border-radius: 8px;
          font-size: 15px;
          font-weight: 600;
          text-decoration: none;
          cursor: pointer;
          transition: all 0.2s;
        }}
        .btn-google {{
          background: #ffffff;
          color: #1e293b;
          margin-bottom: 16px;
          border: none;
        }}
        .btn-google:hover {{ background: #e2e8f0; }}
        .divider {{
          display: flex;
          align-items: center;
          margin: 20px 0;
          color: #64748b;
          font-size: 13px;
        }}
        .divider::before, .divider::after {{
          content: "";
          flex: 1;
          height: 1px;
          background: #334155;
        }}
        .divider span {{ padding: 0 10px; }}
        input[type="text"] {{
          width: 100%;
          box-sizing: border-box;
          padding: 12px;
          border-radius: 8px;
          border: 1px solid #475569;
          background: #0f172a;
          color: #fff;
          font-size: 16px;
          text-align: center;
          letter-spacing: 2px;
          text-transform: uppercase;
          margin-bottom: 12px;
        }}
        .btn-code {{
          background: #3b82f6;
          color: #ffffff;
          border: none;
        }}
        .btn-code:hover {{ background: #2563eb; }}
      </style>
    </head>
    <body>
      <div class="card">
        <div class="logo">🚀</div>
        <h2>Connect Claude to Job Finder</h2>
        <p>Sign in to allow Claude to access your personalized candidate profile, tailor resumes, and view tracked applications.</p>
        
        <a href="/auth/google?redirect_to={urllib.parse.quote(google_return_path)}" class="btn btn-google">Sign in with Google</a>
        
        <div class="divider"><span>OR QUICK LINK WITH SYNC CODE</span></div>
        
        <form method="POST" action="/oauth/quick-approve">
          <input type="hidden" name="session_id" value="{session_id}">
          <input type="text" name="sync_code" placeholder="ENTER 6-DIGIT SYNC CODE" maxlength="8" required>
          <button type="submit" class="btn btn-code">Authorize with Sync Code</button>
        </form>
      </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html)


@router.post("/oauth/quick-approve")
async def oauth_quick_approve(
    session_id: str = Form(...),
    sync_code: str = Form(...)
):
    """Approves OAuth flow via 6-digit sync code directly."""
    auth_req = _AUTH_SESSIONS.get(session_id)
    if not auth_req:
        raise HTTPException(status_code=400, detail="OAuth authorization session expired. Please retry.")

    clean_code = sync_code.strip().upper()
    user = get_user_by_token(clean_code)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid sync code. Please check your Job Finder profile.")

    # Generate authorization code
    auth_code = f"mcp_code_{uuid.uuid4().hex}"
    _AUTH_CODES[auth_code] = {
        "auth_code": auth_code,
        "user_id": user.get("id"),
        "user_token": clean_code,
        "client_id": auth_req.get("client_id"),
        "redirect_uri": auth_req.get("redirect_uri"),
        "code_challenge": auth_req.get("code_challenge"),
        "code_challenge_method": auth_req.get("code_challenge_method"),
        "created_at": time.time()
    }

    # Redirect back to Claude
    redirect_uri = auth_req["redirect_uri"]
    state = auth_req["state"]
    query_params = {"code": auth_code}
    if state:
        query_params["state"] = state

    target = f"{redirect_uri}{'&' if '?' in redirect_uri else '?'}{urllib.parse.urlencode(query_params)}"
    return RedirectResponse(url=target, status_code=302)


@router.get("/oauth/consent")
async def oauth_consent(
    session: str,
    token: Optional[str] = None
):
    """Callback after Google OAuth completes to issue the authorization code back to Claude."""
    auth_req = _AUTH_SESSIONS.get(session)
    if not auth_req:
        raise HTTPException(status_code=400, detail="OAuth authorization session expired. Please retry.")

    if not token:
        raise HTTPException(status_code=401, detail="Authentication failed: No token received.")

    user = get_user_by_token(token)
    auth_code = f"mcp_code_{uuid.uuid4().hex}"
    _AUTH_CODES[auth_code] = {
        "auth_code": auth_code,
        "user_id": user.get("id") if user else None,
        "user_token": token,
        "client_id": auth_req.get("client_id"),
        "redirect_uri": auth_req.get("redirect_uri"),
        "code_challenge": auth_req.get("code_challenge"),
        "code_challenge_method": auth_req.get("code_challenge_method"),
        "created_at": time.time()
    }

    redirect_uri = auth_req["redirect_uri"]
    state = auth_req["state"]
    query_params = {"code": auth_code}
    if state:
        query_params["state"] = state

    target = f"{redirect_uri}{'&' if '?' in redirect_uri else '?'}{urllib.parse.urlencode(query_params)}"
    return RedirectResponse(url=target, status_code=302)


# ─── 5. OAuth Token Exchange Endpoint ─────────────────────────────────────────
@router.post("/oauth/token")
async def oauth_token(
    grant_type: str = Form("authorization_code"),
    code: Optional[str] = Form(None),
    redirect_uri: Optional[str] = Form(None),
    client_id: Optional[str] = Form(None),
    code_verifier: Optional[str] = Form(None)
):
    """
    OAuth 2.1 /token endpoint.
    Validates PKCE S256 verifier and returns user access token to Claude.
    """
    if grant_type == "authorization_code":
        if not code or code not in _AUTH_CODES:
            raise HTTPException(status_code=400, detail="Invalid or expired authorization code.")

        auth_record = _AUTH_CODES.pop(code)

        # Validate PKCE S256 if challenge was provided
        code_challenge = auth_record.get("code_challenge")
        if code_challenge and code_verifier:
            # SHA256 base64url encode
            digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
            calculated_challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
            if calculated_challenge != code_challenge:
                raise HTTPException(status_code=400, detail="Invalid code_verifier (PKCE validation failed).")

        user_token = auth_record["user_token"]
        return {
            "access_token": user_token,
            "token_type": "Bearer",
            "expires_in": 3600 * 24 * 30,  # 30-day token
            "scope": "mcp:tools"
        }

    elif grant_type == "refresh_token":
        return {
            "access_token": code or str(uuid.uuid4()),
            "token_type": "Bearer",
            "expires_in": 3600 * 24 * 30,
            "scope": "mcp:tools"
        }

    raise HTTPException(status_code=400, detail=f"Unsupported grant_type '{grant_type}'.")
