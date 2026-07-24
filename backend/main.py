import asyncio
import os
import shutil
import json
import subprocess
import re
import io
import ssl
import traceback
import zipfile
import urllib.request
import urllib.parse
from urllib.error import URLError
import uuid
import queue
# pyrefly: ignore [missing-import]
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Header, Request
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
from typing import List, Optional
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv
load_dotenv()
# pyrefly: ignore [missing-import]
from pypdf import PdfReader
import time
import hashlib
import re as _re


from services.resume_parser import parse_resume
from services.scraper import scrape_job_description
from services.llm_agent import analyze_job_fit, review_tailored_resume, tailor_latex_code
from services.resume_generator import generate_pdf_resume
from services.autofill_agent import autofill_job_application
from services.job_searcher import find_matching_jobs
from services.application_tracker import record_application, list_applications
from services.recruiter_extractor import extract_recruiter
from services.outreach_generator import generate_outreach_message
from services.auth import (
    create_or_get_user,
    create_session,
    get_user_by_token,
    update_user_api_key,
    get_google_auth_url,
    exchange_google_code_for_email
)
from services.log_queue import LLMClientLogQueue
from utils.latex_utils import extract_latex_command, apply_latex_hotfix, generate_latex_from_json
from utils.ssl_utils import SSL_CONTEXT
from utils.ttl_cache import TTLCache
# --- Background Task to Clean Files Older Than 1 Hour (Runs every 30 mins) ---
from contextlib import asynccontextmanager

# Use absolute paths to prevent working directory shifts on Render container startup
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
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
        
        # 1. Clean output folder
        if os.path.exists(OUTPUT_DIR):
            for filename in os.listdir(OUTPUT_DIR):
                if filename == "resume_state.json" or filename.startswith("application_history_"):
                    continue
                file_path = os.path.join(OUTPUT_DIR, filename)
                try:
                    mtime = os.path.getmtime(file_path)
                    if force_startup_purge or mtime < cutoff:
                        if os.path.isfile(file_path) or os.path.islink(file_path):
                            os.unlink(file_path)
                            print(f"[Auto Clean Output] Deleted file: {filename} (Modified {now - mtime:.1f}s ago)")
                        elif os.path.isdir(file_path):
                            shutil.rmtree(file_path)
                            print(f"[Auto Clean Output] Deleted directory: {filename}")
                except Exception as ex:
                    print(f"[Auto Clean Output] Failed to delete {file_path}: {ex}")
        
        # 2. Clean uploads folder (keep fallback resume.cls)
        if os.path.exists(UPLOAD_DIR):
            for filename in os.listdir(UPLOAD_DIR):
                if filename == "resume.cls":
                    continue
                file_path = os.path.join(UPLOAD_DIR, filename)
                try:
                    mtime = os.path.getmtime(file_path)
                    if force_startup_purge or mtime < cutoff:
                        if os.path.isfile(file_path) or os.path.islink(file_path):
                            os.unlink(file_path)
                            print(f"[Auto Clean Uploads] Deleted file: {filename} (Modified {now - mtime:.1f}s ago)")
                        elif os.path.isdir(file_path):
                            shutil.rmtree(file_path)
                            print(f"[Auto Clean Uploads] Deleted directory: {filename}")
                except Exception as ex:
                    print(f"[Auto Clean Uploads] Failed to delete {file_path}: {ex}")
        
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

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Perform immediate full purge of leftover files from previous deployment container instances
    await auto_clean_expired_files(force_startup_purge=True)
    # Start the background checker loop task
    clean_task = asyncio.create_task(auto_clean_expired_files_loop())
    yield
    # Shutdown
    clean_task.cancel()
    try:
        await clean_task
    except asyncio.CancelledError:
        pass

# Initialize FastAPI with the lifespan handler
app = FastAPI(title="AI Job Finder Agent API", lifespan=lifespan)

# FIX #5: allow_origins=["*"] combined with allow_credentials=True is invalid per the
# CORS spec (browsers will reject it even though FastAPI won't error at startup).
# This API authenticates via a Bearer token header, not cookies, so credentialed
# CORS requests aren't actually needed. If you later need cookie-based auth,
# replace allow_origins=["*"] with an explicit list of trusted origins instead.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

import threading

# Maps any token (real user token, guest UUID, or "guest") to resume state.
# Backed in-memory with optional Supabase persistence for authenticated users.
_session_store: dict[str, dict] = {}
_store_lock = threading.Lock()

RESUME_STATE_FILE = os.path.join(OUTPUT_DIR, "resume_state.json")

# Helpers to manage state safely
from services.auth import update_user_resume_data


def _safe_key(token: Optional[str]) -> str:
    """FIX #2 helper: turn a token (or 'guest') into a filesystem/cache-safe key
    with no path separators, so it can be used to build per-user file paths."""
    key = token or "guest"
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
    if any(os.getenv(v) for v in ("RENDER", "RAILWAY_ENVIRONMENT", "RAILWAY_PROJECT_ID", "FLY_APP_NAME")):
        return False
    frontend_url = os.getenv("FRONTEND_URL", "")
    return "localhost" in frontend_url or "127.0.0.1" in frontend_url


def _user_output_paths(token: Optional[str]) -> tuple[str, str]:
    """FIX #2: Return per-user tex/pdf output paths instead of the single global
    'tailored_resume.tex' / 'tailored_resume.pdf' filenames. Using fixed global
    filenames meant concurrent users could overwrite each other's compiled resume,
    and in the worst case /apply could submit one user's resume to another
    user's job application."""
    key = _safe_key(token)
    tex_path = os.path.join(OUTPUT_DIR, f"tailored_resume_{key}.tex")
    pdf_path = os.path.join(OUTPUT_DIR, f"tailored_resume_{key}.pdf")
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
        if data and data.get("data"):
            return data
            
    # Try fetching from Supabase if token exists
    if token:
        try:
            user = get_user_by_token(token)
            # Query the user_resumes table instead or query users safely
            if user:
                # We dynamically check if Supabase returned the fields or try querying user_resumes
                user_id = user.get("id")
                from services.auth import supabase_request
                res = supabase_request(f"user_resumes?user_id=eq.{user_id}", "GET")
                if res and len(res) > 0:
                    resume_dict = json.loads(res[0].get("resume_data", "{}"))
                    path = ""
                    master_latex = res[0].get("master_latex", "")
                    if master_latex:
                        path = os.path.join(UPLOAD_DIR, f"{user_id}_master.tex")
                        with open(path, "w", encoding="utf-8") as f:
                            f.write(master_latex)
                    with _store_lock:
                        _session_store[token] = {"data": resume_dict, "path": path}
                    return {"data": resume_dict, "path": path}
        except Exception as e:
            print(f"Failed to load resume from Supabase user session: {e}")

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
        if path and os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
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

# Load stored resume state if exists at startup (initialized to the guest session)
if os.path.exists(RESUME_STATE_FILE):
    try:
        with open(RESUME_STATE_FILE, "r") as f:
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
            file_path = uploaded_files[0]
            print(f"Found uploaded resume at startup: {file_path}. Auto-parsing...")
            structured_data = parse_resume(file_path)
            set_session_data("guest", structured_data.model_dump(), file_path)
            with open(RESUME_STATE_FILE, "w") as f:
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
        file_path = os.path.join(UPLOAD_DIR, safe_filename)

        # Stream-copy in chunks rather than shutil.copyfileobj's unbounded read,
        # so an oversized upload is rejected (and its partial file removed)
        # instead of being fully written to disk first — there was previously
        # no cap at all, so a multi-GB upload would happily write to disk and
        # tie up parse_resume() before anyone noticed.
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
        structured_data = parse_resume(file_path)
        data = structured_data.model_dump()
        path = file_path
        
        # If uploaded file is a PDF/DOCX, generate and save a canonical .tex version
        # so master_latex always has the correct \name and \address blocks
        if not file_path.endswith(".tex"):
            canonical_tex_path = os.path.join(UPLOAD_DIR, f"{uuid.uuid4().hex}_master.tex")
            canonical_tex = generate_latex_from_json(data)
            with open(canonical_tex_path, "w", encoding="utf-8") as f:
                f.write(canonical_tex)
            # Use this as the master going forward
            path = canonical_tex_path
        
        # Save to session-scoped cache
        set_session_data(token, data, path)
        
        # Save default guest state to local file for persistence compatibility
        if not token or token == "guest":
            with open(RESUME_STATE_FILE, "w") as f:
                json.dump({"data": data, "path": path}, f, indent=2)
        
        return {"message": "Resume uploaded and parsed successfully", "data": data}
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

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
            # Company name is between "at-" and the next "-" followed by digits or "/"
            linkedin_job_match = _re_url.search(r'-at-([a-z0-9-]+?)(?:-\d+|/|$)', cleaned_url.lower())
            if linkedin_job_match:
                company_from_linkedin = linkedin_job_match.group(1).strip().replace('-', ' ').strip().title()
                if company_from_linkedin and company_from_linkedin.lower() not in {'', 'unknown'}:
                    print(f"[_extract_company_from_jd] ✓ Extracted from LinkedIn Job URL: {company_from_linkedin}")
                    return company_from_linkedin

            # LinkedIn Company URL: https://www.linkedin.com/company/merimen-technologies-singapore-pte-ltd/life/
            # Extract company slug and scrape the page to get the actual company name
            linkedin_company_match = _re_url.search(r'/company/([a-z0-9\-]+)(?:/|$)', cleaned_url.lower())
            if linkedin_company_match:
                company_slug = linkedin_company_match.group(1)
                print(f"[_extract_company_from_jd] Found LinkedIn company slug: {company_slug}")

                # Try to scrape the LinkedIn company page to get the actual company name
                try:
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

            # Indeed: https://www.indeed.com/viewjob?jk=abc123def456&company=CompanyName
            # Try to extract company from query params
            indeed_match = _re_url.search(r'[?&]company=([^&]+)', cleaned_url)
            if indeed_match:
                company_from_indeed = indeed_match.group(1).replace('+', ' ').replace('%20', ' ').title()
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
            import traceback
            traceback.print_exc()

    # If URL extraction failed, try JD-based extraction
    if not jd_text:
        print(f"[_extract_company_from_jd] ✗ No company found in URL or JD")
        return ""

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
            if name.lower() not in {'the', 'a', 'an', 'we', 'our', 'this', 'you', 'your', 'us', 'etl', 'api', 'sdk', 'framework', 'platform', 'tool', 'system', 'devops', 'mlops', 'data', 'engineering'}:
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
    key = hashlib.md5(key_src.encode("utf-8")).hexdigest()
    return _analysis_cache.get(key)

def set_cached_analysis(token: str, job_title: str, jd_text: str, analysis: dict):
    if not jd_text:
        return
    key_src = f"{token or 'guest'}:{job_title}:{jd_text}"
    key = hashlib.md5(key_src.encode("utf-8")).hexdigest()
    _analysis_cache.set(key, analysis)

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

@app.post("/analyze_job")
async def analyze_job(request: JobAnalysisRequest, http_request: Request, authorization: Optional[str] = Header(None), x_gemini_api_key: Optional[str] = Header(None)):
    # This is the single most expensive endpoint in the app — multiple LLM
    # calls, an optional Playwright scrape, a Tectonic LaTeX compile, and up
    # to 3 recruiter-review retry rounds — yet unlike /scrape_job, /apply, and
    # /search_matching_jobs, it had no rate limit at all.
    _check_rate_limit(http_request, "analyze_job", max_requests=10, window_seconds=300)
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]

    session = get_session_data(token)
    session_resume_data = session.get("data")
    session_resume_path = session.get("path")

    if not session_resume_data:
        raise HTTPException(status_code=400, detail="Please upload a resume first.")
        
    # Check cache early before starting the generator
    if request.job_description:
        cached = get_cached_analysis(token, request.job_title, request.job_description)
        if cached:
            # Strip latex code if user requested skip_tailoring
            if request.skip_tailoring:
                cached = dict(cached)
                cached["latex_code"] = ""
            elif not request.skip_tailoring:
                # A cache hit on the full-tailoring path is a completed tailoring
                # result exactly like the live path's final yield below — record it
                # the same way, or repeat visits to an already-cached job silently
                # never show up in history.
                try:
                    record_application(token, {
                        "job_title": request.job_title,
                        "company": _extract_company_from_jd(request.job_description, request.job_url),
                        "job_url": request.job_url or "",
                        "score": cached.get("match_analysis", {}).get("overall_score"),
                        "status": "tailored",
                    })
                except Exception as hist_err:
                    print(f"[analyze_job] Failed to record application history (cache hit): {hist_err}")
            async def cached_event_generator():
                yield json.dumps({"type": "log", "message": "⚡ Loaded analysis from local cache!"}) + "\n"
                company_name = _extract_company_from_jd(request.job_description, request.job_url)
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
                user = get_user_by_token(token)
                if user:
                    db_api_key = user.get("gemini_api_key")
            
            active_api_key = x_gemini_api_key or db_api_key
            jd_text = request.job_description
            job_title = request.job_title
            if request.job_url and not jd_text:
                yield json.dumps({"type": "log", "message": "🤖 Launching Playwright browser to scrape job link..."}) + "\n"
                t0 = time.time()
                scraped = await scrape_job_description(request.job_url)
                jd_text = scraped["description"]
                job_title = scraped["title"]
                ctx.log_step("scrape_job", time.time() - t0)
                yield json.dumps({"type": "log", "message": f"✅ Scraped job details for: {job_title}"}) + "\n"
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
                            record_application(token, {
                                "job_title": job_title,
                                "company": _extract_company_from_jd(jd_text, request.job_url),
                                "job_url": request.job_url or "",
                                "score": cached.get("match_analysis", {}).get("overall_score"),
                                "status": "tailored",
                            })
                        except Exception as hist_err:
                            print(f"[analyze_job] Failed to record application history (cache hit): {hist_err}")
                    yield json.dumps({"type": "log", "message": "⚡ Loaded analysis from local cache!"}) + "\n"
                    company_name = _extract_company_from_jd(jd_text, request.job_url)
                    yield json.dumps({
                        "type": "result",
                        "job_title": job_title,
                        "job_description": jd_text,
                        "company": company_name,
                        "analysis": cached
                    }) + "\n"
                    return
                
            yield json.dumps({"type": "log", "message": "🤖 Comparing candidate profile & calculating ATS gap analysis..."}) + "\n"
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

            t0 = time.time()
            # Run fit analysis in a background task so we can drain log messages concurrently
            import asyncio
            fit_task = asyncio.create_task(
                analyze_job_fit(session_resume_data, job_title, jd_text, master_latex if not request.skip_tailoring else None, active_api_key, on_log=log_callback)
                # analyze_job_fit(session_resume_data, job_title, jd_text, master_latex if not request.skip_tailoring else None, active_api_key, on_log=None)
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

            yield json.dumps({"type": "log", "message": "✍️ Generated tailored resume content and cover letter."}) + "\n"

            if request.skip_tailoring:
                dumped = analysis.model_dump()
                company_name = _extract_company_from_jd(jd_text, request.job_url)
                yield json.dumps({
                    "type": "result",
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
                prev_review_hash = hashlib.md5(analysis.latex_code.encode("utf-8")).hexdigest()
                
                last_rejection_feedback = ""
                review = None
                stalled_on_identical_output = False
                
                if not request.force_tailoring:
                    while reviewer_attempts < 3:
                        yield json.dumps({"type": "log", "message": f"👀 Recruiter review check (Attempt {reviewer_attempts + 1})..."}) + "\n"
                        t0 = time.time()
                        
                        # Task-wrapped check to drain logs concurrently
                        review_task = asyncio.create_task(
                            asyncio.to_thread(review_tailored_resume, analysis.latex_code, session_resume_data, job_title, jd_text, active_api_key, on_log=log_callback)
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
                            yield json.dumps({"type": "log", "message": "✅ Recruiter review approved!"}) + "\n"
                            break
        
                        last_rejection_feedback = review.feedback
                        yield json.dumps({"type": "log", "message": f"⚠️ Recruiter rejected (Attempt {reviewer_attempts + 1}): {review.feedback}"}) + "\n"
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
                                
                        curr_hash = hashlib.md5(analysis.latex_code.encode("utf-8")).hexdigest()
                        if curr_hash == prev_review_hash:
                            yield json.dumps({"type": "log", "message": "⚠️ AI reviewer feedback generated identical LaTeX output. Breaking reviewer loop."}) + "\n"
                            stalled_on_identical_output = True
                            break
                        prev_review_hash = curr_hash
                        reviewer_attempts += 1

                    if review is not None and not review.satisfied and (reviewer_attempts >= 3 or stalled_on_identical_output):
                        yield json.dumps({
                            "type": "rejection_warning", 
                            "message": f"Candidate may not be a suitable fit for this job after {reviewer_attempts + 1} recruitment checks. Reason: {last_rejection_feedback}"
                        }) + "\n"
                        return
                else:
                    yield json.dumps({
                        "type": "log",
                        "message": "⚠️ Proceeding with resume tailoring anyway due to user override request."
                    }) + "\n"
    
                # --- Page-fit loop (compile first, try mechanical adjustments first) ---
                yield json.dumps({"type": "log", "message": "⚙️ Compiling PDF & checking page layout..."}) + "\n"
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
                prev_latex_hash = hashlib.md5(analysis.latex_code.encode("utf-8")).hexdigest()
    
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
                    
                    curr_hash = hashlib.md5(analysis.latex_code.encode("utf-8")).hexdigest()
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
    
                analysis.latex_code = apply_latex_hotfix(analysis.latex_code, optimal_scale, optimal_linespread, master_latex)
            else:
                analysis.latex_code = apply_latex_hotfix(analysis.latex_code, 1.0, 1.0, master_latex)

            dumped = analysis.model_dump()
            set_cached_analysis(token, job_title, jd_text, dumped)
            company_name = _extract_company_from_jd(jd_text, request.job_url)
            try:
                record_application(token, {
                    "job_title": job_title,
                    "company": company_name,
                    "job_url": request.job_url or "",
                    "score": dumped.get("match_analysis", {}).get("overall_score"),
                    "status": "tailored",
                })
            except Exception as hist_err:
                print(f"[analyze_job] Failed to record application history: {hist_err}")
            yield json.dumps({
                "type": "result",
                "job_title": job_title,
                "job_description": jd_text or "",
                "company": company_name,
                "analysis": dumped
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
        return FileResponse(pdf_path, media_type="application/pdf", filename="resume.pdf")
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/clear_cache")
async def clear_cache(authorization: Optional[str] = Header(None)):
    """Resets all in-memory caches and deletes temporary files in uploads and output folders."""
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]
        
    try:
        # 1. Clear in-memory caches
        _analysis_cache.clear()
        _job_search_cache.clear()
            
        # 2. Clean temporary output files
        if os.path.exists(OUTPUT_DIR):
            for filename in os.listdir(OUTPUT_DIR):
                file_path = os.path.join(OUTPUT_DIR, filename)
                # Keep resume_state.json unless guest cache is cleared
                if filename == "resume_state.json":
                    continue
                try:
                    if os.path.isfile(file_path) or os.path.islink(file_path):
                        os.unlink(file_path)
                    elif os.path.isdir(file_path):
                        shutil.rmtree(file_path)
                except Exception as ex:
                    print(f"Failed to delete output file {file_path}: {ex}")
                    
        # 3. Clean temporary uploads (except for the default resume.cls)
        if os.path.exists(UPLOAD_DIR):
            for filename in os.listdir(UPLOAD_DIR):
                if filename == "resume.cls":
                    continue
                file_path = os.path.join(UPLOAD_DIR, filename)
                try:
                    if os.path.isfile(file_path) or os.path.islink(file_path):
                        os.unlink(file_path)
                    elif os.path.isdir(file_path):
                        shutil.rmtree(file_path)
                except Exception as ex:
                    print(f"Failed to delete upload file {file_path}: {ex}")

        # Also reset session store for guest/user
        if token:
            with _store_lock:
                _session_store.pop(token, None)
        else:
            with _store_lock:
                _session_store.clear()
                
        # Re-sync resume.cls fallback
        if os.path.exists(default_cls_source):
            shutil.copy2(default_cls_source, target_cls_path)

        return {"status": "success", "message": "All cache, session store, and temporary files cleared successfully."}
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
        user = get_user_by_token(token)
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
                record_application(token, {
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


def _build_original_latex(resume_data: dict) -> str:
    """Build a clean LaTeX resume from raw parsed resume JSON — no AI tailoring."""
    def esc(s: str) -> str:
        """Escape special LaTeX characters."""
        if not s:
            return ""
        for char, rep in [("&", r"\&"), ("%", r"\%"), ("$", r"\$"), ("#", r"\#"),
                           ("_", r"\_"), ("{", r"\{"), ("}", r"\}"), ("~", r"\textasciitilde{}"),
                           ("^", r"\^{}"), ("\\", r"\textbackslash{}")]:
            s = s.replace(char, rep)
        return s

    name = esc(resume_data.get("name", ""))
    email = esc(resume_data.get("email", ""))
    phone = esc(resume_data.get("phone", ""))
    linkedin = esc(resume_data.get("linkedin", ""))
    summary = esc(resume_data.get("summary", ""))
    skills = resume_data.get("skills", [])
    experience = resume_data.get("experience", [])
    education = resume_data.get("education", [])

    contact_parts = [p for p in [email, phone, linkedin] if p]
    contact_line = " $\\vert$ ".join(contact_parts)

    # Skills block
    skills_str = ""
    if skills:
        # Chunk into rows of 6
        chunks = [skills[i:i+6] for i in range(0, len(skills), 6)]
        rows = []
        for chunk in chunks:
            rows.append(f"    \\textbf{{Skills}} & {esc(', '.join(chunk))} \\\\")
        skills_str = f"""
\\begin{{rSection}}{{Technical Skills}}
\\begin{{tabular}}{{ @{{}} >{{\\bfseries}}l @{{\\hspace{{6ex}}}} l }}
{chr(10).join(rows)}
\\end{{tabular}}
\\end{{rSection}}"""

    # Experience block
    exp_str = ""
    if experience:
        exp_blocks = []
        for exp in experience:
            company = esc(exp.get("company", ""))
            role = esc(exp.get("role", ""))
            
            # Extract start and end dates or fall back to dates/duration string
            start_date = exp.get("start_date")
            end_date = exp.get("end_date")
            dates = exp.get("dates", exp.get("date", exp.get("duration", "")))
            
            if start_date:
                # Normalize current/present working
                end_normalized = "Present"
                if end_date:
                    end_clean = end_date.strip().lower()
                    if end_clean not in ["current", "present", "now", "present working", "currently working"]:
                        end_normalized = end_date
                dates_str = f"{start_date} -- {end_normalized}"
            else:
                dates_str = dates
            
            # Clean up the final dates string case-insensitively for current/present
            if dates_str:
                for term in ["current", "present working", "currently working", "present"]:
                    if term in dates_str.lower():
                        # Replace specific term with capitalized "Present"
                        import re
                        dates_str = re.sub(re.escape(term), "Present", dates_str, flags=re.IGNORECASE)
            
            dates_final = esc(dates_str)
            bullets = exp.get("description", [])
            bullet_lines = "\n".join([f"    \\item {esc(b)}" for b in bullets if b])
            exp_blocks.append(
                f"  \\begin{{rSubsection}}{{{company}}}{{{dates_final}}}{{{role}}}{{}}\n{bullet_lines}\n  \\end{{rSubsection}}"
            )
        exp_str = f"""
\\begin{{rSection}}{{Professional Experience}}
{chr(10).join(exp_blocks)}
\\end{{rSection}}"""

    # Education block
    edu_str = ""
    if education:
        edu_blocks = []
        for edu in education:
            if isinstance(edu, dict):
                institution = esc(edu.get("institution", edu.get("school", "")))
                degree = esc(edu.get("degree", ""))
                year = esc(str(edu.get("year", edu.get("graduation_year", ""))))
                edu_blocks.append(f"  \\textbf{{{institution}}} \\hfill {year} \\\\\n  {degree}")
            else:
                edu_blocks.append(f"  {esc(str(edu))}")
        edu_str = f"""
\\begin{{rSection}}{{Education}}
{chr(10).join(edu_blocks)}
\\end{{rSection}}"""

    summary_str = ""
    if summary:
        summary_str = f"""
\\begin{{rSection}}{{Professional Summary}}
{summary}
\\end{{rSection}}"""

    return f"""\\documentclass{{resume}}
\\usepackage[left=0.4in,top=0.4in,right=0.4in,bottom=0.4in]{{geometry}}
\\usepackage{{hyperref}}
\\hypersetup{{hidelinks}}

\\name{{{name}}}
\\address{{{contact_line}}}

\\begin{{document}}
{summary_str}
{skills_str}
{exp_str}
{edu_str}
\\end{{document}}
"""


class OriginalOverleafRequest(BaseModel):
    resume_data: dict
    job_title: Optional[str] = ""
    company: Optional[str] = ""

@app.post("/open_original_in_overleaf")
async def open_original_in_overleaf(request: OriginalOverleafRequest):
    """Export the user's original (non-tailored) resume to Overleaf as LaTeX."""
    try:
        latex_code = _build_original_latex(request.resume_data)
        candidate_name = request.resume_data.get("name", "")
        url = await asyncio.to_thread(upload_zip_to_tmpfiles, latex_code, candidate_name, request.job_title, request.company)
        return {"url": url}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))



@app.get("/auth/url")
async def auth_url():
    return {"url": get_google_auth_url()}

@app.get("/auth/callback")
async def auth_callback(code: str):
    try:
        email, picture_url = exchange_google_code_for_email(code)
        user = create_or_get_user(email, picture_url)
        token = create_session(user["id"])
        frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173")
        return RedirectResponse(url=f"{frontend_url}?token={token}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"OAuth verification failed: {str(e)}")

@app.post("/auth/mock")
async def auth_mock(request: dict):
    # This endpoint mints a valid session for ANY email with zero verification
    # — it exists only for local dev (see the frontend's "Mock Dev Login",
    # which is itself gated to localhost). Without this server-side guard, the
    # UI-only restriction was cosmetic: anyone could POST here directly against
    # a real deployment and obtain a session as any user, bypassing Google
    # OAuth entirely.
    if not _is_local_deployment():
        raise HTTPException(status_code=404, detail="Not Found")
    email = request.get("email", "testuser@example.com")
    user = create_or_get_user(email)
    token = create_session(user["id"])
    return {"token": token}

@app.get("/user/me")
async def user_me(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = authorization.split(" ")[1]
    user = get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid token")
    return user

class SettingsRequest(BaseModel):
    gemini_api_key: str

@app.post("/user/settings")
async def user_settings(request: SettingsRequest, authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = authorization.split(" ")[1]
    user = get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid token")
    update_user_api_key(user["id"], request.gemini_api_key)
    return {"status": "success"}

@app.get("/user/resume")
async def user_resume(authorization: Optional[str] = Header(None)):
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]
    session = get_session_data(token)
    return {"data": session.get("data"), "path": session.get("path")}

@app.get("/applications")
async def get_applications(authorization: Optional[str] = Header(None)):
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]
    return {"applications": list_applications(token)}

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
        result_text = generate_content_with_fallback(prompt)
        return {"status": "success", "markdown": result_text}
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
        user = get_user_by_token(token)
        if user:
            db_api_key = user.get("gemini_api_key")
    active_api_key = x_gemini_api_key or db_api_key
    
    # Check TTL job search cache first
    cache_key = (request.keywords or "", request.location or "Remote", request.timeframe or "48h")
    cached_jobs = _job_search_cache.get(cache_key)
    if cached_jobs is not None:
        async def cached_job_stream():
            yield json.dumps({"type": "log", "message": "⚡ Loaded job results from cache (< 5 min old)!"}) + "\n"
            yield json.dumps({"type": "result", "jobs": cached_jobs}) + "\n"
        return StreamingResponse(cached_job_stream(), media_type="application/x-ndjson")

    try:
        # Wrap the generator to also cache results on completion
        async def caching_job_stream():
            all_jobs = []
            async for chunk in find_matching_jobs(
                resume_data=session_resume_data,
                location=request.location,
                keywords=request.keywords,
                timeframe=request.timeframe or "48h",
                custom_api_key=active_api_key
            ):
                # Intercept result events to extract jobs for caching
                try:
                    parsed = json.loads(chunk.strip())
                    if parsed.get("type") == "result" and parsed.get("jobs"):
                        all_jobs = parsed["jobs"]
                        _job_search_cache.set(cache_key, all_jobs)
                except Exception:
                    pass
                yield chunk
        
        return StreamingResponse(caching_job_stream(), media_type="application/x-ndjson")
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
            user = get_user_by_token(token)
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

        # Create a mock ATS analysis if not provided (for message generation)
        # In real usage, this would come from the analyze_job endpoint
        ats_analysis = {
            "match_analysis": {
                "overall_score": 75,
                "matched_skills": session_resume_data.get("skills", [])[:5],
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

        outreach_msg = generate_outreach_message(
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

frontend_dist = os.path.abspath(os.path.join(os.path.dirname(__file__), "../frontend/dist"))
if os.path.exists(frontend_dist):
    app.mount("/assets", StaticFiles(directory=os.path.join(frontend_dist, "assets")), name="assets")

    @app.get("/{rest_of_path:path}", response_class=HTMLResponse)
    async def serve_frontend(rest_of_path: str):
        # Ignore API endpoints so they pass through to regular routes
        if rest_of_path.startswith(("user/", "auth/", "scrape_job", "upload_resume", "apply", "assets/", "analyze_job", "download_latex", "compile_latex", "generate_tailored_resume", "open_in_overleaf", "search_matching_jobs", "clear_cache")):
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
    # Bind to PORT env variable specified by Render
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)