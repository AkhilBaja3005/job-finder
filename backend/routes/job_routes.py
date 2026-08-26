import os
import json
import time
import uuid
import asyncio
import threading
import traceback
from typing import Optional, List, Dict
from fastapi import APIRouter, HTTPException, Header, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from services.session_store import get_session_data, _user_output_paths
from services.auth import async_get_user_by_token
from services.scraper import scrape_job_description
from services.job_searcher import find_matching_jobs
from services.autofill_agent import autofill_job_application
from services.application_tracker import list_applications, update_application_status, record_application
from utils.ttl_cache import TTLCache

router = APIRouter(tags=["Jobs & Applications"])

# Rate limit tracking
_rate_limits: Dict[str, list] = {}
_rate_limit_lock = threading.Lock()

# Job search TTL cache (5 min)
_job_search_cache = TTLCache(ttl_seconds=300, max_size=500)

# Background task registry for /apply sessions
_task_registry: Dict[str, dict] = {}
_background_tasks: Dict[str, asyncio.Task] = {}
_registry_lock = threading.Lock()


def _check_rate_limit(request: Request, endpoint: str, max_requests: int = 60, window_seconds: int = 60, token: Optional[str] = None):
    client_ip = request.client.host if request.client else "unknown"
    if client_ip in ("127.0.0.1", "localhost", "::1"):
        return  # Exclude local client / Chrome extension calls from restrictive rate limits
    key = f"{endpoint}:{token or client_ip}"
    now = time.time()
    with _rate_limit_lock:
        timestamps = _rate_limits.get(key, [])
        timestamps = [t for t in timestamps if now - t < window_seconds]
        if len(timestamps) >= max_requests:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded for {endpoint}. Try again in a few moments."
            )
        timestamps.append(now)
        _rate_limits[key] = timestamps


def update_task_status(task_id: str, status: str, message: str):
    with _registry_lock:
        _task_registry[task_id] = {
            "status": status,
            "message": message,
            "timestamp": time.time()
        }


@router.get("/extension_version_hash")
def get_extension_version_hash():
    import hashlib
    ext_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "extension"))
    h = hashlib.md5()
    if os.path.exists(ext_dir):
        for root, _, files in sorted(os.walk(ext_dir)):
            for f in sorted(files):
                if not f.startswith(".") and not f.endswith((".pyc", ".swp", "~")):
                    fp = os.path.join(root, f)
                    try:
                        h.update(f"{f}:{os.path.getmtime(fp)}".encode())
                    except OSError:
                        pass
    return {"hash": h.hexdigest()}


def _extract_company_from_jd(jd_text: str, page_url: Optional[str] = None) -> str:
    import re
    if page_url:
        cleaned_url = page_url.split("?")[0].rstrip("/")
        m = re.search(r'https?://(?:www\.)?([^/]+)\.com/([^/]+)', cleaned_url)
        if m:
            domain, path_first = m.group(1).lower(), m.group(2).lower()
            if domain in ["linkedin", "indeed", "glassdoor", "ziprecruiter"]:
                if path_first not in ["jobs", "view", "job", "rc", "m"]:
                    return path_first.replace("-", " ").title()
            elif domain in ["greenhouse", "ashbyhq", "lever", "smartrecruiters", "workday"]:
                return path_first.replace("-", " ").title()
            else:
                return domain.replace("-", " ").title()

    if jd_text:
        match = re.search(r'(?:about|at|join)\s+([A-Z][A-Za-z0-9\s&.,-]{2,30}?)(?:\s+(?:is|are|we|team|to|for|where|who|\.|\n|,))', jd_text)
        if match:
            candidate = match.group(1).strip()
            if candidate.lower() not in ["the", "this", "our", "a", "an"]:
                return candidate
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic Schemas
# ─────────────────────────────────────────────────────────────────────────────
class ScrapeRequest(BaseModel):
    url: str


class SearchJobsRequest(BaseModel):
    location: Optional[str] = "Remote"
    keywords: Optional[str] = None
    timeframe: Optional[str] = "48h"


class ExtensionParseJobRequest(BaseModel):
    page_text: Optional[str] = None
    page_url: Optional[str] = None
    page_title: Optional[str] = None


class ScanPortalsRequest(BaseModel):
    keywords: Optional[List[str]] = None
    min_ats_score: Optional[int] = 70


class ApplyRequest(BaseModel):
    job_url: str
    job_title: Optional[str] = None
    company: Optional[str] = None
    direct_mode: Optional[bool] = False


class UpdateStatusRequest(BaseModel):
    job_url: str
    status: str


# ─────────────────────────────────────────────────────────────────────────────
# Job Discovery & Scraping Routes
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/scrape_job")
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


@router.post("/search_matching_jobs")
async def search_matching_jobs(request: SearchJobsRequest, http_request: Request, authorization: Optional[str] = Header(None), x_gemini_api_key: Optional[str] = Header(None)):
    _check_rate_limit(http_request, "search_matching_jobs", max_requests=5, window_seconds=300)
    token = authorization.split(" ")[1] if authorization and authorization.startswith("Bearer ") else None

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
        async def caching_job_stream():
            q: asyncio.Queue = asyncio.Queue()
            all_jobs = []
            search_done = False

            async def _producer():
                nonlocal all_jobs, search_done
                try:
                    async for chunk in find_matching_jobs(
                        resume_data=session_resume_data,
                        location=request.location or "",
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
                    await q.put(None)

            async def _keepalive():
                while not search_done:
                    await asyncio.sleep(10)
                    if not search_done:
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
                producer_task.cancel()
                keepalive_task.cancel()

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


@router.post("/extension/parse_job_details")
async def parse_job_details_endpoint(request: ExtensionParseJobRequest):
    """Extract exact Company, Job Title & full JD for Chrome Extension popup."""
    title = request.page_title or ""
    company = ""
    description = request.page_text or ""

    if not description and request.page_url and ("linkedin.com/jobs" in request.page_url or "indeed.com" in request.page_url):
        try:
            scraped = await scrape_job_description(request.page_url)
            if scraped and scraped.get("description"):
                if scraped.get("title") and scraped.get("title") not in ["LinkedIn Job", "Indeed Job"]:
                    title = scraped.get("title")
                if scraped.get("company"):
                    company = scraped.get("company")
                if scraped.get("description") and len(scraped.get("description")) > 100:
                    description = scraped.get("description")
        except Exception as e:
            print(f"[/extension/parse_job_details] Scraper enrichment error: {e}")

    if not company and request.page_url:
        company = await asyncio.to_thread(_extract_company_from_jd, description, request.page_url)
    if not company and description:
        company = await asyncio.to_thread(_extract_company_from_jd, description, None)

    invalid_titles = {"sign in", "log in", "login", "register", "apply now", "menu", "search", "indeed", "linkedin", "apple"}
    if title.lower() in invalid_titles or not title.strip():
        if request.page_url and "indeed.com" in request.page_url:
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


@router.post("/portals/scan")
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


# ─────────────────────────────────────────────────────────────────────────────
# Applications & Automation
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/applications")
async def get_applications(authorization: Optional[str] = Header(None)):
    token = authorization.split(" ")[1] if authorization and authorization.startswith("Bearer ") else None
    return {"applications": await asyncio.to_thread(list_applications, token)}


@router.post("/update_application_status")
async def update_status_endpoint(request: UpdateStatusRequest, authorization: Optional[str] = Header(None)):
    token = authorization.split(" ")[1] if authorization and authorization.startswith("Bearer ") else None
    success = await asyncio.to_thread(update_application_status, token, request.job_url, request.status)
    return {"status": "success" if success else "not_found"}


@router.post("/apply")
async def apply(request: ApplyRequest, http_request: Request, authorization: Optional[str] = Header(None), x_gemini_api_key: Optional[str] = Header(None)):
    _check_rate_limit(http_request, "apply", max_requests=5, window_seconds=300)
    token = authorization.split(" ")[1] if authorization and authorization.startswith("Bearer ") else None

    session = get_session_data(token)
    session_resume_data = session.get("data")
    session_resume_path = session.get("path")

    _, pdf_path = _user_output_paths(token)
    if not os.path.exists(pdf_path):
        if not session_resume_path or not os.path.exists(session_resume_path):
            raise HTTPException(status_code=400, detail="No resume available to upload.")
        pdf_path = session_resume_path

    if not session_resume_data:
        raise HTTPException(status_code=400, detail="Please upload a resume first or sync your profile from the web app.")

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
                    "status": "applied" if request.direct_mode else "autofilled",
                })
            except Exception as hist_err:
                print(f"[apply] Failed to record application history: {hist_err}")
        except Exception as ex:
            update_task_status(task_id, "failed", f"Autofill error: {str(ex)}")
        finally:
            _background_tasks.pop(task_id, None)

    try:
        task = asyncio.create_task(run_autofill_wrapper())
        _background_tasks[task_id] = task
        return {"status": "success", "task_id": task_id, "message": "Autofill session started in separate browser window."}
    except Exception as e:
        traceback.print_exc()
        update_task_status(task_id, "failed", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/apply/status/{task_id}")
async def apply_status(task_id: str):
    MAX_STREAM_SECONDS = 1800

    async def status_stream():
        last_message = ""
        start = time.time()
        while True:
            if time.time() - start > MAX_STREAM_SECONDS:
                yield json.dumps({"status": "timeout", "message": "Stopped watching after 30 minutes."}) + "\n"
                break

            with _registry_lock:
                entry = _task_registry.get(task_id)
            if not entry:
                yield json.dumps({"status": "unknown", "message": "Task not found."}) + "\n"
                break

            if entry["message"] != last_message:
                yield json.dumps({"status": entry["status"], "message": entry["message"]}) + "\n"
                last_message = entry["message"]

            if entry["status"] in ["completed", "failed"]:
                break

            await asyncio.sleep(0.5)

    return StreamingResponse(
        status_stream(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )
