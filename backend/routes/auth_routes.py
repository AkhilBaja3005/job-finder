import os
import json
import urllib.parse
from typing import Optional, Any, Dict, List, Union
from fastapi import APIRouter, HTTPException, Header, Request, BackgroundTasks
from fastapi.responses import RedirectResponse, HTMLResponse
from pydantic import BaseModel

from services.auth import (
    create_or_get_user,
    create_session,
    async_get_user_by_token,
    invalidate_token_cache,
    update_user_api_key,
    get_google_auth_url,
    exchange_google_code_for_email,
    generate_user_sync_code,
    supabase_request,
    _is_local_deployment
)

router = APIRouter(tags=["Authentication & Settings"])


class SubscriptionRequest(BaseModel):
    cron_enabled: bool
    cron_role: Optional[str] = None
    cron_location: Optional[str] = "Remote"
    cron_time: Optional[str] = "18:00:00"
    send_tailored_email: Optional[bool] = True


class SettingsRequest(BaseModel):
    gemini_api_key: str


class ProfileUpdateRequest(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    portfolio: Optional[str] = None
    linkedin: Optional[str] = None
    github: Optional[str] = None
    notice_period: Optional[str] = None
    salary_expectations: Optional[str] = None
    work_auth: Optional[str] = None
    sponsorship: Optional[str] = None
    skills: Optional[Any] = None
    summary: Optional[str] = None
    raw_resume_data: Optional[dict] = None


@router.get("/auth/google")
@router.get("/auth/url")
async def auth_google(request: Request):
    custom_redirect = None
    if not os.getenv("GOOGLE_REDIRECT_URI"):
        custom_redirect = f"{str(request.base_url).rstrip('/')}/auth/callback"
    auth_url = get_google_auth_url(redirect_uri=custom_redirect)
    if not auth_url:
        raise HTTPException(status_code=500, detail="Google OAuth client ID is not configured.")
    return {"url": auth_url}


@router.get("/auth/callback")
async def auth_callback(code: str, request: Request):
    try:
        custom_redirect = None
        if not os.getenv("GOOGLE_REDIRECT_URI"):
            custom_redirect = f"{str(request.base_url).rstrip('/')}/auth/callback"
        email, picture_url = exchange_google_code_for_email(code, redirect_uri=custom_redirect)
        user = create_or_get_user(email, picture_url)
        token = create_session(user["id"])

        frontend_url = os.getenv("FRONTEND_URL")
        if not frontend_url:
            base = str(request.base_url).rstrip("/")
            frontend_url = base
        return RedirectResponse(url=f"{frontend_url.rstrip('/')}?token={token}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"OAuth verification failed: {str(e)}")


@router.post("/auth/mock")
async def auth_mock(request: dict):
    if not _is_local_deployment():
        raise HTTPException(status_code=404, detail="Not Found")
    email = request.get("email", "testuser@example.com")
    user = create_or_get_user(email)
    token = create_session(user["id"])
    return {"token": token}


@router.get("/user/me")
async def user_me(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = authorization.split(" ")[1]
    user = await async_get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid token")
    if not user.get("sync_code") and user.get("id"):
        sync_code = generate_user_sync_code(user["id"])
        user["sync_code"] = sync_code

    if user.get("id") and not str(user.get("id")).startswith("guest_"):
        try:
            res = supabase_request(f"user_resumes?user_id=eq.{user['id']}&select=resume_data", "GET")
            if res and len(res) > 0:
                raw_rdata = res[0].get("resume_data", {})
                rdata = json.loads(raw_rdata) if isinstance(raw_rdata, str) else (raw_rdata or {})
                user["resume_data"] = rdata
                if rdata.get("name"):
                    user["resume_name"] = rdata.get("name")
        except Exception as e:
            print(f"Failed to fetch candidate name for user_me from Supabase: {e}")

    if not user.get("resume_data"):
        try:
            from services.session_store import get_session_data
            sess = get_session_data(token)
            if sess and isinstance(sess.get("data"), dict) and sess["data"]:
                user["resume_data"] = sess["data"]
                if sess["data"].get("name"):
                    user["resume_name"] = sess["data"].get("name")
        except Exception:
            pass

    return user


@router.get("/user/sync_code")
async def get_sync_code(authorization: Optional[str] = Header(None)):
    """Returns user's permanent 6-digit alphanumeric extension sync key."""
    token = authorization.split(" ")[1] if authorization and authorization.startswith("Bearer ") else None
    user = await async_get_user_by_token(token) if token else None
    if not user or not user.get("id"):
        guest_key = (token or "guest")[:6].upper()
        return {"sync_code": guest_key}

    code = generate_user_sync_code(user["id"])
    return {"sync_code": code, "email": user.get("email")}


@router.post("/user/settings")
async def user_settings(request: SettingsRequest, authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = authorization.split(" ")[1]
    user = await async_get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid token")
    update_user_api_key(user["id"], request.gemini_api_key)
    invalidate_token_cache(token)
    return {"status": "success"}


@router.post("/user/profile")
async def update_user_profile(request: ProfileUpdateRequest, authorization: Optional[str] = Header(None)):
    """Cloud sync candidate profile (Notice period, salary, portfolio, location, EEO, links) to Supabase."""
    token = authorization.split(" ")[1] if authorization and authorization.startswith("Bearer ") else None
    user = await async_get_user_by_token(token) if token else None

    from services.session_store import get_session_data, set_session_data
    session = get_session_data(token)
    existing_data = session.get("data") or {}

    profile_dict = dict(request.raw_resume_data) if request.raw_resume_data else dict(existing_data)
    if request.name: profile_dict["name"] = request.name
    if request.email: profile_dict["email"] = request.email
    if request.phone: profile_dict["phone"] = request.phone
    if request.location: profile_dict["location"] = request.location
    if request.portfolio: profile_dict["portfolio"] = request.portfolio
    if request.linkedin: profile_dict["linkedin"] = request.linkedin
    if request.github: profile_dict["github"] = request.github
    if request.notice_period: profile_dict["notice_period"] = request.notice_period
    if request.salary_expectations: profile_dict["salary_expectations"] = request.salary_expectations
    if request.work_auth: profile_dict["work_auth"] = request.work_auth
    if request.sponsorship: profile_dict["sponsorship"] = request.sponsorship
    if request.skills: profile_dict["skills"] = request.skills
    if request.summary: profile_dict["summary"] = request.summary

    # Update in-memory session store
    set_session_data(token or "guest", profile_dict, session.get("path", ""))

    # Persist to Supabase if logged-in user exists
    if user and user.get("id") and not str(user.get("id")).startswith("guest_"):
        try:
            user_id = user["id"]
            existing_rows = supabase_request(f"user_resumes?user_id=eq.{user_id}", "GET")
            payload = {
                "user_id": user_id,
                "resume_data": profile_dict,
                "updated_at": "now()"
            }
            if existing_rows and len(existing_rows) > 0:
                supabase_request(f"user_resumes?user_id=eq.{user_id}", "PATCH", payload)
            else:
                supabase_request("user_resumes", "POST", payload)
            if token:
                invalidate_token_cache(token)
        except Exception as e:
            print(f"Supabase profile cloud sync error: {e}")

    return {"status": "success", "profile": profile_dict}


@router.post("/user/subscription")
async def user_subscription(request: SubscriptionRequest, authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = authorization.split(" ")[1]
    user = await async_get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid token")

    payload = {
        "cron_enabled": request.cron_enabled,
        "cron_role": request.cron_role,
        "cron_location": request.cron_location,
        "cron_time": request.cron_time
    }
    if request.send_tailored_email is not None:
        payload["send_tailored_email"] = request.send_tailored_email

    supabase_request(f"users?id=eq.{user['id']}", "PATCH", payload)
    invalidate_token_cache(token)
    return {"status": "success"}


@router.get("/email_action/unsubscribe", response_class=HTMLResponse)
async def email_action_unsubscribe(email: str):
    """Zero-Click Unsubscribe handler clicked from matching digest email."""
    try:
        encoded_email = urllib.parse.quote(email)
        users = supabase_request(f"users?email=eq.{encoded_email}", "GET")
        if not users:
            return HTMLResponse("<h3>Error: Profile matching this email address not found.</h3>", status_code=404)

        user_id = users[0].get("id")
        supabase_request(f"users?id=eq.{user_id}", "PATCH", {"cron_enabled": False})
        return HTMLResponse("""
        <div style="font-family: Arial, sans-serif; max-width: 500px; margin: 50px auto; padding: 30px; border: 1px solid #E2E8F0; border-radius: 12px; text-align: center;">
            <div style="font-size: 3rem; margin-bottom: 12px;">🔕</div>
            <h2 style="color: #0F172A; margin: 0 0 10px;">Unsubscribed</h2>
            <p style="color: #64748B;">You have successfully disabled daily job digest emails.</p>
        </div>
        """)
    except Exception as e:
        return HTMLResponse(f"<h3>Unsubscribe failed: {str(e)}</h3>", status_code=500)
