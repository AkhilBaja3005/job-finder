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
  python scheduled_job_scanner.py "https://www.linkedin.com/jobs/view/4465660238/"
  BROWSER_USE_DISABLE_GUARDRAILS=1 python scheduled_job_scanner.py
"""

import os
import sys
import json
import csv
import asyncio
import re
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Optional, Dict, Any

def format_posted_date_time(raw_post_date: Optional[str]) -> str:
    """
    Standardizes raw posted time strings into a consistent 'date; time' format (e.g. '2026-09-11; 08:30').
    Handles:
    - Relative offsets: '2 hours ago', '1 day ago', '30 minutes ago', 'just now', 'recent', 'today'
    - ISO/Standard timestamps: '2026-09-11 08:30:00', '2026-09-11T08:30'
    - RFC-822 timestamps: 'Thu, 10 Sep 2026 14:30:00 GMT'
    - Date only: '2026-09-11' -> '2026-09-11; 00:00'
    """
    now = datetime.now()
    if not raw_post_date or not raw_post_date.strip():
        return now.strftime("%Y-%m-%d; %H:%M")

    raw = raw_post_date.strip()
    raw_lower = raw.lower()

    # Relative handling: 'just now', 'recent', 'today', 'active'
    if raw_lower in ("recent", "just now", "today", "active", "new"):
        return now.strftime("%Y-%m-%d; %H:%M")

    if raw_lower == "yesterday":
        return (now - timedelta(days=1)).strftime("%Y-%m-%d; %H:%M")

    # Relative handling: 'X minutes/hours/days/weeks/months ago'
    rel_match = re.search(r"(\d+)\s*\+?\s*(minute|min|hour|hr|day|week|month)s?\s*ago", raw_lower)
    if rel_match:
        val = int(rel_match.group(1))
        unit = rel_match.group(2)
        if "min" in unit:
            dt = now - timedelta(minutes=val)
        elif "hour" in unit or "hr" in unit:
            dt = now - timedelta(hours=val)
        elif "day" in unit:
            dt = now - timedelta(days=val)
        elif "week" in unit:
            dt = now - timedelta(weeks=val)
        elif "month" in unit:
            dt = now - timedelta(days=val * 30)
        else:
            dt = now
        return dt.strftime("%Y-%m-%d; %H:%M")

    # Try RFC-822 (e.g. RSS feed dates like 'Thu, 10 Sep 2026 14:30:00 GMT')
    try:
        dt = parsedate_to_datetime(raw)
        return dt.strftime("%Y-%m-%d; %H:%M")
    except Exception:
        pass

    # Try common ISO/standard date/time strings
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y",
        "%b %d, %Y",
        "%B %d, %Y"
    ):
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.strftime("%Y-%m-%d; %H:%M")
        except ValueError:
            continue

    # Fallback to current date; time if unparseable
    return now.strftime("%Y-%m-%d; %H:%M")


def normalize_job_url(u: Optional[str]) -> str:
    """
    Normalizes a job URL for consistent deduplication across Supabase, CSV, and search results.
    Preserves unique job keys for query-based platforms like Indeed (jk=) and LinkedIn (currentJobId=)
    instead of stripping the query and causing all Indeed jobs to collapse into '.../viewjob'.
    """
    if not u or not u.strip():
        return ""
    raw = u.strip().rstrip("/").lower()
    if "jk=" in raw:
        m = re.search(r'jk=([a-f0-9]{16})', raw)
        if m:
            domain = "uk.indeed.com" if "uk.indeed.com" in raw else "indeed.com"
            return f"{domain}/viewjob?jk={m.group(1)}"
    if "currentjobid=" in raw:
        m = re.search(r'currentjobid=(\d+)', raw)
        if m:
            return f"linkedin.com/jobs/view/{m.group(1)}"
    return raw.split("?")[0].rstrip("/").lower()

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
from services.email_service import send_notification_email
from services.job_searcher import normalize_timeframe
from services.scraper import scrape_job_description
from services.ats_scorer import compute_ats_score, compute_overall_score, estimate_role_fit_score
from services.auth import async_supabase_request, supabase_request, SUPABASE_URL, SUPABASE_KEY
import subprocess


def find_master_resume_with_mac_tags() -> str:
    """
    Finds the master resume PDF by checking macOS color tags in iCloud Drive.
    Irrespective of the file name, any PDF tagged with 'Red' is prioritized as the master resume.
    Falls back to Resume_Akhil_Baja.pdf or repository master resume if no Red-tagged PDF exists.
    """
    icloud_folder = "/Users/akhilbaja/Library/Mobile Documents/com~apple~CloudDocs/UK/Imperial/Job Info/Master Resume"
    explicit_fallback = os.path.join(icloud_folder, "Resume_Akhil_Baja.pdf")

    if os.path.exists(icloud_folder):
        try:
            # 1. Scan every PDF file in the folder for the 'Red' macOS tag
            for fname in sorted(os.listdir(icloud_folder)):
                if fname.lower().endswith(".pdf"):
                    full_p = os.path.join(icloud_folder, fname)
                    res = subprocess.run(["mdls", "-name", "kMDItemUserTags", full_p], capture_output=True, text=True)
                    out = res.stdout or ""
                    # Check specifically for "Red" tag (case-insensitive)
                    if "red" in out.lower():
                        print(f"[Master Resume] 🏷️ Found Red-tagged master resume: {full_p}")
                        return full_p
        except Exception as e:
            print(f"[Master Resume] Note: macOS tag inspection failed ({e}), checking fallback paths.")

    # 2. Fallback if no Red tag was found
    if os.path.exists(explicit_fallback):
        print(f"[Master Resume] 📄 No Red-tagged PDF found; falling back to: {explicit_fallback}")
        return explicit_fallback

    # 3. Secondary fallback to repository master resume
    repo_fallback = _get_default_resume_path()
    if repo_fallback and os.path.exists(repo_fallback):
        print(f"[Master Resume] 📄 Falling back to repo master resume: {repo_fallback}")
        return repo_fallback

    return explicit_fallback


def evaluate_pdf_ats(pdf_path: str, jd_text: str, candidate_info: dict) -> int:
    """
    Extracts text from a compiled resume PDF and deterministically computes its overall ATS score against a JD.
    Uses full taxonomy skill extraction from both the parsed PDF text and structured sections.
    """
    try:
        from services.resume_parser import extract_text_from_pdf
        from services.ats_scorer import compute_ats_score, compute_overall_score, estimate_role_fit_score, _extract_taxonomy_skills

        raw_text = extract_text_from_pdf(pdf_path)
        if not raw_text:
            return 0

        # Extract skills using the full canonical taxonomy from the PDF text directly
        extracted_taxonomy_skills = list(_extract_taxonomy_skills(raw_text))

        # Also capture any explicitly formatted skills lines as fallback
        extracted_skills = list(extracted_taxonomy_skills)
        for line in raw_text.split("\n"):
            if any(k in line.lower() for k in ["languages:", "ai/ml", "data & platforms:", "software & infrastructure:", "systems & devops:", "tools:", "skills:"]):
                parts = line.split(":", 1)
                if len(parts) > 1:
                    extracted_skills.extend([s.strip() for s in parts[1].split(",") if s.strip()])

        skills = list(dict.fromkeys(extracted_skills)) if extracted_skills else candidate_info.get("core_skills", [])

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
        return compute_overall_score(ats.skills_score, ats.experience_score, rf)
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
            user_id = cand.get("user_id") or 34

            pdf_p = record_data.get("pdf_path")
            pdf_url = None
            if pdf_p and os.path.exists(pdf_p):
                try:
                    import shutil
                    from services.session_store import USER_DATA_DIR
                    user_out_dir = os.path.join(USER_DATA_DIR, str(user_id), "output")
                    os.makedirs(user_out_dir, exist_ok=True)
                    dest_name = os.path.basename(pdf_p)
                    dest_file = os.path.join(user_out_dir, dest_name)
                    if not os.path.exists(dest_file) or os.path.getsize(dest_file) != os.path.getsize(pdf_p):
                        shutil.copy2(pdf_p, dest_file)
                    pdf_url = f"/download_application_pdf/{user_id}/{dest_name}"

                    # Asynchronously mirror to Hugging Face bucket if HF_TOKEN is configured
                    hf_tok = os.getenv("HF_TOKEN")
                    if hf_tok:
                        try:
                            # pyrefly: ignore [missing-import]
                            from huggingface_hub import HfFileSystem
                            hfs = HfFileSystem(token=hf_tok)
                            bucket_dest = f"buckets/abaja/job-finder-storage/user_data/{user_id}/output/{dest_name}"
                            hfs.put_file(dest_file, bucket_dest)
                        except Exception as hfe:
                            pass
                except Exception as cpy_err:
                    print(f"[Scanner] Note: Could not copy PDF to user output dir: {cpy_err}")

            payload = {
                "user_id": int(user_id),
                "job_title": record_data.get("job_title", "Role"),
                "company": record_data.get("company", "Company"),
                "job_url": record_data.get("job_url", ""),
                "score": int(record_data.get("overall_ats", 0)),
                "status": record_data.get("status", "saved"),
                "source_mode": record_data.get("platform", "scanner"),
            }
            if pdf_url:
                payload["pdf_url"] = pdf_url
            if record_data.get("recruiter"):
                payload["recruiter_name"] = record_data.get("recruiter")
            if record_data.get("recruiter_linkedin"):
                payload["recruiter_profile_url"] = record_data.get("recruiter_linkedin")

            # Check if this job_url exists in Supabase to update or insert
            url_filter = f"applications?job_url=eq.{record_data.get('job_url', '')}"
            existing = await async_supabase_request(url_filter, "GET")
            if existing and len(existing) > 0:
                patch_payload = {"status": payload["status"], "score": payload["score"]}
                if pdf_url:
                    patch_payload["pdf_url"] = pdf_url
                await async_supabase_request(url_filter, "PATCH", patch_payload)
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


async def update_application_status(job_url: str, new_status: str, notes: Optional[str] = None):
    """
    Updates the status of an existing application in Supabase and the CSV tracker.
    """
    if not job_url:
        return

    # 1. Update Supabase
    if SUPABASE_URL and SUPABASE_KEY:
        try:
            url_filter = f"applications?job_url=eq.{job_url}"
            patch_payload = {"status": new_status}
            await async_supabase_request(url_filter, "PATCH", patch_payload)
        except Exception as se:
            print(f"[Tracker] Note: Could not update status in Supabase: {se}")

    # 2. Update CSV Tracker
    if os.path.exists(CSV_PATH):
        try:
            rows = []
            headers = []
            url_norm = job_url.strip().split("?")[0].rstrip("/").lower()
            with open(CSV_PATH, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                headers = next(reader, [])
                for r in reader:
                    if len(r) >= 19:
                        r_url = r[18].strip().split("?")[0].rstrip("/").lower()
                        if r_url == url_norm:
                            r[17] = new_status
                    rows.append(r)

            if headers:
                with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(headers)
                    writer.writerows(rows)
        except Exception as ce:
            print(f"[Tracker] Note: Could not update status in CSV: {ce}")


def notify_user_of_failed_applications(failed_jobs: list, to_email: Optional[str] = None) -> bool:
    """
    Dispatches an email alert to the user listing all applications that failed or need manual review.
    """
    if not failed_jobs:
        return False

    recipient = to_email or os.getenv("NOTIFY_EMAIL") or "akhilbaja.work@gmail.com"
    subject = f"⚠️ Job Finder Alert: User Review Needed for {len(failed_jobs)} Application(s)"

    # Build plain text summary
    text_lines = [
        f"Hi Akhil,",
        f"",
        f"During the recent job application run, {len(failed_jobs)} application(s) could not be submitted automatically and require your review:",
        f""
    ]
    for idx, f in enumerate(failed_jobs, 1):
        text_lines.append(f"{idx}. {f.get('title', 'Role')} @ {f.get('company', 'Company')}")
        text_lines.append(f"   URL: {f.get('url', '')}")
        text_lines.append(f"   Reason: {f.get('reason', 'Submission could not be completed')}")
        text_lines.append("")
    text_lines.append("Please open the links above to inspect the forms and complete submission.")
    text_body = "\n".join(text_lines)

    # Build HTML summary
    table_rows = "".join([
        f"""<tr>
            <td style="padding: 10px; border-bottom: 1px solid #e2e8f0;"><b>{f.get('title', 'Role')}</b></td>
            <td style="padding: 10px; border-bottom: 1px solid #e2e8f0;">{f.get('company', 'Company')}</td>
            <td style="padding: 10px; border-bottom: 1px solid #e2e8f0; color: #e53e3e;">{f.get('reason', 'Submission unconfirmed')}</td>
            <td style="padding: 10px; border-bottom: 1px solid #e2e8f0;">
                <a href="{f.get('url', '')}" style="background-color: #3182ce; color: white; padding: 6px 12px; text-decoration: none; border-radius: 4px; font-weight: 500; font-size: 13px;" target="_blank">Review & Submit</a>
            </td>
        </tr>"""
        for f in failed_jobs
    ])

    html_body = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; max-width: 680px; margin: 0 auto; padding: 20px; border: 1px solid #e2e8f0; border-radius: 8px;">
        <h2 style="color: #c53030; margin-top: 0;">⚠️ User Review Needed: Unable to Submit Applications</h2>
        <p style="color: #4a5568; font-size: 15px;">
            The autonomous job scanner attempted to apply for the following <b>{len(failed_jobs)}</b> role(s), but encountered form validation errors, unselected required fields, or unconfirmed submissions:
        </p>
        <table style="width: 100%; border-collapse: collapse; margin: 20px 0; font-size: 14px; text-align: left;">
            <thead>
                <tr style="background-color: #f7fafc; color: #4a5568;">
                    <th style="padding: 10px; border-bottom: 2px solid #cbd5e0;">Job Title</th>
                    <th style="padding: 10px; border-bottom: 2px solid #cbd5e0;">Company</th>
                    <th style="padding: 10px; border-bottom: 2px solid #cbd5e0;">Issue / Reason</th>
                    <th style="padding: 10px; border-bottom: 2px solid #cbd5e0;">Action</th>
                </tr>
            </thead>
            <tbody>
                {table_rows}
            </tbody>
        </table>
        <p style="color: #718096; font-size: 13px; margin-top: 24px;">
            These applications have been marked as <code>Needs Review (Unsubmitted)</code> in your tracker ledger.
        </p>
    </div>
    """

    print(f"\n[Email Alert] 📧 Sending 'User Review Needed' email for {len(failed_jobs)} failed application(s) to {recipient}...")
    try:
        sent = send_notification_email(
            to_email=recipient,
            subject=subject,
            text_body=text_body,
            html_body=html_body
        )
        if sent:
            print(f"[Email Alert] ✅ Notification email sent successfully to {recipient}!")
        else:
            print(f"[Email Alert] ⚠️ Failed to send notification email to {recipient}.")
        return sent
    except Exception as ee:
        print(f"[Email Alert] ❌ Error sending notification email: {ee}")
        return False


def get_existing_tracked_urls() -> set:
    """
    Collects normalized URLs of jobs already tracked or applied to.
    Checks both Supabase ('applications' table) and local CSV tracker.
    """
    urls = set()

    # 1. Check Supabase applications table if configured
    if SUPABASE_URL and SUPABASE_KEY:
        try:
            records = supabase_request("applications?select=job_url", "GET")
            if records and isinstance(records, list):
                for row in records:
                    u = row.get("job_url")
                    if u:
                        norm = normalize_job_url(u)
                        if norm:
                            urls.add(norm)
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
                        norm = normalize_job_url(u)
                        if norm:
                            urls.add(norm)
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
    headless = os.getenv("BROWSER_USE_HEADLESS", "false").lower() in ("1", "true", "yes")
    from config.constants import get_best_flash_lite_model
    selected_model = get_best_flash_lite_model()
    # Safe execution timeout for each job filling session (default: 300s / 5 minutes, or BROWSER_USE_TIMEOUT env)
    timeout_seconds = float(os.getenv("BROWSER_USE_TIMEOUT", "300"))
    try:
        res = await asyncio.wait_for(
            run_browser_use_autofill(
                job_url=url,
                resume_data=candidate,
                resume_pdf_path=resume_path,
                headless=headless,
                model_name=selected_model,
                auto_submit=auto_submit,
                max_steps=50
            ),
            timeout=timeout_seconds
        )
        print(f"[Browser-Use] Result: {res}")
        return res
    except asyncio.TimeoutError:
        err_msg = f"Job application autofill timed out after {int(timeout_seconds)}s."
        print(f"[Browser-Use] ⏱️ {err_msg}")
        return {
            "status": "failed",
            "job_url": url,
            "error": err_msg,
            "final_result": f"SUBMISSION_FAILED: {err_msg}"
        }
    except Exception as be:
        print(f"[Browser-Use] ❌ Autofill error: {be}")
        return {
            "status": "failed",
            "job_url": url,
            "error": str(be),
            "final_result": f"SUBMISSION_FAILED: {be}"
        }


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
    raw_timeframe = prefs.get("timeframe", "48h")
    timeframe = normalize_timeframe(raw_timeframe)
    min_ats_score = int(prefs.get("min_ats_score", 65))
    DIRECT_APPLY_ATS_THRESHOLD = 80  # >= 80%: apply directly with master resume without tailoring
    max_apps_env = os.getenv("MAX_APPLICATIONS_PER_RUN", "0").strip()
    max_applications = int(max_apps_env) if max_apps_env.isdigit() else 0
    max_apps_str = "No limit (unlimited)" if max_applications <= 0 else str(max_applications)

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 🚀 Starting scheduled unified scan...")
    print(f"Target roles: {keywords}")
    print(f"Location: {location} | Timeframe: {timeframe}")
    print(f"Rule: >= {DIRECT_APPLY_ATS_THRESHOLD}% ATS -> Direct apply (Master Resume)")
    print(f"Rule: {min_ats_score}% - {DIRECT_APPLY_ATS_THRESHOLD - 1}% ATS -> Tailor 1-page LaTeX & PDF, then apply")
    print(f"Database Target: Supabase (`applications` table) with CSV backup")
    print(f"Max Applications Cap: {max_apps_str}")
    print(f"Guardrails Disabled: {disable_guardrails}\n")

    # Run full multi-source web discovery (Portals + LinkedIn + Indeed + Reed)
    search_res = await handle_search_jobs({
        "keywords": keywords,
        "location": location,
        "timeframe": timeframe
    })

    jobs = search_res.get("jobs", [])
    est_jobs = search_res.get("est_jobs", [])
    
    # Merge Indeed est_jobs if not already present in scored jobs
    existing_scored_urls = {normalize_job_url(j.get("url", "")) for j in jobs if j.get("url")}
    merged_count = 0
    for ej in est_jobs:
        u_norm = normalize_job_url(ej.get("url", ""))
        if u_norm and u_norm not in existing_scored_urls:
            jobs.append(ej)
            existing_scored_urls.add(u_norm)
            merged_count += 1

    print(f"\n[Scanner] 📊 Total unique postings discovered and queued: {len(jobs)} ({len(jobs) - merged_count} primary scored + {merged_count} from Indeed/EST)")

    existing_urls = get_existing_tracked_urls()
    print(f"[Scanner] 🔍 Found {len(existing_urls)} previously tracked/applied job URLs across Supabase and CSV.")
    new_jobs_added = 0
    tailored_count = 0
    direct_applied_count = 0
    applied_attempts = 0
    failed_applications = []

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
        raw_posted = job.get("posted_date") or job.get("post_date_raw") or "Recent"
        posted_time = format_posted_date_time(raw_posted)

        recruiter_name = job.get("recruiter_name") or ""
        recruiter_url = job.get("recruiter_url") or ""

        url_norm = normalize_job_url(url)
        is_duplicate = url_norm in existing_urls

        if is_duplicate:
            print(f"[{idx}/{len(jobs)}] Skipping existing: {title} @ {company} ({score}% ATS)")
            continue

        # Decide Application & Tailoring Strategy
        pdf_to_submit = master_resume_pdf
        tex_path = ""
        jd_text = job.get("description") or ""

        # If job description is missing or a brief placeholder (common for Indeed RSS / title-heuristic jobs),
        # fetch the real JD on-demand via the scraper so ATS scoring & tailoring have 100% full content.
        if (not jd_text or len(jd_text.strip()) < 100 or job.get("estimated", False)) and url:
            try:
                print(f"[{idx}/{len(jobs)}] 📥 Fetching live JD on-demand for {title} @ {company} ({platform})...")
                live_scraped = await scrape_job_description(url)

                # Check if Playwright got blocked by Cloudflare / Turnstile
                is_blocked = live_scraped.get("is_bot_blocked", False) if isinstance(live_scraped, dict) else False
                scraped_jd = (live_scraped.get("description") or "").strip() if isinstance(live_scraped, dict) else ""

                # If bot-blocked or empty, and running locally, attempt browser-use fallback to solve Turnstile
                is_cloud = any(os.getenv(v) for v in ("RENDER", "RAILWAY_ENVIRONMENT", "RAILWAY_PROJECT_ID", "FLY_APP_NAME", "SPACE_ID", "HF_SPACE_ID")) or os.getenv("ENVIRONMENT") == "production"
                if (is_blocked or not scraped_jd or len(scraped_jd) < 100) and not is_cloud:
                    print(f"[{idx}/{len(jobs)}] 🛡️ Cloudflare verification detected on Indeed. Activating local browser-use agent to solve Turnstile...")
                    try:
                        from services.browser_use_agent import extract_jd_with_browser_use
                        # Bound browser-use JD extraction to a safe 60s timeout
                        bu_res = await asyncio.wait_for(extract_jd_with_browser_use(url), timeout=60.0)
                        if bu_res and bu_res.get("description") and len(bu_res.get("description", "")) >= 100:
                            live_scraped = bu_res
                            scraped_jd = bu_res["description"].strip()
                            is_blocked = False
                            print(f"[{idx}/{len(jobs)}] ⚡ browser-use successfully solved Turnstile and retrieved JD!")
                    except asyncio.TimeoutError:
                        print(f"[{idx}/{len(jobs)}] ⏱️ browser-use JD extraction timed out after 60s, keeping original listing info.")
                    except Exception as bu_err:
                        print(f"[{idx}/{len(jobs)}] browser-use JD extraction note: {bu_err}")

                # Only accept scraped result if it is NOT a bot-block page and has a substantial description
                if scraped_jd and len(scraped_jd) >= 100 and not is_blocked:
                    jd_text = scraped_jd
                    job["description"] = jd_text
                    scraped_title = live_scraped.get("title", "").strip()
                    # Protect original title: NEVER overwrite with error/fallback strings like 'Unavailable' or 'Not found'
                    invalid_titles = ("indeed job", "job posting", "unavailable", "not found", "just a moment", "target job", "cloudflare verification error")
                    if scraped_title and scraped_title.lower() not in invalid_titles:
                        title = scraped_title
                    scraped_company = live_scraped.get("company", "").strip()
                    if scraped_company and scraped_company.lower() not in ("indeed employer", "company", "not found", ""):
                        company = scraped_company

                    # Compute real deterministic ATS score with candidate profile
                    cand_resume_data = {
                        "name": candidate.get("name"),
                        "location": candidate.get("location"),
                        "skills": candidate.get("core_skills", []),
                        "experience": [
                            {"role": e.get("role", ""), "company": e.get("company", ""), "description": e.get("highlights", [])}
                            for e in candidate.get("work_experience", [])
                        ],
                        "raw_text": ""
                    }
                    ats_res = compute_ats_score(cand_resume_data, jd_text)
                    rf_res = estimate_role_fit_score(cand_resume_data, jd_text)
                    score = compute_overall_score(ats_res.skills_score, ats_res.experience_score, rf_res)
                    matched_skills = ", ".join(ats_res.matched_skills)
                    missing_skills = ", ".join(ats_res.missing_skills)
                    job["ats_score"] = score
                    job["score"] = score
                    job["matched_skills"] = ats_res.matched_skills
                    job["missing_skills"] = ats_res.missing_skills
                    job["skills_score"] = ats_res.skills_score
                    job["exp_score"] = ats_res.experience_score
                    job["role_fit_score"] = rf_res
                    job["estimated"] = False
                    print(f"   ✓ Successfully retrieved JD ({len(jd_text)} chars). Recomputed ATS Score: {score}% (Skills: {ats_res.skills_score}%, Exp: {ats_res.experience_score}%)")
                else:
                    print(f"   ℹ️ Live JD blocked or incomplete, keeping original title '{title}' and estimate ({score}%).")
            except Exception as jd_err:
                print(f"   ⚠️ Could not fetch live JD on-demand ({jd_err}), using current score ({score}%).")

        if score >= DIRECT_APPLY_ATS_THRESHOLD:
            # 🎯 DIRECT APPLY (>= 80% ATS match)
            status = "Ready to Apply"
            print(f"\n[{idx}/{len(jobs)}] 🌟 EXCELLENT MATCH ({score}% >= {DIRECT_APPLY_ATS_THRESHOLD}%): {title} @ {company}")
            print(f"   ⚡ Direct Apply mode: Using master resume (no tailoring needed)")
            direct_applied_count += 1
        elif score >= min_ats_score:
            # 🛠️ TAILOR & APPLY (65% - 79% ATS match)
            status = "Tailored & Ready"
            print(f"\n[{idx}/{len(jobs)}] 🎯 QUALIFIED MATCH ({score}% ATS): {title} @ {company}")
            print(f"   📝 Tailoring 1-page LaTeX resume for keyword & skills alignment...")
            if jd_text:
                try:
                    job_missing = job.get("missing_skills") or []
                    # Bound tailoring & compiling to a safe 90s timeout
                    pdf_res = await asyncio.wait_for(
                        asyncio.to_thread(
                            build_and_compile_tailored_pdf,
                            jd_text=jd_text,
                            job_title=title,
                            company=company,
                            candidate_info=candidate,
                            out_dir=RESUMES_DIR,
                            missing_skills=job_missing
                        ),
                        timeout=90.0
                    )
                    if pdf_res and os.path.exists(pdf_res):
                        tailored_ats = evaluate_pdf_ats(pdf_res, jd_text, candidate)
                        # Apples-to-apples: score the master PDF using the identical PDF text evaluator if exists, else fallback to score
                        master_pdf_score = evaluate_pdf_ats(master_resume_pdf, jd_text, candidate) if (master_resume_pdf and os.path.exists(master_resume_pdf)) else score
                        master_ats = master_pdf_score or score
                        print(f"   📊 ATS Score Comparison: Tailored PDF = {tailored_ats}% vs Master PDF = {master_ats}%")
                        if tailored_ats >= master_ats:
                            pdf_to_submit = pdf_res
                            tex_path = pdf_res.replace(".pdf", ".tex")
                            score = tailored_ats
                            tailored_count += 1
                            print(f"   ✓ Tailored PDF outperforms master ({tailored_ats}% >= {master_ats}%). Selected: {os.path.basename(pdf_to_submit)}")
                        else:
                            pdf_to_submit = master_resume_pdf
                            print(f"   ℹ️ Master resume scored higher ({master_ats}% > {tailored_ats}%). Keeping master resume: {os.path.basename(pdf_to_submit)}")
                except asyncio.TimeoutError:
                    print(f"   ⏱️ Resume tailoring timed out after 90s. Falling back to master resume.")
                    pdf_to_submit = master_resume_pdf
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
            if max_applications > 0 and applied_attempts >= max_applications:
                print(f"[Scanner] ⏸️ Reached maximum application limit ({max_applications}) for this run. Remaining qualified matches are saved to tracker.")
            else:
                applied_attempts += 1
                disp_total = str(max_applications) if max_applications > 0 else "∞"
                print(f"[Scanner] 🚀 Dispatching application ({applied_attempts}/{disp_total})...")
                res = await apply_to_job(
                    url=url,
                    candidate=candidate,
                    resume_path=pdf_to_submit,
                    title=title,
                    company=company,
                    auto_submit=disable_guardrails
                )

                # Post-Submission Verification Check
                res_status = res.get("status") if isinstance(res, dict) else ""
                final_res = str(res.get("final_result", "")) if isinstance(res, dict) else ""

                if disable_guardrails:
                    if res_status == "success":
                        print(f"   ✅ Application verified & submitted successfully for {title} @ {company}")
                        await update_application_status(url, "applied")
                    else:
                        fail_reason = final_res or "Form validation error or unconfirmed submission"
                        print(f"   ⚠️ Submission verification failed for {title} @ {company}: {fail_reason}")
                        await update_application_status(url, "Needs Review (Unsubmitted)")
                        failed_applications.append({
                            "title": title,
                            "company": company,
                            "url": url,
                            "reason": fail_reason[:150]
                        })
                else:
                    await update_application_status(url, "Ready to Apply (Reviewed)")

    print(f"\n[Scanner] ✅ Scan complete! Discovered & processed {new_jobs_added} new postings ({direct_applied_count} direct applied, {tailored_count} tailored).")

    # Send summary email alert if any applications failed/need review
    if failed_applications:
        cand_email = candidate.get("email") or "akhilbaja.work@gmail.com"
        notify_user_of_failed_applications(failed_applications, to_email=cand_email)


if __name__ == "__main__":
    target_url = sys.argv[1] if len(sys.argv) > 1 else None
    asyncio.run(run_pipeline(target_url))
