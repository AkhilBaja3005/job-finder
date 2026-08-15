import os
import uuid
import json
import asyncio
import urllib.request
import urllib.parse
from typing import Optional

from utils.ssl_utils import SSL_CONTEXT
from utils.ttl_cache import TTLCache

# ── Token → user TTL cache ────────────────────────────────────────────────────
# Avoids hitting Supabase on every authenticated request.
# 120-second TTL is short enough to pick up role/setting changes quickly.
_token_cache: TTLCache = TTLCache(ttl_seconds=120, max_size=2000)
# ─────────────────────────────────────────────────────────────────────────────

# Supabase connection parameters
def get_supabase_client():
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_KEY", "")
    return url, key

def supabase_request(path: str, method: str = "GET", data: dict = None) -> list:
    url_base, key = get_supabase_client()
    if not url_base or not key:
        print("WARNING: Supabase URL or Key not set in environment.")
        return []
    
    url = f"{url_base}/rest/v1/{path}"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }
    
    req_data = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, headers=headers, data=req_data, method=method)
    context = SSL_CONTEXT
    try:
        with urllib.request.urlopen(req, context=context, timeout=15) as response:
            resp_body = response.read().decode("utf-8")
            if not resp_body:
                return []
            return json.loads(resp_body)
    except Exception as e:
        print(f"Supabase request error on {method} {path}: {e}")
        return []

async def async_supabase_request(path: str, method: str = "GET", data: dict = None) -> list:
    """Non-blocking wrapper: runs supabase_request in a thread so it doesn't
    block the asyncio event loop during I/O-heavy Supabase calls."""
    return await asyncio.to_thread(supabase_request, path, method, data)

def create_or_get_user(email: str, picture_url: Optional[str] = None) -> dict:
    encoded_email = urllib.parse.quote(email)
    users = supabase_request(f"users?email=eq.{encoded_email}", "GET")
    if users:
        user = users[0]
        # Generate sync_code if user existed before sync_code column was added
        if not user.get("sync_code"):
            sync_code = generate_user_sync_code(user["id"])
            user["sync_code"] = sync_code
        if picture_url and user.get("picture_url") != picture_url:
            updated = supabase_request(f"users?id=eq.{user['id']}", "PATCH", {"picture_url": picture_url})
            if updated:
                return updated[0]
        return user
        
    # Generate unique 6-character alphanumeric sync code for new user
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    payload = {"email": email, "send_tailored_email": True, "sync_code": code}
    if picture_url:
        payload["picture_url"] = picture_url
    new_users = supabase_request("users", "POST", payload)
    if new_users:
        return new_users[0]
    return {"id": None, "email": email, "gemini_api_key": None, "picture_url": picture_url, "send_tailored_email": True, "sync_code": code}

def create_session(user_id) -> str:
    token = str(uuid.uuid4())
    supabase_request("sessions", "POST", {"token": token, "user_id": user_id})
    return token

def get_user_by_token(token: str) -> Optional[dict]:
    # Fast path: cache hit avoids a Supabase round-trip (~100-300ms saved)
    cached = _token_cache.get(token)
    if cached is not None:
        return cached

    # 1. Check if token is a 6-digit Sync Code (e.g., A7X9K2)
    clean_token = token.strip().upper()
    if len(clean_token) == 6 and clean_token.isalnum():
        users = supabase_request(f"users?sync_code=eq.{clean_token}&select=id,email,gemini_api_key,picture_url,cron_enabled,cron_role,cron_location,cron_time,send_tailored_email,sync_code", "GET")
        if users:
            result = users[0]
            _token_cache.set(token, result)
            return result

    encoded_token = urllib.parse.quote(token)
    sessions = supabase_request(f"sessions?token=eq.{encoded_token}&select=token,user_id,users(id,email,gemini_api_key,picture_url,cron_enabled,cron_role,cron_location,cron_time,send_tailored_email,sync_code)", "GET")
    if sessions:
        user_info = sessions[0].get("users")
        if isinstance(user_info, list) and user_info:
            result = user_info[0]
        elif isinstance(user_info, dict):
            result = user_info
        else:
            return None
        _token_cache.set(token, result)
        return result
    return None

import random
import string

def generate_user_sync_code(user_id) -> str:
    """Generates or fetches a permanent 6-character alphanumeric sync key for linking extension."""
    users = supabase_request(f"users?id=eq.{user_id}&select=sync_code", "GET")
    if users and users[0].get("sync_code"):
        return users[0]["sync_code"]
    
    # Generate unique 6-character alphanumeric code
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    supabase_request(f"users?id=eq.{user_id}", "PATCH", {"sync_code": code})
    return code

async def async_get_user_by_token(token: str) -> Optional[dict]:
    """Non-blocking version of get_user_by_token for use in async handlers."""
    # Cache hit is instant — no thread needed
    cached = _token_cache.get(token)
    if cached is not None:
        return cached
    return await asyncio.to_thread(get_user_by_token, token)

def invalidate_token_cache(token: str):
    """Call after updating user settings so the cache reflects changes immediately."""
    with _token_cache._lock:
        _token_cache._store.pop(token, None)

def update_user_api_key(user_id, api_key: str):
    supabase_request(f"users?id=eq.{user_id}", "PATCH", {"gemini_api_key": api_key})

def update_user_resume_data(user_id, resume_data: dict, master_latex: str = None):
    payload = {"resume_data": json.dumps(resume_data)}
    if master_latex is not None:
        payload["master_latex"] = master_latex
    supabase_request(f"users?id=eq.{user_id}", "PATCH", payload)

# Google OAuth Parameters (dynamic lookup helpers)
def get_google_auth_url(host: Optional[str] = None) -> str:
    client_id = os.getenv("GOOGLE_CLIENT_ID", "")
    redirect_uri = os.getenv("GOOGLE_REDIRECT_URI", "")
    if host and ("job-finder.space" in host or not redirect_uri):
        redirect_uri = f"{host.rstrip('/')}/auth/callback"
    if not redirect_uri:
        redirect_uri = "http://localhost:8000/auth/callback"
        
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "consent"
    }
    return f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(params)}"

def exchange_google_code_for_email(code: str, host: Optional[str] = None) -> tuple[str, Optional[str]]:
    client_id = os.getenv("GOOGLE_CLIENT_ID", "")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "")
    redirect_uri = os.getenv("GOOGLE_REDIRECT_URI", "")
    if host and ("job-finder.space" in host or not redirect_uri):
        redirect_uri = f"{host.rstrip('/')}/auth/callback"
    if not redirect_uri:
        redirect_uri = "http://localhost:8000/auth/callback"
    
    token_url = "https://oauth2.googleapis.com/token"
    data = urllib.parse.urlencode({
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code"
    }).encode("utf-8")
    
    req = urllib.request.Request(
        token_url,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST"
    )
    
    context = SSL_CONTEXT
    with urllib.request.urlopen(req, context=context, timeout=15) as response:
        token_data = json.loads(response.read().decode("utf-8"))

    access_token = token_data["access_token"]

    userinfo_url = f"https://www.googleapis.com/oauth2/v3/userinfo?access_token={access_token}"
    req_info = urllib.request.Request(userinfo_url, method="GET")
    with urllib.request.urlopen(req_info, context=context, timeout=15) as response:
        user_info = json.loads(response.read().decode("utf-8"))
        
    return user_info.get("email"), user_info.get("picture")


def get_optional_token(authorization: Optional[str] = None) -> Optional[str]:
    """FastAPI dependency to extract Bearer token from Header if present."""
    if not authorization:
        return None
    if authorization.startswith("Bearer "):
        return authorization.split("Bearer ")[1].strip()
    return authorization.strip()
