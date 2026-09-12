"""
autofill_tools.py — Autonomous Browser-Use Application & Pipeline MCP Tools.
Integrates browser-use, ATS scoring, resume tailoring, and persistent Chrome profiles.
"""

import os
import sys
import json
import shutil
import asyncio
import subprocess
from typing import Dict, Any, Optional, List

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "backend", ".env"))
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env"))

from mcp.tools.profile_tools import load_profile_data
from mcp.tools.ats_tools import handle_calculate_ats_score, handle_analyze_skill_gap
from mcp.tools.discovery_tools import handle_search_jobs, handle_scrape_job_posting
from mcp.tools.resume_tools import handle_tailor_resume_latex
from utils.latex_utils import apply_latex_hotfix, compile_and_check_page_metrics
from services.application_tracker import record_application, update_application_status
from services.browser_use_agent import run_browser_use_autofill

AUTOFILL_TOOLS_SPEC = [
    {
        "name": "apply_to_job_browser",
        "description": "Autonomously navigates, autofills, and optionally submits a job application on Ashby, Greenhouse, Lever, Workday, or LinkedIn using a persistent Chrome browser session.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_url": {
                    "type": "string",
                    "description": "The target job posting or application link."
                },
                "auto_submit": {
                    "type": "boolean",
                    "description": "If True, auto-clicks the final Submit Application button without stopping. If False, stops on review screen.",
                    "default": False
                },
                "model_name": {
                    "type": "string",
                    "description": "Gemini model to drive browser-use actions.",
                    "default": "gemini-3.5-flash-lite"
                },
                "resume_pdf_path": {
                    "type": "string",
                    "description": "Custom path to candidate resume PDF. If omitted, uses tailored or master resume."
                },
                "token": {
                    "type": "string",
                    "description": "Optional user session token to retrieve candidate profile."
                },
                "max_steps": {
                    "type": "integer",
                    "description": "Maximum steps for agent navigation.",
                    "default": 50
                }
            },
            "required": ["job_url"]
        }
    },
    {
        "name": "pipeline_auto_apply",
        "description": "End-to-end autonomous career pipeline: Searches jobs matching candidate profile, calculates ATS score, checks if resume can be tailored to JD, compiles tailored 1-page PDF, and auto-applies/submits via browser-use in the persistent browser.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "keywords": {
                    "type": "string",
                    "description": "Target job keywords (e.g. 'AI Engineer', 'Machine Learning Systems'). If omitted, uses profile target roles."
                },
                "location": {
                    "type": "string",
                    "description": "Target location. If omitted, uses profile target locations.",
                    "default": "London, UK"
                },
                "min_ats_score": {
                    "type": "integer",
                    "description": "Minimum ATS compatibility score threshold required to trigger application (e.g. 80).",
                    "default": 80
                },
                "auto_submit": {
                    "type": "boolean",
                    "description": "If True, automatically submits the application. If False, stops at preview for review.",
                    "default": False
                },
                "tailor_resume": {
                    "type": "boolean",
                    "description": "Whether to check and tailor the LaTeX resume for the specific job description before applying.",
                    "default": True
                },
                "max_applications": {
                    "type": "integer",
                    "description": "Maximum number of qualifying jobs to process and apply to in one run.",
                    "default": 3
                },
                "model_name": {
                    "type": "string",
                    "description": "Gemini model for browser-use.",
                    "default": "gemini-3.5-flash-lite"
                },
                "token": {
                    "type": "string",
                    "description": "Optional session token to retrieve candidate profile."
                }
            }
        }
    }
]


def _get_base_dirs():
    # File is at backend/mcp/tools/autofill_tools.py -> dirname x 4 = project root
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    return base_dir


def _get_default_resume_path() -> Optional[str]:
    custom = os.getenv("MASTER_RESUME_PATH")
    if custom and os.path.exists(custom):
        return custom

    base_dir = _get_base_dirs()
    candidate_resumes = [
        os.path.join(base_dir, "output", "master_resume.pdf"),
        os.path.join(base_dir, "applications_tracker", "tailored_resumes", "master_resume.pdf"),
        os.path.join(base_dir, "tests", "fixtures", "sample_resume.pdf"),
    ]
    # Check any subfolder in output directory
    out_dir = os.path.join(base_dir, "backend", "output")
    if os.path.exists(out_dir):
        for entry in os.listdir(out_dir):
            sub_pdf = os.path.join(out_dir, entry, "master_resume.pdf")
            if os.path.exists(sub_pdf):
                candidate_resumes.append(sub_pdf)

    for p in candidate_resumes:
        if os.path.exists(p):
            return p
    return None


def _get_master_latex_source() -> Optional[str]:
    base_dir = _get_base_dirs()
    candidates = [
        os.path.join(base_dir, "backend", "assets", "master_resume_template.tex"),
        os.path.join(base_dir, "assets", "master_resume_template.tex"),
        os.path.join(base_dir, "output", "tailored_resume.tex"),
    ]
    out_dir = os.path.join(base_dir, "backend", "output")
    if os.path.exists(out_dir):
        for entry in os.listdir(out_dir):
            sub_tex = os.path.join(out_dir, entry, "master_resume.tex")
            if os.path.exists(sub_tex):
                candidates.insert(0, sub_tex)
    for p in candidates:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception:
                continue
    return None


def build_and_compile_tailored_pdf(
    jd_text: str,
    job_title: str,
    company: str,
    candidate_info: Dict[str, Any],
    out_dir: str,
    missing_skills: Optional[List[str]] = None
) -> Optional[str]:
    """
    Checks if resume can be tailored to the JD, adapts the master LaTeX resume code,
    enforces a strict 1-page budget, and compiles a job-specific tailored PDF using Tectonic.
    Prioritizes sub-second precision slot injection before falling back to LLM rewriting.
    """
    master_latex = _get_master_latex_source()
    if not master_latex:
        return None

    os.makedirs(out_dir, exist_ok=True)
    base_dir = _get_base_dirs()

    # Ensure resume.cls is available in the target build directory
    cls_candidates = [
        os.path.join(base_dir, "backend", "assets", "resume.cls"),
        os.path.join(base_dir, "assets", "resume.cls"),
        os.path.join(base_dir, "backend", "uploads", "resume.cls"),
    ]
    for c in cls_candidates:
        if os.path.exists(c):
            shutil.copy2(c, os.path.join(out_dir, "resume.cls"))
            break

    skills_to_inject = [s.strip() for s in (missing_skills or []) if s and s.strip()]
    if not skills_to_inject and jd_text:
        try:
            from services.ats_scorer import extract_jd_skills
            req, pref = extract_jd_skills(jd_text)
            skills_to_inject = (req + pref)[:5]
        except Exception:
            pass

    # 1. Fast Path: Sub-second precision slot injection on Master LaTeX layout
    raw_tailored = None
    if skills_to_inject:
        try:
            from utils.latex_utils import inject_tailored_slots
            slotted = inject_tailored_slots(
                master_latex=master_latex,
                user_selected_skills=skills_to_inject,
                candidate_info=candidate_info
            )
            if slotted and "\\begin{document}" in slotted and "\\documentclass" in slotted:
                print(f"[tailor_resume] ⚡ Applied instantaneous precision slot injection for {len(skills_to_inject)} skills: {skills_to_inject}")
                raw_tailored = slotted
        except Exception as se:
            print(f"[tailor_resume] Slot injection error, falling back: {se}")

    # Fallback to LLM tailoring if slot injection was skipped or failed
    if not raw_tailored:
        from services.llm_agent import tailor_latex_code
        try:
            raw_tailored = tailor_latex_code(
                master_latex=master_latex,
                job_title=job_title,
                job_description=jd_text,
                suggestions={},
                missing_skills=skills_to_inject
            )
        except Exception as e:
            print(f"[tailor_resume] LLM Tailoring failed, using master template with hotfixes: {e}")
            raw_tailored = master_latex

    # 2. Multi-pass page budget optimization to guarantee single page
    opt_scale, opt_ls = 1.0, 1.0
    pages, _ = compile_and_check_page_metrics(raw_tailored, 1.0, 1.0, master_latex)
    if pages > 1:
        p = pages
        for ls in [0.95, 0.91, 0.88, 0.82, 0.78]:
            p, _ = compile_and_check_page_metrics(raw_tailored, 1.0, ls, master_latex)
            if p == 1:
                opt_ls = ls
                break
        if p > 1:
            for scale in [0.95, 0.90, 0.85, 0.80]:
                p, _ = compile_and_check_page_metrics(raw_tailored, scale, opt_ls, master_latex)
                if p == 1:
                    opt_scale = scale
                    break

    final_latex = apply_latex_hotfix(raw_tailored, opt_scale, opt_ls, master_latex)

    safe_company = "".join(c for c in company if c.isalnum() or c in ("-", "_")).strip() or "Company"
    tex_filename = f"tailored_resume_{safe_company}.tex"
    pdf_filename = f"tailored_resume_{safe_company}.pdf"
    tex_path = os.path.join(out_dir, tex_filename)
    pdf_path = os.path.join(out_dir, pdf_filename)

    with open(tex_path, "w", encoding="utf-8") as f:
        f.write(final_latex)

    # Compile with Tectonic
    proc = subprocess.run(
        ["tectonic", tex_path, "--outdir", out_dir],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    if proc.returncode == 0 and os.path.exists(pdf_path):
        print(f"[tailor_resume] Successfully compiled 1-page tailored PDF: {pdf_path}")
        return pdf_path
    else:
        print(f"[tailor_resume] Tectonic compilation failed: {proc.stderr}")
        return None


async def handle_apply_to_job_browser(arguments: Dict[str, Any]) -> Dict[str, Any]:
    job_url = arguments.get("job_url")
    if not job_url:
        return {"error": "Missing required argument 'job_url'"}

    auto_submit = arguments.get("auto_submit", False)
    model_name = arguments.get("model_name", "gemini-3.5-flash-lite")
    max_steps = arguments.get("max_steps", 50)
    token = arguments.get("token")

    # Load candidate profile
    profile_data = load_profile_data() or {}
    candidate_info = profile_data.get("candidate", {})

    # Resume PDF resolution
    resume_pdf_path = arguments.get("resume_pdf_path") or _get_default_resume_path()

    result = await run_browser_use_autofill(
        job_url=job_url,
        resume_data=candidate_info,
        resume_pdf_path=resume_pdf_path,
        headless=False,
        model_name=model_name,
        auto_submit=auto_submit,
        max_steps=max_steps
    )

    # Track in CRM
    try:
        record_application(
            token=token,
            entry={
                "job_url": job_url,
                "status": "applied" if auto_submit else "tailored",
                "job_title": arguments.get("job_title", "Software Engineer"),
                "company": arguments.get("company", "Company"),
                "score": arguments.get("ats_score", 0),
            }
        )
    except Exception:
        pass

    return result


async def handle_pipeline_auto_apply(arguments: Dict[str, Any]) -> Dict[str, Any]:
    token = arguments.get("token")
    profile_data = load_profile_data() or {}
    candidate = profile_data.get("candidate", {})
    search_prefs = profile_data.get("search_preferences", {})

    keywords = arguments.get("keywords")
    if not keywords:
        target_roles = search_prefs.get("target_roles", ["AI Engineer"])
        keywords = target_roles[0] if target_roles else "AI Engineer"

    location = arguments.get("location")
    if not location:
        target_locs = search_prefs.get("target_locations", ["London, UK"])
        location = target_locs[0] if target_locs else "London, UK"

    min_ats_score = int(arguments.get("min_ats_score", 80))
    auto_submit = arguments.get("auto_submit", False)
    tailor_resume = arguments.get("tailor_resume", True)
    max_applications = int(arguments.get("max_applications", 3))
    model_name = arguments.get("model_name", "gemini-3.5-flash-lite")

    from services.log_queue import log_ist
    print(f"\n[Pipeline] 🚀 Pipeline Auto-Apply Started", flush=True)
    print(f"[Pipeline] 🎯 Keywords: '{keywords}' | 📍 Location: '{location}' | 🎯 Min ATS: {min_ats_score}%", flush=True)
    log_ist(f"[Pipeline] 🚀 Pipeline Auto-Apply started for '{keywords}' in '{location}' (Min ATS: {min_ats_score}%)")

    # 1. Search for matching jobs
    search_res = await handle_search_jobs({
        "keywords": keywords,
        "location": location,
        "timeframe": search_prefs.get("timeframe", "24h"),
        "token": token
    })

    jobs = search_res.get("jobs", [])
    print(f"[Pipeline] 📊 Discovered {len(jobs)} total jobs to evaluate", flush=True)
    log_ist(f"[Pipeline] 📊 Discovered {len(jobs)} total jobs to evaluate")

    if not jobs:
        return {
            "status": "completed",
            "message": f"No job postings discovered for '{keywords}' in '{location}'.",
            "applied_count": 0,
            "processed_jobs": []
        }

    processed_jobs = []
    applied_count = 0
    base_dir = _get_base_dirs()
    tailored_dir = os.path.join(base_dir, "applications_tracker", "tailored_resumes")
    master_resume_pdf = _get_default_resume_path()

    for idx, job in enumerate(jobs, start=1):
        if applied_count >= max_applications:
            print(f"[Pipeline] 🛑 Reached max target applications limit ({max_applications}). Stopping.", flush=True)
            break

        job_url = job.get("url")
        job_title = job.get("title", "Role")
        company = job.get("company", "Company")
        ats_score = job.get("ats_score") or job.get("score")
        jd_text = ""

        print(f"\n[Pipeline] [{idx}/{len(jobs)}] Evaluating '{job_title}' @ {company}...", flush=True)
        log_ist(f"[Pipeline] Evaluating [{idx}/{len(jobs)}] '{job_title}' @ {company}")

        # Deep scrape to evaluate match & tailoring opportunities
        scrape_res = await handle_scrape_job_posting({"url": job_url})
        jd_text = scrape_res.get("description", "")

        # 2. Score if ATS score is missing
        if ats_score is None:
            if jd_text:
                score_res = await handle_calculate_ats_score({
                    "job_description": jd_text,
                    "resume_data": candidate,
                    "token": token
                })
                ats_score = score_res.get("overall_score") or score_res.get("score", 0)
            else:
                ats_score = 0

        print(f"[Pipeline] 📈 ATS Compatibility: {ats_score}% (Required: {min_ats_score}%)", flush=True)

        job_summary = {
            "title": job_title,
            "company": company,
            "url": job_url,
            "ats_score": ats_score,
            "status": "skipped",
            "tailored_resume_used": False
        }

        # 3. Check ATS threshold (>= min_ats_score)
        if ats_score >= min_ats_score:
            print(f"[Pipeline] ✅ QUALIFIED! '{job_title}' at {company} ({ats_score}% >= {min_ats_score}%)", flush=True)
            log_ist(f"[Pipeline] ✅ QUALIFIED: '{job_title}' @ {company} ({ats_score}%)")

            # Check if resume can/should be tailored to the JD
            resume_to_upload = master_resume_pdf
            if tailor_resume and jd_text:
                try:
                    tailored_pdf = await asyncio.to_thread(
                        build_and_compile_tailored_pdf,
                        jd_text=jd_text,
                        job_title=job_title,
                        company=company,
                        candidate_info=candidate,
                        out_dir=tailored_dir
                    )
                    if tailored_pdf and os.path.exists(tailored_pdf):
                        resume_to_upload = tailored_pdf
                        job_summary["tailored_resume_used"] = True
                        job_summary["tailored_pdf_path"] = tailored_pdf
                except Exception as e:
                    print(f"[Pipeline] Resume tailoring attempt had error: {e}. Falling back to master resume.")

            # 4. Autofill / Auto-apply via browser-use (50 max steps)
            action_desc = "Submitting application" if auto_submit else "Autofilling application (Preview Mode)"
            print(f"[Pipeline] 🌐 Launching browser-use: {action_desc} for {company}...", flush=True)
            log_ist(f"[Pipeline] 🌐 Launching browser-use: {action_desc} for {company}")

            apply_res = await run_browser_use_autofill(
                job_url=job_url,
                resume_data=candidate,
                resume_pdf_path=resume_to_upload,
                headless=False,
                model_name=model_name,
                auto_submit=auto_submit,
                max_steps=50
            )

            job_summary["status"] = "applied" if auto_submit else "filled_review_needed"
            job_summary["browser_result"] = apply_res.get("final_result")
            applied_count += 1
            print(f"[Pipeline] ✨ Completed application cycle for '{job_title}' @ {company}! Status: {job_summary['status']}", flush=True)
            log_ist(f"[Pipeline] ✨ Completed application cycle for '{job_title}' @ {company} ({job_summary['status']})")

            # 5. Record application status in CRM
            try:
                record_application(
                    token=token,
                    entry={
                        "job_url": job_url,
                        "status": "applied" if auto_submit else "tailored",
                        "job_title": job_title,
                        "company": company,
                        "score": int(ats_score),
                    }
                )
            except Exception:
                pass
        else:
            job_summary["status"] = f"below_threshold_{ats_score}_vs_{min_ats_score}"

        processed_jobs.append(job_summary)

    return {
        "status": "completed",
        "keywords": keywords,
        "location": location,
        "min_ats_score": min_ats_score,
        "auto_submit": auto_submit,
        "tailor_resume": tailor_resume,
        "model_used": model_name,
        "applied_count": applied_count,
        "processed_jobs": processed_jobs
    }
