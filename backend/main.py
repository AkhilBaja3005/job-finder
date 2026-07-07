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
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
# pyrefly: ignore [missing-import]
# Mount static files for hosting the built frontend as part of the same service
from fastapi.staticfiles import StaticFiles
# pyrefly: ignore [missing-import]
from fastapi.responses import HTMLResponse
# pyrefly: ignore [missing-import]
from pydantic import BaseModel
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
# --- Background Task to Clean Files Older Than 1 Hour (Runs every 30 mins) ---
from contextlib import asynccontextmanager

# Use absolute paths to prevent working directory shifts on Render container startup
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
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
                if filename == "resume_state.json":
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
    job_title: str
    job_description: Optional[str] = None
    skip_tailoring: bool = False
    force_tailoring: bool = False

class ApplyRequest(BaseModel):
    job_url: str
    direct_mode: bool = False

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
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
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

def _extract_company_from_jd(jd_text: str) -> str:
    """Heuristically extract the hiring company name from a job description."""
    patterns = [
        r"(?:About|Join|At|with)\s+([A-Z][\w&.,'-]{1,40}(?:\s+[A-Z][\w&.,'-]{1,20}){0,3})",
        r"([A-Z][\w&.,'-]{2,40}(?:\s+[A-Z][\w&.,'-]{1,20}){0,2})\s+is\s+(?:hiring|looking|seeking|a|an)",
        r"([A-Z][\w&.,'-]{2,40}(?:\s+[A-Z][\w&.,'-]{1,20}){0,2})\s+(?:Inc\.?|LLC|Ltd\.?|Corp\.?|Co\.?)",
    ]
    for pat in patterns:
        m = _re.search(pat, jd_text[:1500])
        if m:
            name = m.group(1).strip().rstrip('.,;')
            # Filter out generic words
            if name.lower() not in {'the', 'a', 'an', 'we', 'our', 'this', 'you', 'your', 'us'}:
                return name
    return ""

# In-memory analysis cache: keys are MD5(token + job_title + jd_text), values are {"analysis": AnalysisResponse_model_dump, "timestamp": float}
_analysis_cache: dict[str, dict] = {}
_cache_lock = threading.Lock()

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

# In-memory job search TTL cache: keys are (keywords, location, timeframe), values are (timestamp, jobs_list)
_job_search_cache: dict[tuple, tuple] = {}
_job_cache_lock = threading.Lock()
JOB_SEARCH_CACHE_TTL = 300  # 5 minutes

def get_cached_analysis(token: str, job_title: str, jd_text: str) -> Optional[dict]:
    if not jd_text:
        return None
    key_src = f"{token or 'guest'}:{job_title}:{jd_text}"
    key = hashlib.md5(key_src.encode("utf-8")).hexdigest()
    with _cache_lock:
        entry = _analysis_cache.get(key)
        if entry:
            # 1 hour expiration limit
            if time.time() - entry["timestamp"] < 3600:
                return entry["analysis"]
            else:
                _analysis_cache.pop(key, None)
    return None

def set_cached_analysis(token: str, job_title: str, jd_text: str, analysis: dict):
    if not jd_text:
        return
    key_src = f"{token or 'guest'}:{job_title}:{jd_text}"
    key = hashlib.md5(key_src.encode("utf-8")).hexdigest()
    with _cache_lock:
        # FIX #8: opportunistically prune expired entries whenever we write, so the
        # cache doesn't grow unbounded over the life of a long-running process
        # (previously expired entries were only ever removed if someone happened
        # to read that exact key again after expiry).
        now = time.time()
        expired = [k for k, v in _analysis_cache.items() if now - v["timestamp"] >= 3600]
        for k in expired:
            _analysis_cache.pop(k, None)
        _analysis_cache[key] = {
            "analysis": analysis,
            "timestamp": now
        }

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
async def analyze_job(request: JobAnalysisRequest, authorization: Optional[str] = Header(None), x_gemini_api_key: Optional[str] = Header(None)):
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
            async def cached_event_generator():
                yield json.dumps({"type": "log", "message": "⚡ Loaded analysis from local cache!"}) + "\n"
                yield json.dumps({
                    "type": "result",
                    "job_title": request.job_title,
                    "job_description": request.job_description,
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
                    yield json.dumps({"type": "log", "message": "⚡ Loaded analysis from local cache!"}) + "\n"
                    yield json.dumps({
                        "type": "result",
                        "job_title": job_title,
                        "job_description": jd_text,
                        "analysis": cached
                    }) + "\n"
                    return
                
            yield json.dumps({"type": "log", "message": "🤖 Comparing candidate profile & calculating ATS gap analysis..."}) + "\n"
            master_latex = None
            if session_resume_path and session_resume_path.endswith(".tex"):
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
                yield json.dumps({
                    "type": "result",
                    "job_title": job_title,
                    "job_description": jd_text,
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
            company_name = _extract_company_from_jd(jd_text)
            yield json.dumps({
                "type": "result",
                "job_title": job_title,
                "job_description": jd_text,
                "company": company_name,
                "analysis": dumped
            }) + "\n"
        except Exception as e:
            yield json.dumps({"type": "error", "message": str(e)}) + "\n"
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
        with _cache_lock:
            _analysis_cache.clear()
        with _job_cache_lock:
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
        if not session_resume_path:
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
                interactive_mode=not request.direct_mode
            )
            update_task_status(task_id, "completed", "Job application form auto-filled successfully!")
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
    
    # 2. Build a descriptive project name from candidate / role / company
    parts = [_sanitize_filename_part(candidate_name), _sanitize_filename_part(job_title), _sanitize_filename_part(company)]
    parts = [p for p in parts if p]  # drop empty parts
    project_name = " - ".join(parts) + " Resume" if parts else "Resume"
    zip_filename = f"{project_name}.zip"
    print(f"[Overleaf ZIP Export] Project filename: {zip_filename}")

    # 3. Upload to tmpfiles.org
    boundary = f"----WebKitFormBoundary{uuid.uuid4().hex}"
    
    body = []
    body.append(f"--{boundary}".encode('utf-8'))
    body.append(f'Content-Disposition: form-data; name="file"; filename="{zip_filename}"'.encode('utf-8'))
    body.append(b'Content-Type: application/zip')
    body.append(b'')
    body.append(zip_data)
    body.append(f"--{boundary}--".encode('utf-8'))
    
    body_data = b'\r\n'.join(body)
    
    req = urllib.request.Request(
        "https://tmpfiles.org/api/v1/upload",
        data=body_data,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body_data)),
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        },
        method="POST"
    )
    
    # tmpfiles.org serves a certificate that fails strict validation in some
    # environments (weak EE key) even though the connection itself is fine —
    # try the verified context first, and only fall back to an unverified one
    # for this specific known-quirky host if that fails. This request carries
    # no secrets (just the LaTeX zip being uploaded for an Overleaf import
    # link), so the fallback's reduced MITM protection is an acceptable
    # trade-off scoped to this one call site rather than a blanket policy.
    try:
        with urllib.request.urlopen(req, context=SSL_CONTEXT) as response:
            resp_data = json.loads(response.read().decode('utf-8'))
    except URLError as e:
        print(f"[Overleaf ZIP Export] Verified TLS failed for tmpfiles.org ({e}); retrying with an unverified context for this known-quirky host.")
        with urllib.request.urlopen(req, context=ssl._create_unverified_context()) as response:
            resp_data = json.loads(response.read().decode('utf-8'))
        
    if resp_data.get("status") == "success":
        upload_url = resp_data["data"]["url"]
        # Convert to raw download link
        raw_url = upload_url.replace("https://tmpfiles.org/", "https://tmpfiles.org/dl/")
        # snip_name sets the project title inside Overleaf directly (ignores ZIP filename)
        encoded_name = urllib.parse.quote(project_name)
        return f"https://www.overleaf.com/docs?snip_uri={urllib.parse.quote(raw_url)}&snip_name={encoded_name}"
    else:
        raise Exception("Upload to tmpfiles.org failed.")

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
        email = exchange_google_code_for_email(code)
        user = create_or_get_user(email)
        token = create_session(user["id"])
        frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173")
        return RedirectResponse(url=f"{frontend_url}?token={token}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"OAuth verification failed: {str(e)}")

@app.post("/auth/mock")
async def auth_mock(request: dict):
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
    with _job_cache_lock:
        cached_entry = _job_search_cache.get(cache_key)
        if cached_entry:
            cached_ts, cached_jobs = cached_entry
            if time.time() - cached_ts < JOB_SEARCH_CACHE_TTL:
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
                        with _job_cache_lock:
                            _job_search_cache[cache_key] = (time.time(), all_jobs)
                except Exception:
                    pass
                yield chunk
        
        return StreamingResponse(caching_job_stream(), media_type="application/x-ndjson")
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