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
from services.resume_parser import sanitize_resume_summary

router = APIRouter(tags=["Authentication & Settings"])


class SubscriptionRequest(BaseModel):
    cron_enabled: bool
    cron_role: Optional[str] = None
    cron_location: Optional[str] = "Remote"
    cron_time: Optional[str] = "18:00:00"
    send_tailored_email: Optional[bool] = True
    skip_portals: Optional[List[str]] = None


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
    skip_portals: Optional[List[str]] = None
    raw_resume_data: Optional[dict] = None


@router.get("/auth/google")
@router.get("/auth/url")
async def auth_google(request: Request, redirect_to: Optional[str] = None):
    custom_redirect = None
    if not os.getenv("GOOGLE_REDIRECT_URI"):
        custom_redirect = f"{str(request.base_url).rstrip('/')}/auth/callback"
    
    # State holds the destination path (e.g. /platform, /docs, or specific deep link)
    state = redirect_to if (redirect_to and redirect_to.startswith("/")) else "/platform"
    auth_url = get_google_auth_url(redirect_uri=custom_redirect, state=state)
    if not auth_url:
        raise HTTPException(status_code=500, detail="Google OAuth client ID is not configured.")
    return {"url": auth_url}


@router.get("/auth/callback")
async def auth_callback(code: str, request: Request, state: Optional[str] = None):
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

        # Safely determine destination path from state (defaulting to /platform)
        dest_path = "/platform"
        if state and state.startswith("/"):
            # Prevent open redirects by ensuring it's a relative path starting with single slash
            if not state.startswith("//"):
                dest_path = state

        return RedirectResponse(url=f"{frontend_url.rstrip('/')}{dest_path}?token={token}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"OAuth verification failed: {str(e)}")


class RequestOtpPayload(BaseModel):
    email: str


class VerifyOtpPayload(BaseModel):
    email: str
    code: str


class ContactQueryPayload(BaseModel):
    name: Optional[str] = "Anonymous"
    email: str
    message: str


# In-memory store for OTPs: email -> {"code": "123456", "expires_at": timestamp, "attempts": 0}
_OTP_CACHE: Dict[str, Dict[str, Any]] = {}

# In-memory rate limiting for contact submissions: ip -> list of timestamps
_CONTACT_RATE_LIMIT: Dict[str, List[float]] = {}
CONTACT_MAX_PER_WINDOW = 3
CONTACT_WINDOW_SECONDS = 600  # 10 minutes


@router.post("/contact")
async def submit_contact_query(payload: ContactQueryPayload, request: Request, background_tasks: BackgroundTasks):
    import time
    from services.email_service import async_send_notification_email

    # Extract client IP (respecting standard reverse-proxy headers like CF-Connecting-IP, X-Forwarded-For)
    client_ip = (
        request.headers.get("cf-connecting-ip")
        or request.headers.get("x-real-ip")
        or (request.headers.get("x-forwarded-for", "").split(",")[0].strip() if request.headers.get("x-forwarded-for") else None)
        or (request.client.host if request.client else "unknown")
    )

    now = time.time()
    ip_history = _CONTACT_RATE_LIMIT.get(client_ip, [])
    # Prune submissions older than the 10-minute window
    ip_history = [ts for ts in ip_history if now - ts < CONTACT_WINDOW_SECONDS]

    if len(ip_history) >= CONTACT_MAX_PER_WINDOW:
        wait_seconds = int(CONTACT_WINDOW_SECONDS - (now - ip_history[0]))
        raise HTTPException(
            status_code=429,
            detail=f"Too many contact submissions. Please try again in {max(1, wait_seconds // 60)} minutes."
        )

    clean_email = payload.email.strip().lower()
    clean_msg = payload.message.strip()
    clean_name = (payload.name or "").strip() or "Prospective User"

    if not clean_email or "@" not in clean_email:
        raise HTTPException(status_code=400, detail="A valid email address is required.")
    if not clean_msg:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    # Record valid request timestamp for rate limiting
    ip_history.append(now)
    _CONTACT_RATE_LIMIT[client_ip] = ip_history

    target_email = "akhilbaja.work@gmail.com"
    subject = f"[JobFinder Inquiry] New query from {clean_name}"
    text_body = f"Sender Name: {clean_name}\nSender Email: {clean_email}\n\nMessage:\n{clean_msg}"
    html_body = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head><meta charset="utf-8"></head>
    <body style="font-family: -apple-system, sans-serif; background: #f8fafc; padding: 24px; color: #0f172a;">
      <div style="max-width: 560px; margin: 0 auto; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 24px;">
        <div style="font-size: 13px; font-weight: 700; color: #2563eb; text-transform: uppercase; margin-bottom: 12px;">JobFinder User Inquiry</div>
        <h3 style="margin: 0 0 16px; color: #0f172a;">New Message from {clean_name}</h3>
        <div style="background: #f1f5f9; padding: 12px; border-radius: 6px; font-size: 14px; margin-bottom: 16px;">
          <strong>Email:</strong> <a href="mailto:{clean_email}" style="color: #2563eb;">{clean_email}</a>
        </div>
        <div style="font-size: 14px; line-height: 1.6; color: #334155; white-space: pre-wrap; background: #fafafa; border: 1px solid #e2e8f0; padding: 16px; border-radius: 6px;">{clean_msg}</div>
      </div>
    </body>
    </html>
    """

    async def _send_inquiry_bg():
        try:
            await async_send_notification_email(
                to_email=target_email,
                subject=subject,
                text_body=text_body,
                html_body=html_body,
                sender_name="JobFinder Enquiry",
                reply_to=clean_email
            )
        except Exception as e:
            print(f"[Contact] Error dispatching inquiry: {e}")

    background_tasks.add_task(_send_inquiry_bg)
    return {"status": "success", "success": True, "message": "Inquiry submitted successfully. We will follow up shortly."}


@router.post("/auth/request-otp")
async def request_otp_endpoint(payload: RequestOtpPayload, background_tasks: BackgroundTasks):
    import time
    import random
    from services.email_service import async_send_notification_email

    clean_email = payload.email.strip().lower()
    if not clean_email or "@" not in clean_email or "." not in clean_email:
        raise HTTPException(status_code=400, detail="Invalid email address format.")

    # Generate secure 6-digit numeric OTP
    otp_code = f"{random.randint(100000, 999999)}"
    now = time.time()
    _OTP_CACHE[clean_email] = {
        "code": otp_code,
        "expires_at": now + 600,  # 10 minutes TTL
        "attempts": 0
    }

    # Format clean, corporate light-mode verification email
    subject = f"{otp_code} is your JobFinder verification code"
    text_body = f"Your single-use authentication code is: {otp_code}\n\nThis code will expire in 10 minutes.\nIf you did not request this code, you can safely ignore this email."
    html_body = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="utf-8">
      <meta name="color-scheme" content="light">
      <meta name="supported-color-schemes" content="light">
      <style>
        :root {{ color-scheme: light; supported-color-schemes: light; }}
        body {{ background-color: #F8FAFC !important; color: #0F172A !important; }}
      </style>
    </head>
    <body style="margin: 0; padding: 24px 12px; background-color: #F8FAFC; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;">
      <div style="max-width: 480px; margin: 0 auto; background-color: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 8px; padding: 32px 28px; box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);">
        <div style="font-size: 13px; font-weight: 700; color: #2563EB; letter-spacing: 0.05em; text-transform: uppercase; margin-bottom: 16px;">JobFinder Verification</div>
        <h2 style="font-size: 20px; font-weight: 700; color: #0F172A; margin: 0 0 12px; letter-spacing: -0.01em;">Single-Use Security Code</h2>
        <p style="font-size: 14px; color: #475569; line-height: 1.6; margin: 0 0 24px;">Use the code below to complete your sign-in to JobFinder. This code expires in 10 minutes.</p>
        <div style="background-color: #F1F5F9; border: 1px solid #CBD5E1; padding: 18px 24px; text-align: center; border-radius: 6px; letter-spacing: 0.28em; font-size: 30px; font-weight: 700; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; color: #0F172A; margin-bottom: 24px;">
          {otp_code}
        </div>
        <p style="font-size: 12px; color: #64748B; margin: 0; line-height: 1.5;">If you didn't request this code, no action is needed.</p>
      </div>
    </body>
    </html>
    """

    async def _send_otp_bg():
        try:
            await async_send_notification_email(
                to_email=clean_email,
                subject=subject,
                text_body=text_body,
                html_body=html_body,
                sender_name="JobFinder Security"
            )
        except Exception as e:
            print(f"[Auth] Error dispatching OTP email to {clean_email}: {e}")

    background_tasks.add_task(_send_otp_bg)
    return {"status": "success", "message": "Verification code dispatched to your email."}


@router.post("/auth/verify-otp")
async def verify_otp_endpoint(payload: VerifyOtpPayload):
    import time
    clean_email = payload.email.strip().lower()
    clean_code = payload.code.strip()

    record = _OTP_CACHE.get(clean_email)
    if not record:
        raise HTTPException(status_code=400, detail="No active verification code found. Please request a new one.")

    if time.time() > record["expires_at"]:
        _OTP_CACHE.pop(clean_email, None)
        raise HTTPException(status_code=400, detail="Verification code has expired. Please request a new one.")

    record["attempts"] += 1
    if record["attempts"] > 5:
        _OTP_CACHE.pop(clean_email, None)
        raise HTTPException(status_code=429, detail="Too many invalid attempts. Please request a fresh code.")

    if record["code"] != clean_code:
        raise HTTPException(status_code=400, detail="Invalid verification code. Please check and try again.")

    # Code verified! Clear cache and generate session
    _OTP_CACHE.pop(clean_email, None)
    user = create_or_get_user(clean_email)
    token = create_session(user["id"])
    return {
        "status": "success",
        "token": token,
        "user": {
            "id": user["id"],
            "email": user["email"],
            "name": user.get("name") or clean_email.split("@")[0].capitalize(),
            "picture_url": user.get("picture_url"),
            "sync_code": user.get("sync_code")
        }
    }


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

    if user.get("skip_portals") is None:
        user["skip_portals"] = ["targetjobs"]

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
    if request.summary: profile_dict["summary"] = sanitize_resume_summary(request.summary)

    # Update in-memory session store
    safe_key = token or "guest"
    from services.session_store import _safe_key, _get_user_storage_dirs
    from services.ats_scorer import evaluate_master_resume
    set_session_data(safe_key, profile_dict, session.get("path", ""))

    # Also sync to guest state file on disk
    try:
        _, user_out_dir = _get_user_storage_dirs(_safe_key(safe_key))
        guest_file = os.path.join(user_out_dir, f"resume_state_{_safe_key(safe_key)}.json")
        eval_data = evaluate_master_resume(profile_dict)
        with open(guest_file, "w", encoding="utf-8") as gf:
            json.dump({"data": profile_dict, "path": session.get("path", ""), "evaluation": eval_data}, gf, indent=2)
    except Exception as g_err:
        print(f"[update_user_profile] Warning updating guest file: {g_err}")

    # Also persist telemetry updates to config/candidate_profile.json
    try:
        from mcp.tools.profile_tools import PROFILE_CONFIG_PATH
        if os.path.exists(PROFILE_CONFIG_PATH):
            with open(PROFILE_CONFIG_PATH, "r", encoding="utf-8") as cf:
                cfg_data = json.load(cf)
            cand = cfg_data.setdefault("candidate", {})
            if request.name: cand["name"] = request.name
            if request.email: cand["email"] = request.email
            if request.phone: cand["phone"] = request.phone
            if request.location: cand["location"] = request.location
            if request.portfolio: cand["portfolio"] = request.portfolio
            if request.linkedin: cand["linkedin"] = request.linkedin
            if request.github: cand["github"] = request.github
            with open(PROFILE_CONFIG_PATH, "w", encoding="utf-8") as cf:
                json.dump(cfg_data, cf, indent=2)
    except Exception as cfg_err:
        print(f"[update_user_profile] Warning updating candidate_profile.json: {cfg_err}")

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

            if request.skip_portals is not None:
                supabase_request(f"users?id=eq.{user_id}", "PATCH", {"skip_portals": request.skip_portals})

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
    if request.skip_portals is not None:
        payload["skip_portals"] = request.skip_portals

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


@router.get("/email_action/tailor", response_class=HTMLResponse)
async def email_action_tailor(job_url: str, email: str, title: Optional[str] = None, company: Optional[str] = None):
    """
    Zero-Click 1-Tap Tailoring Handler from Daily Job Digest Email.
    Retrieves user profile, runs full LaTeX tailoring & Reviewer Agent check,
    compiles single-page PDF, attaches to delivery email, and records to history.
    """
    try:
        encoded_email = urllib.parse.quote(email)
        users = supabase_request(f"users?email=eq.{encoded_email}", "GET")
        if not users:
            return HTMLResponse("<h3>Error: User matching this email address not found.</h3>", status_code=404)

        user = users[0]
        user_id = user.get("id")
        user_token = user.get("token") or user_id

        # Load candidate resume data
        resume_rows = supabase_request(f"user_resumes?user_id=eq.{user_id}&select=resume_data", "GET")
        if not resume_rows:
            return HTMLResponse("<h3>Error: No master resume found. Upload a resume in the Job Finder web app first.</h3>", status_code=400)

        raw_data = resume_rows[0].get("resume_data")
        candidate_profile = json.loads(raw_data) if isinstance(raw_data, str) else (raw_data or {})

        from routes.ai_routes import JobAnalysisRequest, analyze_job
        from starlette.datastructures import Headers

        # Create dummy Request object for rate limiting and invocation
        scope = {
            "type": "http",
            "method": "POST",
            "headers": [(b"authorization", f"Bearer {user_token}".encode("utf-8"))],
            "client": ("127.0.0.1", 80),
            "scheme": "http",
            "server": ("127.0.0.1", 80),
        }
        fake_http_request = Request(scope)

        req_payload = JobAnalysisRequest(
            job_url=job_url,
            job_title=title or "Target Role",
            company=company or "Company",
            send_email=True,
            skip_tailoring=False,
            force_tailoring=True,
            candidate_profile=candidate_profile,
            tailoring_intensity="balanced",
            source_mode="digest_email"
        )

        res = await analyze_job(
            request=req_payload,
            http_request=fake_http_request,
            authorization=f"Bearer {user_token}",
            x_gemini_api_key=user.get("gemini_api_key")
        )

        # Consume streaming generator in background thread
        async for _ in res.body_iterator:
            pass

        target_title = title or "Target Role"
        target_company = company or "Company"
        return HTMLResponse(f"""
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 520px; margin: 40px auto; padding: 32px 24px; border: 1px solid #10B981; border-radius: 16px; text-align: center; box-shadow: 0 10px 30px rgba(0,0,0,0.06); background-color: #ffffff;">
            <div style="font-size: 3.5rem; margin-bottom: 16px;">⚡</div>
            <h2 style="color: #0F172A; margin: 0 0 12px; font-weight: 800;">Tailoring Completed!</h2>
            <p style="color: #475569; font-size: 0.95rem; line-height: 1.6; margin-bottom: 20px;">
                Your resume for <strong>{target_title}</strong> at <strong>{target_company}</strong> has been tailored, verified by the Senior Recruiter Agent, and compiled.
            </p>
            <div style="background-color: #F0FDF4; border: 1px solid #BBF7D0; border-radius: 10px; padding: 14px; margin-bottom: 24px; color: #166534; font-size: 0.9rem; font-weight: 600;">
                📧 We've dispatched the tailored PDF directly to <strong>{email}</strong>.
            </div>
            <a href="{job_url}" target="_blank" style="display: inline-block; background-color: #0284C7; color: #ffffff; padding: 12px 24px; border-radius: 8px; text-decoration: none; font-weight: 700; font-size: 0.92rem;">
                Open Job & Apply Now &rarr;
            </a>
            <p style="font-size: 0.8rem; color: #94A3B8; margin-top: 24px;">You can safely close this window.</p>
        </div>
        """)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return HTMLResponse(f"<h3>Tailoring failed: {str(e)}</h3>", status_code=500)
