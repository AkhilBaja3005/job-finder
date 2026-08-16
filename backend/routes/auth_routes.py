from fastapi import APIRouter, HTTPException, Header, Request
from fastapi.responses import RedirectResponse
from typing import Optional
from pydantic import BaseModel
import os

from services.auth import (
    create_or_get_user,
    create_session,
    async_get_user_by_token,
    invalidate_token_cache,
    get_google_auth_url,
    exchange_google_code_for_email,
    generate_user_sync_code,
    _is_local_deployment
)

router = APIRouter(tags=["Authentication"])

class SubscriptionRequest(BaseModel):
    cron_enabled: bool
    cron_role: Optional[str] = None
    cron_location: Optional[str] = "Remote"
    cron_time: Optional[str] = "18:00:00"
    send_tailored_email: Optional[bool] = True

@router.get("/auth/google")
async def auth_google():
    return {"url": get_google_auth_url()}

@router.get("/auth/callback")
async def auth_callback(code: str):
    try:
        email, picture_url = exchange_google_code_for_email(code)
        user = create_or_get_user(email, picture_url)
        token = create_session(user["id"])
        frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173")
        return RedirectResponse(url=f"{frontend_url}?token={token}")
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
    return user

@router.post("/user/subscription")
async def user_subscription(request: SubscriptionRequest, authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = authorization.split(" ")[1]
    user = await async_get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid token")

    from services.auth import supabase_request
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
