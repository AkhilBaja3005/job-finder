import os
import re
import json
import time
import uuid
import shutil
import asyncio
import subprocess
import traceback
from typing import Optional, List, Dict
from fastapi import APIRouter, HTTPException, Header, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from services.session_store import (
    BASE_DIR,
    UPLOAD_DIR,
    OUTPUT_DIR,
    _safe_key,
    _get_user_storage_dirs,
    _user_output_paths,
    get_session_data,
    LLMClientLogQueue,
    _stream_task_logs,
    _drain_remaining_logs
)
from services.auth import async_get_user_by_token
from services.scraper import scrape_job_description
from services.llm_agent import analyze_job_fit, tailor_latex_code as tailor_resume
from utils.latex_utils import generate_latex_from_json, apply_latex_hotfix, compile_and_check_page_metrics
from services.overleaf import upload_zip_to_tmpfiles
from services.application_tracker import record_application
from services.recruiter_extractor import extract_recruiter
from services.outreach_generator import generate_outreach_message
from services.cron_scheduler import process_and_send_user_digest
from routes.job_routes import _extract_company_from_jd, _check_rate_limit

router = APIRouter(tags=["AI & Tailoring"])

# Local In-Memory Analysis Cache
_analysis_cache: Dict[str, dict] = {}


def _get_analysis_cache_key(token: Optional[str], job_title: str, jd_text: str) -> str:
    user_part = token or "guest"
    jt = (job_title or "").strip().lower()
    jd = (jd_text or "").strip()[:500].lower()
    return f"{user_part}:{jt}:{hash(jd)}"


def get_cached_analysis(token: Optional[str], job_title: str, jd_text: str) -> Optional[dict]:
    key = _get_analysis_cache_key(token, job_title, jd_text)
    return _analysis_cache.get(key)


def set_cached_analysis(token: Optional[str], job_title: str, jd_text: str, data: dict):
    key = _get_analysis_cache_key(token, job_title, jd_text)
    _analysis_cache[key] = data


def clear_user_cached_analysis(token: Optional[str]):
    user_part = token or "guest"
    keys_to_del = [k for k in _analysis_cache if k.startswith(f"{user_part}:")]
    for k in keys_to_del:
        del _analysis_cache[k]


class RunContext:
    def __init__(self, user_token: Optional[str], job_title: Optional[str]):
        self.run_id = uuid.uuid4().hex[:8]
        self.user = user_token or "guest"
        self.job = job_title or "Unknown"
        self.start_time = time.time()

    def log_step(self, step_name: str, duration_sec: float, model: Optional[str] = None):
        elapsed = round(time.time() - self.start_time, 3)
        data = {
            "run_id": self.run_id,
            "user": self.user,
            "job": self.job,
            "step": step_name,
            "latency_sec": round(duration_sec, 3),
            "model": model,
            "elapsed_total": elapsed
        }
        print(f"[TRACE] {json.dumps(data)}")


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic Schemas
# ─────────────────────────────────────────────────────────────────────────────
class JobAnalysisRequest(BaseModel):
    job_description: Optional[str] = None
    job_url: Optional[str] = None
    job_title: Optional[str] = None
    company: Optional[str] = None
    skip_tailoring: Optional[bool] = False
    force_tailoring: Optional[bool] = False
    send_email: Optional[bool] = False
    source_mode: Optional[str] = "website"
    user_selected_skills: Optional[List[str]] = None


class TailorResumeRequest(BaseModel):
    job_title: str
    job_description: str
    missing_skills: Optional[List[str]] = []
    company_name: Optional[str] = "Company"


class InterviewPrepRequest(BaseModel):
    job_title: str
    company: str
    job_url: Optional[str] = None


class CoverLetterHistoryRequest(BaseModel):
    job_title: str
    company: str
    job_url: Optional[str] = None


class GenerateOutreachRequest(BaseModel):
    job_url: Optional[str] = None
    job_title: Optional[str] = None
    company_name: Optional[str] = None
    job_description: Optional[str] = None
    recruiter_name: Optional[str] = None
    platform: Optional[str] = None


class OutreachRequest(BaseModel):
    job_description: str
    job_title: Optional[str] = "Target Role"
    company_name: Optional[str] = "Company"
    recruiter_name: Optional[str] = None
    recruiter_email: Optional[str] = None
    send_email: Optional[bool] = False


class SendOutreachEmailRequest(BaseModel):
    recipient_email: str
    subject: str
    body: str
    resume_path: Optional[str] = None


class SendApplicationPdfEmailRequest(BaseModel):
    pdf_url: str
    job_title: Optional[str] = "Role"
    company: Optional[str] = "Company"
    score: Optional[int] = None
    overleaf_url: Optional[str] = None
    job_url: Optional[str] = None


class AnswerQuestionRequest(BaseModel):
    question: str
    company_name: Optional[str] = None
    job_title: Optional[str] = None
    job_description: Optional[str] = None
    candidate_profile: Optional[dict] = None


class SolveFieldRequest(BaseModel):
    field_name: str
    field_type: Optional[str] = "text"
    options: Optional[List[str]] = None
    context: Optional[str] = None
    api_key: Optional[str] = None


class GeneratePromptQueryRequest(BaseModel):
    suggestion: str


# ─────────────────────────────────────────────────────────────────────────────
# AI Analysis & Tailoring Endpoints
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/analyze_job")
async def analyze_job(request: JobAnalysisRequest, http_request: Request, authorization: Optional[str] = Header(None), x_gemini_api_key: Optional[str] = Header(None)):
    _check_rate_limit(http_request, "analyze_job", max_requests=10, window_seconds=300)
    token = authorization.split(" ")[1] if authorization and authorization.startswith("Bearer ") else None

    session = get_session_data(token)
    session_resume_data = session.get("data")
    session_resume_path = session.get("path")

    if not session_resume_data:
        raise HTTPException(status_code=400, detail="Please upload a resume first.")

    # Cache hit check
    if request.job_description and not request.force_tailoring:
        cached = get_cached_analysis(token, request.job_title, request.job_description)
        if cached:
            if request.skip_tailoring:
                cached = dict(cached)
                cached["latex_code"] = ""
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
                yield json.dumps({"type": "log", "percent": 15, "message": "🤖 Launching browser to scrape job link..."}) + "\n"
                t0 = time.time()
                scraped = await scrape_job_description(request.job_url)
                jd_text = scraped["description"]
                job_title = scraped["title"]

                _bot_block_phrases = ["cloudflare security verification", "anti-bot challenge", "verify you are human"]
                if scraped.get("is_bot_blocked") or any(p in jd_text.lower() for p in _bot_block_phrases):
                    yield json.dumps({"type": "log", "percent": 100, "message": "⚠️ Security challenge detected on job page."}) + "\n"
                    yield json.dumps({
                        "type": "error",
                        "message": "The job posting URL returned an anti-bot challenge page. Please paste the raw job description text directly."
                    }) + "\n"
                    return

                ctx.log_step("scrape_job", time.time() - t0)
                yield json.dumps({"type": "log", "percent": 20, "message": f"✅ Scraped job details for: {job_title}"}) + "\n"
                yield json.dumps({"type": "scraped_data", "job_title": job_title, "job_description": jd_text}) + "\n"

            yield json.dumps({"type": "log", "percent": 40, "message": "🤖 Calculating ATS fit score & career-ops analysis..."}) + "\n"

            master_latex = None
            if session_resume_path and session_resume_path.endswith(".tex") and os.path.exists(session_resume_path):
                with open(session_resume_path, "r", encoding="utf-8") as f:
                    master_latex = f.read()
            else:
                master_latex = generate_latex_from_json(session_resume_data)

            def log_callback(msg_json: str):
                try:
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

            async for event in _stream_task_logs(fit_task):
                yield event

            analysis = await fit_task
            ctx.log_step("analyze_job_fit", time.time() - t0, "gemini-3.1-flash-lite")

            for event in _drain_remaining_logs():
                yield event

            yield json.dumps({"type": "log", "percent": 75, "message": "✍️ Generated tailored resume content and cover letter."}) + "\n"

            if request.skip_tailoring:
                dumped = analysis.model_dump()
                company_name = await asyncio.to_thread(_extract_company_from_jd, jd_text, request.job_url)
                yield json.dumps({
                    "type": "result",
                    "percent": 100,
                    "fit_score": dumped.get("match_analysis", {}).get("overall_score"),
                    "job_title": job_title,
                    "job_description": jd_text,
                    "company": company_name,
                    "analysis": dumped
                }) + "\n"
                set_cached_analysis(token, job_title, jd_text, dumped)
                return

            yield json.dumps({"type": "log", "percent": 85, "message": "⚙️ Compiling tailored LaTeX resume to PDF..."}) + "\n"
            t0 = time.time()

            raw_tailored_latex = analysis.latex_code
            safe_key = _safe_key(token)
            user_up_dir, user_out_dir = _get_user_storage_dirs(safe_key)
            tex_path = os.path.join(user_out_dir, f"tailored_resume_{safe_key}.tex")
            temp_pdf_path = os.path.join(user_out_dir, f"tailored_resume_{safe_key}.pdf")

            cls_source = os.path.join(UPLOAD_DIR, "resume.cls")
            if not os.path.exists(cls_source):
                cls_source = os.path.join(BASE_DIR, "assets", "resume.cls")
            if os.path.exists(cls_source):
                shutil.copy2(cls_source, os.path.join(user_out_dir, "resume.cls"))

            pages, _ = await asyncio.to_thread(compile_and_check_page_metrics, raw_tailored_latex, 1.0, 1.0, None)
            opt_scale, opt_ls = 1.0, 1.0
            if pages > 1:
                for ls in [0.95, 0.91, 0.88, 0.82, 0.78]:
                    p, _ = await asyncio.to_thread(compile_and_check_page_metrics, raw_tailored_latex, 1.0, ls, None)
                    if p == 1:
                        opt_ls = ls
                        break

            final_latex = apply_latex_hotfix(raw_tailored_latex, opt_scale, opt_ls, None)
            with open(tex_path, "w", encoding="utf-8") as f:
                f.write(final_latex)

            proc = await asyncio.to_thread(
                subprocess.run,
                ["tectonic", tex_path, "--outdir", user_out_dir],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
            if proc.returncode != 0:
                print(f"[analyze_job] Tectonic compilation failed: {proc.stderr}")

            ctx.log_step("compile_pdf", time.time() - t0)

            candidate_name = session_resume_data.get("name", "") if isinstance(session_resume_data, dict) else ""
            extracted_company = request.company if (request.company and request.company not in ['Target Company', 'Hiring Company']) else await asyncio.to_thread(_extract_company_from_jd, jd_text, request.job_url)

            overleaf_url = None
            try:
                overleaf_url = await asyncio.to_thread(upload_zip_to_tmpfiles, final_latex, candidate_name, job_title, extracted_company)
            except Exception as e:
                print(f"[analyze_job] Overleaf upload warning: {e}")

            pdf_download_url = f"/download_application_pdf/{safe_key}/{os.path.basename(temp_pdf_path)}" if os.path.exists(temp_pdf_path) else None

            dumped = analysis.model_dump()
            dumped["latex_code"] = final_latex
            dumped["overleaf_url"] = overleaf_url
            dumped["download_pdf_url"] = pdf_download_url

            set_cached_analysis(token, job_title, jd_text, dumped)

            yield json.dumps({
                "type": "result",
                "percent": 100,
                "fit_score": dumped.get("match_analysis", {}).get("overall_score"),
                "job_title": job_title,
                "job_description": jd_text,
                "company": extracted_company,
                "analysis": dumped,
                "overleaf_url": overleaf_url,
                "download_pdf_url": pdf_download_url
            }) + "\n"

        except Exception as e:
            traceback.print_exc()
            yield json.dumps({"type": "error", "message": str(e)}) + "\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/generate_tailored_resume")
async def generate_tailored_resume(request: TailorResumeRequest, authorization: Optional[str] = Header(None)):
    token = authorization.split(" ")[1] if authorization and authorization.startswith("Bearer ") else None
    session = get_session_data(token)
    session_resume_data = session.get("data")
    if not session_resume_data:
        raise HTTPException(status_code=400, detail="Please upload a resume first.")

    try:
        raw_tailored_latex = await asyncio.to_thread(
            tailor_resume,
            session_resume_data,
            request.job_description,
            request.job_title,
            request.missing_skills
        )
        return {"status": "success", "latex_code": raw_tailored_latex}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/generate_cover_letter_history")
async def generate_cover_letter_history(request: CoverLetterHistoryRequest, authorization: Optional[str] = Header(None)):
    token = authorization.split(" ")[1] if authorization and authorization.startswith("Bearer ") else "guest"
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
3. STRICTLY NO CLICHES or generic filler phrases.
4. Active, confident voice. Focus on problem-solving accomplishments from candidate's profile.
5. Return ONLY the raw cover letter text."""

    from services.gemini_client import generate_content_with_fallback
    try:
        cover_letter = await asyncio.to_thread(generate_content_with_fallback, prompt, model_tier="lite")
        return {"status": "success", "cover_letter": cover_letter.strip()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/generate_interview_prep")
async def generate_interview_prep(request: InterviewPrepRequest, authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = authorization.split(" ")[1]

    session = get_session_data(token)
    resume = session.get("data")
    if not resume:
        raise HTTPException(status_code=400, detail="No resume uploaded yet. Upload a resume first.")

    jd_text = ""
    if request.job_url:
        try:
            scraped = await scrape_job_description(request.job_url)
            jd_text = scraped.get("description", "")
        except Exception:
            pass

    prompt = f"""You are a professional Interview Coach.
Help the candidate prepare for an upcoming interview.

CANDIDATE PROFILE:
{json.dumps(resume, indent=2)}

TARGET POSITION:
Role: {request.job_title}
Company: {request.company}
Job Description context: {jd_text[:1200] if jd_text else "Not provided"}

Output a complete Markdown Interview Preparation Pack following these sections:
1. **Behavioral STAR Q&A:** Formulate 3-4 custom STAR stories mapping candidate's experience to likely questions.
2. **Technical Review Checklist:** List 5 key topics or tools mentioned in the job context.
3. **Common Tough Questions:** Specific answers for 'Why this company?' and how to address gaps.
4. **Smart Questions to Ask Them:** List 3-4 engaging questions for the interviewer.

Do NOT add conversational intro/outro. Output ONLY the raw Markdown."""

    from services.gemini_client import generate_content_with_fallback
    try:
        result_text = await asyncio.to_thread(generate_content_with_fallback, prompt, model_tier="lite")
        return {"status": "success", "markdown": result_text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/generate_outreach")
async def generate_outreach(request: GenerateOutreachRequest, authorization: Optional[str] = Header(None), x_gemini_api_key: Optional[str] = Header(None)):
    token = authorization.split(" ")[1] if authorization and authorization.startswith("Bearer ") else None
    try:
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

        recruiter_info = {
            "recruiter_name": request.recruiter_name,
            "recruiter_profile_url": None,
            "company_name": request.company_name,
            "platform": request.platform or "unknown"
        }

        if request.job_url:
            recruiter_info = await extract_recruiter(request.job_url, request.platform)
            if not recruiter_info.get("company_name"):
                recruiter_info["company_name"] = request.company_name

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

        outreach_msg = await asyncio.to_thread(
            generate_outreach_message,
            job_description=request.job_description,
            resume_data=session_resume_data,
            ats_analysis=ats_analysis,
            recruiter_name=recruiter_info.get("recruiter_name"),
            company_name=recruiter_info.get("company_name", request.company_name),
            custom_api_key=active_api_key
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


@router.post("/generate_recruiter_outreach")
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


@router.post("/answer_question")
async def answer_question(request: AnswerQuestionRequest, authorization: Optional[str] = Header(None), x_gemini_api_key: Optional[str] = Header(None)):
    """Generate high-impact, personalized screening question answers using LLM and candidate resume."""
    token = authorization.split(" ")[1] if authorization and authorization.startswith("Bearer ") else None

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

    q_lower = request.question.lower()
    if "notice" in q_lower or "how soon" in q_lower or "start date" in q_lower:
        return {"status": "success", "answer": "Available immediately (2 weeks notice)."}
    if "hear about" in q_lower or "source" in q_lower or "referred" in q_lower:
        return {"status": "success", "answer": "LinkedIn"}
    if "salary" in q_lower or "compensation" in q_lower or "expectation" in q_lower:
        return {"status": "success", "answer": "Competitive market rate / Open to discuss based on role scope."}

    skills_list = session_resume_data.get("skills", [])
    if isinstance(skills_list, dict):
        skills_str = ", ".join([str(s) for sub in skills_list.values() for s in (sub if isinstance(sub, list) else [sub])][:8])
    elif isinstance(skills_list, list):
        skills_str = ", ".join([str(s) for s in skills_list[:8]])
    else:
        skills_str = "GenAI, LLM Systems, Python, Distributed Systems, Machine Learning"

    prompt = f"""You are answering an application screening question for a candidate.

Candidate Profile:
Name: {session_resume_data.get('name', 'Akhil Baja')}
Skills: {skills_str}
Key Experience: {json.dumps(session_resume_data.get('work_experience', session_resume_data.get('experience', []))[:2], indent=2)}

Company: {request.company_name or 'Granola'}
Target Role: {request.job_title or 'AI Engineer'}
Question: "{request.question}"

CRITICAL INSTRUCTIONS:
1. Answer ONLY what the question asks. DO NOT write a cover letter.
2. If asked for 'one line' or 'super-condensed cover letter', provide EXACTLY 1 concise, powerful sentence (max 25 words).
3. If asked 'Why [Company]' or '5 sentences or less', write 3-4 clear, impactful sentences explaining direct alignment with their product/mission.
4. Sound natural, confident, and authentic. No conversational filler or meta-intros. Output ONLY the answer string."""

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
        return {"status": "success", "answer": answer_text.strip().strip('"')}
    except Exception as e:
        print(f"[answer_question] LLM generation error: {e}")
        if "one line" in q_lower or "one-line" in q_lower or "condensed" in q_lower:
            return {"status": "success", "answer": "AI Systems Engineer with 3+ years experience building production-grade GenAI pipelines and scalable LLM applications."}
        elif "why" in q_lower:
            company = request.company_name or "Granola"
            return {"status": "success", "answer": f"I am deeply inspired by {company}'s focus on reimagining productivity workflows with intuitive AI. With my experience building low-latency LLM systems, I want to contribute directly to advancing your product capabilities and user experience."}
        return {"status": "success", "answer": f"Excited to bring my technical skills in AI engineering and systems development to {request.company_name or 'the team'}."}


@router.post("/user/solve_field")
async def user_solve_field(request: SolveFieldRequest, authorization: Optional[str] = Header(None)):
    token = authorization.split(" ")[1] if authorization and authorization.startswith("Bearer ") else None
    session_data = get_session_data(token)
    resume = session_data.get("data", {})

    from services.autofill_agent import get_answer_from_llm
    answer = await asyncio.to_thread(
        get_answer_from_llm,
        request.field_name,
        request.context or "",
        resume,
        request.api_key
    )
    return {"answer": answer}


@router.post("/user/generate_prompt_query")
async def generate_prompt_query(request: GeneratePromptQueryRequest, authorization: Optional[str] = Header(None)):
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
        raw_res = await asyncio.to_thread(generate_content_with_fallback, prompt, model_tier="lite")
        cleaned = raw_res.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
            cleaned = re.sub(r'\s*```$', '', cleaned)
        data = json.loads(cleaned)
        return {"status": "success", "prompt_text": data.get("prompt_text", "")}
    except Exception as e:
        return {
            "status": "success",
            "prompt_text": f"This recommendation requests additional metrics or details:\n\n\"{request.suggestion}\"\n\nPlease enter the requested detail or metric:"
        }


@router.post("/send_application_pdf_email")
async def send_application_pdf_email(request: SendApplicationPdfEmailRequest, authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized. Please sign in.")
    token = authorization.split(" ")[1]
    user = await async_get_user_by_token(token)
    if not user or not user.get("email"):
        raise HTTPException(status_code=400, detail="User email not found. Please log in.")

    clean_rel = os.path.normpath(request.pdf_url.replace("/download_application_pdf/", "")).lstrip("/")
    pdf_path = os.path.abspath(os.path.join(OUTPUT_DIR, clean_rel))
    out_dir_abs = os.path.abspath(OUTPUT_DIR)

    if not pdf_path.startswith(out_dir_abs) or not os.path.exists(pdf_path):
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
        f"View the job listing and apply here:\n{request.job_url or ''}\n\n"
        f"Open it in Overleaf:\n{request.overleaf_url or ''}\n\n"
        f"Best of luck with your application!"
    )
    email_html = f"""
    <div style="font-family: 'Segoe UI', sans-serif; max-width: 600px; margin: 0 auto; padding: 25px; border: 1px solid #E2E8F0; border-radius: 12px; background-color: #FAFAFA;">
        <h2 style="color: #0284C7;">Tailored Resume PDF</h2>
        <p>For your application at <strong>{request.company}</strong> ({request.job_title})</p>
        <p>ATS Match Score: <strong>{ats_display}</strong></p>
        <div style="text-align: center; margin: 25px 0;">
            {"<a href='" + request.job_url + "' style='display:inline-block; background-color:#10B981; color:#fff; padding:10px 20px; border-radius:6px; text-decoration:none; margin-right:10px;'>View Job & Apply</a>" if request.job_url else ""}
            {"<a href='" + request.overleaf_url + "' style='display:inline-block; background-color:#0284C7; color:#fff; padding:10px 20px; border-radius:6px; text-decoration:none;'>Open in Overleaf</a>" if request.overleaf_url else ""}
        </div>
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


@router.post("/send_outreach_email")
async def send_outreach_email(request: SendOutreachEmailRequest, authorization: Optional[str] = Header(None)):
    token = authorization.split(" ")[1] if authorization and authorization.startswith("Bearer ") else None

    try:
        if not request.recipient_email or '@' not in request.recipient_email:
            raise HTTPException(status_code=400, detail="Invalid recipient email address.")

        print(f"[Outreach Email] To: {request.recipient_email}")
        print(f"[Outreach Email] Subject: {request.subject}")

        return {
            "status": "success",
            "message": "Email prepared for sending.",
            "recipient": request.recipient_email,
            "subject": request.subject
        }
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/user/test_email")
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
