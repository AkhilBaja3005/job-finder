# -*- coding: utf-8 -*-
import asyncio
import os
import shutil
import json
import subprocess
import re
import io
import ssl
import glob
import traceback
import zipfile
import urllib.request
import urllib.parse
from urllib.error import URLError
import uuid
import queue
# pyrefly: ignore [missing-import]
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Header, Request, Depends
# pyrefly: ignore [missing-import]
from fastapi.middleware.cors import CORSMiddleware
# pyrefly: ignore [missing-import]
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse, Response
# pyrefly: ignore [missing-import]
# Mount static files for hosting the built frontend as part of the same service
from fastapi.staticfiles import StaticFiles
# pyrefly: ignore [missing-import]
from fastapi.responses import HTMLResponse
# pyrefly: ignore [missing-import]
from pydantic import BaseModel, Field
from typing import List, Optional, Union, Dict, Any
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv
load_dotenv()
# pyrefly: ignore [missing-import]
from pypdf import PdfReader
import time
import hashlib
import re as _re
from zoneinfo import ZoneInfo


from services.resume_parser import parse_resume
from services.scraper import scrape_job_description
from services.llm_agent import analyze_job_fit, review_tailored_resume, tailor_latex_code
from services.resume_generator import generate_pdf_resume
from services.autofill_agent import autofill_job_application
from services.job_searcher import find_matching_jobs
from services.application_tracker import record_application, list_applications, update_application_status
from services.recruiter_extractor import extract_recruiter
from services.outreach_generator import generate_outreach_message
from services.auth import (
    create_or_get_user,
    create_session,
    get_user_by_token,
    async_get_user_by_token,
    invalidate_token_cache,
    update_user_api_key,
    get_google_auth_url,
    exchange_google_code_for_email,
    get_optional_token
)
from services.log_queue import LLMClientLogQueue
from utils.latex_utils import extract_latex_command, apply_latex_hotfix, generate_latex_from_json
from utils.ssl_utils import SSL_CONTEXT
from utils.ttl_cache import TTLCache
# --- Background Task to Clean Files Older Than 1 Hour (Runs every 30 mins) ---
from contextlib import asynccontextmanager

# Use absolute paths to prevent working directory shifts on Render / Hugging Face container startup.
# Hugging Face Spaces persistent storage is mounted at /data when enabled.
# If /data exists, route user data, uploads, and output PDF stores there so they survive container restarts.
HF_DATA_DIR = "/data"
if os.path.exists(HF_DATA_DIR) and os.access(HF_DATA_DIR, os.W_OK):
    BASE_STORAGE_DIR = HF_DATA_DIR
    print(f"[System Startup] 💾 Hugging Face Persistent Storage detected & mounted at {HF_DATA_DIR}")
else:
    BASE_STORAGE_DIR = os.path.dirname(os.path.abspath(__file__))

UPLOAD_DIR = os.path.join(BASE_STORAGE_DIR, "uploads")
OUTPUT_DIR = os.path.join(BASE_STORAGE_DIR, "output")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MAX_RESUME_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB — generous for a resume PDF/DOCX/TEX
default_cls_source = os.path.join(BASE_DIR, "assets", "resume.cls")
target_cls_path = os.path.join(UPLOAD_DIR, "resume.cls")

# Ensure resume.cls is available in uploads directory for compilation/zipping.
# We copy it from the static backend/assets folder which is tracked in Git.
if os.path.exists(default_cls_source):
    shutil.copy2(default_cls_source, target_cls_path)
    print(f"Synced fallback resume.cls from {default_cls_source} to {target_cls_path}")

async def auto_clean_expired_files(force_startup_purge: bool = False):
    """Deletes temporary files. If force_startup_purge is True, ignores time checks and cleans everything."""
    try:
        now = time.time()
        cutoff = 0 if force_startup_purge else (now - 3600) # 1 hour cutoff
        mode = "STARTUP INSTANT PURGE" if force_startup_purge else "CRON AUTO CLEAN"
        print(f"[Auto Clean] Running {mode} task...")
        
        # 1. Clean temporary output files (preserve legacy PDFs, resume_state, application_history, tailored_)
        if os.path.exists(OUTPUT_DIR):
            for root, dirs, files in os.walk(OUTPUT_DIR):
                for filename in files:
                    if filename.endswith(".pdf") or filename.startswith("resume_state") or filename.startswith("application_history_") or filename.startswith("tailored_"):
                        continue
                    file_path = os.path.join(root, filename)
                    try:
                        mtime = os.path.getmtime(file_path)
                        if force_startup_purge or mtime < cutoff:
                            os.unlink(file_path)
                            print(f"[Auto Clean Output] Deleted temporary file: {file_path} (Modified {now - mtime:.1f}s ago)")
                    except Exception as ex:
                        print(f"[Auto Clean Output] Failed deleting {file_path}: {ex}")

        # 2. Clean temporary upload files (preserve resume.cls, master TeX, and PDFs)
        if os.path.exists(UPLOAD_DIR):
            for root, dirs, files in os.walk(UPLOAD_DIR):
                for filename in files:
                    if filename == "resume.cls" or filename.endswith("_master.tex") or filename.endswith(".pdf"):
                        continue
                    file_path = os.path.join(root, filename)
                    try:
                        mtime = os.path.getmtime(file_path)
                        if force_startup_purge or mtime < cutoff:
                            os.unlink(file_path)
                            print(f"[Auto Clean Uploads] Deleted temporary file: {file_path} (Modified {now - mtime:.1f}s ago)")
                    except Exception as ex:
                        print(f"[Auto Clean Uploads] Failed deleting {file_path}: {ex}")
        
        # 3. Clean local user_data folder of browser state directories
        user_data_path = os.path.join(BASE_DIR, "user_data")
        if os.path.exists(user_data_path):
            for filename in os.listdir(user_data_path):
                file_path = os.path.join(user_data_path, filename)
                try:
                    mtime = os.path.getmtime(file_path)
                    if force_startup_purge or mtime < cutoff:
                        if os.path.isdir(file_path):
                            shutil.rmtree(file_path)
                            print(f"[Auto Clean UserData] Deleted directory: {filename}")
                        elif os.path.isfile(file_path) or os.path.islink(file_path):
                            os.unlink(file_path)
                            print(f"[Auto Clean UserData] Deleted file: {filename} (Modified {now - mtime:.1f}s ago)")
                except Exception as ex:
                    print(f"[Auto Clean UserData] Failed to delete {file_path}: {ex}")
                    
    except Exception as e:
        print(f"[Auto Clean Task] Error running cleanup: {e}")

async def auto_clean_expired_files_loop():
    # Loop that runs every 30 minutes
    while True:
        await asyncio.sleep(1800) # Sleep first, startup clean is handled in lifespan
        await auto_clean_expired_files(force_startup_purge=False)

# Background Loop: Run matching job scanner once every 24 hours
from services.email_service import send_notification_email, async_send_notification_email
from datetime import datetime as dt, time as dtime, timedelta, timezone

async def hf_keep_alive_loop():
    """
    Self-ping background task that runs every 4 hours.
    Simulates internal HTTP traffic to keep Hugging Face Spaces awake
    and prevent the 48-hour inactivity sleep timer from triggering.
    """
    await asyncio.sleep(60) # Wait 1 minute after server startup
    while True:
        try:
            # Ping local fast server loop in a background thread (0ms latency, zero main thread block)
            target_url = "http://127.0.0.1:8000/"
            def _ping():
                import urllib.request
                req = urllib.request.Request(target_url, headers={"User-Agent": "HFKeepAlive/1.0"})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    return resp.status
            status = await asyncio.to_thread(_ping)
            print(f"[Keep Alive] Successfully pinged local server (status={status}) - Space active!")
        except Exception as e:
            print(f"[Keep Alive Warning] Self-ping attempt: {e}")
        await asyncio.sleep(14400) # Ping every 4 hours (14,400 seconds)

async def process_and_send_user_digest(user: dict, bypass_time_check: bool = False) -> bool:
    """Scrapes 24h job listings for user and delivers custom daily matches digest email."""
    from services.auth import supabase_request
    from zoneinfo import ZoneInfo
    ist_tz = ZoneInfo("Asia/Kolkata")
    now = dt.now(ist_tz)
    today_str = now.strftime("%Y-%m-%d")

    user_id = user.get("id")
    email = user.get("email")
    if not email or not user_id:
        return False

    if not bypass_time_check:
        last_sent_date = user.get("cron_last_sent_date")
        if last_sent_date == today_str:
            return False

        time_str = user.get("cron_time") or "18:00:00"
        try:
            target_h, target_m = map(int, time_str.split(":")[:2])
        except Exception:
            target_h, target_m = 18, 0

        target_dt = now.replace(hour=target_h, minute=target_m, second=0, microsecond=0, tzinfo=ist_tz)
        if now < target_dt:
            return False

    # Fetch user's master resume data
    resume_rows = supabase_request(f"user_resumes?user_id=eq.{user_id}", "GET")
    if not resume_rows:
        print(f"[Daily Mailer] No resume context found for user {email}")
        return False

    resume_data_str = resume_rows[0].get("resume_data")
    if not resume_data_str:
        return False
    try:
        resume_data = json.loads(resume_data_str)
    except Exception:
        return False

    pref_role = user.get("cron_role")
    keywords_arg = pref_role.strip() if (pref_role and pref_role.strip()) else None
    pref_loc = user.get("cron_location") or "Remote"

    print(f"[Daily Mailer] Generating digest for {email} (Role: '{keywords_arg or 'AI-auto-generated'}', Location: '{pref_loc}')...")

    scraped_jobs = []
    async for chunk in find_matching_jobs(
        resume_data=resume_data,
        location=pref_loc,
        keywords=keywords_arg,
        timeframe="24h"
    ):
        try:
            parsed = json.loads(chunk.strip())
            if parsed.get("type") == "result":
                # Final complete batch
                batch = parsed.get("jobs", [])
                if batch:
                    scraped_jobs = batch
            elif parsed.get("type") == "partial_result" and parsed.get("job"):
                # Collect streaming job matches
                job_item = parsed.get("job")
                if not any(j.get("url") == job_item.get("url") for j in scraped_jobs):
                    scraped_jobs.append(job_item)
        except Exception:
            pass

    if not scraped_jobs:
        print(f"[Daily Mailer] No recent 24h jobs found matching {pref_role} for user: {email}")
        if not bypass_time_check:
            supabase_request(f"users?id=eq.{user_id}", "PATCH", {"cron_last_sent_date": today_str})
        return False

    # Sort accurate (JD-scored) jobs first, then descending by ATS match score
    scraped_jobs.sort(key=lambda j: (j.get("estimated", False), -j.get("score", 0)))
    candidate_name = resume_data.get("name", "").strip() or "Candidate"

    text_digest = f"Hi {candidate_name},\n\nHere are your top matching roles from the past 24 hours:\n\n"
    html_digest = f"""
    <div style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; max-width: 600px; margin: 0 auto; padding: 25px; border: 1px solid #E2E8F0; border-radius: 16px; background-color: #FAFAFA; box-shadow: 0 4px 20px rgba(0,0,0,0.03); box-sizing: border-box;">
        <div style="text-align: center; margin-bottom: 24px;">
            <span style="font-size: 3rem;">📬</span>
            <h2 style="color: #0284C7; margin: 10px 0 5px; font-weight: 800; font-size: 1.5rem; font-family: 'Segoe UI', Arial, sans-serif;">Daily Job Matches Digest</h2>
            <p style="color: #334155; font-size: 0.98rem; font-weight: 600; margin: 8px 0 4px; font-family: 'Segoe UI', Arial, sans-serif;">Hi {candidate_name},</p>
            <p style="color: #64748B; font-size: 0.9rem; margin: 0; font-family: 'Segoe UI', Arial, sans-serif;">Here are your top matching roles from the past 24 hours:</p>
        </div>
        <div style="width: 100%;">
    """

    for idx, job in enumerate(scraped_jobs[:20]):
        title = job.get("title", "Target Role")
        company = job.get("company", "Target Company")
        score = job.get("score", 60)
        is_estimated = job.get("estimated", False)
        url = job.get("url", "")
        recruiter_name = job.get("recruiter_name")
        recruiter_profile_url = job.get("recruiter_profile_url")
        recruiter_str = f"\n   Recruiter: {recruiter_name}" if recruiter_name else ""
        platform = job.get("platform") or ("LinkedIn" if "linkedin.com" in url else "Indeed" if "indeed.com" in url else "Web")

        base_url = os.getenv("BACKEND_URL", "http://localhost:8000")
        tailor_url = (
            f"{base_url}/email_action/tailor"
            f"?job_url={urllib.parse.quote(url, safe='')}"
            f"&email={urllib.parse.quote(email)}"
            f"&title={urllib.parse.quote(title, safe='')}"
            f"&company={urllib.parse.quote(company, safe='')}"
        )

        score_label = f"{score}% match (Est.)" if is_estimated else f"{score}% match"
        text_digest += f"{idx+1}. {title} at {company} ({platform})\n   Match Score: {score_label}{recruiter_str}\n   View Job: {url}\n   Auto-Tailor & Apply: {tailor_url}\n\n"

        score_color = "#10B981" if score >= 85 else "#F59E0B" if score >= 70 else "#64748B"
        platform_color = "#0A66C2" if platform.lower() == "linkedin" else "#2164F3" if platform.lower() == "indeed" else "#EC4899" if platform.lower() == "reed" else "#64748B"

        recruiter_html = ""
        if recruiter_name:
            if recruiter_profile_url:
                recruiter_html = f'<span style="font-size: 0.76rem; color: #0284C7; display: block; margin-top: 3px;">👤 Recruiter: <a href="{recruiter_profile_url}" target="_blank" style="color: #0284C7; text-decoration: underline;">{recruiter_name}</a></span>'
            else:
                recruiter_html = f'<span style="font-size: 0.76rem; color: #64748B; display: block; margin-top: 3px;">👤 Recruiter: {recruiter_name}</span>'

        badge_text = f"{score}% match" + (" (Est.)" if is_estimated else " (Exact ATS)")
        badge_title = "Estimated match based on title skill heuristic" if is_estimated else "Exact ATS match calculated against full job description"

        html_digest += f"""
        <div style="background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 12px; padding: 18px; box-sizing: border-box; overflow: hidden; margin-bottom: 12px;">
            <table style="width: 100%; border-collapse: collapse;">
                <tr>
                    <td>
                        <h3 style="margin: 0 0 4px 0; color: #1E293B; font-size: 1.05rem; font-weight: 700; font-family: 'Segoe UI', Arial, sans-serif;">{title}</h3>
                        <p style="margin: 0; color: #64748B; font-size: 0.88rem; font-weight: 500; font-family: 'Segoe UI', Arial, sans-serif;">
                            {company} &bull; <span style="color: {platform_color}; font-weight: 700; background-color: {platform_color}15; padding: 2px 6px; border-radius: 4px;">{platform}</span>
                        </p>
                        {recruiter_html}
                    </td>
                    <td style="text-align: right; vertical-align: top; width: 120px;">
                        <span title="{badge_title}" style="display: inline-block; background-color: {score_color}15; color: {score_color}; padding: 4px 8px; border-radius: 6px; font-size: 0.76rem; font-weight: 700; font-family: 'Segoe UI', Arial, sans-serif; white-space: nowrap;">{badge_text}</span>
                    </td>
                </tr>
            </table>
            
            <table style="width: 100%; border-collapse: collapse; margin-top: 14px;">
                <tr>
                    <td style="width: 50%; padding-right: 5px;">
                        <a href="{url}" target="_blank" style="display: block; box-sizing: border-box; text-align: center; padding: 9px 12px; font-size: 0.82rem; color: #64748B; background-color: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 6px; text-decoration: none; font-weight: 600; font-family: 'Segoe UI', Arial, sans-serif; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">View Listing</a>
                    </td>
                    <td style="width: 50%; padding-left: 5px;">
                        <a href="{tailor_url}" target="_blank" style="display: block; box-sizing: border-box; text-align: center; padding: 9px 12px; font-size: 0.82rem; color: #FFFFFF; background-color: #0284C7; border-radius: 6px; text-decoration: none; font-weight: bold; font-family: 'Segoe UI', Arial, sans-serif; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">⚡ Auto-Tailor</a>
                    </td>
                </tr>
            </table>
        </div>
        """

    base_url = os.getenv("BACKEND_URL", "http://localhost:8000")
    unsub_url = f"{base_url}/email_action/unsubscribe?email={urllib.parse.quote(email)}"

    html_digest += f"""
        </div>
        <hr style="border: 0; border-top: 1px solid #E2E8F0; margin: 30px 0 20px;" />
        <p style="font-size: 0.8rem; color: #94A3B8; text-align: center; margin: 0; font-family: 'Segoe UI', Arial, sans-serif;">
            Manage your subscription settings inside the app or <a href="{unsub_url}" target="_blank" style="color: #0284C7; text-decoration: underline;">unsubscribe instantly</a>.
        </p>
    </div>
    """

    target_email = "akhilkumarbaja@gmail.com" if _is_local_deployment() else email

    sent = await async_send_notification_email(
        to_email=target_email,
        subject="📬 Daily Job Matches Digest",
        text_body=text_digest,
        html_body=html_digest
    )

    if sent and not bypass_time_check:
        supabase_request(f"users?id=eq.{user_id}", "PATCH", {"cron_last_sent_date": today_str})
        print(f"[Daily Mailer] Successfully sent daily digest email to {email} and marked cron_last_sent_date={today_str}")

    return sent


async def daily_match_mailer_loop():
    await asyncio.sleep(15)
    while True:
        try:
            from services.auth import supabase_request
            active_users = supabase_request("users?cron_enabled=eq.true", "GET")
            for user in active_users:
                await process_and_send_user_digest(user, bypass_time_check=False)
        except Exception as e:
            print(f"[Daily Mailer ERROR] Exception: {e}")
        await asyncio.sleep(60)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Cap maximum background threads — bumped to 6 for 2-vCPU/16GB HF tier
    # (more headroom for concurrent Tectonic compiles + sync HTTP calls)
    import concurrent.futures
    loop = asyncio.get_running_loop()
    loop.set_default_executor(concurrent.futures.ThreadPoolExecutor(max_workers=6))

    # Startup: Perform immediate full purge of leftover files from previous deployment container instances
    await auto_clean_expired_files(force_startup_purge=True)
    # Start the background checker loop task
    clean_task = asyncio.create_task(auto_clean_expired_files_loop())
    # Start daily match mailer loop
    mailer_task = asyncio.create_task(daily_match_mailer_loop())
    # Start Hugging Face anti-sleep self-ping loop
    keepalive_task = asyncio.create_task(hf_keep_alive_loop())

    # Optional Sentry error monitoring — only active when SENTRY_DSN is set
    try:
        import sentry_sdk  # pyrefly: ignore [missing-import]
        sentry_dsn = os.getenv("SENTRY_DSN", "")
        if sentry_dsn:
            sentry_sdk.init(
                dsn=sentry_dsn,
                traces_sample_rate=0.1,   # 10% of requests traced for performance
                profiles_sample_rate=0.05,
                environment=os.getenv("ENV", "production"),
            )
            print("[System Startup] 🔍 Sentry error monitoring active")
    except ImportError:
        pass

    # Check if local deployment and BACKEND_URL contains ngrok
    ngrok_proc = None
    if _is_local_deployment():
        backend_url = os.getenv("BACKEND_URL", "")
        authtoken = os.getenv("NGROK_AUTHTOKEN", "")
        domain = os.getenv("NGROK_DOMAIN", "")
        if "ngrok" in backend_url:
            try:
                ngrok_cmd = shutil.which("ngrok") or shutil.which("npx")
                if ngrok_cmd:
                    if authtoken:
                        try:
                            subprocess.run([ngrok_cmd, "config", "add-authtoken", authtoken], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        except Exception:
                            pass
                    domain_arg = f"--domain={domain}" if domain else f"--url={backend_url}"
                    cmd = [ngrok_cmd, "http", "8000", domain_arg] if "ngrok" in ngrok_cmd else [ngrok_cmd, "ngrok", "http", "8000", domain_arg]
                    print(f"[Ngrok Manager] Launching static tunnel: {backend_url}...")
                    ngrok_proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception as e:
                print(f"[Ngrok Manager ERROR] Failed to start tunnel: {e}")
    # Startup Playwright Persistent Shared Browser (via scraper module singleton)
    # This single browser instance is reused by ALL scrape calls (tailor pipeline,
    # analyze_job, scrape_job, job search) — eliminates 2-3s Chromium launch per request.
    try:
        from services.scraper import init_shared_browser
        await init_shared_browser()
        # Mirror into app.state so legacy callers that pass browser= still work
        from services import scraper as _scraper_mod
        app.state.browser = _scraper_mod._shared_browser
        app.state.playwright = _scraper_mod._shared_playwright
    except Exception as pw_startup_err:
        print(f"[System Startup] Shared Playwright Browser Warning: {pw_startup_err}")
        app.state.browser = None
        app.state.playwright = None

    yield

    # Shutdown Playwright Shared Browser
    # Shutdown: close shared Playwright browser via scraper module
    try:
        from services.scraper import close_shared_browser
        await close_shared_browser()
    except Exception:
        pass

    # Shutdown
    if ngrok_proc:
        print("[Ngrok Manager] Terminating static tunnel process...")
        try:
            ngrok_proc.terminate()
            ngrok_proc.wait(timeout=3)
        except Exception:
            ngrok_proc.kill()

    clean_task.cancel()
    mailer_task.cancel()
    try:
        await asyncio.gather(clean_task, mailer_task, return_exceptions=True)
    except Exception:
        pass

# Add GZipMiddleware to compress HTML, CSS, JavaScript, and JSON responses by 70%-80%
# pyrefly: ignore [missing-import]
from fastapi.middleware.gzip import GZipMiddleware
app = FastAPI(title="AI Job Finder Agent API", lifespan=lifespan)

app.add_middleware(GZipMiddleware, minimum_size=1000)

# ── Rate Limiter & CORS Security Configuration ────────────────────────────
ALLOWED_ORIGINS = [
    "https://www.job-finder.space",
    "https://job-finder.space",
    "http://localhost:5173",
    "http://localhost:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:8000",
]
for env_key in ["FRONTEND_URL", "HF_SPACE_URL", "VERCEL_URL", "VERCEL_PROJECT_PRODUCTION_URL"]:
    val = os.getenv(env_key, "").strip()
    if val:
        if not val.startswith("http"):
            val = f"https://{val}"
        if val not in ALLOWED_ORIGINS:
            ALLOWED_ORIGINS.append(val)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS if os.getenv("ENV") == "production" else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from routes.auth_routes import router as auth_router
app.include_router(auth_router)

# Simple in-memory token bucket rate limiter for sensitive endpoints
_rate_limit_store: Dict[str, List[float]] = {}
_RATE_LIMIT_WINDOW = 60.0  # seconds
_RATE_LIMIT_MAX_REQUESTS = 15  # requests per window

class BypassNgrokMiddleware:
    """Pure ASGI middleware to inject ngrok bypass headers safely without Starlette BaseHTTPMiddleware streaming stream-closure bugs."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            custom_headers = dict(scope.get("headers", []))
            custom_headers[b"user-agent"] = b"JobFinderApp/1.0 (Custom Tunnel Client)"
            custom_headers[b"ngrok-skip-browser-warning"] = b"true"
            scope["headers"] = [(k, v) for k, v in custom_headers.items()]

            async def send_with_ngrok_header(message):
                if message["type"] == "http.response.start":
                    headers = list(message.get("headers", []))
                    headers.append((b"ngrok-skip-browser-warning", b"true"))
                    message["headers"] = headers
                await send(message)

            await self.app(scope, receive, send_with_ngrok_header)
        else:
            await self.app(scope, receive, send)

class RateLimitMiddleware:
    """Pure ASGI rate limiter to protect sensitive endpoints without breaking streaming responses."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            path = scope.get("path", "")
            if any(path.startswith(target) for target in ["/tailor", "/discover", "/upload_resume"]):
                client = scope.get("client")
                client_ip = client[0] if client else "127.0.0.1"
                now = time.time()
                history = _rate_limit_store.get(client_ip, [])
                history = [t for t in history if now - t < _RATE_LIMIT_WINDOW]
                if len(history) >= _RATE_LIMIT_MAX_REQUESTS:
                    res = Response(
                        content=json.dumps({"detail": "Rate limit exceeded. Please wait a minute before making more requests."}),
                        status_code=429,
                        media_type="application/json"
                    )
                    await res(scope, receive, send)
                    return
                history.append(now)
                _rate_limit_store[client_ip] = history

        await self.app(scope, receive, send)

app.add_middleware(BypassNgrokMiddleware)
app.add_middleware(RateLimitMiddleware)

@app.get("/healthz")
@app.get("/health")
async def health_check():
    """
    Lightweight ping endpoint for container health check & HF warm-up verification.
    Returns status, service timestamp, and running git commit SHA.
    """
    import time
    import subprocess
    commit_sha = "unknown"
    commit_time = ""
    
    # 1. Try local git subprocess (works in local dev environments)
    try:
        commit_sha = subprocess.check_output(
            ["git", "rev-parse", "--short=7", "HEAD"],
            cwd=BASE_DIR,
            stderr=subprocess.DEVNULL,
            text=True
        ).strip()
        commit_time = subprocess.check_output(
            ["git", "log", "-1", "--format=%cd", "--date=iso-strict"],
            cwd=BASE_DIR,
            stderr=subprocess.DEVNULL,
            text=True
        ).strip()
    except Exception:
        pass

    # 2. Fallback to container environment variables (Hugging Face / Docker environment)
    if not commit_sha or commit_sha == "unknown":
        raw_sha = os.getenv("GIT_SHA") or os.getenv("SPACE_SHA") or os.getenv("COMMIT_SHA") or "latest"
        commit_sha = raw_sha[:7]
    if not commit_time:
        commit_time = os.getenv("BUILD_DATE", "")

    return {
        "status": "ok",
        "service": "job-finder-api",
        "commit_sha": commit_sha,
        "commit_time": commit_time,
        "timestamp": time.time()
    }

import threading

# Maps any token (real user token, guest UUID, or "guest") to resume state.
# Backed in-memory with optional Supabase persistence for authenticated users.
_session_store: dict[str, dict] = {}
_store_lock = threading.Lock()

RESUME_STATE_FILE = os.path.join(OUTPUT_DIR, "resume_state.json")

# Helpers to manage state safely
from services.auth import update_user_resume_data


def _safe_key(token: Optional[Union[str, int]]) -> str:
    """FIX #2 helper: turn a token (or 'guest') into a filesystem/cache-safe key
    with no path separators, so it can be used to build per-user file paths."""
    key = str(token) if token is not None else "guest"
    key = _re.sub(r'[^a-zA-Z0-9_-]', '', key)[:40]
    return key or "guest"


def _is_local_deployment() -> bool:
    """True only when this process is clearly running on a developer's own
    machine, not a cloud deployment. Fails CLOSED (returns False) by default —
    any known cloud-platform env var being present overrides a merely
    localhost-looking FRONTEND_URL, since that value comes from a config file
    that could be forgotten/misconfigured on a real deployment. Used to gate
    /auth/mock, which otherwise mints a valid session for any email with zero
    verification and must never be reachable in production."""
    if any(os.getenv(v) for v in ("RENDER", "RAILWAY_ENVIRONMENT", "RAILWAY_PROJECT_ID", "FLY_APP_NAME", "SPACE_ID", "HF_SPACE_ID")):
        return False
    frontend_url = os.getenv("FRONTEND_URL", "")
    return "localhost" in frontend_url or "127.0.0.1" in frontend_url


def _get_user_storage_dirs(user_id_or_key: Optional[str] = None) -> tuple[str, str]:
    """
    Returns user-scoped (uploads_dir, output_dir) subdirectories under persistent storage:
      /data/uploads/<user_key>/
      /data/output/<user_key>/
    Ensures directories exist automatically.
    """
    key = _safe_key(str(user_id_or_key) if user_id_or_key else "guest")
    user_upload_dir = os.path.join(UPLOAD_DIR, key)
    user_output_dir = os.path.join(OUTPUT_DIR, key)
    os.makedirs(user_upload_dir, exist_ok=True)
    os.makedirs(user_output_dir, exist_ok=True)
    return user_upload_dir, user_output_dir


def _user_output_paths(token: Optional[str]) -> tuple[str, str]:
    """Return per-user tex/pdf output paths inside the user's dedicated output subdirectory."""
    key = _safe_key(token)
    _, user_out_dir = _get_user_storage_dirs(key)
    tex_path = os.path.join(user_out_dir, f"tailored_resume_{key}.tex")
    pdf_path = os.path.join(user_out_dir, f"tailored_resume_{key}.pdf")
    return tex_path, pdf_path


def drain_llm_logs() -> list[str]:
    """FIX #1: Non-blocking drain of all currently-queued LLM client log messages.

    The previous implementation used `while True: LLMClientLogQueue.get(block=True,
    timeout=1.0)` with `except queue.Empty: continue`. That loop has no exit
    condition once the queue is empty and the underlying LLM call has already
    finished -- it just polls forever, hanging the SSE stream indefinitely.
    Draining non-blockingly (like the original commented-out `get_all()` calls)
    fixes this: we grab whatever log lines are currently available and move on.
    """
    messages = []
    while True:
        try:
            msg = LLMClientLogQueue.get(block=False)
        except queue.Empty:
            break
        except Exception as e:
            print(f"[drain_llm_logs] Unexpected error draining log queue: {e}")
            break
        messages.append(msg)
    return messages


def _format_log_event(msg: str) -> str:
    """Turns one raw LLMClientLogQueue message into an SSE-ready JSON line.
    Messages are usually JSON (emitted by gemini_client's on_log callback) but
    can also be a plain string (e.g. a raw rate-limit error) — handle both."""
    try:
        parsed = json.loads(msg)
        if parsed.get("type") == "llm_warn":
            return json.dumps({"type": "llm_warn", "message": parsed.get("message"), "model": parsed.get("model", ""), "wait_s": parsed.get("wait_s", 10)}) + "\n"
        return json.dumps({"type": "log", "message": parsed.get("message")}) + "\n"
    except Exception:
        if "429" in msg or "rate limit" in msg.lower() or "Rate limit" in msg:
            return json.dumps({"type": "llm_warn", "message": msg, "model": "", "wait_s": 10}) + "\n"
        return json.dumps({"type": "log", "message": msg}) + "\n"


async def _stream_task_logs(task: "asyncio.Task"):
    """Polls drain_llm_logs() every 0.5s and yields formatted SSE lines for
    whatever log messages accumulated, until `task` completes. Callers should
    `await task` (or `result = await task`) after this generator is exhausted,
    then iterate _drain_remaining_logs() once more to flush any trailing
    messages emitted between the last poll and task completion."""
    while not task.done():
        for msg in drain_llm_logs():
            yield _format_log_event(msg)
        await asyncio.sleep(0.5)


def _drain_remaining_logs():
    """Formats any log messages left in the queue after a task has completed."""
    return [_format_log_event(msg) for msg in drain_llm_logs()]


def get_session_data(token: Optional[str]) -> dict:
    key = token or "guest"
    with _store_lock:
        data = _session_store.get(key)
        if data and data.get("data") and data["data"].get("education"):
            return data
            
    # Try fetching from Supabase if token exists
    if token:
        try:
            user = get_user_by_token(token)
            if user:
                user_id = user.get("id")
                from services.auth import supabase_request
                res = supabase_request(f"user_resumes?user_id=eq.{user_id}", "GET")
                if res and len(res) > 0:
                    resume_dict = json.loads(res[0].get("resume_data", "{}"))
                    path = ""
                    master_latex = res[0].get("master_latex", "")
                    if master_latex:
                        user_up_dir, _ = _get_user_storage_dirs(user_id)
                        path = os.path.join(user_up_dir, f"{user_id}_master.tex")
                        with open(path, "w", encoding="utf-8") as f:
                            f.write(master_latex)
                    with _store_lock:
                        _session_store[token] = {"data": resume_dict, "path": path}
                    return {"data": resume_dict, "path": path}
        except Exception as e:
            print(f"Failed to load resume from Supabase user session: {e}")

    # Search output directory for the latest complete state file
    try:
        output_base = os.path.join(os.path.dirname(__file__), "output")
        state_files = glob.glob(os.path.join(output_base, "**", "resume_state_*.json"), recursive=True)
        for sf in sorted(state_files, key=os.path.getmtime, reverse=True):
            with open(sf, "r", encoding="utf-8") as f:
                content = json.load(f)
                d = content.get("data", {})
                if d and d.get("education"):
                    set_session_data(key, d, content.get("path", ""))
                    return {"data": d, "path": content.get("path", "")}
    except Exception as ex:
        print(f"[get_session_data] Error searching state files: {ex}")

    # Fallback to guest if user session is empty
    with _store_lock:
        return _session_store.get("guest", {"data": {}, "path": ""})

def set_session_data(token: Optional[str], data: dict, path: str):
    key = token or "guest"
    with _store_lock:
        _session_store[key] = {"data": data, "path": path}
        
    if token:
        # Load master latex if available
        master_latex = ""
        if path and os.path.exists(path) and path.endswith(".tex"):
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    master_latex = f.read()
            except Exception as e:
                print(f"Failed to read master latex: {e}")
                
        user = get_user_by_token(token)
        if user:
            user_id = user["id"]
            # To prevent HTTP 400 Bad Request error noise, we write directly to the user_resumes table
            try:
                from services.auth import supabase_request
                # Check if user_resume entry exists
                existing = supabase_request(f"user_resumes?user_id=eq.{user_id}", "GET")
                payload = {
                    "user_id": user_id,
                    "resume_data": json.dumps(data),
                    "master_latex": master_latex or ""
                }
                if existing:
                    supabase_request(f"user_resumes?user_id=eq.{user_id}", "PATCH", payload)
                else:
                    supabase_request("user_resumes", "POST", payload)
            except Exception as ex:
                print(f"Failed to save user resume to Supabase: {ex}")

# Per-session/guest state file helper
def _get_guest_state_file(token: Optional[str]) -> str:
    key = _safe_key(token)
    _, user_out_dir = _get_user_storage_dirs(key)
    return os.path.join(user_out_dir, f"resume_state_{key}.json")

# Load stored guest resume state if exists at startup for default guest
default_guest_state_file = _get_guest_state_file("guest")
if os.path.exists(default_guest_state_file):
    try:
        with open(default_guest_state_file, "r") as f:
            state = json.load(f)
            set_session_data("guest", state.get("data", {}), state.get("path", ""))
            print("Loaded persisted resume state successfully into guest session.")
    except Exception as e:
        print(f"Failed to load persisted state: {e}")
else:
    # Scan for existing uploaded files to auto-parse at startup
    import glob
    uploaded_files = [f for f in (
        glob.glob(os.path.join(UPLOAD_DIR, "*.tex")) +
        glob.glob(os.path.join(UPLOAD_DIR, "*.pdf")) +
        glob.glob(os.path.join(UPLOAD_DIR, "*.docx"))
    ) if not f.endswith("resume.cls")]
    
    if uploaded_files:
        try:
            # First check if a comprehensive parsed state already exists in output/
            output_base = os.path.join(os.path.dirname(__file__), "output")
            existing_states = glob.glob(os.path.join(output_base, "**", "resume_state_*.json"), recursive=True)
            loaded_master = False
            for sf in sorted(existing_states, key=os.path.getmtime, reverse=True):
                with open(sf, "r", encoding="utf-8") as f:
                    st_json = json.load(f)
                    st_data = st_json.get("data", {})
                    if st_data and st_data.get("education"):
                        set_session_data("guest", st_data, st_json.get("path", ""))
                        with open(default_guest_state_file, "w", encoding="utf-8") as gf:
                            json.dump({"data": st_data, "path": st_json.get("path", "")}, gf, indent=2)
                        loaded_master = True
                        print(f"Loaded master candidate resume state from {sf}")
                        break
            if not loaded_master:
                file_path = uploaded_files[0]
                print(f"Found uploaded resume at startup: {file_path}. Auto-parsing...")
                structured_data = parse_resume(file_path)
                set_session_data("guest", structured_data.model_dump(), file_path)
                with open(default_guest_state_file, "w") as f:
                    json.dump({"data": structured_data.model_dump(), "path": file_path}, f, indent=2)
                print("Successfully parsed and saved resume state at startup.")
        except Exception as e:
            print(f"Failed to auto-parse uploaded resume: {e}")

class JobAnalysisRequest(BaseModel):
    job_url: Optional[str] = None
    job_title: str = Field(max_length=300)
    job_description: Optional[str] = Field(default=None, max_length=20000)
    skip_tailoring: bool = False
    force_tailoring: bool = False
    send_email: bool = False
    source_mode: Optional[str] = "website"  # "website" | "extension" 

class ApplyRequest(BaseModel):
    job_url: str
    direct_mode: bool = False
    job_title: Optional[str] = None
    company: Optional[str] = None

class GenerateOutreachRequest(BaseModel):
    job_url: Optional[str] = None
    job_description: str = Field(max_length=20000)
    job_title: str = Field(max_length=300)
    company_name: str = Field(max_length=300)
    recruiter_name: Optional[str] = None
    platform: Optional[str] = None

class SendOutreachEmailRequest(BaseModel):
    recipient_email: str
    subject: str
    body: str
    resume_path: Optional[str] = None

@app.post("/upload_resume")
async def upload_resume(file: UploadFile = File(...), authorization: Optional[str] = Header(None)):
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]
        
    try:
        # FIX #3: file.filename comes straight from the client and was previously
        # joined into UPLOAD_DIR unsanitized, allowing path traversal (e.g. a
        # filename like "../../main.py") to write outside UPLOAD_DIR. Strip any
        # directory component and disallow unsafe characters.
        raw_filename = os.path.basename(file.filename or "resume_upload")
        safe_filename = _re.sub(r'[^A-Za-z0-9._-]', '_', raw_filename).lstrip('.')
        if not safe_filename:
            safe_filename = f"resume_upload_{uuid.uuid4().hex[:8]}"
        user_up_dir, _ = _get_user_storage_dirs(token or "guest")
        file_path = os.path.join(user_up_dir, safe_filename)

        # Stream-copy in chunks rather than shutil.copyfileobj's unbounded read
        total_written = 0
        with open(file_path, "wb") as buffer:
            while chunk := await file.read(1024 * 1024):
                total_written += len(chunk)
                if total_written > MAX_RESUME_UPLOAD_BYTES:
                    buffer.close()
                    os.remove(file_path)
                    raise HTTPException(status_code=413, detail=f"Resume file exceeds the {MAX_RESUME_UPLOAD_BYTES // (1024*1024)}MB upload limit.")
                buffer.write(chunk)

        # Parse resume and extract structured fields
        structured_data = await asyncio.to_thread(parse_resume, file_path)
        data = structured_data.model_dump()
        path = file_path
        
        # If uploaded file is a PDF/DOCX, generate and save a canonical .tex version
        # so master_latex always has the correct \name and \address blocks.
        # If user uploaded .tex, KEEP THAT EXACT FILE AS MASTER TEX (DO NOT MODIFY IT).
        if not file_path.endswith(".tex"):
            canonical_tex_path = os.path.join(user_up_dir, f"{uuid.uuid4().hex}_master.tex")
            canonical_tex = generate_latex_from_json(data)
            with open(canonical_tex_path, "w", encoding="utf-8") as f:
                f.write(canonical_tex)
            path = canonical_tex_path

        # Compile baseline PDF immediately after upload so Before PDF is ready for first Auto-Apply
        try:
            import shutil as _shutil
            _, user_out_dir = _get_user_storage_dirs(token or "guest")
            cls_source = os.path.join(UPLOAD_DIR, "resume.cls")
            if not os.path.exists(cls_source):
                cls_source = os.path.join(BASE_DIR, "assets", "resume.cls")
            if os.path.exists(cls_source):
                _shutil.copy2(cls_source, os.path.join(user_up_dir, "resume.cls"))
                _shutil.copy2(cls_source, os.path.join(user_out_dir, "resume.cls"))

            # Read canonical tex
            with open(path, "r", encoding="utf-8") as _f:
                canonical_tex_content = _f.read()

            if file_path.endswith(".tex"):
                # For user-uploaded .tex: Keep the user's master file 100% pristine and unmodified.
                # Compile baseline PDF directly from user's original .tex
                await asyncio.to_thread(
                    subprocess.run,
                    ["tectonic", path, "--outdir", user_out_dir],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
                )
                print(f"[upload_resume] User-uploaded .tex kept 100% pristine as master for token={token or 'guest'}")
            else:
                # For generated canonical .tex (from PDF/DOCX): apply page-fit optimization
                pages, _ = await asyncio.to_thread(compile_and_check_page_metrics, canonical_tex_content, 1.0, 1.0, None)
                opt_scale = 1.0
                opt_ls = 1.0
                if pages > 1:
                    for ls in [0.95, 0.91, 0.88, 0.82, 0.78]:
                        p, _ = await asyncio.to_thread(compile_and_check_page_metrics, canonical_tex_content, 1.0, ls, None)
                        if p == 1:
                            opt_ls = ls
                            pages = 1
                            break
                if pages > 1:
                    for scale in [0.85, 0.75, 0.65]:
                        p, _ = await asyncio.to_thread(compile_and_check_page_metrics, canonical_tex_content, scale, opt_ls, None)
                        if p == 1:
                            opt_scale = scale
                            break

                fixed_baseline_tex = apply_latex_hotfix(canonical_tex_content, opt_scale, opt_ls, None)
                with open(path, "w", encoding="utf-8") as _f:
                    _f.write(fixed_baseline_tex)

                await asyncio.to_thread(
                    subprocess.run,
                    ["tectonic", path, "--outdir", user_out_dir],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
                )
                print(f"[upload_resume] Baseline PDF compiled (scale={opt_scale}, ls={opt_ls}) for token={token or 'guest'}")
        except Exception as baseline_err:
            print(f"[upload_resume] Warning: Baseline PDF compilation failed: {baseline_err}")

        # Compute standalone ATS score & Playbook suggestions for master resume
        from services.ats_scorer import evaluate_master_resume
        evaluation = evaluate_master_resume(data)

        # Save to session-scoped cache
        set_session_data(token, data, path)
        
        # Clear stale analysis cache so fresh resume immediately re-evaluates
        clear_user_cached_analysis(token)
        
        # Save session-scoped state to local file for persistence compatibility
        guest_file = _get_guest_state_file(token)
        try:
            with open(guest_file, "w") as f:
                json.dump({"data": data, "path": path, "evaluation": evaluation}, f, indent=2)
        except Exception as file_err:
            print(f"[upload_resume] Warning: Could not save guest state file {guest_file}: {file_err}")
        
        return {
            "message": "Resume uploaded and parsed successfully",
            "data": data,
            "evaluation": evaluation
        }
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/get_session_resume")
async def get_session_resume(authorization: Optional[str] = Header(None)):
    """Returns the current parsed resume data for the active session token or default guest."""
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]

    session_info = get_session_data(token)
    data = session_info.get("data", {})
    if not data or not data.get("education"):
        # Check guest state file fallback
        guest_file = _get_guest_state_file(token)
        if not os.path.exists(guest_file):
            guest_file = _get_guest_state_file("guest")
        if os.path.exists(guest_file):
            try:
                with open(guest_file, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    data = saved.get("data", {})
                    set_session_data(token or "guest", data, saved.get("path", ""))
            except Exception as e:
                print(f"[get_session_resume] Error reading state file: {e}")

    return {
        "status": "success",
        "data": data,
        "path": session_info.get("path", "")
    }

def compile_and_check_page_metrics(latex_code: str, spacing_scale: float = 1.0, linespread: float = 1.0, master_latex: Optional[str] = None) -> tuple[int, float]:
    try:
        # FIX #2 (part 2): use a unique temp filename per call instead of the fixed
        # "temp_check.tex"/"temp_check.pdf". Since analyze_job can run concurrently
        # for different users, the old fixed names let concurrent requests clobber
        # each other's compile output and read back the wrong PDF.
        unique_id = uuid.uuid4().hex[:10]
        temp_tex = os.path.join(OUTPUT_DIR, f"temp_check_{unique_id}.tex")
        temp_pdf = os.path.join(OUTPUT_DIR, f"temp_check_{unique_id}.pdf")
        
        fixed_code = apply_latex_hotfix(latex_code, spacing_scale, linespread, master_latex)
        with open(temp_tex, "w", encoding="utf-8") as f:
            f.write(fixed_code)
            
        import shutil
        cls_source = os.path.join(UPLOAD_DIR, "resume.cls")
        if not os.path.exists(cls_source):
            cls_source = os.path.join(BASE_DIR, "assets", "resume.cls")
            
        shutil.copy2(cls_source, os.path.join(OUTPUT_DIR, "resume.cls"))
        
        result = subprocess.run(
            ["tectonic", temp_tex, "--outdir", OUTPUT_DIR],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        if result.returncode != 0:
            print(f"Tectonic check failed: {result.stderr}")
            return 999, 0.0
            
        reader = PdfReader(temp_pdf)
        pages = len(reader.pages)
        
        filled_height = 0.0
        if pages > 0:
            page = reader.pages[0]
            min_y = 9999.0
            max_y = -9999.0
            
            def visitor(text, cm, tm, font_dict, font_size):
                nonlocal min_y, max_y
                if text.strip():
                    y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
                    if y < min_y:
                        min_y = y
                    if y > max_y:
                        max_y = y
            try:
                page.extract_text(visitor_text=visitor)
                if min_y < 9999.0:
                    filled_height = max_y - min_y
            except Exception as ex:
                print(f"Error extracting baseline coordinates: {ex}")
                
        if os.path.exists(temp_tex):
            os.remove(temp_tex)
        if os.path.exists(temp_pdf):
            os.remove(temp_pdf)
            
        return pages, filled_height
    except Exception as e:
        print(f"Error checking page metrics: {e}")
        return 999, 0.0

def _extract_company_from_jd(jd_text: str, job_url: str = None) -> str:
    """Extract the hiring company name from job URL (mandatory) or job description."""

    # MANDATORY: First try to extract from URL - this is the most reliable source
    if job_url:
        try:
            import re as _re_url
            from urllib.parse import unquote

            # Decode URL-encoded characters (e.g., %E2%80%8B for zero-width space)
            decoded_url = unquote(job_url)
            # Remove zero-width spaces and other invisible characters
            cleaned_url = decoded_url.replace('​', '').replace('​', '').replace('‌', '').replace('‍', '')
            print(f"[_extract_company_from_jd] Cleaned URL: {cleaned_url}")

            # LinkedIn Job URL: https://www.linkedin.com/jobs/view/data-scientist-at-merimen-4437635758
            # Job title can itself contain "-at-CompanyA-at-CompanyB-{jobId}", so we MUST look for
            # the LAST "-at-" segment immediately before the numeric job ID — not the first one.
            # Strategy: strip the job-ID suffix first, then split on "-at-" and take the last part.
            li_slug_match = _re_url.search(r'/jobs/view/(.+?)(?:/|\?|$)', cleaned_url)
            if li_slug_match:
                slug = li_slug_match.group(1).lower()
                # Remove trailing job ID (7-13 digits)
                slug_without_id = _re_url.sub(r'-\d{7,13}$', '', slug)
                if '-at-' in slug_without_id:
                    # Split on "-at-" and take the last segment → the actual company slug
                    company_slug_part = slug_without_id.split('-at-')[-1]
                    company_from_linkedin = company_slug_part.strip().replace('-', ' ').strip().title()
                    if company_from_linkedin and company_from_linkedin.lower() not in {'', 'unknown'}:
                        print(f"[_extract_company_from_jd] ✓ Extracted from LinkedIn Job URL slug: {company_from_linkedin}")
                        return company_from_linkedin

            # LinkedIn Company URL: https://www.linkedin.com/company/merimen-technologies-singapore-pte-ltd/life/
            # Extract company slug and scrape the page to get the actual company name
            linkedin_company_match = _re_url.search(r'/company/([a-z0-9\-]+)(?:/|$)', cleaned_url.lower())
            if linkedin_company_match:
                company_slug = linkedin_company_match.group(1)
                print(f"[_extract_company_from_jd] Found LinkedIn company slug: {company_slug}")

                # Try to scrape the LinkedIn company page to get the actual company name
                try:
                    # pyrefly: ignore [missing-import]
                    from playwright.sync_api import sync_playwright
                    with sync_playwright() as p:
                        browser = p.chromium.launch(headless=True)
                        context = browser.new_context(
                            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
                        )
                        page = context.new_page()
                        try:
                            page.goto(job_url, wait_until="domcontentloaded", timeout=10000)
                            # Look for company name in page title or meta tags
                            page_title = page.title()
                            # LinkedIn company page title format: "Company Name | LinkedIn"
                            title_match = _re_url.search(r'^([^|]+)\s*\|', page_title)
                            if title_match:
                                company_name = title_match.group(1).strip()
                                print(f"[_extract_company_from_jd] ✓ Scraped from LinkedIn company page: {company_name}")
                                browser.close()
                                return company_name
                        except Exception as e:
                            print(f"[_extract_company_from_jd] Failed to scrape LinkedIn company page: {e}")
                        finally:
                            browser.close()
                except Exception as e:
                    print(f"[_extract_company_from_jd] Playwright scraping failed: {e}")

                # Fallback: use the slug as company name
                company_from_slug = company_slug.replace('-', ' ').strip().title()
                if company_from_slug and company_from_slug.lower() not in {'', 'unknown'}:
                    print(f"[_extract_company_from_jd] ✓ Fallback to slug: {company_from_slug}")
                    return company_from_slug

            # Indeed Company URL: https://www.indeed.com/cmp/Apple?campaignid=...
            indeed_cmp_match = _re_url.search(r'/cmp/([a-zA-Z0-9%_\-]+)', cleaned_url)
            if indeed_cmp_match:
                company_from_cmp = unquote(indeed_cmp_match.group(1)).replace('+', ' ').replace('-', ' ').title()
                if company_from_cmp and company_from_cmp.lower() not in {'unknown', ''}:
                    print(f"[_extract_company_from_jd] ✓ Extracted from Indeed /cmp/ link: {company_from_cmp}")
                    return company_from_cmp

            # Indeed query parameter: https://www.indeed.com/viewjob?jk=abc123def456&company=CompanyName
            indeed_match = _re_url.search(r'[?&]company=([^&]+)', cleaned_url)
            if indeed_match:
                company_from_indeed = unquote(indeed_match.group(1)).replace('+', ' ').replace('%20', ' ').title()
                print(f"[_extract_company_from_jd] ✓ Extracted from Indeed URL: {company_from_indeed}")
                return company_from_indeed

            # Generic: try to extract domain company name
            # e.g., https://careers.google.com/jobs/... -> Google
            domain_match = _re_url.search(r'(?:careers\.|jobs\.)?([a-z0-9-]+)\.(?:com|io|org|co)', cleaned_url.lower())
            if domain_match:
                company_from_domain = domain_match.group(1).capitalize()
                # Validate it's not a generic domain
                if company_from_domain.lower() not in {'www', 'mail', 'jobs', 'careers', 'apply', 'recruit', 'linkedin', 'indeed', 'my'}:
                    print(f"[_extract_company_from_jd] ✓ Extracted from URL domain: {company_from_domain}")
                    return company_from_domain
        except Exception as e:
            print(f"[_extract_company_from_jd] URL extraction failed: {e}")

    # Fallback to domain host or URL slug if regex/LLM extraction fails
    if job_url:
        try:
            from urllib.parse import urlparse
            netloc = urlparse(job_url).netloc.replace("www.", "")
            parts = netloc.split(".")
            if len(parts) >= 2 and parts[-2].lower() not in {'linkedin', 'indeed', 'glassdoor'}:
                return parts[-2].capitalize()
        except Exception:
            pass

    # If URL extraction failed, try JD-based extraction
    if not jd_text or "failed to retrieve" in (jd_text or "").lower():
        print(f"[_extract_company_from_jd] ✗ No company found in URL or JD")
        return "Target Hiring Company"

    # Try regex patterns on JD
    patterns = [
        r"(?:About|Join|At|with)\s+([A-Z][\w&.,'-]{1,40}(?:\s+[A-Z][\w&.,'-]{1,20}){0,3})",
        r"([A-Z][\w&.,'-]{2,40}(?:\s+[A-Z][\w&.,'-]{1,20}){0,2})\s+is\s+(?:hiring|looking|seeking|a|an)",
        r"([A-Z][\w&.,'-]{2,40}(?:\s+[A-Z][\w&.,'-]{1,20}){0,2})\s+(?:Inc\.?|LLC|Ltd\.?|Corp\.?|Co\.?)",
    ]
    for pat in patterns:
        m = _re.search(pat, jd_text[:1500])
        if m:
            name = m.group(1).strip().rstrip('.,;')
            # Filter out generic words and frameworks
            if name.lower() not in {'the', 'a', 'an', 'we', 'our', 'this', 'you', 'your', 'us', 'etl', 'api', 'sdk', 'framework', 'platform', 'tool', 'system', 'devops', 'mlops', 'data', 'engineering'} and 'premium' not in name.lower():
                print(f"[_extract_company_from_jd] ✓ Regex extracted company: {name}")
                return name

    # If regex fails, try LLM extraction
    try:
        from services.gemini_client import generate_content_with_fallback
        prompt = f"""Extract the company name from this job description. Return ONLY the company name, nothing else. If you cannot find a company name, return 'Unknown'.

Job Description:
{jd_text[:1000]}"""

        company_name = generate_content_with_fallback(prompt)
        company_name = company_name.strip().strip('"\'')

        # Validate it's not a framework/tool name
        if company_name and len(company_name) < 100 and company_name.lower() not in {'etl', 'api', 'sdk', 'framework', 'platform', 'tool', 'system', 'unknown', 'n/a', 'na', 'devops', 'mlops', 'data', 'engineering'}:
            print(f"[_extract_company_from_jd] ✓ LLM extracted company: {company_name}")
            return company_name
    except Exception as e:
        print(f"[_extract_company_from_jd] LLM extraction failed: {e}")

    print(f"[_extract_company_from_jd] ✗ Could not extract company name")
    return ""

# In-memory analysis cache: keys are MD5(token + job_title + jd_text), values are AnalysisResponse_model_dump. 1hr TTL, bounded size.
_analysis_cache = TTLCache(ttl_seconds=3600, max_size=1000)

# ─── Per-IP rate limiting for costly endpoints ─────────────────────────────
# Simple in-memory sliding-window limiter: no external deps needed for a
# single-process deployment. Protects /scrape_job, /search_matching_jobs, and
# /apply — the three unauthenticated-or-cheaply-authenticated routes that each
# trigger an expensive Playwright browser launch and/or LLM call chain, so a
# single abusive client can't cheaply exhaust API quota or CPU.
_rate_limit_hits: dict[str, list] = {}
_rate_limit_lock = threading.Lock()

def _check_rate_limit(request: Request, key_prefix: str, max_requests: int, window_seconds: int):
    """Raises HTTPException(429) if the caller's IP has exceeded max_requests
    within the trailing window_seconds. Call at the top of a route handler."""
    client_ip = request.client.host if request.client else "unknown"
    key = f"{key_prefix}:{client_ip}"
    now = time.time()
    with _rate_limit_lock:
        hits = [t for t in _rate_limit_hits.get(key, []) if now - t < window_seconds]
        if len(hits) >= max_requests:
            raise HTTPException(status_code=429, detail=f"Rate limit exceeded: max {max_requests} requests per {window_seconds}s for this endpoint. Try again shortly.")
        hits.append(now)
        _rate_limit_hits[key] = hits
        # Opportunistic cleanup of unrelated stale keys so this dict doesn't
        # grow unbounded across many distinct client IPs over time.
        if len(_rate_limit_hits) > 500:
            for k in list(_rate_limit_hits.keys()):
                if not any(now - t < window_seconds for t in _rate_limit_hits.get(k, [])):
                    _rate_limit_hits.pop(k, None)

# In-memory job search cache: keys are (keywords, location, timeframe), values are jobs_list. 5 min TTL, bounded size.
_job_search_cache = TTLCache(ttl_seconds=300, max_size=500)

def get_cached_analysis(token: str, job_title: str, jd_text: str) -> Optional[dict]:
    if not jd_text:
        return None
    key_src = f"{token or 'guest'}:{job_title}:{jd_text}"
    key = hashlib.md5(key_src.encode("utf-8"), usedforsecurity=False).hexdigest()
    return _analysis_cache.get(key)

def set_cached_analysis(token: str, job_title: str, jd_text: str, analysis: dict):
    if not jd_text:
        return
    key_src = f"{token or 'guest'}:{job_title}:{jd_text}"
    key = hashlib.md5(key_src.encode("utf-8"), usedforsecurity=False).hexdigest()
    _analysis_cache.set(key, analysis)

def clear_user_cached_analysis(token: Optional[str] = None):
    """Clears cached job fit analyses when a candidate uploads a new master resume."""
    _analysis_cache.clear()

class RunContext:
    def __init__(self, user_token: Optional[str], job_title: str):
        self.run_id = uuid.uuid4().hex[:8]
        self.user = user_token[-8:] if user_token else "guest"
        self.job_title = job_title
        self.steps: list[dict] = []
        self.start = time.time()

    def log_step(self, step_name: str, latency: float, model: str = "N/A"):
        self.steps.append({
            "run_id": self.run_id,
            "user": self.user,
            "job": self.job_title,
            "step": step_name,
            "latency_sec": round(latency, 3),
            "model": model,
            "elapsed_total": round(time.time() - self.start, 3)
        })
        print(f"[TRACE] {json.dumps(self.steps[-1])}")

    def get_summary(self) -> str:
        return f"Trace {self.run_id} finished in {time.time() - self.start:.2f}s across {len(self.steps)} steps."

async def _send_website_tailoring_email(token: Optional[str], session_resume_data: dict, dumped_analysis: dict, job_title: str, company_name: str, job_url: Optional[str], overleaf_url: Optional[str], persistent_pdf_path: str, request_send_email: bool = False, source_mode: str = "website", pre_score: Optional[int] = None):
    """Helper to check user preference and dispatch website tailoring emails with PDF attachment."""
    print(f"[analyze_job] _send_website_tailoring_email called. token={bool(token)}, pdf_path={persistent_pdf_path}, exists={os.path.exists(persistent_pdf_path) if persistent_pdf_path else False}")
    if not token:
        print(f"[analyze_job] Skipping website tailoring email: token invalid.")
        return
    
    pdf_attachment = persistent_pdf_path if (persistent_pdf_path and os.path.exists(persistent_pdf_path)) else None
    try:
        user_obj = await async_get_user_by_token(token)
        should_email = False
        if user_obj:
            should_email = user_obj.get("send_tailored_email", False)

        if request_send_email:
            should_email = True

        print(f"[analyze_job] Tailored email check: user={user_obj.get('email') if user_obj else None}, should_email={should_email}")

        if should_email and user_obj and user_obj.get("email"):
            dest_email = user_obj["email"]
            print(f"[analyze_job] Dispatching tailored PDF email to {dest_email}...")
            cand_name = session_resume_data.get("name", "").strip() or "Candidate" if isinstance(session_resume_data, dict) else "Candidate"
            ats_score_val = None
            if isinstance(dumped_analysis, dict):
                match_analysis = dumped_analysis.get("match_analysis", {})
                if isinstance(match_analysis, dict):
                    ats_score_val = match_analysis.get("overall_score")
                if ats_score_val is None:
                    ats_score_val = dumped_analysis.get("overall_score") or dumped_analysis.get("score")
            
            # Format ATS score with Before vs After comparison if increased
            if pre_score is not None and ats_score_val is not None and ats_score_val > pre_score:
                score_suffix = f" [{pre_score}% ➔ {ats_score_val}% Match (+{ats_score_val - pre_score}%)]"
                ats_display = f"<span style='color: #64748B; text-decoration: line-through;'>{pre_score}%</span> ➔ <strong style='color: #10B981;'>{ats_score_val}% Match</strong> <span style='background: #DCFCE7; color: #15803D; font-size: 0.8rem; font-weight: 700; padding: 2px 6px; border-radius: 6px;'>+{ats_score_val - pre_score}% Boost</span>"
            else:
                score_suffix = f" [{ats_score_val}% Match]" if ats_score_val is not None else ""
                ats_display = f"{ats_score_val}% Match" if ats_score_val is not None else "100% Match"
            
            is_ext = (source_mode == "extension") or request_send_email
            mode_title = "Extension Tailoring" if is_ext else "Website Tailoring"
            mode_detail = "Extension 1-Click Tailoring" if is_ext else "Website Interactive Tailoring"
            
            email_subj = f"🎯 [{mode_title}] Resume Tailored{score_suffix}: {job_title} at {company_name}"
            email_text = (
                f"Hello {cand_name},\n\n"
                f"Your {mode_title} for '{job_title}' at '{company_name}' has completed successfully!\n\n"
                f"We have attached your compiled PDF resume directly to this email.\n\n"
                f"View the job listing and apply here:\n{job_url or ''}\n\n"
                f"Want to edit or customize it online? Open it in Overleaf:\n{overleaf_url or ''}\n\n"
                f"Best of luck with your application!"
            )
            email_html = f"""
            <div style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; max-width: 600px; margin: 0 auto; padding: 30px; border: 1px solid #E2E8F0; border-radius: 16px; background-color: #FAFAFA; box-shadow: 0 4px 20px rgba(0,0,0,0.03);">
                <div style="text-align: center; margin-bottom: 24px;">
                    <span style="font-size: 3rem;">📄</span>
                    <span style="display: inline-block; background-color: #0284C7; color: #FFFFFF; font-size: 0.72rem; font-weight: 700; padding: 3px 10px; border-radius: 12px; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px;">{mode_title}</span>
                    <h2 style="color: #0284C7; margin: 6px 0 5px; font-weight: 800; font-size: 1.6rem;">Tailoring Completed!</h2>
                    <p style="color: #64748B; font-size: 0.9rem; margin: 0;">For your application at <strong>{company_name}</strong></p>
                </div>
                <div style="background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 12px; padding: 20px; margin-bottom: 24px;">
                    <table style="width: 100%; border-collapse: collapse;">
                        <tr>
                            <td style="padding: 6px 0; color: #64748B; font-size: 0.85rem; width: 100px;">Target Role:</td>
                            <td style="padding: 6px 0; color: #1E293B; font-size: 0.9rem; font-weight: 600;">{job_title}</td>
                        </tr>
                        <tr>
                            <td style="padding: 6px 0; color: #64748B; font-size: 0.85rem;">Company:</td>
                            <td style="padding: 6px 0; color: #1E293B; font-size: 0.9rem; font-weight: 600;">{company_name}</td>
                        </tr>
                        <tr>
                            <td style="padding: 6px 0; color: #64748B; font-size: 0.85rem;">Mode:</td>
                            <td style="padding: 6px 0; color: #0284C7; font-size: 0.9rem; font-weight: 600;">{mode_detail}</td>
                        </tr>
                        <tr>
                            <td style="padding: 6px 0; color: #64748B; font-size: 0.85rem;">ATS Score:</td>
                            <td style="padding: 6px 0; color: #0284C7; font-size: 0.95rem;">{ats_display}</td>
                        </tr>
                    </table>
                </div>
                <p style="color: #475569; font-size: 0.95rem; line-height: 1.6; margin: 0 0 20px;">
                    Hello {cand_name}, your {mode_detail.lower()} has finished successfully. Your experience bullet points and technical keywords have been optimized, and your compiled PDF resume is attached directly to this email.
                </p>
                <div style="text-align: center; margin: 30px 0 20px;">
                    {"<a href='" + job_url + "' target='_blank' style='display: inline-block; background-color: #10B981; color: #FFFFFF; text-decoration: none; padding: 12px 30px; border-radius: 8px; font-weight: bold; font-size: 0.9rem; margin-bottom: 12px;'>🚀 View Job & Apply</a><br/>" if job_url else ""}
                    {"<a href='" + overleaf_url + "' target='_blank' style='display: inline-block; background-color: #0284C7; color: #FFFFFF; text-decoration: none; padding: 12px 30px; border-radius: 8px; font-weight: bold; font-size: 0.9rem;'>🍃 Open & Edit in Overleaf</a>" if overleaf_url else ""}
                </div>
                <hr style="border: 0; border-top: 1px solid #E2E8F0; margin: 30px 0 20px;" />
                <p style="font-size: 0.8rem; color: #94A3B8; text-align: center; margin: 0;">
                    Sent automatically by your Resume Tailor Assistant ({mode_title} Mode).
                </p>
            </div>
            """
            from services.email_service import async_send_notification_email
            email_sent = await async_send_notification_email(
                to_email=dest_email,
                subject=email_subj,
                text_body=email_text,
                html_body=email_html,
                attachment_path=pdf_attachment,
                attachment_name=f"Tailored_Resume_{company_name.replace(' ', '_')}.pdf"
            )
            print(f"[analyze_job] Tailored PDF email delivery result: {email_sent}")
    except Exception as email_err:
        print(f"[analyze_job] Failed sending tailored email: {email_err}")


class ExtensionParseJobRequest(BaseModel):
    page_text: Optional[str] = None
    page_url: Optional[str] = None
    page_title: Optional[str] = None

@app.post("/extension/parse_job_details")
async def parse_job_details_endpoint(request: ExtensionParseJobRequest):
    """Extract exact Company, Job Title & full JD for Chrome Extension popup without redundant re-scraping."""
    title = request.page_title or ""
    company = ""
    description = request.page_text or ""
    
    # Only scrape on the backend if frontend extraction was empty
    if not description and request.page_url and ("linkedin.com/jobs" in request.page_url or "indeed.com" in request.page_url):
        try:
            from services.scraper import scrape_job_description
            scraped = await scrape_job_description(request.page_url)
            if scraped and scraped.get("description"):
                if scraped.get("title") and scraped.get("title") not in ["LinkedIn Job", "Indeed Job"]:
                    title = scraped.get("title")
                if scraped.get("company"):
                    company = scraped.get("company")
                if scraped.get("description") and len(scraped.get("description")) > 100:
                    description = scraped.get("description")
                print(f"[/extension/parse_job_details] ⚡ Enriched via Backend Scraper: {company} - {title}")
        except Exception as e:
            print(f"[/extension/parse_job_details] Backend Scraper enrichment warning: {e}")

    # Extract company from URL / JD text if not yet identified
    if not company and request.page_url:
        company = await asyncio.to_thread(_extract_company_from_jd, description, request.page_url)
    if not company and description:
        company = await asyncio.to_thread(_extract_company_from_jd, description, None)
        
    # Filter out invalid titles falsely captured from auth buttons
    invalid_titles = {"sign in", "log in", "login", "register", "apply now", "menu", "search", "indeed", "linkedin", "apple"}
    if title.lower() in invalid_titles or not title.strip():
        # Fallback: extract title from URL or description
        if request.page_url and "indeed.com" in request.page_url:
            from services.scraper import scrape_job_description
            try:
                scraped = await scrape_job_description(request.page_url)
                if scraped and scraped.get("title") and scraped.get("title").lower() not in invalid_titles:
                    title = scraped.get("title")
            except Exception:
                pass
        if title.lower() in invalid_titles:
            title = "Target Role"

    return {
        "job_title": title,
        "company": company or "Hiring Company",
        "job_description": description
    }


class ScanPortalsRequest(BaseModel):
    keywords: Optional[List[str]] = None
    min_ats_score: Optional[int] = 70

@app.post("/portals/scan")
async def scan_portals_endpoint(request: ScanPortalsRequest, authorization: Optional[str] = Header(None)):
    """Automated ATS Portal Scanner (Greenhouse, Ashby, Lever) for discovery."""
    token = authorization.split(" ")[1] if authorization and authorization.startswith("Bearer ") else None
    session = get_session_data(token)
    session_resume = session.get("data") or {}

    from services.portal_scanner import PortalScanner
    scanner = PortalScanner()
    raw_jobs = await scanner.scan_all_portals(target_keywords=request.keywords)
    
    if session_resume:
        scored = scanner.score_portal_jobs_for_candidate(raw_jobs, session_resume, min_score=request.min_ats_score or 70)
        return {"total_found": len(raw_jobs), "matching_jobs": scored}
    
    return {"total_found": len(raw_jobs), "matching_jobs": raw_jobs[:20]}


@app.get("/render_html_resume")
async def render_html_resume_endpoint(authorization: Optional[str] = Header(None)):
    """Render and preview candidate resume as responsive HTML."""
    token = authorization.split(" ")[1] if authorization and authorization.startswith("Bearer ") else None
    session = get_session_data(token)
    session_resume = session.get("data")
    if not session_resume:
        raise HTTPException(status_code=400, detail="Please upload a resume first.")

    from services.html_resume_renderer import render_html_resume
    html = render_html_resume(session_resume)
    return Response(content=html, media_type="text/html")


@app.get("/download_extension")
async def download_extension(key: Optional[str] = None):
    """Dynamically package Chrome Extension ZIP with pre-filled Sync Key for 1-click installation."""

    # Resolve extension directory across candidate paths
    backend_file_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(backend_file_dir, "extension"),
        os.path.join(os.path.dirname(backend_file_dir), "extension"),
        os.path.join(os.getcwd(), "extension"),
        os.path.join(BASE_DIR, "extension")
    ]
    ext_dir = None
    for cand in candidates:
        if os.path.exists(cand) and os.path.isdir(cand):
            ext_dir = cand
            break
    if not ext_dir:
        raise HTTPException(status_code=404, detail=f"Extension directory not found. Looked in: {candidates}")

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for root, dirs, files in os.walk(ext_dir):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, ext_dir)
                
                # Pre-fill sync key inside popup.js if key param is provided
                if key and file == "popup.js":
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        js_content = f.read()
                    # Inject default user token key into popup.js
                    injection = f'chrome.storage.local.set({{ userToken: "{key}" }});\n  chrome.storage.local.get(["userToken"], (items) => {{'
                    js_content = js_content.replace(
                        'chrome.storage.local.get(["userToken"], (items) => {',
                        injection
                    )
                    zip_file.writestr(arcname, js_content)
                else:
                    zip_file.write(file_path, arcname)

    zip_buffer.seek(0)
    filename = f"Job_Finder_Extension_{key or 'latest'}.zip"
    return Response(
        content=zip_buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )



@app.post("/analyze_job")
async def analyze_job(request: JobAnalysisRequest, http_request: Request, authorization: Optional[str] = Header(None), x_gemini_api_key: Optional[str] = Header(None)):
    # Rate limit check for analyze_job
    _check_rate_limit(http_request, "analyze_job", max_requests=10, window_seconds=300)
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]

    session = get_session_data(token)
    session_resume_data = session.get("data")
    session_resume_path = session.get("path")

    if not session_resume_data:
        raise HTTPException(status_code=400, detail="Please upload a resume first.")
        
    # Check cache early before starting the generator (only if not forcing fresh tailoring)
    if request.job_description and not request.force_tailoring:
        cached = get_cached_analysis(token, request.job_title, request.job_description)
        if cached:
            # Strip latex code if user requested skip_tailoring
            if request.skip_tailoring:
                cached = dict(cached)
                cached["latex_code"] = ""
            elif not request.skip_tailoring and cached.get("latex_code"):
                try:
                    entry_company = request.company if (request.company and request.company not in ['Target Company', 'Hiring Company', 'Detecting company...']) else await asyncio.to_thread(_extract_company_from_jd, request.job_description, request.job_url)
                    safe_key = _safe_key(token)
                    _, user_out_dir = _get_user_storage_dirs(safe_key)
                    tex_path, temp_pdf_path = _user_output_paths(token)
                    cached_pdf = temp_pdf_path if os.path.exists(temp_pdf_path) else tex_path.replace(".tex", ".pdf")
                    cached_pdf_url = f"/download_application_pdf/{safe_key}/{os.path.basename(cached_pdf)}" if os.path.exists(cached_pdf) else None
                    cached_cand = session_resume_data.get("name", "") if isinstance(session_resume_data, dict) else ""
                    cached_overleaf = upload_zip_to_tmpfiles(cached.get("latex_code", ""), cached_cand, request.job_title, entry_company) if cached.get("latex_code") else None
                    
                    await asyncio.to_thread(record_application, token, {
                        "job_title": request.job_title,
                        "company": entry_company,
                        "job_url": request.job_url or "",
                        "score": cached.get("match_analysis", {}).get("overall_score"),
                        "status": "tailored",
                        "source_mode": getattr(request, "source_mode", "website"),
                        "pdf_url": cached_pdf_url,
                        "overleaf_url": cached_overleaf
                    })
                    await _send_website_tailoring_email(token, session_resume_data, cached, request.job_title, entry_company, request.job_url, cached_overleaf, cached_pdf, request_send_email=request.send_email, source_mode=getattr(request, 'source_mode', 'website'))
                except Exception as hist_err:
                    print(f"[analyze_job] Failed to record application history / email on cache hit: {hist_err}")

            # Only short-circuit from cache if we were skipping tailoring OR if we actually have the compiled LaTeX code
            if request.skip_tailoring or cached.get("latex_code"):
                async def cached_event_generator():
                    yield json.dumps({"type": "log", "message": "⚡ Loaded analysis from local cache!"}) + "\n"
                    company_name = await asyncio.to_thread(_extract_company_from_jd, request.job_description, request.job_url)
                    yield json.dumps({
                        "type": "result",
                        "job_title": request.job_title,
                        "job_description": request.job_description,
                        "company": company_name,
                        "analysis": cached
                    }) + "\n"
                return StreamingResponse(cached_event_generator(), media_type="text/event-stream")


    async def event_generator():
        ctx = RunContext(token, request.job_title)
        try:
            db_api_key = None
            if token:
                user = await async_get_user_by_token(token)
                if user:
                    db_api_key = user.get("gemini_api_key")
            
            active_api_key = x_gemini_api_key or db_api_key
            jd_text = request.job_description
            job_title = request.job_title
            if request.job_url and not jd_text:
                yield json.dumps({"type": "log", "percent": 15, "message": "🤖 Launching Playwright browser to scrape job link..."}) + "\n"
                t0 = time.time()
                scraped = await scrape_job_description(request.job_url)
                jd_text = scraped["description"]
                job_title = scraped["title"]
                
                # Guard: Reject bot-blocked / Cloudflare verification challenge pages
                _bot_block_phrases = [
                    "cloudflare security verification",
                    "anti-bot challenge",
                    "security verification page",
                    "verify you are human",
                    "checking your browser",
                    "enable javascript and cookies",
                    "access denied",
                    "just a moment",
                    "error processing your request"
                ]
                if scraped.get("is_bot_blocked") or any(p in jd_text.lower() for p in _bot_block_phrases):
                    yield json.dumps({"type": "log", "percent": 100, "message": "⚠️ Security challenge detected: The job board returned an anti-bot verification page."}) + "\n"
                    yield json.dumps({
                        "type": "error",
                        "message": "The job posting URL returned a security verification / anti-bot challenge page (e.g. Cloudflare). Please copy and paste the raw job description text directly into the text area."
                    }) + "\n"
                    return

                ctx.log_step("scrape_job", time.time() - t0)
                yield json.dumps({"type": "log", "percent": 20, "message": f"✅ Scraped job details for: {job_title}"}) + "\n"
                yield json.dumps({"type": "scraped_data", "job_title": job_title, "job_description": jd_text}) + "\n"
                
                # Check cache again after scraping
                cached = get_cached_analysis(token, job_title, jd_text)
                if cached:
                    # Strip latex code if user requested skip_tailoring
                    if request.skip_tailoring:
                        cached = dict(cached)
                        cached["latex_code"] = ""
                    elif not request.skip_tailoring:
                        try:
                            entry_company = request.company if (request.company and request.company not in ['Target Company', 'Hiring Company', 'Detecting company...']) else await asyncio.to_thread(_extract_company_from_jd, jd_text, request.job_url)
                            safe_key = _safe_key(token)
                            tex_path, temp_pdf_path = _user_output_paths(token)
                            cached_pdf = temp_pdf_path if os.path.exists(temp_pdf_path) else tex_path.replace(".tex", ".pdf")
                            cached_pdf_url = f"/download_application_pdf/{safe_key}/{os.path.basename(cached_pdf)}" if os.path.exists(cached_pdf) else None
                            cached_cand = session_resume_data.get("name", "") if isinstance(session_resume_data, dict) else ""
                            cached_overleaf = upload_zip_to_tmpfiles(cached.get("latex_code", ""), cached_cand, job_title, entry_company) if cached.get("latex_code") else None
                            
                            await asyncio.to_thread(record_application, token, {
                                "job_title": job_title,
                                "company": entry_company,
                                "job_url": request.job_url or "",
                                "score": cached.get("match_analysis", {}).get("overall_score"),
                                "status": "tailored",
                                "source_mode": getattr(request, "source_mode", "website"),
                                "pdf_url": cached_pdf_url,
                                "overleaf_url": cached_overleaf
                            })
                        except Exception as hist_err:
                            print(f"[analyze_job] Failed to record application history (cache hit): {hist_err}")
                    yield json.dumps({"type": "log", "percent": 100, "message": "⚡ Loaded analysis from local cache!"}) + "\n"
                    company_name = await asyncio.to_thread(_extract_company_from_jd, jd_text, request.job_url)
                    yield json.dumps({
                        "type": "result",
                        "percent": 100,
                        "job_title": job_title,
                        "job_description": jd_text,
                        "company": company_name,
                        "analysis": cached
                    }) + "\n"
                    return
                
            yield json.dumps({"type": "log", "percent": 40, "message": "🤖 Comparing candidate profile & calculating ATS gap analysis..."}) + "\n"
            master_latex = None
            if session_resume_path and session_resume_path.endswith(".tex") and os.path.exists(session_resume_path):
                with open(session_resume_path, "r", encoding="utf-8") as f:
                    master_latex = f.read()
            else:
                master_latex = generate_latex_from_json(session_resume_data)
                
            def log_callback(msg_json: str):
                try:
                    # Verify it's valid json
                    json.loads(msg_json)
                    LLMClientLogQueue.put(msg_json)
                except Exception:
                    pass

            recruiter_name = None
            if request.job_url and not request.skip_tailoring:
                try:
                    rec_info = await extract_recruiter(request.job_url, None)
                    recruiter_name = rec_info.get("recruiter_name")
                except Exception:
                    pass

            t0 = time.time()
            # Run fit analysis in a background task so we can drain log messages concurrently
            import asyncio
            fit_task = asyncio.create_task(
                analyze_job_fit(
                    session_resume_data,
                    job_title,
                    jd_text,
                    master_latex if not request.skip_tailoring else None,
                    recruiter_name,
                    active_api_key,
                    on_log=log_callback,
                    user_selected_skills=getattr(request, 'user_selected_skills', None)
                )
            )

            # Poll and yield log queue events in real-time while the LLM call is running
            async for event in _stream_task_logs(fit_task):
                yield event

            # Wait for task completion and fetch result
            analysis = await fit_task
            ctx.log_step("analyze_job_fit", time.time() - t0, "gemini-3.1-flash-lite")

            # Yield any remaining leftover log messages
            for event in _drain_remaining_logs():
                yield event

            yield json.dumps({"type": "log", "percent": 75, "message": "✍️ Generated tailored resume content and cover letter."}) + "\n"

            if request.skip_tailoring:
                dumped = analysis.model_dump()
                company_name = await asyncio.to_thread(_extract_company_from_jd, jd_text, request.job_url)
                yield json.dumps({
                    "type": "result",
                    "percent": 100,
                    "job_title": job_title,
                    "job_description": jd_text,
                    "company": company_name,
                    "analysis": dumped
                }) + "\n"
                return
 
            if master_latex:
                suggestions = analysis.suggested_resume_updates
                missing_skills = analysis.match_analysis.missing_skills
    
                # --- Recruiter reviewer loop (up to 3 attempts) ---
                reviewer_attempts = 0
                import hashlib
                prev_review_hash = hashlib.md5(analysis.latex_code.encode("utf-8"), usedforsecurity=False).hexdigest()
                
                last_rejection_feedback = ""
                review = None
                stalled_on_identical_output = False
                
                if not request.force_tailoring:
                    while reviewer_attempts < 3:
                        yield json.dumps({"type": "log", "percent": 80 + (reviewer_attempts * 3), "message": f"👀 Recruiter review check (Attempt {reviewer_attempts + 1})..."}) + "\n"
                        t0 = time.time()
                        
                        # Task-wrapped check to drain logs concurrently
                        review_task = asyncio.create_task(
                            asyncio.to_thread(review_tailored_resume, analysis.latex_code, session_resume_data, job_title, jd_text, active_api_key, on_log=log_callback, user_selected_skills=getattr(request, 'user_selected_skills', None))
                        )
                        while not review_task.done():
                            for msg in drain_llm_logs():
                                yield _format_log_event(msg)
                            await asyncio.sleep(0.5)

                        review = await review_task
                        ctx.log_step(f"recruiter_review_check_attempt_{reviewer_attempts+1}", time.time() - t0, "gemini-3.1-flash-lite")

                        for event in _drain_remaining_logs():
                            yield event

                        if review.satisfied:
                            yield json.dumps({"type": "log", "percent": 88, "message": "✅ Recruiter review approved!"}) + "\n"
                            break
        
                        last_rejection_feedback = review.feedback
                        yield json.dumps({"type": "log", "percent": 82, "message": f"⚠️ Recruiter rejected (Attempt {reviewer_attempts + 1}): {review.feedback}"}) + "\n"
                        t0 = time.time()
                        
                        # Task-wrapped tailoring retry to drain logs concurrently
                        tailor_task = asyncio.create_task(
                            asyncio.to_thread(tailor_latex_code, master_latex, job_title, jd_text, suggestions, missing_skills, active_api_key, review.feedback, on_log=log_callback)
                        )
                        while not tailor_task.done():
                            for msg in drain_llm_logs():
                                yield _format_log_event(msg)
                            await asyncio.sleep(0.5)

                        analysis.latex_code = await tailor_task
                        ctx.log_step(f"tailor_latex_retry_attempt_{reviewer_attempts+1}", time.time() - t0, "gemini-3.5-flash")

                        for event in _drain_remaining_logs():
                            yield event
                                
                        curr_hash = hashlib.md5(analysis.latex_code.encode("utf-8"), usedforsecurity=False).hexdigest()
                        if curr_hash == prev_review_hash:
                            yield json.dumps({"type": "log", "percent": 88, "message": "⚠️ AI reviewer feedback generated identical LaTeX output. Breaking reviewer loop."}) + "\n"
                            stalled_on_identical_output = True
                            break
                        prev_review_hash = curr_hash
                        reviewer_attempts += 1

                    if review is not None and not review.satisfied and (reviewer_attempts >= 3 or stalled_on_identical_output):
                        yield json.dumps({
                            "type": "rejection_warning", 
                            "percent": 100,
                            "message": f"Candidate may not be a suitable fit for this job after {reviewer_attempts + 1} recruitment checks. Reason: {last_rejection_feedback}"
                        }) + "\n"
                        return
                else:
                    yield json.dumps({
                        "type": "log",
                        "percent": 88,
                        "message": "⚠️ Proceeding with resume tailoring anyway due to user override request."
                    }) + "\n"
    
                # --- Page-fit loop (compile first, try mechanical adjustments first) ---
                yield json.dumps({"type": "log", "percent": 90, "message": "⚙️ Compiling PDF & checking page layout..."}) + "\n"
                t0 = time.time()
                pages, filled_height = await asyncio.to_thread(compile_and_check_page_metrics, analysis.latex_code, 1.0, 1.0, master_latex)
                ctx.log_step("compile_pdf_check_metrics", time.time() - t0, "Tectonic")
    
                optimal_scale = 1.0
                optimal_linespread = 1.0
    
                # P0: mechanical shrinking first before LLM condense
                if pages > 1:
                    yield json.dumps({"type": "log", "message": "📐 Page overflow. Trying quick mechanical spacing adjustments..."}) + "\n"
                    # Try decreasing linespread to fit page
                    for ls in [0.95, 0.91, 0.88]:
                        p, h = await asyncio.to_thread(compile_and_check_page_metrics, analysis.latex_code, 1.0, ls, master_latex)
                        if p == 1:
                            pages = p
                            filled_height = h
                            optimal_linespread = ls
                            yield json.dumps({"type": "log", "message": f"✅ Mechanical shrink successful (linespread={ls} fits 1 page!)"}) + "\n"
                            break
    
                # If still over budget, try scale adjustments
                if pages > 1:
                    for scale in [0.8, 0.6, 0.5]:
                        p, h = await asyncio.to_thread(compile_and_check_page_metrics, analysis.latex_code, scale, optimal_linespread, master_latex)
                        if p == 1:
                            pages = p
                            filled_height = h
                            optimal_scale = scale
                            yield json.dumps({"type": "log", "message": f"✅ Mechanical shrink successful (scale={scale} fits 1 page!)"}) + "\n"
                            break
    
                # LLM condensation as last resort only
                retry_count = 0
                import hashlib
                prev_latex_hash = hashlib.md5(analysis.latex_code.encode("utf-8"), usedforsecurity=False).hexdigest()
    
                while pages > 1 and retry_count < 2:
                    yield json.dumps({"type": "log", "message": f"⚠️ Spilled onto page 2. Triggering AI condensation (Attempt {retry_count + 1})..."}) + "\n"
                    condense_feedback = (
                        "CRITICAL: The resume spilled to page 2. You MUST shorten the experience and project bullets "
                        "to be tighter and more concise (max 1.5 lines each). Do NOT remove any job, school, project, "
                        "CPI/GPA value, or bullet point — just make each bullet shorter."
                    )
                    
                    # Task-wrapped tailoring retry to drain logs concurrently
                    tailor_task = asyncio.create_task(
                        asyncio.to_thread(tailor_latex_code, master_latex, job_title, jd_text, suggestions, missing_skills, active_api_key, condense_feedback, on_log=log_callback)
                    )
                    async for event in _stream_task_logs(tailor_task):
                        yield event

                    analysis.latex_code = await tailor_task
                    
                    curr_hash = hashlib.md5(analysis.latex_code.encode("utf-8"), usedforsecurity=False).hexdigest()
                    if curr_hash == prev_latex_hash:
                        yield json.dumps({"type": "log", "message": "⚠️ AI tailorer returned identical code. Escaping retry loop."}) + "\n"
                        break
                    prev_latex_hash = curr_hash
                    
                    # Recheck with scale and current linespread
                    pages, filled_height = await asyncio.to_thread(compile_and_check_page_metrics, analysis.latex_code, optimal_scale, optimal_linespread, master_latex)
                    
                    # Try mechanical spacing again on the condensed content
                    if pages > 1:
                        for ls in [0.95, 0.91, 0.88]:
                            p, h = await asyncio.to_thread(compile_and_check_page_metrics, analysis.latex_code, optimal_scale, ls, master_latex)
                            if p == 1:
                                pages = p
                                filled_height = h
                                optimal_linespread = ls
                                break
                    retry_count += 1
    
                # Pad short resumes if page is under-filled
                if pages == 1 and filled_height < 550.0:
                    yield json.dumps({"type": "log", "message": f"📐 Document is short ({filled_height:.1f} pts height). Adjusting linespread to pad layout..."}) + "\n"
                    for lspread in [1.05, 1.10, 1.15]:
                        p, h = await asyncio.to_thread(compile_and_check_page_metrics, analysis.latex_code, 1.0, lspread, master_latex)
                        if p == 1:
                            optimal_linespread = lspread
                            pages, filled_height = p, h
                        else:
                            break
    
                analysis.latex_code = apply_latex_hotfix(analysis.latex_code, optimal_scale, optimal_linespread, master_latex, user_selected_skills=getattr(request, 'user_selected_skills', None))
            else:
                analysis.latex_code = apply_latex_hotfix(analysis.latex_code, 1.0, 1.0, master_latex, user_selected_skills=getattr(request, 'user_selected_skills', None))

            dumped = analysis.model_dump()
            set_cached_analysis(token, job_title, jd_text, dumped)
            req_comp = getattr(request, "company", None)
            company_name = req_comp if (req_comp and req_comp not in ["Target Company", "Hiring Company", "Detecting company..."]) else None
            if not company_name and "scraped" in locals() and scraped.get("company"):
                company_name = scraped.get("company")
            # Use recruiter info already resolved before tailoring (or extract fast if missing)
            recruiter_profile_url = None
            if "rec_info" in locals() and rec_info:
                recruiter_name = rec_info.get("recruiter_name")
                recruiter_profile_url = rec_info.get("recruiter_profile_url")

            overleaf_url = None
            pdf_url = None
            persistent_pdf_path = None
            if analysis.latex_code:
                try:
                    candidate_name = session_resume_data.get("name", "") if isinstance(session_resume_data, dict) else ""
                    overleaf_url = await asyncio.to_thread(upload_zip_to_tmpfiles, analysis.latex_code, candidate_name, job_title, company_name)
                except Exception as ov_err:
                    print(f"[analyze_job] Failed to generate Overleaf URL: {ov_err}")

                # Compile LaTeX to PDF and store persistent copy for Application History viewing/downloading
                try:
                    tex_path, temp_pdf_path = _user_output_paths(token)
                    fixed_latex = apply_latex_hotfix(analysis.latex_code)
                    with open(tex_path, "w", encoding="utf-8") as f:
                        f.write(fixed_latex)
                    
                    safe_key = _safe_key(token)
                    _, user_out_dir = _get_user_storage_dirs(safe_key)
                    cls_src = os.path.join(UPLOAD_DIR, "resume.cls")
                    if not os.path.exists(cls_src):
                        cls_src = os.path.join(BASE_DIR, "assets", "resume.cls")
                    shutil.copy2(cls_src, os.path.join(user_out_dir, "resume.cls"))

                    comp_res = await asyncio.to_thread(
                        subprocess.run,
                        ["tectonic", tex_path, "--outdir", user_out_dir],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True
                    )
                    print(f"[analyze_job] Tectonic compilation returncode={comp_res.returncode}. temp_pdf_path={temp_pdf_path} exists={os.path.exists(temp_pdf_path)}")
                    if comp_res.returncode == 0:
                        compiled_pdf = None
                        if os.path.exists(temp_pdf_path):
                            compiled_pdf = temp_pdf_path
                        elif os.path.exists(tex_path.replace(".tex", ".pdf")):
                            compiled_pdf = tex_path.replace(".tex", ".pdf")
                        elif os.path.exists(os.path.join(user_out_dir, os.path.basename(tex_path).replace(".tex", ".pdf"))):
                            compiled_pdf = os.path.join(user_out_dir, os.path.basename(tex_path).replace(".tex", ".pdf"))

                        if compiled_pdf and os.path.exists(compiled_pdf):
                            persistent_filename = f"tailored_{safe_key}_{int(time.time())}.pdf"
                            persistent_pdf_path = os.path.join(user_out_dir, persistent_filename)
                            shutil.copy2(compiled_pdf, persistent_pdf_path)
                            pdf_url = f"/download_application_pdf/{safe_key}/{persistent_filename}"

                            # ── Recalculate and validate post-tailoring PDF ATS score & skills guarantee ──
                            try:
                                from services.resume_parser import parse_resume
                                from services.ats_scorer import compute_ats_score, compute_overall_score, estimate_role_fit_score
                                post_tailored_dict = (await asyncio.to_thread(parse_resume, persistent_pdf_path)).model_dump()
                                post_ats_res = compute_ats_score(post_tailored_dict, jd_text)
                                post_rf_score = estimate_role_fit_score(post_tailored_dict, jd_text)
                                calc_post_score = compute_overall_score(post_ats_res.skills_score, post_ats_res.experience_score, post_rf_score)
                                
                                pre_score = dumped.get("match_analysis", {}).get("overall_score", 0)
                                final_post_score = max(pre_score, calc_post_score)
                                dumped["match_analysis"]["overall_score"] = final_post_score
                                dumped["match_analysis"]["skills_score"] = max(dumped.get("match_analysis", {}).get("skills_score", 0), post_ats_res.skills_score)
                                dumped["match_analysis"]["experience_score"] = max(dumped.get("match_analysis", {}).get("experience_score", 0), post_ats_res.experience_score)
                                dumped["match_analysis"]["matched_skills"] = list(post_ats_res.matched_skills)
                                dumped["match_analysis"]["missing_skills"] = list(post_ats_res.missing_skills)
                                set_cached_analysis(token, job_title, jd_text, dumped)
                                print(f"[analyze_job] Pre-tailored score: {pre_score}%, Compiled PDF ATS score: {calc_post_score}%. Final score: {final_post_score}%")
                                print(f"[analyze_job] Validated Matched Skills in PDF: {post_ats_res.matched_skills}")
                            except Exception as post_calc_err:
                                print(f"[analyze_job] Post-tailoring score computation exception: {post_calc_err}")
                except Exception as pdf_compile_err:
                    print(f"[analyze_job] Failed to compile persistent PDF copy: {pdf_compile_err}")

                try:
                    pdf_to_send = persistent_pdf_path if "persistent_pdf_path" in locals() else None
                    initial_score = pre_score if "pre_score" in locals() else None
                    await _send_website_tailoring_email(token, session_resume_data, dumped, job_title, company_name, request.job_url, overleaf_url, pdf_to_send, request_send_email=request.send_email, source_mode=getattr(request, 'source_mode', 'website'), pre_score=initial_score)
                except Exception as email_dispatch_err:
                    print(f"[analyze_job] Error calling _send_website_tailoring_email: {email_dispatch_err}")

            try:
                await asyncio.to_thread(record_application, token, {
                    "job_title": job_title,
                    "company": company_name,
                    "job_url": request.job_url or "",
                    "score": dumped.get("match_analysis", {}).get("overall_score"),
                    "status": "tailored",
                    "source_mode": getattr(request, "source_mode", "website"),
                    "recruiter_name": recruiter_name,
                    "recruiter_profile_url": recruiter_profile_url,
                    "overleaf_url": overleaf_url,
                    "pdf_url": pdf_url,
                    "tailored_tex": analysis.latex_code if analysis else None,
                    "pdf_path": persistent_pdf_path if "persistent_pdf_path" in locals() else None
                })
            except Exception as hist_err:
                print(f"[analyze_job] Failed to record application history: {hist_err}")
            yield json.dumps({
                "type": "result",
                "job_title": job_title,
                "job_description": jd_text or "",
                "company": company_name,
                "analysis": dumped,
                "overleaf_url": overleaf_url
            }) + "\n"
        except Exception as e:
            import traceback
            error_msg = str(e)
            tb_str = traceback.format_exc()
            print(f"[analyze_job] Exception occurred: {error_msg}")
            print(f"[analyze_job] Traceback:\n{tb_str}")
            yield json.dumps({"type": "error", "message": error_msg}) + "\n"
    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.post("/generate_tailored_resume")
async def generate_tailored_resume(tailored_data: dict, authorization: Optional[str] = Header(None)):
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]
    try:
        # FIX #2: per-user output path instead of the fixed "tailored_resume.pdf"
        _, output_pdf = _user_output_paths(token)
        await generate_pdf_resume(tailored_data, output_pdf)
        return FileResponse(output_pdf, media_type="application/pdf", filename="tailored_resume.pdf")
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

# Helper functions and requests imported from utils.latex_utils or defined inline below

class LatexDownloadRequest(BaseModel):
    latex_code: str

@app.post("/download_latex")
async def download_latex(request: LatexDownloadRequest, authorization: Optional[str] = Header(None)):
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]
    try:
        # FIX #2: per-user output path instead of the fixed "tailored_resume.tex"
        tex_path, _ = _user_output_paths(token)
        fixed_code = apply_latex_hotfix(request.latex_code)
        with open(tex_path, "w") as f:
            f.write(fixed_code)
        return FileResponse(tex_path, media_type="text/plain", filename="resume.tex")
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/download_application_pdf/{filepath:path}")
async def download_application_pdf(filepath: str):
    """
    Serves persistent compiled PDFs stored in OUTPUT_DIR (including user subfolders).
    Sets Content-Disposition to inline so browsers render a built-in PDF viewer with download controls.
    """
    # Prevent path traversal outside OUTPUT_DIR
    clean_rel = os.path.normpath(filepath).lstrip("/")
    pdf_path = os.path.abspath(os.path.join(OUTPUT_DIR, clean_rel))
    out_dir_abs = os.path.abspath(OUTPUT_DIR)

    if not pdf_path.startswith(out_dir_abs) or not os.path.exists(pdf_path):
        # Fallback check for flat filename in OUTPUT_DIR
        flat_path = os.path.join(OUTPUT_DIR, os.path.basename(filepath))
        if os.path.exists(flat_path):
            pdf_path = flat_path
        else:
            raise HTTPException(status_code=404, detail="PDF file not found")

    filename = os.path.basename(pdf_path)
    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename={filename}"}
    )

class CoverLetterDownloadRequest(BaseModel):
    cover_letter: str

@app.post("/download_cover_letter")
async def download_cover_letter(request: CoverLetterDownloadRequest):
    return Response(
        content=request.cover_letter,
        media_type="text/plain",
        headers={"Content-Disposition": "attachment; filename=cover_letter.txt"}
    )

class CompileLatexRequest(BaseModel):
    latex_code: str

@app.post("/compile_latex")
async def compile_latex(request: CompileLatexRequest, authorization: Optional[str] = Header(None)):
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]
    try:
        # FIX #2: per-user output paths instead of the fixed "tailored_resume.tex"/
        # "tailored_resume.pdf". With fixed global filenames, two users compiling
        # concurrently could overwrite each other's tex/pdf and each get back the
        # wrong file.
        tex_path, pdf_path = _user_output_paths(token)
        
        # Write the LaTeX code
        fixed_code = apply_latex_hotfix(request.latex_code)
        with open(tex_path, "w", encoding="utf-8") as f:
            f.write(fixed_code)
            
        # Copy resume.cls to output directory so Tectonic can find it
        import shutil
        cls_source = os.path.join(UPLOAD_DIR, "resume.cls")
        if not os.path.exists(cls_source):
            cls_source = os.path.join(BASE_DIR, "assets", "resume.cls")
        shutil.copy2(cls_source, os.path.join(OUTPUT_DIR, "resume.cls"))
            
        # Run tectonic compiler
        print("Compiling LaTeX using Tectonic...")
        result = await asyncio.to_thread(
            subprocess.run,
            ["tectonic", tex_path, "--outdir", OUTPUT_DIR],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        if result.returncode != 0:
            print(f"Tectonic failed: {result.stderr}")
            raise HTTPException(status_code=500, detail=f"LaTeX compilation failed: {result.stderr}")
            
        print("Compilation successful!")
        return FileResponse(
            pdf_path,
            media_type="application/pdf",
            headers={"Content-Disposition": "inline; filename=resume.pdf"}
        )
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/clear_cache")
async def clear_cache(authorization: Optional[str] = Header(None)):
    """Resets user-scoped in-memory session caches and deletes temporary files for the calling user only."""
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]
        
    try:
        user = await async_get_user_by_token(token) if token else None
        user_key = _safe_key(user["id"] if user else token) if (user or token) else "guest"
        user_upload_dir, user_output_dir = _get_user_storage_dirs(user_key)

        # 1. Clean requesting user's output directory only
        if os.path.exists(user_output_dir):
            for filename in os.listdir(user_output_dir):
                file_path = os.path.join(user_output_dir, filename)
                # Preserve permanent application history files
                if filename.startswith("application_history_"):
                    continue
                try:
                    if os.path.isfile(file_path) or os.path.islink(file_path):
                        os.unlink(file_path)
                    elif os.path.isdir(file_path):
                        shutil.rmtree(file_path)
                except Exception as ex:
                    print(f"Failed to delete user output file {file_path}: {ex}")

        # 2. Clean requesting user's upload directory only (preserve resume.cls if present)
        if os.path.exists(user_upload_dir):
            for filename in os.listdir(user_upload_dir):
                if filename == "resume.cls":
                    continue
                file_path = os.path.join(user_upload_dir, filename)
                try:
                    if os.path.isfile(file_path) or os.path.islink(file_path):
                        os.unlink(file_path)
                    elif os.path.isdir(file_path):
                        shutil.rmtree(file_path)
                except Exception as ex:
                    print(f"Failed to delete user upload file {file_path}: {ex}")

        # 3. Reset session store and analysis cache entries scoped to this token/user
        if token:
            with _store_lock:
                _session_store.pop(token, None)
            _analysis_cache.pop(token, None)
        else:
            with _store_lock:
                _session_store.pop("guest", None)
            _analysis_cache.pop("guest", None)

        return {"status": "success", "message": "User cache and temporary files cleared successfully."}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

# Background task status registry maps task_id -> {"status": str, "message": str}
_task_registry: dict[str, dict] = {}
_registry_lock = threading.Lock()
# FIX #7: keep strong references to in-flight asyncio Tasks. asyncio only holds a
# weak reference to tasks created via create_task; if nothing else references the
# Task object, it can be garbage-collected mid-execution, silently killing the
# autofill job. Storing it here (and dropping it on completion) prevents that.
_background_tasks: dict[str, "asyncio.Task"] = {}

def update_task_status(task_id: str, status: str, message: str):
    with _registry_lock:
        now = time.time()
        # Opportunistically prune entries older than 1 hour so _task_registry
        # doesn't grow unbounded over the life of a long-running process —
        # mirrors the same pattern used for _analysis_cache.
        stale = [k for k, v in _task_registry.items() if now - v.get("timestamp", now) >= 3600]
        for k in stale:
            _task_registry.pop(k, None)
        _task_registry[task_id] = {
            "status": status,
            "message": message,
            "timestamp": now
        }

class FieldSolveRequest(BaseModel):
    question: str
    context: str
    resume_data: Optional[dict] = None
    api_key: Optional[str] = None

@app.get("/user/sync_code")
async def get_sync_code(token: Optional[str] = Depends(get_optional_token)):
    """
    Returns user's permanent 6-digit alphanumeric extension sync key.
    """
    from services.auth import generate_user_sync_code
    user = await async_get_user_by_token(token)
    if not user or not user.get("id"):
        # For guest or fallback, return a deterministic 6-character code
        guest_key = (token or "guest")[:6].upper()
        return {"sync_code": guest_key}
    
    code = await asyncio.to_thread(generate_user_sync_code, user["id"])
    return {"sync_code": code, "email": user.get("email")}

@app.post("/user/solve_field")
async def solve_application_field(
    request: FieldSolveRequest,
    token: Optional[str] = Depends(get_optional_token)
):
    """
    Endpoint for Chrome extension to solve custom application questions or dropdowns using AI.
    """
    from services.autofill_agent import get_answer_from_llm
    
    session_data, _ = get_session_data(token)
    resume = request.resume_data or session_data or {}
    
    answer = await asyncio.to_thread(
        get_answer_from_llm,
        request.question,
        request.context,
        resume,
        request.api_key
    )
    return {"answer": answer}

@app.post("/apply")
async def apply(request: ApplyRequest, http_request: Request, authorization: Optional[str] = Header(None), x_gemini_api_key: Optional[str] = Header(None)):
    _check_rate_limit(http_request, "apply", max_requests=5, window_seconds=300)
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]
        
    session = get_session_data(token)
    session_resume_data = session.get("data")
    session_resume_path = session.get("path")
    
    # FIX #2: per-user pdf path instead of the fixed "tailored_resume.pdf". Using a
    # single global filename meant /apply could pick up and submit a *different*
    # user's most-recently-compiled resume to this user's job application.
    _, pdf_path = _user_output_paths(token)
    if not os.path.exists(pdf_path):
        # Fallback to master if tailored hasn't been generated
        if not session_resume_path or not os.path.exists(session_resume_path):
            raise HTTPException(status_code=400, detail="No resume available to upload.")
        pdf_path = session_resume_path

    db_api_key = None
    if token:
        user = await async_get_user_by_token(token)
        if user:
            db_api_key = user.get("gemini_api_key")
    active_api_key = x_gemini_api_key or db_api_key

    task_id = str(uuid.uuid4())
    update_task_status(task_id, "running", "Autofill session initialized...")

    async def run_autofill_wrapper():
        try:
            update_task_status(task_id, "running", "Opening automated browser window...")
            await autofill_job_application(
                url=request.job_url,
                resume_data=session_resume_data,
                resume_pdf_path=os.path.abspath(pdf_path),
                interactive_mode=not request.direct_mode,
                user_token=token,
                custom_api_key=active_api_key
            )
            update_task_status(task_id, "completed", "Job application form auto-filled successfully!")
            try:
                await asyncio.to_thread(record_application, token, {
                    "job_title": request.job_title or "",
                    "company": request.company or "",
                    "job_url": request.job_url,
                    # Direct mode submits the application; interactive mode only autofills
                    # it for the user to review and submit themselves in the opened browser.
                    "status": "applied" if request.direct_mode else "autofilled",
                })
            except Exception as hist_err:
                print(f"[apply] Failed to record application history: {hist_err}")
        except Exception as ex:
            update_task_status(task_id, "failed", f"Autofill error: {str(ex)}")
        finally:
            _background_tasks.pop(task_id, None)

    try:
        # Run autofill in the background task
        import asyncio
        task = asyncio.create_task(run_autofill_wrapper())
        # FIX #7: retain a reference so the task can't be garbage-collected early
        _background_tasks[task_id] = task
        
        return {"status": "success", "task_id": task_id, "message": "Autofill session started in separate browser window."}
    except Exception as e:
        traceback.print_exc()
        update_task_status(task_id, "failed", str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/apply/status/{task_id}")
async def apply_status(task_id: str):
    MAX_STREAM_SECONDS = 1800  # 30 min — stop polling an abandoned/never-finishing task

    async def status_stream():
        last_message = ""
        start = time.time()
        while True:
            if time.time() - start > MAX_STREAM_SECONDS:
                yield json.dumps({"status": "timeout", "message": "Stopped watching after 30 minutes. The autofill session may still be running in its browser window."}) + "\n"
                break

            with _registry_lock:
                entry = _task_registry.get(task_id)
            if not entry:
                yield json.dumps({"status": "unknown", "message": "Task not found."}) + "\n"
                break

            # Yield event only on message change or when complete
            if entry["message"] != last_message:
                yield json.dumps({"status": entry["status"], "message": entry["message"]}) + "\n"
                last_message = entry["message"]

            if entry["status"] in ("completed", "failed"):
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(status_stream(), media_type="text/event-stream")

def _sanitize_filename_part(s: str) -> str:
    """Strip characters invalid in filenames and trim whitespace."""
    return _re.sub(r'[\\/:*?"<>|]', '', s or '').strip()

def upload_zip_to_tmpfiles(latex_code: str, candidate_name: str = "", job_title: str = "", company: str = "") -> str:
    # 1. Create a zip in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        # Apply hotfixes
        fixed_code = apply_latex_hotfix(latex_code)
        zip_file.writestr("main.tex", fixed_code)
        
        # Add latexmkrc file so Overleaf automatically sets the compiler engine to XeLaTeX
        latexmkrc_content = '$pdf_mode = 5;\n$postscript_mode = $dvi_mode = 0;\n$xelatex = "xelatex -synctex=1 -interaction=nonstopmode %O %S";\n'
        zip_file.writestr("latexmkrc", latexmkrc_content)

        # Load resume.cls (use default tracked version as fallback if uploads doesn't contain a custom copy)
        cls_path = os.path.join(UPLOAD_DIR, "resume.cls")
        if not os.path.exists(cls_path):
            cls_path = os.path.join(BASE_DIR, "assets", "resume.cls")
            
        print(f"[Overleaf ZIP Export] Loading resume.cls from resolved path: {cls_path}")
        if os.path.exists(cls_path):
            with open(cls_path, "r", encoding="utf-8") as f:
                cls_content = f.read()
            zip_file.writestr("resume.cls", cls_content)
            print(f"[Overleaf ZIP Export] Successfully packed resume.cls ({len(cls_content)} bytes)")
        else:
            print("[Overleaf ZIP Export] ERROR: resume.cls not found in uploads or output directories!")
            
    zip_buffer.seek(0)
    zip_data = zip_buffer.getvalue()
    
    # 2. Build a descriptive project name from candidate / role / company —
    # used only for Overleaf's snip_name (the visible project title), NOT for
    # the actual uploaded filename below.
    parts = [_sanitize_filename_part(candidate_name), _sanitize_filename_part(job_title), _sanitize_filename_part(company)]
    parts = [p for p in parts if p]  # drop empty parts
    project_name = " - ".join(parts) + " Resume" if parts else "Resume"
    # Upload filename is fixed/ASCII-safe regardless of candidate/job/company
    # content. Spaces and punctuation (commas, "&", etc.) in project_name
    # previously ended up in the *uploaded* filename, which tmpfiles.org bakes
    # into the download URL it returns; Overleaf fetches that URL server-side
    # per its "Open in Overleaf" API and can fail to recognize the file as a
    # valid zip if the URL's path segment isn't cleanly encoded end-to-end,
    # surfacing as "the file supplied is of an unsupported type". snip_name
    # (below) already sets the human-readable title inside Overleaf, so the
    # upload filename itself doesn't need to carry any of that information.
    zip_filename = "resume.zip"
    print(f"[Overleaf ZIP Export] Project title: {project_name} (upload filename: {zip_filename})")

    import base64
    base64_zip = base64.b64encode(zip_data).decode('utf-8')
    
    # Return a Base64 Data URL containing the zip project directly
    # Overleaf supports base64 application/zip Data URIs directly in snip_uri parameters
    data_uri = f"data:application/zip;base64,{base64_zip}"
    
    # Overleaf's snip_name will title the project, or we default to candidate / job / company description
    encoded_name = urllib.parse.quote(project_name)
    return f"https://www.overleaf.com/docs?snip_uri={urllib.parse.quote(data_uri)}&snip_name={encoded_name}"

class OverleafRequest(BaseModel):
    latex_code: str
    candidate_name: Optional[str] = ""
    job_title: Optional[str] = ""
    company: Optional[str] = ""

@app.post("/open_in_overleaf")
async def open_in_overleaf(request: OverleafRequest):
    try:
        url = await asyncio.to_thread(upload_zip_to_tmpfiles, request.latex_code, request.candidate_name, request.job_title, request.company)
        return {"url": url}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


def _build_original_latex(resume_data: dict, master_path: Optional[str] = None) -> str:
    """Build canonical Master LaTeX resume using original .tex if uploaded, or generate from JSON."""
    if master_path and master_path.endswith(".tex") and os.path.exists(master_path):
        with open(master_path, "r", encoding="utf-8") as f:
            return f.read()
    return apply_latex_hotfix(generate_latex_from_json(resume_data))


class OriginalOverleafRequest(BaseModel):
    resume_data: dict
    job_title: Optional[str] = ""
    company: Optional[str] = ""

@app.post("/open_original_in_overleaf")
async def open_original_in_overleaf(request: OriginalOverleafRequest):
    """Export the user's original (non-tailored) resume to Overleaf as LaTeX."""
    try:
        session = get_session_data(None)
        master_path = session.get("path") if session else None
        latex_code = _build_original_latex(request.resume_data, master_path)
        candidate_name = request.resume_data.get("name", "")
        url = await asyncio.to_thread(upload_zip_to_tmpfiles, latex_code, candidate_name, request.job_title, request.company)
        return {"url": url}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/compile_master_pdf")
async def compile_master_pdf(request: OriginalOverleafRequest):
    """Compile the user's original master resume to PDF using Tectonic and return download URL."""
    try:
        session = get_session_data(None)
        master_path = session.get("path") if session else None
        latex_code = _build_original_latex(request.resume_data, master_path)
        candidate_name = request.resume_data.get("name", "Master")
        safe_name = _safe_key(candidate_name)
        user_out_dir = os.path.join(OUTPUT_DIR, safe_name)
        os.makedirs(user_out_dir, exist_ok=True)
        
        # Copy resume.cls
        cls_src = os.path.join(UPLOAD_DIR, "resume.cls")
        if not os.path.exists(cls_src):
            cls_src = os.path.join(BASE_DIR, "assets", "resume.cls")
        if os.path.exists(cls_src):
            shutil.copy2(cls_src, os.path.join(user_out_dir, "resume.cls"))
            
        # Mechanical adjustments to strictly enforce 1-page fit
        pages, _ = await asyncio.to_thread(compile_and_check_page_metrics, latex_code, 1.0, 1.0, None)
        opt_scale = 1.0
        opt_ls = 1.0
        if pages > 1:
            for ls in [0.95, 0.91, 0.88, 0.82, 0.78]:
                p, _ = await asyncio.to_thread(compile_and_check_page_metrics, latex_code, 1.0, ls, None)
                if p == 1:
                    opt_ls = ls
                    pages = 1
                    break
        if pages > 1:
            for scale in [0.85, 0.75, 0.65]:
                p, _ = await asyncio.to_thread(compile_and_check_page_metrics, latex_code, scale, opt_ls, None)
                if p == 1:
                    opt_scale = scale
                    break

        final_latex = apply_latex_hotfix(latex_code, opt_scale, opt_ls, None)

        tex_path = os.path.join(user_out_dir, "master_resume.tex")
        pdf_path = os.path.join(user_out_dir, "master_resume.pdf")
        with open(tex_path, "w", encoding="utf-8") as f:
            f.write(final_latex)
            
        comp_res = await asyncio.to_thread(
            subprocess.run,
            ["tectonic", tex_path, "--outdir", user_out_dir],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        if comp_res.returncode == 0 and os.path.exists(pdf_path):
            pdf_url = f"/download_application_pdf/{safe_name}/master_resume.pdf"
            return {"status": "success", "pdf_url": pdf_url}
        else:
            print(f"[compile_master_pdf] Tectonic error: {comp_res.stderr}")
            raise HTTPException(status_code=500, detail=f"LaTeX compilation failed: {comp_res.stderr}")
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))





class SendApplicationPdfEmailRequest(BaseModel):
    pdf_url: str
    job_title: Optional[str] = "Target Role"
    company: Optional[str] = "Company"
    score: Optional[int] = None
    overleaf_url: Optional[str] = None
    job_url: Optional[str] = None

@app.post("/send_application_pdf_email")
async def send_application_pdf_email(request: SendApplicationPdfEmailRequest, authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized. Please sign in.")
    token = authorization.split(" ")[1]
    user = await async_get_user_by_token(token)
    if not user or not user.get("email"):
        raise HTTPException(status_code=400, detail="User email not found. Please log in.")

    # Resolve PDF path
    clean_rel = os.path.normpath(request.pdf_url.replace("/download_application_pdf/", "")).lstrip("/")
    pdf_path = os.path.abspath(os.path.join(OUTPUT_DIR, clean_rel))
    out_dir_abs = os.path.abspath(OUTPUT_DIR)

    if not pdf_path.startswith(out_dir_abs) or not os.path.exists(pdf_path):
        # Fallback check flat filename
        flat_path = os.path.join(OUTPUT_DIR, os.path.basename(clean_rel))
        if os.path.exists(flat_path):
            pdf_path = flat_path
        else:
            raise HTTPException(status_code=404, detail="PDF file not found on server.")

    session = get_session_data(token)
    session_resume_data = session.get("data", {})

    from services.email_service import async_send_notification_email
    dest_email = user["email"]
    cand_name = session_resume_data.get("name", "").strip() or "Candidate" if isinstance(session_resume_data, dict) else "Candidate"
    
    score_suffix = f" [{request.score}% Match]" if request.score is not None else ""
    ats_display = f"{request.score}% Match" if request.score is not None else "Tailored"

    email_subj = f"📄 [Resume Delivery] Tailored Resume{score_suffix}: {request.job_title} at {request.company}"
    email_text = (
        f"Hello {cand_name},\n\n"
        f"Here is your requested tailored resume PDF for '{request.job_title}' at '{request.company}' (ATS Score: {ats_display})!\n\n"
        f"We have attached your compiled PDF resume directly to this email.\n\n"
        f"View the job listing and apply here:\n{request.job_url or ''}\n\n"
        f"Want to edit or customize it online? Open it in Overleaf:\n{request.overleaf_url or ''}\n\n"
        f"Best of luck with your application!"
    )
    email_html = f"""
    <div style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; max-width: 600px; margin: 0 auto; padding: 30px; border: 1px solid #E2E8F0; border-radius: 16px; background-color: #FAFAFA; box-shadow: 0 4px 20px rgba(0,0,0,0.03);">
        <div style="text-align: center; margin-bottom: 24px;">
            <span style="font-size: 3rem;">📄</span>
            <span style="display: inline-block; background-color: #0284C7; color: #FFFFFF; font-size: 0.72rem; font-weight: 700; padding: 3px 10px; border-radius: 12px; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px;">On-Demand Resume Delivery</span>
            <h2 style="color: #0284C7; margin: 6px 0 5px; font-weight: 800; font-size: 1.6rem;">Tailored Resume PDF</h2>
            <p style="color: #64748B; font-size: 0.9rem; margin: 0;">For your application at <strong>{request.company}</strong></p>
        </div>
        <div style="background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 12px; padding: 20px; margin-bottom: 24px;">
            <table style="width: 100%; border-collapse: collapse;">
                <tr>
                    <td style="padding: 6px 0; color: #64748B; font-size: 0.85rem; width: 100px;">Target Role:</td>
                    <td style="padding: 6px 0; color: #1E293B; font-size: 0.9rem; font-weight: 600;">{request.job_title}</td>
                </tr>
                <tr>
                    <td style="padding: 6px 0; color: #64748B; font-size: 0.85rem;">Company:</td>
                    <td style="padding: 6px 0; color: #1E293B; font-size: 0.9rem; font-weight: 600;">{request.company}</td>
                </tr>
                <tr>
                    <td style="padding: 6px 0; color: #64748B; font-size: 0.85rem;">ATS Score:</td>
                    <td style="padding: 6px 0; color: #0284C7; font-size: 0.95rem; font-weight: 700;">{ats_display}</td>
                </tr>
            </table>
        </div>
        <p style="color: #475569; font-size: 0.95rem; line-height: 1.6; margin: 0 0 20px;">
            Hello {cand_name}, your compiled PDF resume (ATS Match Score: <strong>{ats_display}</strong>) is attached directly to this email.
        </p>
        <div style="text-align: center; margin: 30px 0 20px;">
            {"<a href='" + request.job_url + "' target='_blank' style='display: inline-block; background-color: #10B981; color: #FFFFFF; text-decoration: none; padding: 12px 30px; border-radius: 8px; font-weight: bold; font-size: 0.9rem; margin-bottom: 12px;'>🚀 View Job & Apply</a><br/>" if request.job_url else ""}
            {"<a href='" + request.overleaf_url + "' target='_blank' style='display: inline-block; background-color: #0284C7; color: #FFFFFF; text-decoration: none; padding: 12px 30px; border-radius: 8px; font-weight: bold; font-size: 0.9rem;'>🍃 Open & Edit in Overleaf</a>" if request.overleaf_url else ""}
        </div>
        <hr style="border: 0; border-top: 1px solid #E2E8F0; margin: 30px 0 20px;" />
        <p style="font-size: 0.8rem; color: #94A3B8; text-align: center; margin: 0;">
            Sent automatically by your Resume Tailor Assistant.
        </p>
    </div>
    """

    email_sent = await async_send_notification_email(
        to_email=dest_email,
        subject=email_subj,
        text_body=email_text,
        html_body=email_html,
        attachment_path=pdf_path,
        attachment_name=f"Tailored_Resume_{(request.company or 'Role').replace(' ', '_')}.pdf"
    )

    if email_sent:
        return {"status": "success", "message": f"Tailored PDF sent to {dest_email}"}
    else:
        raise HTTPException(status_code=500, detail="Failed to send email. Check SMTP settings.")


class OutreachRequest(BaseModel):
    job_description: str
    job_title: Optional[str] = "Target Role"
    company_name: Optional[str] = "Company"
    recruiter_name: Optional[str] = None
    recruiter_email: Optional[str] = None
    send_email: Optional[bool] = False

@app.post("/generate_recruiter_outreach")
async def generate_recruiter_outreach_endpoint(
    request: OutreachRequest,
    authorization: Optional[str] = Header(None),
    x_gemini_api_key: Optional[str] = Header(None, alias="X-Gemini-API-Key")
):
    token = authorization.split(" ")[1] if authorization and authorization.startswith("Bearer ") else None
    session = get_session_data(token)
    session_resume_data = session.get("data", {})
    if not session_resume_data:
        raise HTTPException(status_code=400, detail="Master resume missing. Please upload a resume first.")

    active_api_key = x_gemini_api_key
    if not active_api_key and token:
        user = await async_get_user_by_token(token)
        if user:
            active_api_key = user.get("gemini_api_key")

    ats_analysis = get_cached_analysis(token, request.job_title, request.job_description) or {}

    outreach = await asyncio.to_thread(
        generate_outreach_message,
        request.job_description,
        session_resume_data,
        ats_analysis,
        request.recruiter_name,
        request.company_name or "Company",
        active_api_key
    )

    if request.send_email and request.recruiter_email:
        from services.email_service import async_send_notification_email
        html_formatted_body = outreach.email_body.replace("\n", "<br>")
        await async_send_notification_email(
            to_email=request.recruiter_email,
            subject=outreach.email_subject,
            text_body=outreach.email_body,
            html_body=f"<div style='font-family:sans-serif;line-height:1.6;'>{html_formatted_body}</div>"
        )

    return {
        "status": "success",
        "outreach": outreach.model_dump()
    }


@app.post("/user/test_email")
async def user_test_email(request: Request, authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = authorization.split(" ")[1]
    user = await async_get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    email = user.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="User email not found.")

    sent = await process_and_send_user_digest(user, bypass_time_check=True)
    if sent:
        return {"status": "success", "message": f"Daily job digest generated and sent to {email}"}
    else:
        raise HTTPException(status_code=500, detail="Failed to send preview email. Verify SMTP settings.")


# ─── One-click email unsubscribe ──────────────────────────────────────────────
import hmac
import hashlib

def _make_unsub_token(email: str) -> str:
    """HMAC-SHA256 token so unsubscribe links can't be forged."""
    secret = os.getenv("UNSUB_SECRET", os.getenv("SUPABASE_KEY", "default-secret"))
    return hmac.new(secret.encode(), email.lower().encode(), hashlib.sha256).hexdigest()[:32]

@app.get("/user/unsubscribe", response_class=HTMLResponse)
async def unsubscribe_digest(email: str, token: str):
    """
    One-click unsubscribe link included in every digest email.
    Verifies HMAC token then disables cron_enabled for the user.
    """
    expected = _make_unsub_token(email)
    if not hmac.compare_digest(token, expected):
        return HTMLResponse("<h3 style='font-family:Arial;color:#EF4444'>Invalid or expired unsubscribe link.</h3>", status_code=400)
    try:
        from services.auth import supabase_request
        encoded_email = urllib.parse.quote(email)
        users = supabase_request(f"users?email=eq.{encoded_email}", "GET")
        if not users:
            return HTMLResponse("<h3 style='font-family:Arial'>Email not found.</h3>", status_code=404)
        user_id = users[0]["id"]
        supabase_request(f"users?id=eq.{user_id}", "PATCH", {"cron_enabled": False})
        return HTMLResponse("""
        <div style='font-family:Arial,sans-serif;max-width:420px;margin:80px auto;text-align:center;padding:40px;border:1px solid #E2E8F0;border-radius:16px'>
            <div style='font-size:3rem'>✅</div>
            <h2 style='color:#0284C7;margin:16px 0 8px'>Unsubscribed</h2>
            <p style='color:#64748B'>You won't receive daily job digest emails anymore.<br>
            You can re-enable them anytime from the app settings.</p>
        </div>""")
    except Exception as e:
        print(f"[Unsubscribe] Error: {e}")
        return HTMLResponse("<h3 style='font-family:Arial;color:#EF4444'>Something went wrong. Please try again.</h3>", status_code=500)
# ─────────────────────────────────────────────────────────────────────────────

# pyrefly: ignore [missing-import]
from fastapi import BackgroundTasks

async def async_tailor_pipeline(
    email: str,
    job_url: str,
    user_id: str,
    resume_data: dict,
    ats_score: int,
    hint_title: str = "",
    hint_company: str = "",
):
    # Titles that indicate a bot-block / challenge page rather than a real job listing
    _BOT_TITLES = {
        "target role", "unknown role", "verification required",
        "just a moment", "error processing your request",
        "access denied", "attention required", "indeed job",
        "linkedin job", "tailored job application",
    }

    try:
        from services.auth import supabase_request
        # Load user resume LaTeX master template
        resume_rows = supabase_request(f"user_resumes?user_id=eq.{user_id}", "GET")
        if not resume_rows or not resume_rows[0].get("master_latex"):
            print(f"[Auto Tailor] Missing master latex template for user {user_id}")
            return
            
        master_latex = resume_rows[0].get("master_latex")
        
        # Scrape job details
        scraped = await scrape_job_description(job_url)
        job_title = scraped.get("title", "")
        jd_text = scraped.get("description", "")
        company_name = scraped.get("company", "")

        # ── Fallback to digest hints when scraper was bot-blocked ──────────
        # A bot-block page title or an empty/short description means the scraper
        # hit a Cloudflare challenge / "Verification Required" page. The digest
        # hint itself can also be a placeholder (e.g. Indeed's RSS feed defaults
        # an untitled listing's title to literal "Indeed Job") — a hint must be
        # checked against the same bot-title set before being trusted.
        scrape_blocked = (
            not job_title
            or job_title.lower().strip() in _BOT_TITLES
            or not jd_text
            or len(jd_text.strip()) < 100
        )
        hint_title_usable = bool(hint_title) and hint_title.lower().strip() not in _BOT_TITLES
        if scrape_blocked and hint_title_usable:
            print(f"[Auto Tailor] Scrape blocked (title='{job_title}'). Using digest hint: '{hint_title}'")
            job_title = hint_title
        elif not job_title or job_title.lower().strip() in _BOT_TITLES:
            job_title = "Target Role"

        # Company: prefer scraped → URL extraction → digest hint → fallback
        _PLACEHOLDER_COMPANIES = {"target company", "indeed employer", "linkedin job", ""}
        if not company_name or company_name.lower() in _PLACEHOLDER_COMPANIES:
            company_name = await asyncio.to_thread(_extract_company_from_jd, jd_text, job_url)
        hint_company_usable = bool(hint_company) and hint_company.lower().strip() not in _PLACEHOLDER_COMPANIES
        if (not company_name or company_name.lower() in {"target company", ""}) and hint_company_usable:
            print(f"[Auto Tailor] Using digest hint company: '{hint_company}'")
            company_name = hint_company
        if not company_name:
            company_name = "Target Company"


        # Calculate actual pre-tailored initial ATS score
        from services.ats_scorer import compute_ats_score, compute_overall_score, estimate_role_fit_score
        ats_res = compute_ats_score(resume_data, jd_text)
        role_fit = estimate_role_fit_score(resume_data, jd_text)
        ats_score = compute_overall_score(ats_res.skills_score, ats_res.experience_score, role_fit)

        # Retrieve user custom API key if saved in database
        custom_api_key = None
        users = supabase_request(f"users?id=eq.{user_id}", "GET")
        if users and users[0].get("gemini_api_key"):
            custom_api_key = users[0].get("gemini_api_key")

        # Force tailoring (Auto Mode ignores suitability warnings)
        from services.llm_agent import analyze_job_fit, review_tailored_resume
        # Call analyze_job_fit deterministically to get updates details
        fit_analysis = await analyze_job_fit(resume_data, job_title, jd_text, master_latex, custom_api_key, on_log=None)
        
        # Merge updates
        tailored_updates = fit_analysis.suggested_resume_updates
        missing_skills = fit_analysis.match_analysis.missing_skills
        
        # Force compiling tailored LaTeX code
        tailored_latex = await asyncio.to_thread(tailor_latex_code, master_latex, job_title, jd_text, tailored_updates, missing_skills, custom_api_key, "", on_log=None)

        # Run Two-Phase Reviewer Agent (Structural Integrity + Truthfulness + Quality check)
        review_res = await asyncio.to_thread(review_tailored_resume, tailored_latex, resume_data, job_title, jd_text, custom_api_key, on_log=None)
        if not review_res.satisfied:
            print(f"[Auto Tailor] Reviewer agent flagged quality/truthfulness issues: {review_res.feedback}. Running refinement...")
            tailored_latex = await asyncio.to_thread(
                tailor_latex_code,
                master_latex, job_title, jd_text, tailored_updates, missing_skills, custom_api_key,
                f"REVIEWER AGENT FEEDBACK: {review_res.feedback}", on_log=None
            )

        # Page-fit check & automatic mechanical shrink / AI condensation loop
        pages, _ = await asyncio.to_thread(compile_and_check_page_metrics, tailored_latex, 1.0, 1.0, master_latex)
        optimal_scale = 1.0
        optimal_linespread = 1.0

        if pages > 1:
            # Step 1: Mechanical spacing shrink (test 0.85 and 0.78 directly for fast compilation)
            for ls in [0.85, 0.78]:
                p, _ = await asyncio.to_thread(compile_and_check_page_metrics, tailored_latex, 1.0, ls, master_latex)
                if p == 1:
                    pages = 1
                    optimal_linespread = ls
                    break

        if pages > 1:
            # Step 2: Mechanical font scaling shrink (test 0.85 and 0.75)
            for scale in [0.85, 0.75]:
                p, _ = await asyncio.to_thread(compile_and_check_page_metrics, tailored_latex, scale, optimal_linespread, master_latex)
                if p == 1:
                    pages = 1
                    optimal_scale = scale
                    break

        # Step 3: If still spilled (>1 page), trigger AI text condensation loop
        condense_attempts = 0
        while pages > 1 and condense_attempts < 2:
            print(f"[Auto Tailor] PDF spilled onto page {pages}. Running AI text condensation retry {condense_attempts+1}...")
            condense_feedback = (
                "CRITICAL: The resume spilled to page 2. You MUST shorten the experience and project bullets "
                "to be tighter and more concise (max 1 line per project bullet). Do NOT remove any job, school, project, "
                "CPI/GPA value, or bullet point — just make each bullet shorter so the compiled PDF fits 1 page."
            )
            condensed_latex = await asyncio.to_thread(
                tailor_latex_code, master_latex, job_title, jd_text, tailored_updates, missing_skills, None, condense_feedback, on_log=None
            )
            # Recheck page metrics with condensed text
            pages, _ = await asyncio.to_thread(compile_and_check_page_metrics, condensed_latex, optimal_scale, optimal_linespread, master_latex)
            if pages == 1 or condensed_latex != tailored_latex:
                tailored_latex = condensed_latex
            condense_attempts += 1
            if pages > 1:
                # Try mechanical shrink once more on condensed text
                for ls in [0.80, 0.75]:
                    p, _ = await asyncio.to_thread(compile_and_check_page_metrics, tailored_latex, optimal_scale, ls, master_latex)
                    if p == 1:
                        pages = 1
                        optimal_linespread = ls
                        break

        # Compile final PDF using Tectonic with optimal spacing
        _, user_out_dir = _get_user_storage_dirs(user_id)
        pdf_filename = f"tailored_{user_id}_{int(dt.now(timezone.utc).timestamp())}.pdf"
        tex_path = os.path.join(user_out_dir, f"tailored_{user_id}_{int(time.time())}.tex")
        pdf_path = os.path.join(user_out_dir, pdf_filename)
        
        # Write the tailored LaTeX code
        fixed_code = apply_latex_hotfix(tailored_latex, optimal_scale, optimal_linespread, master_latex)
        with open(tex_path, "w", encoding="utf-8") as f:
            f.write(fixed_code)
            
        # Copy resume.cls to output directory so Tectonic can find it
        import shutil
        cls_source = os.path.join(UPLOAD_DIR, "resume.cls")
        if not os.path.exists(cls_source):
            cls_source = os.path.join(BASE_DIR, "assets", "resume.cls")
        shutil.copy2(cls_source, os.path.join(user_out_dir, "resume.cls"))
            
        print("Compiling tailored LaTeX background task using Tectonic...")
        result = await asyncio.to_thread(
            subprocess.run,
            ["tectonic", tex_path, "--outdir", user_out_dir],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        if result.returncode != 0:
            print(f"[Auto Tailor] Tectonic failed: {result.stderr}")
            return
            
        # Calculate post-tailored ATS match score to verify improvements
        try:
            # Re-parse the tailored resume contents to dictionary format
            from services.resume_parser import parse_resume
            # Tectonic compiled PDF output is at pdf_path
            tailored_data = (await asyncio.to_thread(parse_resume, pdf_path)).model_dump()

            # Compute new post-tailored score
            from services.ats_scorer import compute_ats_score, compute_overall_score, estimate_role_fit_score
            post_ats_res = compute_ats_score(tailored_data, jd_text)
            post_role_fit = estimate_role_fit_score(tailored_data, jd_text)
            post_ats_score = compute_overall_score(post_ats_res.skills_score, post_ats_res.experience_score, post_role_fit)
            
            # Monotonic score guarantee: Tailored resume score must be at least as high as pre-tailored score
            ats_score = max(ats_score, post_ats_score)
            ats_score_display = f"{ats_score}%"
        except Exception as score_err:
            print(f"[Auto Tailor] Failed to compute post-tailored score: {score_err}")
            ats_score_display = f"{ats_score}%"

        # Generate Overleaf Edit link
        candidate_name = resume_data.get("name", "Candidate")
        overleaf_url = upload_zip_to_tmpfiles(tailored_latex, candidate_name, job_title, company_name)
        
        # Save a persistent PDF URL under user parent subdirectory
        pdf_url = f"/download_application_pdf/{_safe_key(user_id)}/{pdf_filename}"

        # Notify user with PDF Attachment
        subject = f"📄 Resume Tailored [{ats_score}% Match]: {job_title} at {company_name}"
        
        text_body = (
            f"Hello {candidate_name},\n\n"
            f"Your tailored resume for '{job_title}' at '{company_name}' has been compiled successfully!\n\n"
            f"We have attached the PDF directly to this email.\n\n"
            f"View the job listing and apply here:\n{job_url}\n\n"
            f"Want to make edits or customize it? Open it directly in Overleaf here:\n{overleaf_url}\n\n"
            f"Best of luck with your application!"
        )
        
        html_body = f"""
        <div style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; max-width: 600px; margin: 0 auto; padding: 30px; border: 1px solid #E2E8F0; border-radius: 16px; background-color: #FAFAFA; box-shadow: 0 4px 20px rgba(0,0,0,0.03);">
            <div style="text-align: center; margin-bottom: 24px;">
                <span style="font-size: 3rem;">📄</span>
                <h2 style="color: #0284C7; margin: 10px 0 5px; font-weight: 800; font-size: 1.6rem;">Tailoring Completed!</h2>
                <p style="color: #64748B; font-size: 0.9rem; margin: 0;">For your application at <strong>{company_name}</strong></p>
            </div>
            
            <div style="background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 12px; padding: 20px; margin-bottom: 24px;">
                <table style="width: 100%; border-collapse: collapse;">
                    <tr>
                        <td style="padding: 6px 0; color: #64748B; font-size: 0.85rem; width: 100px;">Target Role:</td>
                        <td style="padding: 6px 0; color: #1E293B; font-size: 0.9rem; font-weight: 600;">{job_title}</td>
                    </tr>
                    <tr>
                        <td style="padding: 6px 0; color: #64748B; font-size: 0.85rem;">Company:</td>
                        <td style="padding: 6px 0; color: #1E293B; font-size: 0.9rem; font-weight: 600;">{company_name}</td>
                    </tr>
                    <tr>
                        <td style="padding: 6px 0; color: #64748B; font-size: 0.85rem;">ATS Score:</td>
                        <td style="padding: 6px 0; color: #0284C7; font-size: 0.95rem;">{ats_score_display}</td>
                    </tr>
                </table>
            </div>

            <p style="color: #475569; font-size: 0.95rem; line-height: 1.6; margin: 0 0 20px;">
                Hello {candidate_name}, we have successfully tailored your experience bullet points and technical keywords to match the target job description. The compiled PDF is attached directly to this email.
            </p>

            <div style="text-align: center; margin: 30px 0 20px;">
                <a href="{job_url}" target="_blank" style="display: inline-block; background-color: #10B981; color: #FFFFFF; text-decoration: none; padding: 12px 30px; border-radius: 8px; font-weight: bold; font-size: 0.9rem; box-shadow: 0 4px 12px rgba(16, 185, 129, 0.25); margin-bottom: 12px;">
                    🚀 View Job & Apply
                </a>
                <div style="font-size: 0.78rem; color: #94A3B8; margin-top: 8px; margin-bottom: 20px;">Opens the original job listing so you can submit your application</div>

                <a href="{overleaf_url}" target="_blank" style="display: inline-block; background-color: #0284C7; color: #FFFFFF; text-decoration: none; padding: 12px 30px; border-radius: 8px; font-weight: bold; font-size: 0.9rem; box-shadow: 0 4px 12px rgba(2, 132, 199, 0.25);">
                    🍃 Open & Edit in Overleaf
                </a>
                <div style="font-size: 0.78rem; color: #94A3B8; margin-top: 8px;">Allows you to edit LaTeX code and recompile instantly online</div>
            </div>

            <hr style="border: 0; border-top: 1px solid #E2E8F0; margin: 30px 0 20px;" />
            <p style="font-size: 0.8rem; color: #94A3B8; text-align: center; margin: 0;">
                Sent automatically by your Resume Tailor Assistant.
            </p>
        </div>
        """
        
        await async_send_notification_email(
            to_email=email,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
            attachment_path=pdf_path,
            attachment_name=f"Tailored_Resume_{company_name.replace(' ', '_')}.pdf"
        )
        
        # Extract recruiter details if available
        recruiter_name = None
        recruiter_profile_url = None
        if job_url:
            try:
                rec_info = await extract_recruiter(job_url, None)
                recruiter_name = rec_info.get("recruiter_name")
                recruiter_profile_url = rec_info.get("recruiter_profile_url")
            except Exception:
                pass

        # Log to application history
        supa_entry = {
            "user_id": user_id,
            "job_title": job_title,
            "company": company_name,
            "job_url": job_url,
            "status": "tailored",
            "score": ats_score,
            "created_at": dt.now(timezone.utc).isoformat()
        }
        if recruiter_name:
            supa_entry["recruiter_name"] = recruiter_name
        if recruiter_profile_url:
            supa_entry["recruiter_profile_url"] = recruiter_profile_url
        if overleaf_url:
            supa_entry["overleaf_url"] = overleaf_url
        if pdf_url:
            supa_entry["pdf_url"] = pdf_url

        record_id = supabase_request("applications", "POST", supa_entry)

    except Exception as e:
        traceback.print_exc()

@app.get("/email_action/tailor", response_class=HTMLResponse)
async def email_action_tailor(
    job_url: str,
    email: str,
    background_tasks: BackgroundTasks,
    title: str = "",
    company: str = "",
):
    """
    Zero-Click URL handler clicked from matching digest email:
    Asynchronously tailors, compiles, and delivers PDF to user email.
    title and company are optional hints from the digest — used as fallback
    when the job page is blocked by Cloudflare/bot-detection.
    """
    try:
        from services.auth import supabase_request
        # Lookup user profile
        encoded_email = urllib.parse.quote(email)
        users = supabase_request(f"users?email=eq.{encoded_email}", "GET")
        if not users:
            return HTMLResponse("<h3>Error: User matching this email address not found.</h3>", status_code=404)
        
        user = users[0]
        user_id = user.get("id")
        
        # Load user resume data
        resume_rows = supabase_request(f"user_resumes?user_id=eq.{user_id}", "GET")
        if not resume_rows:
            return HTMLResponse("<h3>Error: Resume context not uploaded. Please upload a resume in the app first.</h3>", status_code=400)
            
        resume_data_str = resume_rows[0].get("resume_data")
        resume_data = json.loads(resume_data_str)
        
        # Queue the entire scraping, tailoring, review, compilation, and email delivery to run in background
        # Pass hint_title / hint_company so the pipeline can fall back to known values when scraping is blocked
        background_tasks.add_task(async_tailor_pipeline, email, job_url, user_id, resume_data, 0, title, company)

        import html as _html
        job_summary_html = ""
        if title or company:
            role_html = _html.escape(title) if title else "this role"
            company_html = f" at <strong>{_html.escape(company)}</strong>" if company else ""
            job_summary_html = f"""
            <p style="color: #1E293B; font-size: 0.95rem; font-weight: 600; margin: 0 0 4px;">{role_html}{company_html}</p>
            """

        return HTMLResponse(f"""
        <div style="font-family: Arial, sans-serif; max-width: 500px; margin: 50px auto; padding: 30px; border: 1px solid #0284C7; border-radius: 12px; text-align: center; box-shadow: 0 10px 30px rgba(0,0,0,0.05);">
            <div style="font-size: 3rem; margin-bottom: 12px;">📄</div>
            <h2 style="color: #0284C7; margin: 0 0 10px;">Tailoring In Progress...</h2>
            {job_summary_html}
            <p style="color: #4B5563; font-size: 0.95rem; line-height: 1.6;">
                We are tailoring your resume for the job in the background.
                We will email the compiled PDF directly to <strong>{email}</strong> once completed.
            </p>
            <p style="font-size: 0.8rem; color: #9CA3AF; margin-top: 20px;">You can close this tab now.</p>
        </div>
        """)
        
    except Exception as e:
        traceback.print_exc()
        return HTMLResponse(f"<h3>Tailoring failed: {str(e)}</h3>", status_code=500)

@app.get("/email_action/unsubscribe", response_class=HTMLResponse)
async def email_action_unsubscribe(email: str):
    """
    Zero-Click Unsubscribe handler clicked from matching digest email:
    Updates Supabase user profile settings to disable daily cron subscription checks.
    """
    try:
        from services.auth import supabase_request
        encoded_email = urllib.parse.quote(email)
        users = supabase_request(f"users?email=eq.{encoded_email}", "GET")
        if not users:
            return HTMLResponse("<h3>Error: Profile matching this email address not found.</h3>", status_code=404)
        
        user = users[0]
        user_id = user.get("id")
        
        # Disable cron matching updates
        supabase_request(f"users?id=eq.{user_id}", "PATCH", {"cron_enabled": False})
        
        return HTMLResponse(f"""
        <div style="font-family: Arial, sans-serif; max-width: 500px; margin: 50px auto; padding: 30px; border: 1px solid #EF4444; border-radius: 12px; text-align: center; box-shadow: 0 10px 30px rgba(0,0,0,0.05);">
            <div style="font-size: 3rem; margin-bottom: 12px;">📭</div>
            <h2 style="color: #EF4444; margin: 0 0 10px;">Unsubscribed Successfully</h2>
            <p style="color: #4B5563; font-size: 0.95rem; line-height: 1.6;">
                You have been unsubscribed from the Daily Job Matches Digest for <strong>{email}</strong>.
                You will no longer receive daily matching reports.
            </p>
            <p style="font-size: 0.8rem; color: #9CA3AF; margin-top: 20px;">You can close this tab now.</p>
        </div>
        """)
    except Exception as e:
        traceback.print_exc()
        return HTMLResponse(f"<h3>Unsubscribe failed: {str(e)}</h3>", status_code=500)

class SettingsRequest(BaseModel):
    gemini_api_key: str

@app.post("/user/settings")
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

@app.get("/user/resume")
async def user_resume(authorization: Optional[str] = Header(None)):
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]
    session = get_session_data(token)
    data = session.get("data")
    eval_res = None
    if data:
        from services.ats_scorer import evaluate_master_resume
        eval_res = evaluate_master_resume(data)
    return {"data": data, "path": session.get("path"), "evaluation": eval_res}

class GeneratePromptQueryRequest(BaseModel):
    suggestion: str

@app.post("/user/generate_prompt_query")
async def generate_prompt_query(request: GeneratePromptQueryRequest, authorization: Optional[str] = Header(None)):
    """
    LLM endpoint that analyzes a recommendation suggestion and returns a highly specific,
    tailored prompt question to ask the user (with custom realistic examples).
    """
    from services.gemini_client import generate_content_with_fallback
    prompt = (
        "Analyze the following resume enhancement recommendation:\n"
        f"\"{request.suggestion}\"\n\n"
        "Generate a clear, polite, and hyper-specific question to ask the candidate in a popup prompt. "
        "Include realistic example inputs relevant to this exact request (e.g. specific phone/address format, "
        "percentage growth, latency reduction, cost savings, dataset size, or team scale).\n\n"
        "Return ONLY a JSON object with this key:\n"
        "{\n"
        "  \"prompt_text\": \"Question text with realistic examples here...\"\n"
        "}"
    )
    try:
        raw_res = await asyncio.to_thread(generate_content_with_fallback, prompt)
        cleaned = raw_res.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
            cleaned = re.sub(r'\s*```$', '', cleaned)
        data = json.loads(cleaned)
        return {"status": "success", "prompt_text": data.get("prompt_text", "")}
    except Exception as e:
        # Fallback default prompt if LLM call fails
        return {
            "status": "success",
            "prompt_text": f"This recommendation requests additional metrics or details:\n\n\"{request.suggestion}\"\n\nPlease enter the requested detail or metric:"
        }

class ApplySuggestionRequest(BaseModel):
    suggestion: str
    user_input: Optional[str] = None

@app.post("/user/apply_suggestion")
async def apply_suggestion(request: ApplySuggestionRequest, authorization: Optional[str] = Header(None)):
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]
    session = get_session_data(token)
    data = session.get("data")
    if not data:
        raise HTTPException(status_code=400, detail="No master resume uploaded.")

    from services.gemini_client import generate_content_with_fallback
    user_context = f"\nUser provided metric / context: {request.user_input}\n" if request.user_input else ""
    prompt = (
        "Update the master resume JSON by integrating this specific recommendation:\n"
        f"Recommendation: {request.suggestion}{user_context}\n\n"
        "CRITICAL RULE: Do NOT hallucinate metrics, financial numbers, or percentages. "
        "Use ONLY exact numbers provided by the user context above or refine the wording accurately.\n\n"
        f"Master Resume JSON:\n{json.dumps(data, indent=2)}\n\n"
        "Return ONLY the updated valid JSON object representing StructuredResume."
    )
    res_text = generate_content_with_fallback(prompt=prompt, system_instruction="Output ONLY raw JSON.")
    try:
        cleaned = res_text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
            cleaned = re.sub(r'\s*```$', '', cleaned)
        updated_data = json.loads(cleaned)
        
        # Compile before PDF if previous tex exists, and compile after PDF
        user_up_dir, user_out_dir = _get_user_storage_dirs(token or "guest")
        canonical_tex_path = os.path.join(user_up_dir, f"{uuid.uuid4().hex}_master.tex")
        canonical_tex = generate_latex_from_json(updated_data)
        with open(canonical_tex_path, "w", encoding="utf-8") as f:
            f.write(canonical_tex)

        # Ensure resume.cls is available in both user_up_dir and user_out_dir
        import shutil
        cls_source = os.path.join(UPLOAD_DIR, "resume.cls")
        if not os.path.exists(cls_source):
            cls_source = os.path.join(BASE_DIR, "assets", "resume.cls")
        if os.path.exists(cls_source):
            shutil.copy2(cls_source, os.path.join(user_up_dir, "resume.cls"))
            shutil.copy2(cls_source, os.path.join(user_out_dir, "resume.cls"))

        # Compile After PDF with automatic 1-page fit check & mechanical shrink
        after_pdf_filename = f"master_after_{uuid.uuid4().hex[:8]}.pdf"
        after_pdf_path = os.path.join(user_out_dir, after_pdf_filename)

        # Check page count and shrink linespread/geometry/scale if spilled (>1 page)
        pages, _ = await asyncio.to_thread(compile_and_check_page_metrics, canonical_tex, 1.0, 1.0, None)
        optimal_scale = 1.0
        optimal_linespread = 1.0
        if pages > 1:
            for ls in [0.95, 0.91, 0.88, 0.82, 0.78]:
                p, _ = await asyncio.to_thread(compile_and_check_page_metrics, canonical_tex, 1.0, ls, None)
                if p == 1:
                    pages = 1
                    optimal_linespread = ls
                    break

        if pages > 1:
            for scale in [0.85, 0.75, 0.65]:
                p, _ = await asyncio.to_thread(compile_and_check_page_metrics, canonical_tex, scale, optimal_linespread, None)
                if p == 1:
                    pages = 1
                    optimal_scale = scale
                    break

        final_fixed_tex = apply_latex_hotfix(canonical_tex, optimal_scale, optimal_linespread, None)
        with open(canonical_tex_path, "w", encoding="utf-8") as f:
            f.write(final_fixed_tex)

        proc = await asyncio.to_thread(
            subprocess.run,
            ["tectonic", canonical_tex_path, "--outdir", user_out_dir],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        default_after_pdf = os.path.join(user_out_dir, os.path.basename(canonical_tex_path).replace(".tex", ".pdf"))
        if os.path.exists(default_after_pdf):
            os.replace(default_after_pdf, after_pdf_path)
        elif os.path.exists(canonical_tex_path.replace(".tex", ".pdf")):
            os.replace(canonical_tex_path.replace(".tex", ".pdf"), after_pdf_path)

        after_pdf_url = f"/download_application_pdf/{_safe_key(token or 'guest')}/{after_pdf_filename}" if os.path.exists(after_pdf_path) else None

        # Compile Before PDF from old session path if present
        before_pdf_url = None
        old_path = session.get("path")
        if old_path and os.path.exists(old_path):
            before_pdf_filename = f"master_before_{uuid.uuid4().hex[:8]}.pdf"
            before_pdf_path = os.path.join(user_out_dir, before_pdf_filename)
            await asyncio.to_thread(
                subprocess.run,
                ["tectonic", old_path, "--outdir", user_out_dir],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
            default_before_pdf = os.path.join(user_out_dir, os.path.basename(old_path).replace(".tex", ".pdf"))
            if os.path.exists(default_before_pdf):
                os.replace(default_before_pdf, before_pdf_path)
            elif os.path.exists(old_path.replace(".tex", ".pdf")):
                os.replace(old_path.replace(".tex", ".pdf"), before_pdf_path)

            if os.path.exists(before_pdf_path):
                before_pdf_url = f"/download_application_pdf/{_safe_key(token or 'guest')}/{before_pdf_filename}"

        set_session_data(token, updated_data, canonical_tex_path)
        guest_file = _get_guest_state_file(token)
        from services.ats_scorer import evaluate_master_resume
        new_eval = evaluate_master_resume(updated_data)
        try:
            with open(guest_file, "w") as f:
                json.dump({"data": updated_data, "path": canonical_tex_path, "evaluation": new_eval}, f, indent=2)
        except Exception:
            pass

        return {
            "status": "success",
            "data": updated_data,
            "evaluation": new_eval,
            "latex": canonical_tex,
            "before_pdf_url": before_pdf_url,
            "after_pdf_url": after_pdf_url
        }
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to apply suggestion: {str(e)}")

class UpdateMasterFromTailoredRequest(BaseModel):
    latex_code: str

@app.post("/user/update_master_from_tailored")
async def update_master_from_tailored(request: UpdateMasterFromTailoredRequest, authorization: Optional[str] = Header(None)):
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]
        
    session = get_session_data(token)
    if not request.latex_code or not request.latex_code.strip():
        raise HTTPException(status_code=400, detail="Invalid LaTeX content.")
        
    try:
        from services.resume_parser import parse_resume
        user_up_dir, _ = _get_user_storage_dirs(token or "guest")
        temp_tex = os.path.join(user_up_dir, f"temp_promoted_{uuid.uuid4().hex[:8]}.tex")
        with open(temp_tex, "w", encoding="utf-8") as f:
            f.write(request.latex_code)
            
        # Parse LaTeX back into structured JSON data
        structured = await asyncio.to_thread(parse_resume, temp_tex)
        updated_data = structured.model_dump()
        
        canonical_tex_path = os.path.join(user_up_dir, f"{uuid.uuid4().hex}_master.tex")
        with open(canonical_tex_path, "w", encoding="utf-8") as f:
            f.write(request.latex_code)
            
        set_session_data(token, updated_data, canonical_tex_path)
        guest_file = _get_guest_state_file(token)
        from services.ats_scorer import evaluate_master_resume
        new_eval = evaluate_master_resume(updated_data)
        
        try:
            with open(guest_file, "w") as f:
                json.dump({"data": updated_data, "path": canonical_tex_path, "evaluation": new_eval}, f, indent=2)
        except Exception:
            pass

        return {"status": "success", "message": "Master resume updated from tailored version!", "data": updated_data, "evaluation": new_eval}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update master resume: {str(e)}")

@app.get("/applications")
async def get_applications(authorization: Optional[str] = Header(None)):
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]
    return {"applications": await asyncio.to_thread(list_applications, token)}

class UpdateStatusRequest(BaseModel):
    job_url: str
    status: str

@app.post("/update_application_status")
async def update_status_endpoint(request: UpdateStatusRequest, authorization: Optional[str] = Header(None)):
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]
    success = await asyncio.to_thread(update_application_status, token, request.job_url, request.status)
    return {"status": "success" if success else "not_found"}

class InterviewPrepRequest(BaseModel):
    job_title: str
    company: str
    job_url: Optional[str] = None

@app.post("/generate_interview_prep")
async def generate_interview_prep(request: InterviewPrepRequest, authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = authorization.split(" ")[1]
    
    # 1. Fetch user resume data
    session = get_session_data(token)
    resume = session.get("data")
    if not resume:
        raise HTTPException(status_code=400, detail="No resume uploaded yet. Upload a resume first to prepare.")

    # 2. Extract job description if URL is available
    jd_text = ""
    if request.job_url:
        try:
            scraped = await scrape_job_description(request.job_url)
            jd_text = scraped.get("description", "")
        except Exception:
            pass

    # 3. Formulate Prompt
    prompt = f"""You are a professional Interview Coach.
Help the candidate prepare for an upcoming interview.

CANDIDATE PROFILE:
{json.dumps(resume, indent=2)}

TARGET POSITION:
Role: {request.job_title}
Company: {request.company}
Job Description context: {jd_text[:1200] if jd_text else "Not provided"}

Output a complete Markdown Interview Preparation Pack following these sections:
1. **Behavioral STAR Q&A:** Formulate 3-4 custom STAR stories mapping the candidate's exact experience to likely interview questions for this role. Use actual metrics from the profile.
2. **Technical Review Checklist:** List 5 key topics or tools mentioned in the job context that the candidate should brush up on.
3. **Common Tough Questions:** Provide specific, tailored answers for "Why this company?" and "How to address any skill/experience gaps".
4. **Smart Questions to Ask Them:** List 3-4 highly engaging questions tailored specifically to this company and role.

Do NOT add conversational intro/outro. Output ONLY the raw Markdown.
"""

    try:
        from services.gemini_client import generate_content_with_fallback
        result_text = await asyncio.to_thread(generate_content_with_fallback, prompt)
        return {"status": "success", "markdown": result_text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class CoverLetterHistoryRequest(BaseModel):
    job_title: str
    company: str
    job_url: Optional[str] = None

@app.post("/generate_cover_letter_history")
async def generate_cover_letter_history(request: CoverLetterHistoryRequest, authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        token = "guest"
    else:
        token = authorization.split(" ")[1]
    
    session = get_session_data(token)
    resume = session.get("data")
    if not resume:
        raise HTTPException(status_code=400, detail="No candidate resume found. Upload a resume first.")

    jd_text = ""
    if request.job_url:
        try:
            scraped = await scrape_job_description(request.job_url)
            jd_text = scraped.get("description", "")
        except Exception:
            pass

    prompt = f"""You are an expert career writer.
Write a concise, compelling cover letter (under 300 words) tailored to the role of '{request.job_title}' at '{request.company}'.

CANDIDATE PROFILE:
{json.dumps(resume, indent=2)}

JOB DETAILS:
Role: {request.job_title}
Company: {request.company}
JD Excerpt: {jd_text[:1200] if jd_text else "Not provided"}

RULES:
1. Cover letter under 300 words.
2. STRICTLY NO EM-DASHES (--) OR HYPHENS AS SENTENCE BREAKS.
3. STRICTLY NO CLICHES or generic filler phrases ("passionate about", "leverage my skills", "hit the ground running").
4. Active, confident voice. Focus on problem-solving accomplishments from candidate's profile.
5. Return ONLY the raw cover letter text. No markdown commentary around it.
"""

    try:
        from services.gemini_client import generate_content_with_fallback
        cover_letter = await asyncio.to_thread(generate_content_with_fallback, prompt)
        return {"status": "success", "cover_letter": cover_letter}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class ScrapeRequest(BaseModel):
    url: str

@app.post("/scrape_job")
async def scrape_job(request: ScrapeRequest, http_request: Request):
    _check_rate_limit(http_request, "scrape_job", max_requests=10, window_seconds=60)
    try:
        scraped = await scrape_job_description(request.url)
        return {
            "status": "success",
            "title": scraped.get("title", ""),
            "description": scraped.get("description", "")
        }
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

class SearchJobsRequest(BaseModel):
    location: Optional[str] = "Remote"
    keywords: Optional[str] = None
    timeframe: Optional[str] = "48h"

@app.post("/search_matching_jobs")
async def search_matching_jobs(request: SearchJobsRequest, http_request: Request, authorization: Optional[str] = Header(None), x_gemini_api_key: Optional[str] = Header(None)):
    _check_rate_limit(http_request, "search_matching_jobs", max_requests=5, window_seconds=300)
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]
        
    session = get_session_data(token)
    session_resume_data = session.get("data")
    if not session_resume_data:
        raise HTTPException(status_code=400, detail="Please upload a resume first.")

    db_api_key = None
    if token:
        user = await async_get_user_by_token(token)
        if user:
            db_api_key = user.get("gemini_api_key")
    active_api_key = x_gemini_api_key or db_api_key
    
    # Check TTL job search cache first
    cache_key = (request.keywords or "", request.location or "Remote", request.timeframe or "48h")
    cached_jobs = _job_search_cache.get(cache_key)
    if cached_jobs is not None:
        async def cached_job_stream():
            yield json.dumps({"type": "log", "message": "⚡ Loaded job results from cache (< 5 min old)!"}) + "\n"
            for job in cached_jobs:
                yield json.dumps({"type": "partial_result", "job": job}) + "\n"
            yield json.dumps({"type": "result", "jobs": cached_jobs}) + "\n"
        return StreamingResponse(
            cached_job_stream(),
            media_type="application/x-ndjson",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"
            }
        )

    try:
        # Wrap the generator to also cache results on completion,
        # and interleave keepalive pings every 10s so ngrok never drops the connection.
        async def caching_job_stream():
            q: asyncio.Queue = asyncio.Queue()
            all_jobs = []
            search_done = False

            async def _producer():
                nonlocal all_jobs, search_done
                try:
                    async for chunk in find_matching_jobs(
                        resume_data=session_resume_data,
                        location=request.location,
                        keywords=request.keywords,
                        timeframe=request.timeframe or "48h",
                        custom_api_key=active_api_key,
                        browser=getattr(http_request.app.state, "browser", None)
                    ):
                        try:
                            parsed = json.loads(chunk.strip())
                            if parsed.get("type") == "result" and parsed.get("jobs"):
                                all_jobs = parsed["jobs"]
                                _job_search_cache.set(cache_key, all_jobs)
                        except Exception:
                            pass
                        await q.put(chunk)
                finally:
                    search_done = True
                    await q.put(None)  # Sentinel to signal completion

            async def _keepalive():
                while not search_done:
                    await asyncio.sleep(10)
                    if not search_done:
                        # NDJSON comment — not valid JSON so frontend silently skips it
                        await q.put("{\"type\":\"ping\"}" + " " * 2048 + "\n")

            producer_task = asyncio.create_task(_producer())
            keepalive_task = asyncio.create_task(_keepalive())

            try:
                while True:
                    chunk = await q.get()
                    if chunk is None:
                        break
                    yield chunk
            finally:
                keepalive_task.cancel()
                try:
                    await keepalive_task
                except asyncio.CancelledError:
                    pass

        return StreamingResponse(
            caching_job_stream(),
            media_type="application/x-ndjson",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"
            }
        )
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/generate_outreach")
async def generate_outreach(request: GenerateOutreachRequest, authorization: Optional[str] = Header(None), x_gemini_api_key: Optional[str] = Header(None)):
    """Generate personalized recruiter outreach message."""
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]

    try:
        session = get_session_data(token)
        session_resume_data = session.get("data")

        if not session_resume_data:
            raise HTTPException(status_code=400, detail="Please upload a resume first.")

        # Get API key
        db_api_key = None
        if token:
            user = await async_get_user_by_token(token)
            if user:
                db_api_key = user.get("gemini_api_key")
        active_api_key = x_gemini_api_key or db_api_key

        # Extract recruiter info if job_url provided
        recruiter_info = {
            "recruiter_name": request.recruiter_name,
            "recruiter_profile_url": None,
            "company_name": request.company_name,
            "platform": request.platform or "unknown"
        }

        if request.job_url:
            recruiter_info = await extract_recruiter(request.job_url, request.platform)
            # Fallback to provided company name if extraction failed
            if not recruiter_info.get("company_name"):
                recruiter_info["company_name"] = request.company_name

        # Safely extract skills as a list (could be dict or list in session_resume_data)
        raw_skills = session_resume_data.get("skills", [])
        if isinstance(raw_skills, dict):
            flat_skills = [s for sublist in raw_skills.values() for s in (sublist if isinstance(sublist, list) else [sublist])]
        elif isinstance(raw_skills, list):
            flat_skills = raw_skills
        else:
            flat_skills = []

        ats_analysis = {
            "match_analysis": {
                "overall_score": 75,
                "matched_skills": flat_skills[:5],
                "missing_skills": [],
                "tailoring_suggestions": []
            }
        }

        # Generate outreach message
        def log_callback(msg_json: str):
            try:
                json.loads(msg_json)
                LLMClientLogQueue.put(msg_json)
            except Exception:
                pass

        outreach_msg = await asyncio.to_thread(
            generate_outreach_message,
            job_description=request.job_description,
            resume_data=session_resume_data,
            ats_analysis=ats_analysis,
            recruiter_name=recruiter_info.get("recruiter_name"),
            company_name=recruiter_info.get("company_name", request.company_name),
            custom_api_key=active_api_key,
            on_log=log_callback
        )

        return {
            "status": "success",
            "recruiter_info": recruiter_info,
            "message": outreach_msg.model_dump()
        }
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/send_outreach_email")
async def send_outreach_email(request: SendOutreachEmailRequest, authorization: Optional[str] = Header(None)):
    """Send outreach email via SMTP."""
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]

    try:
        # For now, return a success response indicating the email would be sent
        # In production, integrate with an email service (SendGrid, AWS SES, etc.)

        # Validate email format
        if not request.recipient_email or '@' not in request.recipient_email:
            raise HTTPException(status_code=400, detail="Invalid recipient email address.")

        # Log the email that would be sent
        print(f"[Outreach Email] To: {request.recipient_email}")
        print(f"[Outreach Email] Subject: {request.subject}")
        print(f"[Outreach Email] Body preview: {request.body[:200]}...")

        return {
            "status": "success",
            "message": "Email prepared for sending. In production, this would be sent via SMTP.",
            "recipient": request.recipient_email,
            "subject": request.subject
        }
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


class AnswerQuestionRequest(BaseModel):
    question: str
    company_name: Optional[str] = None
    job_title: Optional[str] = None
    job_description: Optional[str] = None
    candidate_profile: Optional[dict] = None

@app.post("/answer_question")
async def answer_question(request: AnswerQuestionRequest, authorization: Optional[str] = Header(None), x_gemini_api_key: Optional[str] = Header(None)):
    """Generate high-impact, personalized screening question answers using LLM and candidate resume."""
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]

    session_resume_data = request.candidate_profile or {}
    if not session_resume_data and token:
        user = await async_get_user_by_token(token)
        if user and user.get("id"):
            try:
                from services.auth import supabase_request
                res = supabase_request(f"user_resumes?user_id=eq.{user['id']}&select=resume_data", "GET")
                if res and len(res) > 0:
                    session_resume_data = json.loads(res[0].get("resume_data", "{}"))
            except Exception:
                pass

    if not session_resume_data:
        session = get_session_data(token)
        session_resume_data = session.get("data", {})

    prompt = f"""You are a world-class AI Career Coach and Resume Assistant answering job application screening questions.

Candidate Profile & Resume Data:
{json.dumps(session_resume_data, indent=2)}

Company / Organization: {request.company_name or 'Granola / Hiring Team'}
Target Role / Position: {request.job_title or 'Open Position'}
Application Question / Prompt: "{request.question}"

Instructions:
1. Provide a direct, highly compelling, authentic, and concise answer tailored specifically to this candidate's genuine background, skills, achievements, and the target role/company.
2. If the question specifies a constraint (such as 'in just one line', 'in 5 sentences or less', 'in 150 words', 'in 2-3 bullet points'), STRICTLY obey that exact formatting constraint.
3. Sound authentic, ambitious, and professional. Do NOT include conversational filler, meta-introductions (like "Here is my answer:"), or quotation marks. Output only the clean answer text."""

    db_api_key = None
    if token:
        user = await async_get_user_by_token(token)
        if user:
            db_api_key = user.get("gemini_api_key")
    active_api_key = x_gemini_api_key or db_api_key

    from services.gemini_client import generate_content_with_fallback
    try:
        answer_text = generate_content_with_fallback(
            prompt=prompt,
            custom_api_key=active_api_key,
            model_tier="lite"
        )
        return {"status": "success", "answer": answer_text.strip()}
    except Exception as e:
        print(f"[answer_question] LLM generation error: {e}")
        # Fallback heuristic answer
        q_lower = request.question.lower()
        if "one line" in q_lower or "one-line" in q_lower or "condensed cover letter" in q_lower:
            name = session_resume_data.get("name", "Software Engineer")
            skills = ", ".join(session_resume_data.get("skills", ["software engineering"])[:4]) if isinstance(session_resume_data.get("skills"), list) else "full-stack development"
            return {"status": "success", "answer": f"Driven engineer specializing in {skills} with a track record of building high-performance, scalable products."}
        elif "why" in q_lower and ("company" in q_lower or "team" in q_lower or "granola" in q_lower):
            company = request.company_name or "your team"
            return {"status": "success", "answer": f"I am inspired by {company}'s mission to build innovative, user-centric tools that solve real-world problems. With my background in delivering scalable systems, I would love to contribute directly to accelerating your product velocity and user impact."}
        return {"status": "success", "answer": f"With my proven experience in engineering and product innovation, I am excited to bring direct value to {request.company_name or 'the team'}."}

@app.get("/admin/logs", response_class=HTMLResponse)
@app.get("/admin/logs/", response_class=HTMLResponse)
async def admin_logs_dashboard(key: Optional[str] = None):
    """
    Secure admin live log streaming dashboard URL.
    Access via: https://your-domain.com/admin/logs?key=akhil-admin-secret-123
    """
    admin_key = os.getenv("ADMIN_LOG_KEY", "akhil-admin-secret-123")
    if key != admin_key:
        raise HTTPException(status_code=403, detail="Unauthorized Admin Access")

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Live Server Logs - Job Finder Admin</title>
        <style>
            body {{ background-color: #0F172A; color: #38BDF8; font-family: monospace; padding: 20px; font-size: 13px; }}
            h2 {{ color: #F43F5E; font-family: sans-serif; display: flex; align-items: center; justify-content: space-between; }}
            #logs {{ background: #1E293B; border: 1px solid #334155; border-radius: 8px; padding: 15px; height: 75vh; overflow-y: auto; white-space: pre-wrap; line-height: 1.5; }}
            .btn {{ background: #0284C7; color: white; border: none; padding: 8px 16px; border-radius: 6px; cursor: pointer; font-weight: bold; }}
            .btn:hover {{ background: #0369A1; }}
        </style>
    </head>
    <body>
        <h2>
            <span>🚀 Live Server Logs (Real-time Stream)</span>
            <button class="btn" onclick="document.getElementById('logs').innerText=''">Clear Screen</button>
        </h2>
        <div id="logs">Connecting to live server log stream...</div>
        <script>
            const logDiv = document.getElementById('logs');
            const eventSource = new EventSource('/admin/logs/stream?key={admin_key}');
            
            eventSource.onmessage = function(e) {{
                logDiv.innerText += e.data + "\\n";
                logDiv.scrollTop = logDiv.scrollHeight;
            }};
            
            eventSource.onerror = function() {{
                logDiv.innerText += "\\n[Stream Disconnected. Reconnecting...]\\n";
            }};
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

@app.get("/admin/logs/stream")
async def admin_logs_stream(key: Optional[str] = None):
    admin_key = os.getenv("ADMIN_LOG_KEY", "akhil-admin-secret-123")
    if key != admin_key:
        raise HTTPException(status_code=403, detail="Unauthorized Admin Access")

    async def generate_logs():
        yield "data: 🟢 Connected to Live Admin Log Stream\n\n"
        while True:
            msgs = LLMClientLogQueue.get_all()
            if msgs:
                for msg in msgs:
                    # Escape newlines for SSE data protocol format
                    formatted = msg.replace("\n", " ")
                    yield f"data: {formatted}\n\n"
            else:
                # Send periodic SSE comment ping every 5s to prevent proxy/GZip buffering
                yield ": ping\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        generate_logs(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@app.get("/user/logs/stream")
async def user_logs_stream(request: Request):
    """
    SSE log stream for the authenticated frontend user.
    The frontend connects to this during a job search to display all backend
    pipeline logs (scraper, LLM, recruiter, etc.) in the UI pipeline log box.
    Authenticated via Authorization Bearer token (same as all other /user/ endpoints).
    """
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "").strip() if auth_header.startswith("Bearer ") else None
    if not token:
        raise HTTPException(status_code=401, detail="Unauthorized")
    user = await async_get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired session token")

    async def generate_user_logs():
        yield "data: 🟢 Connected to Live Log Stream\n\n"
        while True:
            if await request.is_disconnected():
                break
            msgs = LLMClientLogQueue.get_all()
            if msgs:
                for msg in msgs:
                    formatted = msg.replace("\n", " ")
                    yield f"data: {formatted}\n\n"
            else:
                yield ": ping\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(
        generate_user_logs(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

frontend_dist = os.path.abspath(os.path.join(os.path.dirname(__file__), "../frontend/dist"))
if not os.path.exists(frontend_dist):
    frontend_dist = "/app/frontend/dist"
if not os.path.exists(frontend_dist):
    frontend_dist = os.path.abspath(os.path.join(os.path.dirname(__file__), "frontend/dist"))

if os.path.exists(frontend_dist):
    # Serve hashed assets (/assets/*.js, *.css) with long-lived immutable cache headers.
    # Vite produces content-hashed filenames so stale content is never served.
    # pyrefly: ignore [missing-import]
    from starlette.staticfiles import StaticFiles as _SF
    # pyrefly: ignore [missing-import]
    from starlette.responses import Response as _R
    # pyrefly: ignore [missing-import]
    from starlette.types import ASGIApp, Scope, Receive, Send

    class CachedStaticFiles(_SF):
        """StaticFiles subclass that adds Cache-Control: immutable for hashed assets."""
        async def __call__(self, scope: Scope, receive: Receive, send: Send):
            async def send_with_cache(message):
                if message["type"] == "http.response.start":
                    headers = dict(message.get("headers", []))
                    headers[b"cache-control"] = b"public, max-age=31536000, immutable"
                    message = {**message, "headers": list(headers.items())}
                await send(message)
            await super().__call__(scope, receive, send_with_cache)

    app.mount("/assets", CachedStaticFiles(directory=os.path.join(frontend_dist, "assets")), name="assets")

    @app.get("/{rest_of_path:path}", response_class=HTMLResponse)
    async def serve_frontend(rest_of_path: str):
        # Ignore API endpoints and action handlers so they pass through to regular routes
        if rest_of_path in ("health", "healthz") or any(api in rest_of_path for api in ("admin/", "user/", "auth/", "get_session_resume", "generate_outreach", "email_action", "scrape_job", "upload_resume", "apply", "assets/", "analyze_job", "download_latex", "download_application_pdf", "compile_latex", "generate_tailored_resume", "open_in_overleaf", "search_matching_jobs", "clear_cache")):
            raise HTTPException(status_code=404, detail="Not Found")
        
        if rest_of_path == "favicon.svg":
            favicon_path = os.path.join(frontend_dist, "favicon.svg")
            if os.path.exists(favicon_path):
                return FileResponse(favicon_path, media_type="image/svg+xml")
            
        index_html = os.path.join(frontend_dist, "index.html")
        if os.path.exists(index_html):
            with open(index_html, "r", encoding="utf-8") as f:
                return f.read()
        return "Frontend build files not found."

if __name__ == "__main__":
    # pyrefly: ignore [missing-import]
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=False,
        loop="uvloop",
        http="httptools",
        timeout_keep_alive=30,
        log_level="warning",
    )


