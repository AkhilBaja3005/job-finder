#!/usr/bin/env python3
"""
scheduled_job_scanner.py
------------------------
Automated periodic pipeline using the unified multi-platform discovery engine:
1. Concurrently scans ATS Portals (Greenhouse, Ashby, Lever) + LinkedIn, Indeed, Reed & Google Grounding.
2. Evaluates ATS compatibility deterministically against the candidate profile.
3. If ATS Score > 85%: Direct apply with master resume (skips tailoring).
   If ATS Score >= min_threshold (e.g. 65%-85%): Tailors 1-page LaTeX resume & PDF, then applies.
4. Updates application history in Supabase (`applications` table); if Supabase credentials aren't
   configured or table is unreachable, falls back cleanly to the CSV tracker.
5. Autonomously fills application forms via browser-use (respecting BROWSER_USE_DISABLE_GUARDRAILS).

CLI Usage:
  python scheduled_job_scanner.py
  python scheduled_job_scanner.py "https://www.linkedin.com/jobs/view/4449829595/"
  BROWSER_USE_DISABLE_GUARDRAILS=1 python scheduled_job_scanner.py
"""

import os
import sys
import json
import csv
import asyncio
from datetime import datetime
from typing import Optional, Dict, Any

JOB_FINDER_ROOT = "/Users/akhilbaja/Documents/Akhil/Job Finder"
BACKEND_DIR = os.path.join(JOB_FINDER_ROOT, "backend")
TRACKER_DIR = os.path.join(JOB_FINDER_ROOT, "applications_tracker")
RESUMES_DIR = os.path.join(TRACKER_DIR, "tailored_resumes")
CSV_PATH = os.path.join(TRACKER_DIR, "job_applications_tracker.csv")

sys.path.insert(0, BACKEND_DIR)

# pyrefly: ignore [missing-import]
from dotenv import load_dotenv
load_dotenv(os.path.join(BACKEND_DIR, ".env"))

from mcp.tools.discovery_tools import handle_search_jobs
from mcp.tools.profile_tools import load_profile_data
from mcp.tools.tracking_tools import handle_track_application
from mcp.tools.autofill_tools import build_and_compile_tailored_pdf, _get_default_resume_path
from mcp.tools.ats_tools import handle_calculate_ats_score
from services.browser_use_agent import run_browser_use_autofill
from services.auth import async_supabase_request, SUPABASE_URL, SUPABASE_KEY
import subprocess


def find_master_resume_with_mac_tags() -> str:
    """
    Finds the master resume PDF by checking macOS color tags in iCloud Drive,
    falling back to known default paths if tags aren't present.
    """
    icloud_folder = "/Users/akhilbaja/Library/Mobile Documents/com~apple~CloudDocs/UK/Imperial/Job Info/Master Resume"
    explicit_fallback = os.path.join(icloud_folder, "Resume_Akhil_Baja.pdf")

    if os.path.exists(icloud_folder):
        try:
            for fname in os.listdir(icloud_folder):
                if fname.lower().endswith(".pdf"):
                    full_p = os.path.join(icloud_folder, fname)
                    res = subprocess.run(["mdls", "-name", "kMDItemUserTags", full_p], capture_output=True, text=True)
                    out = res.stdout or ""
                    # Check if tagged with Red, Green, Blue or any user tag
                    if "kMDItemUserTags = (" in out and "null" not in out.lower():
                        print(f"[Master Resume] 🏷️ Found macOS tagged master resume: {full_p}")
                        return full_p
        except Exception as e:
            print(f"[Master Resume] Note: Tag inspection failed ({e}), checking explicit path.")

    if os.path.exists(explicit_fallback):
        print(f"[Master Resume] 📄 Found explicit master resume: {explicit_fallback}")
        return explicit_fallback

    # Secondary fallback to repo master resume
    repo_fallback = _get_default_resume_path()
    if repo_fallback and os.path.exists(repo_fallback):
        print(f"[Master Resume] 📄 Falling back to repo master resume: {repo_fallback}")
        return repo_fallback

    return explicit_fallback


def evaluate_pdf_ats(pdf_path: str, jd_text: str, candidate_info: dict) -> int:
    """
    Extracts text from a compiled resume PDF and deterministically computes its overall ATS score against a JD.
    """
    try:
        from services.resume_parser import extract_text_from_pdf
        from services.ats_scorer import compute_ats_score, compute_overall_score, estimate_role_fit_score

        raw_text = extract_text_from_pdf(pdf_path)
        if not raw_text:
            return 0

        # Extract skills section dynamically from the PDF text
        extracted_skills = []
        for line in raw_text.split("\n"):
            if any(k in line.lower() for k in ["languages:", "ai/ml", "data & platforms:", "software & infrastructure:", "skills:"]):
                parts = line.split(":", 1)
                if len(parts) > 1:
                    extracted_skills.extend([s.strip() for s in parts[1].split(",") if s.strip()])

        skills = extracted_skills if extracted_skills else candidate_info.get("core_skills", [])

        resume_data = {
            "name": candidate_info.get("name"),
            "location": candidate_info.get("location"),
            "skills": skills,
            "experience": [
                {
                    "role": e.get("role", ""),
                    "company": e.get("company", ""),
                    "description": e.get("highlights", [])
                }
                for e in candidate_info.get("work_experience", [])
            ],
            "raw_text": raw_text
        }
        ats = compute_ats_score(resume_data, jd_text)
        rf = estimate_role_fit_score(resume_data, jd_text)
        return int(compute_overall_score(ats.skills_score, ats.experience_score, rf))
    except Exception as e:
        print(f"[ATS Scorer] Warning: Could not score PDF {pdf_path}: {e}")
        return 0


async def record_to_supabase_or_csv(record_data: dict):
    """
    Saves the application record to Supabase (`applications` table) if creds exist.
    Always updates the local CSV file as a reliable offline ledger/fallback.
    """
    supabase_synced = False

    if SUPABASE_URL and SUPABASE_KEY:
        try:
            profile_data = load_profile_data() or {}
            cand = profile_data.get("candidate", {})
            user_id = cand.get("user_id") or 23

            payload = {
                "user_id": int(user_id),
                "job_title": record_data.get("job_title", "Role"),
                "company": record_data.get("company", "Company"),
                "job_url": record_data.get("job_url", ""),
                "score": int(record_data.get("overall_ats", 0)),
                "status": record_data.get("status", "saved"),
                "source_mode": record_data.get("platform", "scanner"),
            }
            if record_data.get("recruiter"):
                payload["recruiter_name"] = record_data.get("recruiter")
            if record_data.get("recruiter_linkedin"):
                payload["recruiter_profile_url"] = record_data.get("recruiter_linkedin")

            # Check if this job_url exists in Supabase to update or insert
            url_filter = f"applications?job_url=eq.{record_data.get('job_url', '')}"
            existing = await async_supabase_request(url_filter, "GET")
            if existing and len(existing) > 0:
                await async_supabase_request(url_filter, "PATCH", {"status": payload["status"], "score": payload["score"]})
                supabase_synced = True
            else:
                inserted = await async_supabase_request("applications", "POST", payload)
                if inserted:
                    supabase_synced = True
        except Exception as se:
            print(f"[Supabase] ⚠️ Synced error: {se}. Falling back to CSV.")

    # Record to local CSV ledger
    try:
        file_exists = os.path.exists(CSV_PATH)
        csv_headers = [
            "Company", "Job Title", "Location", "Platform", "Posted Time",
            "Overall ATS", "Skills Match", "Experience Match", "Role Fit",
            "Matched Skills", "Missing Skills", "Salary", "Seniority",
            "Recruiter", "Recruiter LinkedIn", "PDF Path", "LaTeX Path",
            "Status", "Job URL"
        ]
        with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(csv_headers)
            writer.writerow([
                record_data.get("company", ""),
                record_data.get("job_title", ""),
                record_data.get("location", ""),
                record_data.get("platform", ""),
                record_data.get("posted_time", ""),
                f"{record_data.get('overall_ats', 0)}%",
                f"{record_data.get('skills_match', 0)}%",
                f"{record_data.get('experience_match', 0)}%",
                f"{record_data.get('role_fit', 0)}%",
                record_data.get("matched_skills", ""),
                record_data.get("missing_skills", ""),
                record_data.get("salary", ""),
                record_data.get("seniority", ""),
                record_data.get("recruiter", ""),
                record_data.get("recruiter_linkedin", ""),
                record_data.get("pdf_path", ""),
                record_data.get("latex_path", ""),
                record_data.get("status", ""),
                record_data.get("job_url", "")
            ])

        dest = "Supabase + CSV" if supabase_synced else "CSV Tracker"
        print(f"   💾 Recorded to: {dest} (Status: {record_data.get('status')})")
    except Exception as ce:
        print(f"[CSV Tracker] Error saving application: {ce}")


def get_existing_tracked_urls() -> set:
    """
    Collects normalized URLs of jobs already tracked or applied to.
    Checks both Supabase ('applications' table) and local CSV tracker.
    """
    urls = set()

    # 1. Check Supabase applications table if configured
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if supabase_url and supabase_key:
        try:
            # pyrefly: ignore [missing-import]
            from supabase import create_client
            client = create_client(supabase_url, supabase_key)
            resp = client.table("applications").select("job_url").execute()
            if resp and resp.data:
                for row in resp.data:
                    u = row.get("job_url")
                    if u:
                        urls.add(u.strip().split("?")[0].rstrip("/").lower())
        except Exception as se:
            print(f"[Tracker] Note: Could not fetch existing URLs from Supabase: {se}")

    # 2. Check Local CSV tracker
    if os.path.exists(CSV_PATH):
        try:
            with open(CSV_PATH, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    u = row.get("Job URL") or row.get("url")
                    if u:
                        urls.add(u.strip().split("?")[0].rstrip("/").lower())
        except Exception as ce:
            print(f"[Tracker] Note: Could not read CSV tracker: {ce}")

    return urls


async def apply_to_job(
    url: str,
    candidate: dict,
    resume_path: Optional[str] = None,
    title: str = "Role",
    company: str = "Company",
    auto_submit: bool = False
):
    print(f"\n[Browser-Use] 🌐 Launching browser autofill for: {title} @ {company}")
    print(f"[Browser-Use] 🔗 URL: {url}")
    print(f"[Browser-Use] 📄 Resume: {resume_path}")
    print(f"[Browser-Use] ⚡ Guardrails: {'Disabled (Auto-Submit Enabled)' if (auto_submit or os.getenv('BROWSER_USE_DISABLE_GUARDRAILS') in ('1', 'true', 'True')) else 'Enabled (Preview Mode)'}")
    try:
        res = await run_browser_use_autofill(
            job_url=url,
            resume_data=candidate,
            resume_pdf_path=resume_path,
            headless=False,
            model_name="gemini-3.5-flash-lite",
            auto_submit=auto_submit,
            max_steps=25
        )
        print(f"[Browser-Use] Result: {res}")
        return res
    except Exception as be:
        print(f"[Browser-Use] ❌ Autofill error: {be}")
        return {"status": "error", "error": str(be)}


async def run_pipeline(target_url: Optional[str] = None):
    profile = load_profile_data()
    candidate = profile.get("candidate", {})
    prefs = profile.get("search_preferences", {})

    disable_guardrails = os.getenv("BROWSER_USE_DISABLE_GUARDRAILS") in ("1", "true", "True")
    master_resume_pdf = find_master_resume_with_mac_tags()

    # Mode A: Direct application to single job URL passed via CLI
    if target_url:
        print(f"[2026-09-10] 🎯 Targeting single job URL: {target_url}")
        await apply_to_job(
            url=target_url,
            candidate=candidate,
            resume_path=master_resume_pdf,
            title="Target Role",
            company="Company",
            auto_submit=disable_guardrails
        )
        return

    # Mode B: Unified Multi-Source Discovery, Selective Tailoring & Application
    raw_target_roles = prefs.get("target_roles", [
        "AI Engineer",
        "Generative AI Engineer",
        "Machine Learning Engineer",
        "AI Systems Engineer",
        "Applied AI Scientist"
    ])
    # Deduplicate target roles while preserving order
    target_roles = list(dict.fromkeys(raw_target_roles))
    keywords = ", ".join(target_roles)
    target_locations = prefs.get("target_locations", ["London, UK"])
    location = target_locations[0] if target_locations else "London, UK"
    timeframe = prefs.get("timeframe", "24h")
    min_ats_score = int(prefs.get("min_ats_score", 65))
    DIRECT_APPLY_ATS_THRESHOLD = 80  # >= 80%: apply directly with master resume without tailoring
    max_applications = int(os.getenv("MAX_APPLICATIONS_PER_RUN", "10"))

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 🚀 Starting scheduled unified scan...")
    print(f"Target roles: {keywords}")
    print(f"Location: {location} | Timeframe: {timeframe}")
    print(f"Rule: >= {DIRECT_APPLY_ATS_THRESHOLD}% ATS -> Direct apply (Master Resume)")
    print(f"Rule: {min_ats_score}% - {DIRECT_APPLY_ATS_THRESHOLD - 1}% ATS -> Tailor 1-page LaTeX & PDF, then apply")
    print(f"Database Target: Supabase (`applications` table) with CSV backup")
    print(f"Max Applications Cap: {max_applications}")
    print(f"Guardrails Disabled: {disable_guardrails}\n")

    # Run full multi-source web discovery (Portals + LinkedIn + Indeed + Reed)
    search_res = await handle_search_jobs({
        "keywords": keywords,
        "location": location,
        "timeframe": timeframe
    })

    jobs = search_res.get("jobs", [])
    print(f"\n[Scanner] 📊 Total unique postings discovered and scored: {len(jobs)}")

    existing_urls = get_existing_tracked_urls()
    print(f"[Scanner] 🔍 Found {len(existing_urls)} previously tracked/applied job URLs across Supabase and CSV.")
    new_jobs_added = 0
    tailored_count = 0
    direct_applied_count = 0
    applied_attempts = 0

    for idx, job in enumerate(jobs, start=1):
        title = job.get("title", "Role")
        company = job.get("company", "Company")
        url = job.get("url") or job.get("apply_url", "")
        score = job.get("ats_score") or job.get("score", 0)
        platform = job.get("source") or job.get("platform", "Web")
        matched_skills = ", ".join(job.get("matched_skills", []))
        missing_skills = ", ".join(job.get("missing_skills", []))
        salary = job.get("salary") or ""
        seniority = job.get("seniority") or ""
        posted_time = job.get("posted_date") or job.get("post_date_raw") or "Recent"

        recruiter_name = job.get("recruiter_name") or ""
        recruiter_url = job.get("recruiter_url") or ""

        url_norm = url.strip().split("?")[0].rstrip("/").lower()
        is_duplicate = url_norm in existing_urls

        if is_duplicate:
            print(f"[{idx}/{len(jobs)}] Skipping existing: {title} @ {company} ({score}% ATS)")
            continue

        # Decide Application & Tailoring Strategy
        pdf_to_submit = master_resume_pdf
        tex_path = ""
        jd_text = job.get("description") or ""

        if score >= DIRECT_APPLY_ATS_THRESHOLD:
            # 🎯 DIRECT APPLY (>= 80% ATS match)
            status = "applied" if disable_guardrails else "Ready to Apply"
            print(f"\n[{idx}/{len(jobs)}] 🌟 EXCELLENT MATCH ({score}% >= {DIRECT_APPLY_ATS_THRESHOLD}%): {title} @ {company}")
            print(f"   ⚡ Direct Apply mode: Using master resume (no tailoring needed)")
            direct_applied_count += 1
        elif score >= min_ats_score:
            # 🛠️ TAILOR & APPLY (65% - 79% ATS match)
            status = "applied" if disable_guardrails else "Tailored & Ready"
            print(f"\n[{idx}/{len(jobs)}] 🎯 QUALIFIED MATCH ({score}% ATS): {title} @ {company}")
            print(f"   📝 Tailoring 1-page LaTeX resume for keyword & skills alignment...")
            if jd_text:
                try:
                    pdf_res = await asyncio.to_thread(
                        build_and_compile_tailored_pdf,
                        jd_text=jd_text,
                        job_title=title,
                        company=company,
                        candidate_info=candidate,
                        out_dir=RESUMES_DIR
                    )
                    if pdf_res and os.path.exists(pdf_res):
                        tailored_ats = evaluate_pdf_ats(pdf_res, jd_text, candidate)
                        master_ats = score  # initial score was against master profile / resume
                        print(f"   📊 ATS Score Comparison: Tailored PDF = {tailored_ats}% vs Master PDF = {master_ats}%")
                        if tailored_ats >= master_ats:
                            pdf_to_submit = pdf_res
                            tex_path = pdf_res.replace(".pdf", ".tex")
                            score = tailored_ats
                            tailored_count += 1
                            print(f"   ✓ Tailored PDF outperforms master ({tailored_ats}% >= {master_ats}%). Selected: {os.path.basename(pdf_to_submit)}")
                        else:
                            pdf_to_submit = master_resume_pdf
                            print(f"   ℹ️ Master resume scored higher or equal ({master_ats}% > {tailored_ats}%). Keeping master resume: {os.path.basename(pdf_to_submit)}")
                except Exception as te:
                    print(f"   ⚠️ Tailoring error: {te}. Falling back to master resume.")
        else:
            status = "Saved & Scored"
            print(f"[{idx}/{len(jobs)}] ℹ️ Below threshold: {title} @ {company} ({score}% < {min_ats_score}%) - Saved.")

        # Record to Supabase (and CSV fallback)
        record_payload = {
            "company": company,
            "job_title": title,
            "location": job.get("location", location),
            "platform": platform,
            "posted_time": posted_time,
            "overall_ats": score,
            "skills_match": job.get("skills_score", 0),
            "experience_match": job.get("exp_score", 0),
            "role_fit": job.get("role_fit_score", 0),
            "matched_skills": matched_skills,
            "missing_skills": missing_skills,
            "salary": salary,
            "seniority": seniority,
            "recruiter": recruiter_name,
            "recruiter_linkedin": recruiter_url,
            "pdf_path": pdf_to_submit,
            "latex_path": tex_path,
            "status": status,
            "job_url": url
        }
        await record_to_supabase_or_csv(record_payload)

        existing_urls.add(url_norm)
        new_jobs_added += 1

        # Autofill application if score meets minimum threshold
        if score >= min_ats_score and url:
            if applied_attempts >= max_applications:
                print(f"[Scanner] ⏸️ Reached maximum application limit ({max_applications}) for this run. Remaining qualified matches are saved to tracker.")
            else:
                applied_attempts += 1
                print(f"[Scanner] 🚀 Dispatching application ({applied_attempts}/{max_applications})...")
                await apply_to_job(
                    url=url,
                    candidate=candidate,
                    resume_path=pdf_to_submit,
                    title=title,
                    company=company,
                    auto_submit=disable_guardrails
                )

    print(f"\n[Scanner] ✅ Scan complete! Discovered & processed {new_jobs_added} new postings ({direct_applied_count} direct applied, {tailored_count} tailored).")


if __name__ == "__main__":
    target_url = sys.argv[1] if len(sys.argv) > 1 else None
    asyncio.run(run_pipeline(target_url))
