import os
import sqlite3
import uuid
import json
import urllib.request
import urllib.parse
import ssl
from typing import Optional

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
    context = ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(req, context=context) as response:
            resp_body = response.read().decode("utf-8")
            if not resp_body:
                return []
            return json.loads(resp_body)
    except Exception as e:
        print(f"Supabase request error on {method} {path}: {e}")
        return []

def create_or_get_user(email: str) -> dict:
    encoded_email = urllib.parse.quote(email)
    users = supabase_request(f"users?email=eq.{encoded_email}", "GET")
    if users:
        return users[0]
        
    new_users = supabase_request("users", "POST", {"email": email})
    if new_users:
        return new_users[0]
    return {"id": None, "email": email, "gemini_api_key": None}

def create_session(user_id) -> str:
    token = str(uuid.uuid4())
    supabase_request("sessions", "POST", {"token": token, "user_id": user_id})
    return token

def get_user_by_token(token: str) -> Optional[dict]:
    encoded_token = urllib.parse.quote(token)
    sessions = supabase_request(f"sessions?token=eq.{encoded_token}&select=token,user_id,users(id,email,gemini_api_key)", "GET")
    if sessions:
        user_info = sessions[0].get("users")
        if isinstance(user_info, list) and user_info:
            return user_info[0]
        elif isinstance(user_info, dict):
            return user_info
    return None

def update_user_api_key(user_id, api_key: str):
    supabase_request(f"users?id=eq.{user_id}", "PATCH", {"gemini_api_key": api_key})

# Google OAuth Parameters (dynamic lookup helpers)
def get_google_auth_url() -> str:
    client_id = os.getenv("GOOGLE_CLIENT_ID", "")
    redirect_uri = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/callback")
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "consent"
    }
    return f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(params)}"

def exchange_google_code_for_email(code: str) -> str:
    client_id = os.getenv("GOOGLE_CLIENT_ID", "")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "")
    redirect_uri = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/callback")
    
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
    
    context = ssl._create_unverified_context()
    with urllib.request.urlopen(req, context=context) as response:
        token_data = json.loads(response.read().decode("utf-8"))
        
    access_token = token_data["access_token"]
    
    userinfo_url = f"https://www.googleapis.com/oauth2/v3/userinfo?access_token={access_token}"
    req_info = urllib.request.Request(userinfo_url, method="GET")
    with urllib.request.urlopen(req_info, context=context) as response:
        user_info = json.loads(response.read().decode("utf-8"))
        
    return user_info["email"]
