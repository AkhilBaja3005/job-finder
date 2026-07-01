import os
import shutil
import json
import subprocess
import re
import io
import zipfile
import urllib.request
import urllib.parse
import uuid
import ssl
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel
from typing import List, Optional
from dotenv import load_dotenv
load_dotenv()
from pypdf import PdfReader

from services.resume_parser import parse_resume
from services.scraper import scrape_job_description
from services.llm_agent import analyze_job_fit, review_tailored_resume, tailor_latex_code
from services.resume_generator import generate_pdf_resume
from services.autofill_agent import autofill_job_application
from services.auth import (
    create_or_get_user,
    create_session,
    get_user_by_token,
    update_user_api_key,
    get_google_auth_url,
    exchange_google_code_for_email
)
from utils.latex_utils import extract_latex_command, apply_latex_hotfix, generate_latex_from_json

app = FastAPI(title="AI Job Finder Agent API")

# Enable CORS for React Frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Use absolute paths to prevent working directory shifts on Render container startup
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Ensure resume.cls is available in uploads directory for compilation/zipping
# We copy it from the static backend/assets folder which is tracked in Git.
default_cls_source = os.path.join(BASE_DIR, "assets", "resume.cls")
target_cls_path = os.path.join(UPLOAD_DIR, "resume.cls")
if os.path.exists(default_cls_source):
    import shutil
    shutil.copy2(default_cls_source, target_cls_path)
    print(f"Synced fallback resume.cls from {default_cls_source} to {target_cls_path}")

import threading

# Session-scoped state storage: maps session_token -> {"data": resume_data_dict, "path": master_resume_path_str}
_session_store: dict[str, dict] = {}
_store_lock = threading.Lock()

RESUME_STATE_FILE = os.path.join(OUTPUT_DIR, "resume_state.json")

# Helpers to manage state safely
from services.auth import update_user_resume_data

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
    uploaded_files = glob.glob(os.path.join(UPLOAD_DIR, "*.tex")) or \
                     glob.glob(os.path.join(UPLOAD_DIR, "*.pdf")) or \
                     glob.glob(os.path.join(UPLOAD_DIR, "*.docx")) or \
                     glob.glob(os.path.join(UPLOAD_DIR, "*"))
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
        file_path = os.path.join(UPLOAD_DIR, file.filename)
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
        raise HTTPException(status_code=500, detail=str(e))

def compile_and_check_page_metrics(latex_code: str, spacing_scale: float = 1.0, linespread: float = 1.0, master_latex: Optional[str] = None) -> tuple[int, float]:
    try:
        temp_tex = os.path.join(OUTPUT_DIR, "temp_check.tex")
        temp_pdf = os.path.join(OUTPUT_DIR, "temp_check.pdf")
        
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

import time
import hashlib

# In-memory analysis cache: keys are MD5(token + job_title + jd_text), values are {"analysis": AnalysisResponse_model_dump, "timestamp": float}
_analysis_cache: dict[str, dict] = {}
_cache_lock = threading.Lock()

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
        _analysis_cache[key] = {
            "analysis": analysis,
            "timestamp": time.time()
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
                
            t0 = time.time()
            analysis = await analyze_job_fit(session_resume_data, job_title, jd_text, master_latex if not request.skip_tailoring else None, active_api_key)
            ctx.log_step("analyze_job_fit", time.time() - t0, "gemini-3.1-flash-lite")
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
                
                while reviewer_attempts < 3:
                    yield json.dumps({"type": "log", "message": f"👀 Recruiter review check (Attempt {reviewer_attempts + 1})..."}) + "\n"
                    t0 = time.time()
                    review = review_tailored_resume(analysis.latex_code, session_resume_data, job_title, jd_text, active_api_key)
                    ctx.log_step(f"recruiter_review_check_attempt_{reviewer_attempts+1}", time.time() - t0, "gemini-3.1-flash-lite")
    
                    if review.satisfied:
                        yield json.dumps({"type": "log", "message": "✅ Recruiter review approved!"}) + "\n"
                        break
    
                    last_rejection_feedback = review.feedback
                    yield json.dumps({"type": "log", "message": f"⚠️ Recruiter rejected (Attempt {reviewer_attempts + 1}): {review.feedback}"}) + "\n"
                    t0 = time.time()
                    analysis.latex_code = tailor_latex_code(
                        master_latex, job_title, jd_text, suggestions, missing_skills, active_api_key, review.feedback
                    )
                    ctx.log_step(f"tailor_latex_retry_attempt_{reviewer_attempts+1}", time.time() - t0, "gemini-3.5-flash")
                    
                    curr_hash = hashlib.md5(analysis.latex_code.encode("utf-8")).hexdigest()
                    if curr_hash == prev_review_hash:
                        yield json.dumps({"type": "log", "message": "⚠️ AI reviewer feedback generated identical LaTeX output. Breaking reviewer loop."}) + "\n"
                        break
                    prev_review_hash = curr_hash
                    reviewer_attempts += 1

                if not review.satisfied and reviewer_attempts >= 3:
                    if not request.force_tailoring:
                        yield json.dumps({
                            "type": "rejection_warning", 
                            "message": f"Candidate may not be a suitable fit for this job after 3 recruitment checks. Reason: {last_rejection_feedback}"
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
                pages, filled_height = compile_and_check_page_metrics(analysis.latex_code, 1.0, 1.0, master_latex)
                ctx.log_step("compile_pdf_check_metrics", time.time() - t0, "Tectonic")
    
                optimal_scale = 1.0
                optimal_linespread = 1.0
    
                # P0: mechanical shrinking first before LLM condense
                if pages > 1:
                    yield json.dumps({"type": "log", "message": "📐 Page overflow. Trying quick mechanical spacing adjustments..."}) + "\n"
                    # Try decreasing linespread to fit page
                    for ls in [0.95, 0.91, 0.88]:
                        p, h = compile_and_check_page_metrics(analysis.latex_code, 1.0, ls, master_latex)
                        if p == 1:
                            pages = p
                            filled_height = h
                            optimal_linespread = ls
                            yield json.dumps({"type": "log", "message": f"✅ Mechanical shrink successful (linespread={ls} fits 1 page!)"}) + "\n"
                            break
    
                # If still over budget, try scale adjustments
                if pages > 1:
                    for scale in [0.8, 0.6, 0.5]:
                        p, h = compile_and_check_page_metrics(analysis.latex_code, scale, optimal_linespread, master_latex)
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
                    
                    analysis.latex_code = tailor_latex_code(
                        master_latex, job_title, jd_text, suggestions, missing_skills, active_api_key, condense_feedback
                    )
                    
                    curr_hash = hashlib.md5(analysis.latex_code.encode("utf-8")).hexdigest()
                    if curr_hash == prev_latex_hash:
                        yield json.dumps({"type": "log", "message": "⚠️ AI tailorer returned identical code. Escaping retry loop."}) + "\n"
                        break
                    prev_latex_hash = curr_hash
                    
                    # Recheck with scale and current linespread
                    pages, filled_height = compile_and_check_page_metrics(analysis.latex_code, optimal_scale, optimal_linespread, master_latex)
                    
                    # Try mechanical spacing again on the condensed content
                    if pages > 1:
                        for ls in [0.95, 0.91, 0.88]:
                            p, h = compile_and_check_page_metrics(analysis.latex_code, optimal_scale, ls, master_latex)
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
                        p, h = compile_and_check_page_metrics(analysis.latex_code, 1.0, lspread, master_latex)
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
            yield json.dumps({
                "type": "result",
                "job_title": job_title,
                "job_description": jd_text,
                "analysis": dumped
            }) + "\n"
        except Exception as e:
            yield json.dumps({"type": "error", "message": str(e)}) + "\n"
    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.post("/generate_tailored_resume")
async def generate_tailored_resume(tailored_data: dict):
    try:
        output_pdf = os.path.join(OUTPUT_DIR, "tailored_resume.pdf")
        await generate_pdf_resume(tailored_data, output_pdf)
        return FileResponse(output_pdf, media_type="application/pdf", filename="tailored_resume.pdf")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Helper functions and requests imported from utils.latex_utils or defined inline below

class LatexDownloadRequest(BaseModel):
    latex_code: str

@app.post("/download_latex")
async def download_latex(request: LatexDownloadRequest):
    try:
        tex_path = os.path.join(OUTPUT_DIR, "tailored_resume.tex")
        fixed_code = apply_latex_hotfix(request.latex_code)
        with open(tex_path, "w") as f:
            f.write(fixed_code)
        return FileResponse(tex_path, media_type="text/plain", filename="resume.tex")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class CompileLatexRequest(BaseModel):
    latex_code: str

@app.post("/compile_latex")
async def compile_latex(request: CompileLatexRequest):
    try:
        tex_path = os.path.join(OUTPUT_DIR, "tailored_resume.tex")
        pdf_path = os.path.join(OUTPUT_DIR, "tailored_resume.pdf")
        
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
        result = subprocess.run(
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
        raise HTTPException(status_code=500, detail=str(e))

# Background task status registry maps task_id -> {"status": str, "message": str}
_task_registry: dict[str, dict] = {}
_registry_lock = threading.Lock()

def update_task_status(task_id: str, status: str, message: str):
    with _registry_lock:
        _task_registry[task_id] = {
            "status": status,
            "message": message,
            "timestamp": time.time()
        }

@app.post("/apply")
async def apply(request: ApplyRequest, authorization: Optional[str] = Header(None)):
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]
        
    session = get_session_data(token)
    session_resume_data = session.get("data")
    session_resume_path = session.get("path")
    
    pdf_path = os.path.join(OUTPUT_DIR, "tailored_resume.pdf")
    if not os.path.exists(pdf_path):
        # Fallback to master if tailored hasn't been generated
        if not session_resume_path:
            raise HTTPException(status_code=400, detail="No resume available to upload.")
        pdf_path = session_resume_path

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

    try:
        # Run autofill in the background task
        import asyncio
        asyncio.create_task(run_autofill_wrapper())
        
        return {"status": "success", "task_id": task_id, "message": "Autofill session started in separate browser window."}
    except Exception as e:
        update_task_status(task_id, "failed", str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/apply/status/{task_id}")
async def apply_status(task_id: str):
    async def status_stream():
        last_message = ""
        while True:
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

def upload_zip_to_tmpfiles(latex_code: str) -> str:
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
    
    # 2. Upload to tmpfiles.org
    boundary = f"----WebKitFormBoundary{uuid.uuid4().hex}"
    
    body = []
    body.append(f"--{boundary}".encode('utf-8'))
    body.append(f'Content-Disposition: form-data; name="file"; filename="project.zip"'.encode('utf-8'))
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
    
    context = ssl._create_unverified_context()
    with urllib.request.urlopen(req, context=context) as response:
        resp_data = json.loads(response.read().decode('utf-8'))
        
    if resp_data.get("status") == "success":
        upload_url = resp_data["data"]["url"]
        # Convert to raw download link
        raw_url = upload_url.replace("https://tmpfiles.org/", "https://tmpfiles.org/dl/")
        return f"https://www.overleaf.com/docs?snip_uri={urllib.parse.quote(raw_url)}"
    else:
        raise Exception("Upload to tmpfiles.org failed.")

class OverleafRequest(BaseModel):
    latex_code: str

@app.post("/open_in_overleaf")
async def open_in_overleaf(request: OverleafRequest):
    try:
        url = upload_zip_to_tmpfiles(request.latex_code)
        return {"url": url}
    except Exception as e:
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
async def scrape_job(request: ScrapeRequest):
    try:
        scraped = await scrape_job_description(request.url)
        return {
            "status": "success",
            "title": scraped.get("title", ""),
            "description": scraped.get("description", "")
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Mount static files for hosting the built frontend as part of the same service
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse

frontend_dist = os.path.abspath(os.path.join(os.path.dirname(__file__), "../frontend/dist"))
if os.path.exists(frontend_dist):
    app.mount("/assets", StaticFiles(directory=os.path.join(frontend_dist, "assets")), name="assets")

    @app.get("/{rest_of_path:path}", response_class=HTMLResponse)
    async def serve_frontend(rest_of_path: str):
        # Ignore API endpoints so they pass through to regular routes
        if rest_of_path.startswith(("user/", "auth/", "scrape_job", "upload_resume", "apply", "assets/", "analyze_job", "download_latex", "compile_latex", "generate_tailored_resume", "open_in_overleaf")):
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
    import uvicorn
    # Bind to PORT env variable specified by Render
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
