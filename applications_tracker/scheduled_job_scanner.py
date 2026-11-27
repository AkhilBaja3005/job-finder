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
import subprocess
import time
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Optional, Dict, Any

try:
    from applications_tracker.outcomes import daily_cap, submitted_today
except ImportError:  # run as a script from inside applications_tracker/
    from outcomes import daily_cap, submitted_today  # type: ignore


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


# pyrefly: ignore [missing-import]
try:
    if not os.environ.get("JOB_FINDER_ROOT"):
        from dotenv import load_dotenv  # type: ignore
        load_dotenv()
        if os.path.exists(".env"):
            load_dotenv(".env")
except ImportError:
    pass

# Ensure backend directory is discoverable
_this_dir = os.path.dirname(os.path.abspath(__file__))
_repo_candidate = os.path.dirname(_this_dir)
for candidate_backend in [
    os.path.join(_repo_candidate, "backend"),
    os.path.join(os.getcwd(), "backend"),
    _this_dir
]:
    if os.path.isdir(candidate_backend) and candidate_backend not in sys.path:
        sys.path.insert(0, candidate_backend)

from config.constants import (
    resolve_workspace_root,
    get_applications_tracker_dir,
    get_tailored_resumes_dir,
    get_tracker_csv_path
)
from services.excel_tracker import ExcelTracker, approved_path, normalize_job_url, record_from_payload  # noqa: E402
from services import closing_date as closing_date_utils  # noqa: E402
from services.role_spec import resolve_spec  # noqa: E402
from services import fit_scorer  # noqa: E402
from services import job_level  # noqa: E402

JOB_FINDER_ROOT = resolve_workspace_root()
BACKEND_DIR = os.path.join(JOB_FINDER_ROOT, "backend")
TRACKER_DIR = get_applications_tracker_dir()
RESUMES_DIR = get_tailored_resumes_dir()
CSV_PATH = get_tracker_csv_path()

if BACKEND_DIR not in sys.path and os.path.isdir(BACKEND_DIR):
    sys.path.insert(0, BACKEND_DIR)


# Core backend imports
# pyrefly: ignore [missing-import]
from job_finder_mcp.tools.discovery_tools import handle_search_jobs  # type: ignore
from job_finder_mcp.tools.profile_tools import load_profile_data  # type: ignore
from job_finder_mcp.tools.tracking_tools import handle_track_application  # type: ignore
from job_finder_mcp.tools.autofill_tools import build_and_compile_tailored_pdf, _get_default_resume_path  # type: ignore
from job_finder_mcp.tools.ats_tools import handle_calculate_ats_score  # type: ignore
from services.browser_use_agent import run_browser_use_autofill  # type: ignore
from services.email_service import send_notification_email  # type: ignore
from services.job_searcher import normalize_timeframe  # type: ignore
from services.scraper import scrape_job_description  # type: ignore
from services.ats_scorer import compute_ats_score, compute_overall_score, estimate_role_fit_score  # type: ignore
from services.auth import async_supabase_request, supabase_request, SUPABASE_URL, SUPABASE_KEY  # type: ignore
try:
    from applications_tracker.linkedin_top_applicant_scanner import is_top_applicant_badge  # type: ignore
except ImportError:
    try:
        from linkedin_top_applicant_scanner import is_top_applicant_badge  # type: ignore
    except ImportError:
        def is_top_applicant_badge(text: str) -> bool:  # type: ignore
            return False



def find_master_resume_with_mac_tags() -> str:
    """
    Finds the master resume PDF by checking macOS color tags in iCloud Drive or custom directories.
    Irrespective of the file name, any PDF tagged with 'Red' is prioritized as the master resume.
    Falls back to user-configured directory, repo master resume, or sample resume if no Red-tagged PDF exists.
    """
    custom_master = os.getenv("MASTER_RESUME_PATH")
    if custom_master and os.path.exists(custom_master):
        return custom_master

    search_folders = []
    env_dir = os.getenv("MASTER_RESUME_DIR")
    if env_dir:
        search_folders.append(os.path.expanduser(env_dir))

    # Standard macOS iCloud Drive path if present
    home_dir = os.path.expanduser("~")
    icloud_base = os.path.join(home_dir, "Library", "Mobile Documents", "com~apple~CloudDocs")
    if os.path.exists(icloud_base):
        # Check potential resume directories under iCloud
        search_folders.extend([
            os.path.join(icloud_base, "UK", "Imperial", "Job Info", "Master Resume"),
            os.path.join(icloud_base, "Master Resume"),
            os.path.join(icloud_base, "Resumes")
        ])

    # Check each candidate folder
    for folder in search_folders:
        try:
            if os.path.exists(folder):
                # Check for Red-tagged files on macOS if mdls tool is available
                if sys.platform == "darwin":
                    for fname in sorted(os.listdir(folder)):
                        if fname.lower().endswith(".pdf"):
                            full_p = os.path.join(folder, fname)
                            try:
                                res = subprocess.run(["mdls", "-name", "kMDItemUserTags", full_p], capture_output=True, text=True)
                                out = res.stdout or ""
                                if "red" in out.lower():
                                    print(f"[Master Resume] Found Red-tagged master resume: {full_p}")
                                    return full_p
                            except Exception:
                                pass

                # Check for any PDF in candidate folder
                for fname in sorted(os.listdir(folder)):
                    if fname.lower().endswith(".pdf"):
                        return os.path.join(folder, fname)
        except Exception as e:
            print(f"[Master Resume] Note: Folder inspection in '{folder}' skipped: {e}")

    # Secondary fallback to repository master resume or local output
    repo_fallback = _get_default_resume_path()
    if repo_fallback and os.path.exists(repo_fallback):
        print(f"[Master Resume] Using detected resume: {repo_fallback}")
        return repo_fallback

    return repo_fallback or ""


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

                    # Asynchronously mirror to Hugging Face bucket in a non-blocking background thread
                    hf_tok = os.getenv("HF_TOKEN")
                    if hf_tok:
                        def _upload_hf(src, dst, tok):
                            try:
                                # pyrefly: ignore [missing-import]
                                from huggingface_hub import HfFileSystem  # type: ignore
                                hfs = HfFileSystem(token=tok)
                                hfs.put_file(src, dst)
                            except Exception:
                                pass
                        asyncio.create_task(asyncio.to_thread(_upload_hf, dest_file, f"buckets/abaja/job-finder-storage/user_data/{user_id}/output/{dest_name}", hf_tok))
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
            print(f"[Supabase] Synced error: {se}. Falling back to CSV.")

    # Record to the Excel tracker (source of truth)
    try:
        rec = record_from_payload(record_data)
        notes = [record_data.get("notes") or ""]
        if record_data.get("pdf_path"):
            notes.append(f"Resume: {record_data['pdf_path']}")
        if record_data.get("latex_path"):
            notes.append(f"LaTeX: {record_data['latex_path']}")
        rec["Notes"] = " | ".join(n for n in notes if n)
        added, skipped = ExcelTracker().add_jobs([rec])
        dest = "Supabase + Excel" if supabase_synced else "Excel tracker"
        verb = "Recorded" if added else "Already tracked, not duplicated"
        print(f"   {verb}: {dest} (Status: {record_data.get('status')})")
    except Exception as ce:
        print(f"[Excel Tracker] Error saving application: {ce}")


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

    # 2. Update the Excel tracker
    try:
        fields = {"status": new_status}
        if notes:
            fields["notes"] = notes
        ExcelTracker().update(url=job_url, **fields)
    except Exception as ce:
        print(f"[Tracker] Note: Could not update status in Excel tracker: {ce}")


def notify_user_of_failed_applications(failed_jobs: list, to_email: Optional[str] = None) -> bool:
    """
    Dispatches an email alert to the user listing all applications that failed or need manual review.
    """
    if not failed_jobs:
        return False

    recipient = to_email or os.getenv("NOTIFY_EMAIL") or ""
    if not recipient:
        print("[Notify] No recipient configured (set NOTIFY_EMAIL or candidate email); skipping email.")
        return False
    subject = f"Job Finder Alert: User Review Needed for {len(failed_jobs)} Application(s)"

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
        <h2 style="color: #c53030; margin-top: 0;">User Review Needed: Unable to Submit Applications</h2>
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

    print(f"\n[Email Alert] Sending 'User Review Needed' email for {len(failed_jobs)} failed application(s) to {recipient}...")
    try:
        sent = send_notification_email(
            to_email=recipient,
            subject=subject,
            text_body=text_body,
            html_body=html_body
        )
        if sent:
            print(f"[Email Alert] Notification email sent successfully to {recipient}!")
        else:
            print(f"[Email Alert] Failed to send notification email to {recipient}.")
        return sent
    except Exception as ee:
        print(f"[Email Alert] Error sending notification email: {ee}")
        return False


def notify_user_of_applied_applications(applied_jobs: list, to_email: Optional[str] = None) -> bool:
    """
    Dispatches a confirmation email alert to the user listing all applications successfully submitted.
    """
    if not applied_jobs:
        return False

    recipient = to_email or os.getenv("NOTIFY_EMAIL") or ""
    if not recipient:
        print("[Notify] No recipient configured (set NOTIFY_EMAIL or candidate email); skipping email.")
        return False
    subject = f"Job Finder Success: {len(applied_jobs)} Application(s) Submitted Successfully!"

    # Build plain text summary
    cand_name = "Candidate"
    try:
        from backend.job_finder_mcp.tools.profile_tools import load_profile_data
        prof = load_profile_data() or {}
        cand_name = prof.get("candidate", {}).get("name", "Candidate").split()[0]
    except Exception:
        pass

    text_lines = [
        f"Hi {cand_name},",
        f"",
        f"Great news! During the recent job application run, {len(applied_jobs)} application(s) were submitted successfully:",
        f""
    ]
    for idx, f in enumerate(applied_jobs, 1):
        text_lines.append(f"{idx}. {f.get('title', 'Role')} @ {f.get('company', 'Company')}")
        text_lines.append(f"   URL: {f.get('url', '')}")
        if f.get('ats_score'):
            text_lines.append(f"   ATS Compatibility: {f.get('ats_score')}%")
        text_lines.append("")
    text_lines.append("These applications are recorded in your application ledger with tailored resume backups.")
    text_body = "\n".join(text_lines)

    # Build HTML summary
    table_rows = "".join([
        f"""<tr>
            <td style="padding: 10px; border-bottom: 1px solid #e2e8f0;"><b>{f.get('title', 'Role')}</b></td>
            <td style="padding: 10px; border-bottom: 1px solid #e2e8f0;">{f.get('company', 'Company')}</td>
            <td style="padding: 10px; border-bottom: 1px solid #e2e8f0; color: #2b6cb0; font-weight: 600;">{f.get('ats_score', 'N/A')}% ATS</td>
            <td style="padding: 10px; border-bottom: 1px solid #e2e8f0;">
                <a href="{f.get('url', '')}" style="background-color: #38a169; color: white; padding: 6px 12px; text-decoration: none; border-radius: 4px; font-weight: 500; font-size: 13px;" target="_blank">View Listing</a>
            </td>
        </tr>"""
        for f in applied_jobs
    ])

    html_body = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; max-width: 680px; margin: 0 auto; padding: 20px; border: 1px solid #e2e8f0; border-radius: 8px;">
        <h2 style="color: #276749; margin-top: 0;">Applications Submitted Successfully!</h2>
        <p style="color: #4a5568; font-size: 15px;">
            The autonomous job scanner successfully tailored your resume and submitted <b>{len(applied_jobs)}</b> application(s):
        </p>
        <table style="width: 100%; border-collapse: collapse; margin: 20px 0; font-size: 14px; text-align: left;">
            <thead>
                <tr style="background-color: #f0fff4; color: #22543d;">
                    <th style="padding: 10px; border-bottom: 2px solid #9ae6b4;">Job Title</th>
                    <th style="padding: 10px; border-bottom: 2px solid #9ae6b4;">Company</th>
                    <th style="padding: 10px; border-bottom: 2px solid #9ae6b4;">Match</th>
                    <th style="padding: 10px; border-bottom: 2px solid #9ae6b4;">Listing</th>
                </tr>
            </thead>
            <tbody>
                {table_rows}
            </tbody>
        </table>
        <p style="color: #718096; font-size: 13px; margin-top: 24px;">
            All tailored PDF resumes and application metadata have been logged to your application tracker.
        </p>
    </div>
    """

    print(f"\n[Email Alert] Sending 'Application Submitted' email for {len(applied_jobs)} applied role(s) to {recipient}...")
    try:
        sent = send_notification_email(
            to_email=recipient,
            subject=subject,
            text_body=text_body,
            html_body=html_body
        )
        if sent:
            print(f"[Email Alert] Applied confirmation email sent successfully to {recipient}!")
        else:
            print(f"[Email Alert] Failed to send applied confirmation email to {recipient}.")
        return sent
    except Exception as ee:
        print(f"[Email Alert] Error sending applied confirmation email: {ee}")
        return False


def get_existing_tracked_urls() -> set:
    """
    Collects normalized URLs of jobs already tracked or applied to.
    Checks both Supabase ('applications' table) and the local Excel tracker.
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

    # 2. Check the Excel tracker
    try:
        scanned = ExcelTracker()
        urls |= scanned.known_urls()
        urls |= ExcelTracker(approved_path(scanned.path)).known_urls()
    except Exception as ce:
        print(f"[Tracker] Note: Could not read Excel tracker: {ce}")

    return urls


async def apply_to_job(
    url: str,
    candidate: dict,
    resume_path: Optional[str] = None,
    title: str = "Role",
    company: str = "Company",
    auto_submit: bool = False,
    timeout_seconds: Optional[float] = None,
    max_steps: Optional[int] = None,
    model_name: Optional[str] = None,
    headless_override: Optional[bool] = None
):
    print(f"\n[Browser-Use] Launching browser autofill for: {title} @ {company}")
    print(f"[Browser-Use] URL: {url}")
    print(f"[Browser-Use] Resume: {resume_path}")
    print(f"[Browser-Use] Guardrails: {'Disabled (Auto-Submit Enabled)' if (auto_submit or os.getenv('BROWSER_USE_DISABLE_GUARDRAILS') in ('1', 'true', 'True')) else 'Enabled (Preview Mode)'}")
    headless = headless_override if headless_override is not None else (os.getenv("BROWSER_USE_HEADLESS", "false").lower() in ("1", "true", "yes"))
    from config.constants import get_best_flash_lite_model
    selected_model = model_name or get_best_flash_lite_model()
    # Safe execution timeout for each job filling session (default: 300s / 5 minutes, or BROWSER_USE_TIMEOUT env)
    active_timeout = timeout_seconds or float(os.getenv("BROWSER_USE_TIMEOUT", "300"))
    active_steps = max_steps or int(os.getenv("BROWSER_USE_MAX_STEPS", "50"))
    try:
        res = await asyncio.wait_for(
            run_browser_use_autofill(
                job_url=url,
                resume_data=candidate,
                resume_pdf_path=resume_path,
                headless=headless,
                model_name=selected_model,
                auto_submit=auto_submit,
                max_steps=active_steps
            ),
            timeout=active_timeout
        )
        print(f"[Browser-Use] Result: {res}")
        return res
    except (KeyboardInterrupt, asyncio.CancelledError):
        skip_msg = "User skipped application via Ctrl+C."
        print(f"\n[Browser-Use] ⏭Skip signal (Ctrl+C) received! Aborting application for {company} and advancing to next role...")
        return {
            "status": "failed",
            "job_url": url,
            "error": skip_msg,
            "final_result": f"SUBMISSION_SKIPPED: {skip_msg}"
        }
    except asyncio.TimeoutError:
        err_msg = f"Job application autofill timed out after {int(active_timeout)}s."
        print(f"[Browser-Use] ⏱{err_msg}")
        return {
            "status": "failed",
            "job_url": url,
            "error": err_msg,
            "final_result": f"SUBMISSION_FAILED: {err_msg}"
        }
    except Exception as be:
        print(f"[Browser-Use] Autofill error: {be}")
        return {
            "status": "failed",
            "job_url": url,
            "error": str(be),
            "final_result": f"SUBMISSION_FAILED: {be}"
        }


async def discover_jobs(
    target_roles: list,
    location: str,
    timeframe: str,
    prefs: dict,
    skip_portals: Optional[str] = None,
    top_applicant_only: Optional[bool] = None,
    headless: Optional[bool] = None,
    title_filter: Optional[Any] = None,
    use_boards: bool = True,
):
    """
    Multi-source discovery (ATS portals + LinkedIn + Indeed + Reed + Jobserve + community threads).
    Returns ``(jobs, merged_count)``. Shared by `scan` (discover only) and the legacy full pipeline.
    """
    keywords = ", ".join(target_roles)
    jobs = []
    merged_count = 0

    if top_applicant_only:
        print("[Scanner] Running in LinkedIn Top Applicant Only mode...")
        try:
            from applications_tracker.linkedin_top_applicant_scanner import scan_linkedin_for_top_applicant_jobs
        except ImportError:
            from linkedin_top_applicant_scanner import scan_linkedin_for_top_applicant_jobs  # type: ignore

        tf_hours = 24 if timeframe in ("24h", "1d") else (48 if timeframe in ("48h", "2d") else 168)
        existing_urls_pre = get_existing_tracked_urls()
        top_jobs = await scan_linkedin_for_top_applicant_jobs(
            keywords_list=target_roles,
            location=location,
            timeframe_hours=tf_hours,
            existing_urls=existing_urls_pre,
            headless=headless if headless is not None else False
        )
        for tj in top_jobs:
            tj["is_top_applicant"] = True
            tj["ats_score"] = 95
            tj["source"] = "LinkedIn (Top Applicant)"
        jobs = top_jobs
    else:
        # Run full multi-source web discovery (Portals + LinkedIn + Indeed + Reed)
        excluded_list = []
        if skip_portals:
            if skip_portals.strip().lower() in ("none", "false", "0"):
                excluded_list = []
            else:
                excluded_list.extend([p.strip().lower() for p in skip_portals.split(",") if p.strip()])
        else:
            p_skip = prefs.get("skip_portals") if "skip_portals" in prefs else prefs.get("exclude_portals")
            if isinstance(p_skip, list):
                excluded_list.extend([str(p).strip().lower() for p in p_skip if str(p).strip()])
            elif isinstance(p_skip, str):
                excluded_list.extend([p.strip().lower() for p in p_skip.split(",") if p.strip()])
            elif p_skip is None:
                # Default exclusion: targetjobs is skipped by default
                excluded_list.append("targetjobs")

            env_skip = os.getenv("SKIP_PORTALS") or os.getenv("EXCLUDE_PORTALS")
            if env_skip:
                excluded_list.extend([p.strip().lower() for p in env_skip.split(",") if p.strip()])

        # An EMPTY list means "skip nothing" (e.g. --skip-portals none); None would fall back to the default,
        # which silently excludes TargetJobs (a UK graduate/internship board).
        skip_nothing = bool(skip_portals and skip_portals.strip().lower() in ("none", "false", "0")) or \
            (not skip_portals and isinstance(prefs.get("skip_portals", prefs.get("exclude_portals")), list)
             and not prefs.get("skip_portals", prefs.get("exclude_portals")))
        excluded_list = list(dict.fromkeys(excluded_list)) if excluded_list else ([] if skip_nothing else None)
        if excluded_list:
            print(f"[Scanner] Skipping excluded portal(s): {', '.join(excluded_list)}")
        search_res = await handle_search_jobs({
            "keywords": keywords,
            "location": location,
            "timeframe": timeframe,
            "exclude_portals": excluded_list
        })

        jobs = search_res.get("jobs", [])
        est_jobs = search_res.get("est_jobs", [])
        
        # Merge Indeed est_jobs if not already present in scored jobs
        existing_scored_urls = {normalize_job_url(j.get("url", "")) for j in jobs if j.get("url")}
        for ej in est_jobs:
            u_norm = normalize_job_url(ej.get("url", ""))
            if u_norm and u_norm not in existing_scored_urls:
                jobs.append(ej)
                existing_scored_urls.add(u_norm)
                merged_count += 1

        # Agent-Reach: Discover unlisted community jobs (Reddit, Hacker News "Who is Hiring")
        try:
            from services.agent_reach_service import fetch_reddit_hiring_threads
            comm_res = fetch_reddit_hiring_threads(role=target_roles[0] if target_roles else "Software Engineer", location=location)
            for cjob in comm_res.get("community_jobs", []):
                u_norm = normalize_job_url(cjob.get("url", ""))
                if u_norm and u_norm not in existing_scored_urls:
                    jobs.append({
                        "title": cjob.get("title"),
                        "company": "Reddit / Hacker News Community",
                        "url": cjob.get("url"),
                        "platform": "Reddit / Agent-Reach",
                        "ats_score": 85,
                        "description": cjob.get("excerpt", "")
                    })
                    existing_scored_urls.add(u_norm)
                    merged_count += 1
        except Exception as comm_err:
            print(f"[Scanner] Note: Community unlisted job search skipped: {comm_err}")
    # ── extra sources: the company-board index (thousands of Greenhouse/Lever/Ashby boards) + Adzuna (if keyed) ──
    if not top_applicant_only:
        have = {normalize_job_url(j.get("url", "")) for j in jobs if j.get("url")}
        extra: list = []
        if use_boards:
            try:
                from services import board_index as _bi
                if title_filter is None:      # no topic filter: match on the words of the searched roles
                    words = {w.lower() for r in target_roles for w in re.findall(r"[A-Za-z]{3,}", r)} - {"intern", "internship", "engineer", "senior"}
                    title_filter = lambda t: any(w in (t or "").lower() for w in words)  # noqa: E731
                found, st = _bi.search(title_filter, location)
                if st["boards"] == 0:
                    print("[Sources] Company-board index is empty: run `job-finder boards refresh` once to search "
                          "thousands of Greenhouse / Lever / Ashby boards.")
                else:
                    print(f"[Sources] Company boards: {st['boards']} boards indexed, {st['local_jobs']} open jobs in "
                          f"{location.split(',')[0]}, {st['matched']} match your topic.")
                    age = (_bi.status().get("age_hours") or 0)
                    if age > 72:
                        print(f"[Sources] The company-board index is {age / 24:.0f} days old: run `job-finder boards refresh` (about 6 minutes).")
                extra += found
            except Exception as be:
                print(f"[Sources] Company-board index skipped: {be}")
        try:
            from services import aggregators as _ag
            if _ag.adzuna_configured():
                az = await _ag.search_adzuna(target_roles, location, timeframe)
                print(f"[Sources] Adzuna: {len(az)} postings.")
                extra += az
            else:
                print("[Sources] Adzuna not configured (free key: ADZUNA_APP_ID / ADZUNA_APP_KEY in .env).")
        except Exception as ae:
            print(f"[Sources] Adzuna skipped: {ae}")
        added_extra = 0
        for j in extra:
            u = normalize_job_url(j.get("url", ""))
            if u and u not in have:
                have.add(u)
                jobs.append(j)
                added_extra += 1
        merged_count += added_extra
    return jobs, merged_count


_DIRECT_HOSTS = ("greenhouse.io", "lever.co", "ashbyhq.com", "workable.com", "smartrecruiters.com", "myworkdayjobs.com", "bamboohr.com")


def _is_direct(job: dict) -> bool:
    """A link on the employer's own applicant-tracking system (best to apply through) rather than an aggregator."""
    u = (job.get("url") or "").lower()
    src = str(job.get("source") or job.get("platform") or "").lower()
    # Greenhouse/Lever often return links on the employer's OWN domain (e.g. company.com/careers?gh_jid=1), so also
    # trust postings that came from an ATS board API rather than from an aggregator.
    return any(h in u for h in _DIRECT_HOSTS) or any(a in src for a in ("greenhouse", "lever", "ashby", "workday", "bamboo", "workable"))


def _dup_key(job: dict) -> str:
    norm = lambda x: re.sub(r"[^a-z0-9]+", " ", str(x or "").lower()).strip()  # noqa: E731
    return norm(job.get("company")) + "|" + norm(job.get("title"))


IRRELEVANT_TITLE_KEYWORDS = (
    "accountant", "nursing", "nurse", "sales representative", "telemarketing",
    "cook", "chef", "cashier", "cleaner", "driver", "warehouse worker",
    "construction", "plumber", "electrician", "retail assistant", "dental",
    "store manager", "receptionist", "hairdresser", "security officer", "call center",
)


def _candidate_resume_data(candidate: dict) -> dict:
    """Candidate profile in the shape the ATS scorer expects."""
    return {
        "name": candidate.get("name"),
        "location": candidate.get("location"),
        "skills": candidate.get("core_skills", []),
        "experience": [
            {"role": e.get("role", ""), "company": e.get("company", ""), "description": e.get("highlights", [])}
            for e in candidate.get("work_experience", [])
        ],
        "raw_text": "",
    }


async def fetch_live_jd_and_score(job: dict, candidate: dict, timeout: float = 30.0) -> bool:
    """
    Fetch the real job description for `job` (when the listing only had a stub) and score it against
    the candidate. Mutates `job` in place; returns True if a real JD was retrieved and scored.
    Never opens a visible browser: bot-blocked pages are simply left with their estimated score.
    """
    url = job.get("url") or job.get("apply_url", "")
    if not url:
        return False
    try:
        live = await asyncio.wait_for(scrape_job_description(url), timeout=timeout)
    except Exception:
        return False
    if not isinstance(live, dict) or live.get("is_bot_blocked"):
        return False
    jd_text = (live.get("description") or "").strip()
    if len(jd_text) < 100:
        return False

    job["description"] = jd_text
    invalid_titles = ("indeed job", "job posting", "unavailable", "not found", "just a moment", "target job", "cloudflare verification error")
    scraped_title = (live.get("title") or "").strip()
    if scraped_title and scraped_title.lower() not in invalid_titles:
        job["title"] = scraped_title
    scraped_company = (live.get("company") or "").strip()
    if scraped_company and scraped_company.lower() not in ("indeed employer", "company", "not found"):
        job["company"] = scraped_company

    resume = _candidate_resume_data(candidate)
    ats_res = compute_ats_score(resume, jd_text)
    rf = estimate_role_fit_score(resume, jd_text)
    score = compute_overall_score(ats_res.skills_score, ats_res.experience_score, rf)
    job.update({
        "ats_score": score, "score": score,
        "matched_skills": ats_res.matched_skills, "missing_skills": ats_res.missing_skills,
        "skills_score": ats_res.skills_score, "exp_score": ats_res.experience_score,
        "role_fit_score": rf, "estimated": False,
    })
    return True


def _print_dry_run(jobs, kept, drops, spec, queries, location, timeframe, src_of) -> None:
    """Search-only report: where the postings came from, what each stage removed, and every dropped title with its reason."""
    from collections import Counter
    line = "=" * 78
    print(f"\n{line}\nSEARCH-ONLY DRY RUN  (nothing was written to Excel, nothing was scored)\n{line}")
    print(f"Searched : {', '.join(queries)}")
    print(f"Where    : {location}   Window: {timeframe}")
    if spec:
        print(f"Filter   : {spec.describe()}")
    by_src = Counter(src_of(j) for j in jobs)
    print(f"\nDISCOVERED {len(jobs)} postings, by source:")
    for src, n in by_src.most_common():
        kept_n = sum(1 for k in kept if src_of(k) == src)
        print(f"   {src:<28} {n:>4} found  ->  {kept_n:>3} kept")
    stages = Counter(d[0] for d in drops)
    print(f"\nWHERE THE {len(jobs) - len(kept)} REMOVED POSTINGS WENT:")
    for stage, n in stages.most_common():
        print(f"   {stage:<24} {n:>4}")
    reasons = Counter(d[4].split(" (")[0] for d in drops if d[0] == "topic/level filter")
    if reasons:
        print("   of the topic/level filter:")
        for r, n in reasons.most_common():
            print(f"      - {r:<44} {n:>4}")
    print(f"\nWOULD BE SAVED: {len(kept)}")
    if spec:
        from collections import Counter as _T
        tiers = _T(j.get("_tier") or "Core" for j in kept)
        print(f"   match: Core (the exact niche you asked for) {tiers.get('Core', 0)}   Related (adjacent field, labelled in the Match column) {tiers.get('Related', 0)}"
              + ("   [use --core-only to keep only Core]" if tiers.get("Related") else ""))
    if spec and spec.split:
        from collections import Counter as _C
        tally = _C(job_level.classify(j.get("title") or "", "").bucket for j in kept)
        print("   filed by level (judged from the TITLE only in a dry run; the real scan also reads each description for the years required):")
        print("   " + "   ".join(f"{b}: {tally.get(b, 0)}" for b in ("intern", "graduate", "experienced")))
    for j in sorted(kept, key=lambda x: x.get("_tier") != "Core"):
        print(f"   + {('Core   ' if j.get('_tier') == 'Core' else 'Related') if spec else ''} {str(j.get('title'))[:58]:<58} {str(j.get('company'))[:22]:<22} [{src_of(j)}]")
    print("\nREMOVED BY THE TOPIC/LEVEL FILTER (check these: anything here that you wanted means the filter is too strict):")
    for stage, title, company, src, why in sorted((d for d in drops if d[0] == "topic/level filter"), key=lambda d: d[4]):
        print(f"   x {title[:58]:<58} {company[:20]:<20} [{src[:10]}] {why}")
    others = [d for d in drops if d[0] != "topic/level filter"]
    if others:
        print("\nREMOVED AT OTHER STAGES:")
        for stage, title, company, src, why in others:
            print(f"   x {title[:58]:<58} {company[:20]:<20} [{src[:10]}] {stage}: {why}")
    print(f"{line}\nTo save these for real, run the same command without --dry-run.\n")


def _core_title(title: str, company: str = "") -> str:
    """'Senior Research Scientist, AI Safety (London) - Hybrid' -> 'research scientist ai safety'."""
    t = re.sub(r"\(.*?\)|\[.*?\]", " ", title or "")
    t = re.split(r"\s[-–—|@]\s", t)[0]                           # drop ' - London', ' | Fintech', ' @ Company'
    place = r"london|uk|u\.k\.|united kingdom|england|remote|hybrid|emea|europe|eu|onsite|on-site|full[- ]time|part[- ]time|contract|permanent|fixed[- ]term|ftc"
    t = re.sub(rf"(?<![A-Za-z0-9])({place})(?![A-Za-z0-9])", " ", t, flags=re.I)
    for w in re.findall(r"[A-Za-z0-9]{3,}", company or ""):        # the employer's own name is not a job title word
        if w.lower() not in ("the", "and", "ltd", "limited", "labs", "group", "technologies"):
            t = re.sub(rf"(?<![A-Za-z0-9]){re.escape(w)}(?:'s)?(?![A-Za-z0-9])", " ", t, flags=re.I)
    strip = (r"\b(20\d\d|summer|programme|program|interns?|internships?|graduates?|grad|junior|jr|senior|sr|lead|staff|principal|placement|"
             r"early careers?|entry[- ]level|associate|founding|ii|iii|iv|i)\b")
    parts = [re.sub(r"\s+", " ", re.sub(r"[^A-Za-z0-9+#/ ]+", " ", re.sub(strip, " ", x, flags=re.I))).strip().lower() for x in t.split(",")]
    whole = " ".join(x for x in parts if x)
    out = whole if 2 <= len(whole.split()) <= 5 else (parts[0] if parts else "")
    return out if 2 <= len(out.split()) <= 5 else ""


def _snowball_queries(kept: list, used: set, cap: int = 8, accept=None) -> list:
    """
    New searches taken from the job titles that rounds so far actually found (most common first). `accept` lets the caller
    keep only candidates that themselves name the niche, so a generic 'research scientist' can never steer the search.
    """
    from collections import Counter
    counts = Counter(_core_title(j.get("title") or "", j.get("company") or "") for j in kept)
    counts.pop("", None)
    out = []
    for title, _n in counts.most_common():
        if title in used or (accept is not None and not accept(title)):
            continue
        out.append(title)
        if len(out) >= cap:
            break
    return out


def _known_urls(paths: list) -> set:
    urls: set = set()
    for pth in paths:
        urls |= ExcelTracker(pth).known_urls()
        urls |= ExcelTracker(approved_path(pth)).known_urls()
    return urls


async def run_scan(
    role: Optional[str] = None,
    location_override: Optional[str] = None,
    timeframe_override: Optional[str] = None,
    min_ats: Optional[int] = None,
    limit: Optional[int] = None,
    skip_portals: Optional[str] = None,
    sponsor_only: Optional[bool] = None,
    top_applicant_only: Optional[bool] = None,
    headless: Optional[bool] = None,
    enrich: bool = True,
    concurrency: int = 5,
    topic: Optional[str] = None,
    level: Optional[str] = None,
    request: Optional[str] = None,
    loose: bool = False,
    exact: bool = False,
    ai_score: bool = True,
    dry_run: bool = False,
    use_boards: bool = True,
    targets: Optional[Dict[str, str]] = None,
    expand: int = 1,
    ai_limit: int = 60,
    ai_all: bool = False,
    core_only: bool = False,
) -> dict:
    """
    Discover jobs and save them to the Excel tracker. Nothing is tailored or submitted.

    New jobs are added with Status=New, Applied=No. Already-tracked jobs (same URL, or same
    company + role + location) are skipped. Returns a summary dict.

    What to search for comes from `request` (free text like "quantum computing internships"),
    `topic` / `level`, explicit `role` queries, or the profile's `topics` / `level` / `target_roles`
    (see role_spec.resolve_spec). When a topic or level is in play, postings whose title doesn't fit
    are dropped (`loose` also reads the description; `exact` skips LLM synonym expansion).

    With `targets` ({"intern": path, "graduate": path, "experienced": path}) a level-"all" scan files every job into the
    Excel for its level (judged from the title, then from the years of experience in the description); experienced jobs
    carry the years required. `expand` rounds re-search the job titles found so far to surface related roles.

    `dry_run` is search-only: it searches and filters, prints the whole funnel (every dropped title with its reason),
    and writes nothing (no Excel, no scoring, no LLM calls beyond the topic map).

    Scoring: with `ai_score` (default) each posting's full description is analysed against your profile
    by fit_scorer (evidence-based, cached). Where that is unavailable the old keyword scorer's number is
    kept and labelled "Keyword"; listings with no description are labelled "Listing estimate".
    """
    import httpx

    profile = load_profile_data()
    candidate = profile.get("candidate", {})
    prefs = profile.get("search_preferences", {})

    spec = resolve_spec(topic=topic, level=level, request=request, role=role, prefs=prefs, loose=loose, exact=exact)
    if spec and spec.queries:
        target_roles = spec.queries
    elif role:
        target_roles = [r.strip() for r in role.split(",") if r.strip()]
    else:
        target_roles = prefs.get("target_roles") or ["Software Engineer"]
    target_roles = list(dict.fromkeys(target_roles))
    locations = [location_override] if location_override else prefs.get("target_locations", ["London, UK"])
    location = locations[0] if locations else "London, UK"
    timeframe = normalize_timeframe(timeframe_override or prefs.get("timeframe", "48h"))

    split = bool(spec and spec.split)
    if split and not dry_run and not targets:
        raise ValueError("a level-'all' scan needs `targets` (one Excel per level)")
    trackers = {b: ExcelTracker(pth) for b, pth in (targets or {}).items()} if split else {}
    tracker = ExcelTracker() if not trackers else next(iter(trackers.values()))
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Scan (discover only; nothing will be applied to)")
    print(f"Searching: {', '.join(target_roles)}")
    if spec:
        shown = spec.topic_terms[:14]
        print(f"Keeping titles that fit  [{spec.describe()}]" + (f"  matching: {', '.join(shown)}{' ...' if len(spec.topic_terms) > 14 else ''}" if shown else ""))
    print(f"Location: {location} | Timeframe: {timeframe} | " +
          (("Excel per level: " + ", ".join(f"{b}" for b in trackers)) if trackers else f"Tracker: {tracker.path}") + "\n")

    closed = 0 if dry_run else sum(t.mark_expired() for t in (trackers.values() or [tracker]))
    if closed:
        print(f"[Tracker] Marked {closed} listing(s) Closed (closing date passed).")

    jobs, _ = await discover_jobs(
        target_roles=target_roles, location=location, timeframe=timeframe, prefs=prefs,
        skip_portals=skip_portals, top_applicant_only=top_applicant_only, headless=headless,
        title_filter=(lambda t: spec.matches(t or "")[0]) if spec else None, use_boards=use_boards,
    )
    print(f"\n[Scan] {len(jobs)} postings discovered across sources.")

    existing = _known_urls([t.path for t in trackers.values()]) if trackers else get_existing_tracked_urls()
    try:
        from services import searches as _searches
        elsewhere = _searches.handled_elsewhere(exclude_scanned=[t.path for t in (trackers.values() or [tracker])])   # url -> search where you already applied
    except Exception:
        elsewhere = {}
    seen = set()
    counts = {"duplicate": 0, "irrelevant": 0, "non_sponsor": 0, "no_url": 0, "not_a_job": 0, "off_topic": 0}
    fresh = []
    dropped = []  # (title, company, reason) for jobs the topic/level filter rejected, shown so you can sanity-check it
    by_key = {}   # company+title -> the kept posting, so the same job from two sites is saved once
    drops = []    # every job removed at any stage: (stage, title, company, source, reason)
    src_of = lambda j: str(j.get("source") or j.get("platform") or "?")  # noqa: E731
    check_uk_sponsor = None
    try:
        from services.uk_sponsor_service import check_uk_sponsor  # type: ignore
    except Exception:
        pass
    def _filter_into(job_list):
        """Run postings through every filter, adding survivors to `fresh` and every removal to `drops`."""
        for job in job_list:
            url = job.get("url") or job.get("apply_url", "")
            if not url:
                counts["no_url"] += 1
                drops.append(("no link", job.get("title") or "", job.get("company") or "", src_of(job), "posting has no URL"))
                continue
            # Community threads (Reddit / HN) are leads, not postings: no company, nothing `apply` can fill in.
            if any(tag in str(job.get("platform") or job.get("source") or "").lower() for tag in ("reddit", "agent-reach", "hacker news")):
                counts["not_a_job"] += 1
                drops.append(("community thread", job.get("title") or "", job.get("company") or "", src_of(job), "Reddit/HN lead, not a posting"))
                continue
            norm = normalize_job_url(url)
            if norm in elsewhere and norm not in existing:
                counts["duplicate"] += 1
                drops.append(("applied elsewhere", job.get("title") or "", job.get("company") or "", src_of(job),
                              f"you already applied to this in search '{elsewhere[norm]}'"))
                continue
            if norm in existing or norm in seen:
                counts["duplicate"] += 1
                drops.append(("already tracked", job.get("title") or "", job.get("company") or "", src_of(job),
                              "already in your tracker" if norm in existing else "same job seen twice in this scan"))
                continue
            seen.add(norm)
            if any(bad in (job.get("title") or "").lower() for bad in IRRELEVANT_TITLE_KEYWORDS):
                counts["irrelevant"] += 1
                drops.append(("irrelevant title", job.get("title") or "", job.get("company") or "", src_of(job), "non-technical title"))
                continue
            if spec:
                fits, _why = spec.matches(job.get("title") or "", job.get("description") or "")
                if fits:
                    job["_tier"] = spec.tier(job.get("title") or "")
                    if core_only and job["_tier"] != "Core":
                        fits, _why = False, "related field, not the exact niche (--core-only)"
                if not fits:
                    counts["off_topic"] += 1
                    dropped.append((job.get("title") or "", job.get("company") or "", _why))
                    drops.append(("topic/level filter", job.get("title") or "", job.get("company") or "", src_of(job), _why))
                    continue
            sponsor = ""
            if check_uk_sponsor:
                try:
                    sponsor = "Yes" if check_uk_sponsor(job.get("company") or "").get("is_sponsor") else "No"
                except Exception:
                    sponsor = ""
            if sponsor_only and sponsor != "Yes":
                counts["non_sponsor"] += 1
                drops.append(("not a UK sponsor", job.get("title") or "", job.get("company") or "", src_of(job), "company not on the sponsor register"))
                continue
            job["_uk_sponsor"] = sponsor
            key = _dup_key(job)
            if key in by_key:
                prev = by_key[key]
                if _is_direct(job) and not _is_direct(prev):
                    fresh[fresh.index(prev)] = job            # keep the employer's own link, drop the aggregator copy
                    drops.append(("same job, other site", prev.get("title") or "", prev.get("company") or "", src_of(prev),
                                  f"kept the direct {src_of(job)} link instead"))
                    by_key[key] = job
                else:
                    drops.append(("same job, other site", job.get("title") or "", job.get("company") or "", src_of(job),
                                  f"already have it from {src_of(prev)}"))
                counts["duplicate"] += 1
                continue
            by_key[key] = job
            fresh.append(job)

    _filter_into(jobs)

    # ── expansion: search the job titles the results actually contain, to find related roles you did not type ──
    all_jobs = list(jobs)
    if expand and spec and spec.topics and not top_applicant_only:
        used_queries = {q.lower() for q in target_roles} | {t.lower() for t in spec.topics}
        for rnd in range(1, expand + 1):
            more_q = _snowball_queries([j for j in fresh if j.get("_tier", "Core") == "Core"], used_queries, cap=8,
                                       accept=lambda q: spec.tier(q) == "Core")   # learn from the exact niche only
            if not more_q:
                break
            print(f"[Expand] round {rnd}: also searching {len(more_q)} job titles found so far: {', '.join(more_q)}")
            more, _ = await discover_jobs(
                target_roles=more_q, location=location, timeframe=timeframe, prefs=prefs, skip_portals=skip_portals,
                top_applicant_only=top_applicant_only, headless=headless,
                title_filter=(lambda t: spec.matches(t or "")[0]), use_boards=False)
            used_queries |= {q.lower() for q in more_q}
            before = len(fresh)
            _filter_into(more)
            all_jobs += more
            print(f"[Expand] round {rnd}: {len(more)} more postings, {len(fresh) - before} new relevant ones")
    jobs = all_jobs

    if dry_run:
        _print_dry_run(jobs, fresh, drops, spec, target_roles, location, timeframe, src_of)
        return {"added": 0, "duplicates": counts["duplicate"], "discovered": len(jobs), "would_save": len(fresh), "path": None}

    # Enrich concurrently: real JD where the listing was a stub, then the level (intern / graduate / experienced + years
    # required), AI fit analysis (intern + graduate only, to protect the LLM quota), then the closing date.
    live_scored = 0
    ai_scored = 0
    ai_attempts = 0
    done = 0
    enriched = len(fresh) if enrich else 0
    if enrich and fresh:
        print(f"[Scan] Reading {len(fresh)} postings: descriptions, level and years required, fit score, closing date...")
        sem = asyncio.Semaphore(concurrency)
        llm_sem = asyncio.Semaphore(3)
        async with httpx.AsyncClient(timeout=8.0, headers={"User-Agent": "Mozilla/5.0 (job-finder scan)"}) as client:
            async def _enrich(job: dict):
                nonlocal live_scored, ai_scored, ai_attempts, done
                async with sem:
                    stub = len((job.get("description") or "").strip()) < 100 or job.get("estimated", False)
                    if stub and not job.get("is_top_applicant"):
                        if await fetch_live_jd_and_score(job, candidate):
                            live_scored += 1
                    has_jd = len((job.get("description") or "").strip()) >= 100
                    lv = job_level.classify(job.get("title") or "", job.get("description") if has_jd else "")
                    job["_level"] = lv
                    wants_ai = (has_jd and ai_score and not job.get("is_top_applicant")
                                and (ai_all or lv.bucket in ("intern", "graduate")) and ai_attempts < ai_limit)
                    if wants_ai:
                        ai_attempts += 1
                        async with llm_sem:
                            if await fit_scorer.score_job(job, candidate, lv.bucket if lv.bucket in ("intern", "graduate") else None):
                                ai_scored += 1
                    if not job.get("scoring"):
                        job["scoring"] = "Keyword" if has_jd else "Listing estimate"
                    cd = closing_date_utils.from_job(job)
                    if not cd and job.get("llm_closing_date"):
                        cd = closing_date_utils.parse_date(job["llm_closing_date"])
                    if not cd:
                        cd = await closing_date_utils.fetch_closing_date(job.get("url") or "", client)
                    if cd:
                        job["closing_date"] = cd.isoformat()
                    done += 1
                    if done % 25 == 0:
                        print(f"[Scan]   ... {done}/{len(fresh)} postings read")
            await asyncio.gather(*[_enrich(j) for j in fresh], return_exceptions=True)

    def _score(j: dict) -> int:
        return int(j.get("ats_score") or j.get("score") or 0)

    below = 0
    if min_ats is not None:
        kept = [j for j in fresh if _score(j) >= min_ats]
        below = len(fresh) - len(kept)
        fresh = kept
    fresh.sort(key=_score, reverse=True)
    if limit and limit > 0:
        fresh = fresh[:limit]

    records, record_buckets = [], []
    for job in fresh:
        stub = len((job.get("description") or "").strip()) < 100 or job.get("estimated", False)
        lv = job.get("_level") or job_level.classify(job.get("title") or "", "" if stub else (job.get("description") or ""))
        ms, xs = job.get("matched_skills") or [], job.get("missing_skills") or []
        knockout = job.get("knockout")
        note = ("ATS is an estimate from the listing (full JD not retrieved)" if stub
                else ("Scored by the keyword engine" + (" (AI scoring unavailable)" if ai_score else "")
                      if job.get("scoring") == "Keyword" else ""))
        if knockout:
            note = f"Knockout: {knockout}"
        record_buckets.append(lv.bucket)
        records.append(record_from_payload({
            "company": job.get("company") or "", "job_title": job.get("title") or "",
            "location": job.get("location") or location, "platform": job.get("source") or job.get("platform") or "Web",
            "posted_time": format_posted_date_time(job.get("posted_date") or job.get("post_date_raw") or "Recent"),
            "closing_date": job.get("closing_date"), "overall_ats": _score(job),
            "skills_match": job.get("skills_score"), "experience_match": job.get("exp_score"),
            "role_fit": job.get("role_fit_score"),
            "matched_skills": ", ".join(ms) if isinstance(ms, list) else ms,
            "missing_skills": ", ".join(xs) if isinstance(xs, list) else xs,
            "uk_sponsor": job.get("_uk_sponsor"), "seniority": job.get("seniority"), "salary": job.get("salary"),
            "role_level": lv.tag, "years_exp": lv.years_label, "match": job.get("_tier") or "",
            "job_url": job.get("url") or job.get("apply_url"), "status": "Skipped" if knockout else "New",
            "scored_by": job.get("scoring") or ("Listing estimate" if stub else "Keyword"),
            "fit_summary": job.get("fit_summary") or "", "notes": note,
        }))

    by_bucket: Dict[str, list] = {}
    dup_in_sheet = 0
    if split:
        grouped: Dict[str, list] = {b: [] for b in trackers}
        for rec, b in zip(records, record_buckets):
            grouped[b if b in grouped else "experienced"].append(rec)
        for b, recs in grouped.items():
            got, dups = trackers[b].add_jobs(recs) if recs else ([], 0)
            by_bucket[b] = got
            dup_in_sheet += dups
        added = [r for rows in by_bucket.values() for r in rows]
    else:
        added, dup_in_sheet = tracker.add_jobs(records)

    with_deadline = sum(1 for r in added if r.get("Closing Date"))
    print("\n" + "=" * 60)
    print(f"[Scan] Added {len(added)} new job(s)"
          + (f" ({with_deadline} with a closing date)" if added else ""))
    print(f"       Skipped: {counts['duplicate'] + dup_in_sheet} already tracked, {counts['irrelevant']} irrelevant titles"
          + (f", {counts['off_topic']} off topic/level" if spec else "")
          + (f", {counts['not_a_job']} community threads (not postings)" if counts["not_a_job"] else "")
          + (f", {counts['non_sponsor']} non-sponsor" if sponsor_only else "")
          + (f", {below} below ATS {min_ats}%" if min_ats is not None else ""))
    if dropped:
        print(f"       Dropped by the topic/level filter (first {min(len(dropped), 12)} of {len(dropped)}):")
        for t, c, why in dropped[:12]:
            print(f"         x {t[:58]:<58} {c[:22]:<22} [{why}]")
        print("       Wrong? Try --loose (reads descriptions too), or list alternatives with commas,")
        print("       e.g. --topic \"AI security, cyber security\" (a multi-word topic needs ALL its words in the title).")
    if enrich:
        print(f"       Scoring: {ai_scored} AI fit analysis, {live_scored} descriptions newly fetched, out of {enriched} new postings"
              + ("" if ai_score else " (AI scoring off)")
              + ("; experienced roles use the keyword score unless --score-all" if split and ai_score else "")
              + (f"; {enriched - ai_scored} keyword/listing estimates (see 'Scored By')" if ai_score and enriched > ai_scored and not split else ""))
        knocked = [r for r in added if r.get("Status") == "Skipped"]
        if knocked:
            print(f"       {len(knocked)} marked Skipped because you fail a hard requirement (see Notes).")
    if split:
        print("\n       FILED BY LEVEL (each has its own Excel):")
        for b in ("intern", "graduate", "experienced"):
            if b in trackers:
                print(f"         {b:<12} {len(by_bucket.get(b, [])):>4} new   {trackers[b].path}")
    else:
        print(f"       Tracker: {tracker.path}")
    for r in added[:10]:
        print(f"   #{r['ID']:<4} {str(r.get('ATS %') if r.get('ATS %') is not None else '--'):>3}%  {str(r.get('Scored By') or '')[:7]:<7} {str(r.get('Company'))[:24]:<24} {str(r.get('Job Role'))[:44]}")
    if len(added) > 10:
        print(f"   ... and {len(added) - 10} more")
    if added:
        print("\nNext steps:")
        print("  1. open an Excel and set  Approve = Yes  on the jobs you want:   ./jf open --search NAME   (./jf searches lists them)")
        print("  2. move them into the approved queue:                            ./jf approve --search NAME")
        print("  3. preview, then submit:                                         ./jf apply --dry-run   |   ./jf apply --submit")
    else:
        print("\nNothing new to review.")
    return {"added": len(added), "duplicates": counts["duplicate"] + dup_in_sheet, "discovered": len(jobs),
            "path": tracker.path, "by_bucket": {b: len(v) for b, v in by_bucket.items()}}


async def run_pipeline(
    target_url: Optional[str] = None,
    timeout: float = 300.0,
    tailor_timeout: float = 90.0,
    max_steps: int = 50,
    max_apps: Optional[int] = None,
    min_ats: Optional[int] = None,
    role: Optional[str] = None,
    location_override: Optional[str] = None,
    timeframe_override: Optional[str] = None,
    model_override: Optional[str] = None,
    headless: Optional[bool] = None,
    auto_submit_override: Optional[bool] = None,
    top_applicant_only: Optional[bool] = None,
    sponsor_only: Optional[bool] = None,
    skip_portals: Optional[str] = None
):
    profile = load_profile_data()
    candidate = profile.get("candidate", {})
    prefs = profile.get("search_preferences", {})

    disable_guardrails = (
        auto_submit_override
        if auto_submit_override is not None
        else os.getenv("BROWSER_USE_DISABLE_GUARDRAILS") in ("1", "true", "True")
    )
    master_resume_pdf = find_master_resume_with_mac_tags()

    # Dynamic configurable timeouts (defaults: 300s autofill, 90s tailoring)
    autofill_timeout = timeout or float(os.getenv("BROWSER_USE_TIMEOUT", "300"))
    resume_tailor_timeout = tailor_timeout or float(os.getenv("TAILORING_TIMEOUT", "90"))
    steps_limit = max_steps or int(os.getenv("BROWSER_USE_MAX_STEPS", "50"))

    # Mode A: Direct application to single job URL passed via CLI
    if target_url:
        print(f"[2026-09-10] Targeting single job URL: {target_url}")
        res = await apply_to_job(
            url=target_url,
            candidate=candidate,
            resume_path=master_resume_pdf,
            title="Target Role",
            company="Company",
            auto_submit=disable_guardrails,
            timeout_seconds=autofill_timeout,
            max_steps=steps_limit,
            model_name=model_override,
            headless_override=headless
        )
        cand_email = candidate.get("email") or os.getenv("NOTIFY_EMAIL", "")
        res_status = res.get("status") if isinstance(res, dict) else ""
        final_res = str(res.get("final_result", "")) if isinstance(res, dict) else ""
        if disable_guardrails and res_status == "success":
            notify_user_of_applied_applications([{
                "title": "Target Role",
                "company": "Company",
                "url": target_url,
                "ats_score": 95
            }], to_email=cand_email)
        else:
            notify_user_of_failed_applications([{
                "title": "Target Role",
                "company": "Company",
                "url": target_url,
                "reason": final_res or "Guardrails enabled / Unsubmitted preview"
            }], to_email=cand_email)
        return

    # Mode B: Unified Multi-Source Discovery, Selective Tailoring & Application
    raw_target_roles = [role] if role else prefs.get("target_roles", [
        "AI Engineer",
        "Generative AI Engineer",
        "Machine Learning Engineer",
        "AI Systems Engineer",
        "Applied AI Scientist"
    ])
    # Deduplicate target roles while preserving order
    target_roles = list(dict.fromkeys(raw_target_roles))
    # Optional hard title filter, e.g. ["intern", "internship", "placement"]. Whole-word, case-insensitive.
    _req_kw = prefs.get("required_title_keywords") or []
    if isinstance(_req_kw, str):
        _req_kw = [k.strip() for k in _req_kw.split(",") if k.strip()]
    required_title_re = (
        re.compile(r"\b(?:" + "|".join(re.escape(str(k).lower()) + "s?" for k in _req_kw) + r")\b")
        if _req_kw else None
    )
    keywords = ", ".join(target_roles)
    target_locations = [location_override] if location_override else prefs.get("target_locations", ["London, UK"])
    location = target_locations[0] if target_locations else "London, UK"
    raw_timeframe = timeframe_override or prefs.get("timeframe", "48h")
    timeframe = normalize_timeframe(raw_timeframe)
    min_ats_score = int(min_ats if min_ats is not None else prefs.get("min_ats_score", prefs.get("min_ats_score_threshold", 65)))
    DIRECT_APPLY_ATS_THRESHOLD = 80  # >= 80%: apply directly with master resume without tailoring
    max_apps_env = os.getenv("MAX_APPLICATIONS_PER_RUN", "0").strip()
    max_applications = max_apps if max_apps is not None else (int(max_apps_env) if max_apps_env.isdigit() else 0)
    max_apps_str = "No limit (unlimited)" if max_applications <= 0 else str(max_applications)

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Starting scheduled unified scan...")
    print(f"Target roles: {keywords}")
    print(f"Location: {location} | Timeframe: {timeframe}")
    if sponsor_only:
        print(f"Filter: 🇬🇧 Strict Sponsor-Only Mode Active (Only verified Home Office licensed employers)")
    print(f"Rule: LinkedIn Top Applicant Match -> Direct apply (Master Resume, Zero JD scoring/tailoring)")
    print(f"Rule: >= {DIRECT_APPLY_ATS_THRESHOLD}% ATS -> Direct apply (Master Resume)")
    print(f"Rule: {min_ats_score}% - {DIRECT_APPLY_ATS_THRESHOLD - 1}% ATS -> Tailor 1-page LaTeX & PDF, then apply")
    print(f"Timeouts: Autofill = {int(autofill_timeout)}s | Tailoring = {int(resume_tailor_timeout)}s | Max Steps = {steps_limit}")
    print(f"Database Target: Supabase (`applications` table) with CSV backup")
    print(f"Max Applications Cap: {max_apps_str}")
    print(f"Guardrails Disabled: {disable_guardrails}\n")

    jobs, merged_count = await discover_jobs(
        target_roles=target_roles,
        location=location,
        timeframe=timeframe,
        prefs=prefs,
        skip_portals=skip_portals,
        top_applicant_only=top_applicant_only,
        headless=headless,
    )

    print(f"\n[Scanner] Total unique postings discovered and queued: {len(jobs)} ({len(jobs) - merged_count} primary scored + {merged_count} from Indeed/EST)")

    existing_urls = get_existing_tracked_urls()
    print(f"[Scanner] Found {len(existing_urls)} previously tracked/applied job URLs across Supabase and CSV.")
    new_jobs_added = 0
    tailored_count = 0
    direct_applied_count = 0
    applied_attempts = 0
    failed_applications = []
    applied_applications = []
    batch_applied_buffer = []
    batch_failed_buffer = []
    cand_email = candidate.get("email") or os.getenv("NOTIFY_EMAIL", "")
    EMAIL_BATCH_SIZE = int(os.getenv("JOB_FINDER_EMAIL_BATCH_SIZE", "20"))

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

        # Relevance Pre-Filter: Discard titles completely outside user's target domain
        title_lower = title.lower()
        irrelevant_keywords = (
            "accountant", "nursing", "nurse", "sales representative", "telemarketing",
            "cook", "chef", "cashier", "cleaner", "driver", "warehouse worker",
            "construction", "plumber", "electrician", "retail assistant", "dental",
            "store manager", "receptionist", "hairdresser", "security officer", "call center"
        )
        if any(bad in title_lower for bad in irrelevant_keywords):
            print(f"[{idx}/{len(jobs)}] ⏭Skipping irrelevant non-technical posting: {title} @ {company}")
            continue

        if required_title_re and not required_title_re.search(title_lower):
            print(f"[{idx}/{len(jobs)}] Skipping title without required keyword ({', '.join(_req_kw)}): {title} @ {company}")
            continue

        # Check UK visa sponsorship status from official Home Office register
        sponsor_badge_log = ""
        is_uk_sponsor = False
        try:
            from services.uk_sponsor_service import check_uk_sponsor
            sp_check = check_uk_sponsor(company)
            is_uk_sponsor = bool(sp_check.get("is_sponsor"))
            if is_uk_sponsor:
                sponsor_badge_log = " [🇬🇧 UK Visa Sponsor]"
            else:
                sponsor_badge_log = " [Not on UK Sponsor Register]"
        except Exception:
            pass

        # If --sponsor-only flag is set, strictly skip companies not found in the sponsor database
        if sponsor_only and not is_uk_sponsor:
            print(f"[{idx}/{len(jobs)}] ⏭Skipping non-sponsor role (--sponsor-only active): {title} @ {company}")
            continue

        # Decide Application & Tailoring Strategy
        pdf_to_submit = master_resume_pdf
        tex_path = ""
        jd_text = job.get("description") or ""

        # Check if LinkedIn designated this posting as a 'Top Applicant' match
        is_top_applicant = (
            job.get("is_top_applicant", False)
            or bool(job.get("badge") and is_top_applicant_badge(str(job.get("badge"))))
            or bool(job.get("badge_text") and is_top_applicant_badge(str(job.get("badge_text"))))
            or bool(is_top_applicant_badge(str(job.get("title_raw") or "")))
            or bool(is_top_applicant_badge(str(job.get("description") or "")[:300]))
            or ("top applicant" in (job.get("source") or "").lower())
            or ("top applicant" in (job.get("platform") or "").lower())
        )

        if is_top_applicant:
            # LINKEDIN TOP APPLICANT DIRECT APPLY
            # Bypass JD scraping, ATS scoring, and tailoring completely
            status = "Top Applicant - Direct Apply"
            score = 95
            matched_skills = matched_skills or "LinkedIn Top Applicant Match"
            job["ats_score"] = 95
            job["score"] = 95
            job["skills_score"] = 95
            job["exp_score"] = 90
            job["role_fit_score"] = 95
            pdf_to_submit = master_resume_pdf
            direct_applied_count += 1
            print(f"\n[{idx}/{len(jobs)}] LINKEDIN TOP APPLICANT MATCH: {title} @ {company}")
            print(f"   Bypassing JD scoring & tailoring — applying directly with Master Resume ({os.path.basename(pdf_to_submit)}).")
        else:
            # If job description is missing or a brief placeholder (common for Indeed RSS / title-heuristic jobs),
            # fetch the real JD on-demand via the scraper so ATS scoring & tailoring have 100% full content.
            if (not jd_text or len(jd_text.strip()) < 100 or job.get("estimated", False)) and url:
                try:
                    print(f"[{idx}/{len(jobs)}] Fetching live JD on-demand for {title} @ {company} ({platform})...")
                    # Bound live scraping to a safe 30s timeout
                    live_scraped = await asyncio.wait_for(scrape_job_description(url), timeout=30.0)

                    # Check if Playwright got blocked by Cloudflare / Turnstile
                    is_blocked = live_scraped.get("is_bot_blocked", False) if isinstance(live_scraped, dict) else False
                    scraped_jd = (live_scraped.get("description") or "").strip() if isinstance(live_scraped, dict) else ""

                    # If bot-blocked or empty, and running locally, attempt browser-use fallback to solve Turnstile
                    is_cloud = any(os.getenv(v) for v in ("RENDER", "RAILWAY_ENVIRONMENT", "RAILWAY_PROJECT_ID", "FLY_APP_NAME", "SPACE_ID", "HF_SPACE_ID")) or os.getenv("ENVIRONMENT") == "production"
                    if (is_blocked or not scraped_jd or len(scraped_jd) < 100) and not is_cloud:
                        print(f"[{idx}/{len(jobs)}] Cloudflare verification detected on Indeed. Activating local browser-use agent to solve Turnstile...")
                        try:
                            from services.browser_use_agent import extract_jd_with_browser_use
                            # Bound browser-use JD extraction to a safe 60s timeout
                            bu_res = await asyncio.wait_for(extract_jd_with_browser_use(url), timeout=60.0)
                            if bu_res and bu_res.get("description") and len(bu_res.get("description", "")) >= 100:
                                live_scraped = bu_res
                                scraped_jd = bu_res["description"].strip()
                                is_blocked = False
                                print(f"[{idx}/{len(jobs)}] browser-use successfully solved Turnstile and retrieved JD!")
                        except asyncio.TimeoutError:
                            print(f"[{idx}/{len(jobs)}] ⏱browser-use JD extraction timed out after 60s, keeping original listing info.")
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
                        print(f"   Successfully retrieved JD ({len(jd_text)} chars). Recomputed ATS Score: {score}% (Skills: {ats_res.skills_score}%, Exp: {ats_res.experience_score}%)")
                    else:
                        print(f"   Live JD blocked or incomplete, keeping original title '{title}' and estimate ({score}%).")
                except Exception as jd_err:
                    print(f"   Could not fetch live JD on-demand ({jd_err}), using current score ({score}%).")

            if score >= DIRECT_APPLY_ATS_THRESHOLD:
                # DIRECT APPLY (>= 80% ATS match)
                status = "Ready to Apply"
                print(f"\n[{idx}/{len(jobs)}] EXCELLENT MATCH ({score}% >= {DIRECT_APPLY_ATS_THRESHOLD}%): {title} @ {company}{sponsor_badge_log}")
                print(f"   Direct Apply mode: Using master resume (no tailoring needed)")
                direct_applied_count += 1
            elif score >= min_ats_score:
                # TAILOR & APPLY (65% - 79% ATS match)
                status = "Tailored & Ready"
                print(f"\n[{idx}/{len(jobs)}] QUALIFIED MATCH ({score}% ATS): {title} @ {company}{sponsor_badge_log}")
                print(f"   Tailoring 1-page LaTeX resume for keyword & skills alignment...")
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
                            timeout=resume_tailor_timeout
                        )
                        if pdf_res and os.path.exists(pdf_res):
                            tailored_ats = evaluate_pdf_ats(pdf_res, jd_text, candidate)
                            # Apples-to-apples: score the master PDF using the identical PDF text evaluator if exists, else fallback to score
                            master_pdf_score = evaluate_pdf_ats(master_resume_pdf, jd_text, candidate) if (master_resume_pdf and os.path.exists(master_resume_pdf)) else score
                            master_ats = master_pdf_score or score
                            print(f"   ATS Score Comparison: Tailored PDF = {tailored_ats}% vs Master PDF = {master_ats}%")
                            if tailored_ats >= master_ats:
                                pdf_to_submit = pdf_res
                                tex_path = pdf_res.replace(".pdf", ".tex")
                                score = tailored_ats
                                tailored_count += 1
                                print(f"   Tailored PDF outperforms master ({tailored_ats}% >= {master_ats}%). Selected: {os.path.basename(pdf_to_submit)}")
                            else:
                                pdf_to_submit = master_resume_pdf
                                print(f"   Master resume scored higher ({master_ats}% > {tailored_ats}%). Keeping master resume: {os.path.basename(pdf_to_submit)}")
                    except asyncio.TimeoutError:
                        print(f"   ⏱Resume tailoring timed out after 90s. Falling back to master resume.")
                        pdf_to_submit = master_resume_pdf
                    except Exception as te:
                        print(f"   Tailoring error: {te}. Falling back to master resume.")
            else:
                status = "Saved & Scored"
                print(f"[{idx}/{len(jobs)}] Below threshold: {title} @ {company} ({score}% < {min_ats_score}%) - Saved.")

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

        # Autofill application if Top Applicant or score meets minimum threshold
        if (is_top_applicant or score >= min_ats_score) and url:
            _day_cap = daily_cap()
            try:
                from services.relevance import check_relevance
                _fit, _why = check_relevance({**job, "title": title}, jd_text, candidate, prefs)
            except Exception:  # a broken rule must never stop a run
                _fit, _why = True, ""
            if not _fit:
                print(f"[Scanner] Not applying to {title} @ {company}: {_why}.")
            elif _day_cap > 0 and submitted_today() >= _day_cap:
                print(f"[Scanner] Daily limit reached ({_day_cap} applications today, MAX_APPLICATIONS_PER_DAY). Remaining matches are saved to the tracker.")
            elif max_applications > 0 and applied_attempts >= max_applications:
                print(f"[Scanner] ⏸Reached maximum application limit ({max_applications}) for this run. Remaining qualified matches are saved to tracker.")
            else:
                applied_attempts += 1
                disp_total = str(max_applications) if max_applications > 0 else "∞"
                print(f"[Scanner] Dispatching application ({applied_attempts}/{disp_total})...")
                _attempt_started = time.time()
                res = await apply_to_job(
                    url=url,
                    candidate=candidate,
                    resume_path=pdf_to_submit,
                    title=title,
                    company=company,
                    auto_submit=disable_guardrails,
                    timeout_seconds=autofill_timeout,
                    max_steps=steps_limit,
                    model_name=model_override,
                    headless_override=headless
                )

                # Post-Submission Verification Check
                res_status = res.get("status") if isinstance(res, dict) else ""
                final_res = str(res.get("final_result", "")) if isinstance(res, dict) else ""

                # Keep a record of how this attempt ended, for the per-site success rates (`job-finder outcomes`).
                try:
                    from applications_tracker.outcomes import append_outcome
                except ImportError:
                    from outcomes import append_outcome  # type: ignore
                _info = res if isinstance(res, dict) else {}
                append_outcome({
                    "url": url, "company": company, "title": title, "status": res_status, "blocker": _info.get("blocker"),
                    "model": _info.get("model_used"), "steps": _info.get("steps_taken"), "seconds": round(time.time() - _attempt_started),
                    "screenshot": _info.get("review_screenshot"), "final_result": final_res, "submitted_for_real": bool(disable_guardrails),
                    "usage": _info.get("usage") or {},
                    "questions": _info.get("questions") or [],
                })

                if disable_guardrails:
                    if res_status == "success":
                        print(f"   Application verified & submitted successfully for {title} @ {company}")
                        await update_application_status(url, "applied")
                        app_record = {
                            "title": title,
                            "company": company,
                            "url": url,
                            "ats_score": score
                        }
                        applied_applications.append(app_record)
                        batch_applied_buffer.append(app_record)
                    else:
                        fail_reason = final_res or "Form validation error or unconfirmed submission"
                        print(f"   Submission verification failed for {title} @ {company}: {fail_reason}")
                        await update_application_status(url, "Needs Review (Unsubmitted)")
                        fail_record = {
                            "title": title,
                            "company": company,
                            "url": url,
                            "reason": fail_reason[:150]
                        }
                        failed_applications.append(fail_record)
                        batch_failed_buffer.append(fail_record)
                elif isinstance(res, dict) and res.get("blocker"):
                    blocker = res.get("blocker")
                    print(f"   Human-only blocker ({blocker}) for {title} @ {company}; needs manual completion.")
                    await update_application_status(url, f"Needs Review (Blocked: {blocker})")
                    blocked_record = {
                        "title": title,
                        "company": company,
                        "url": url,
                        "reason": f"Blocked by {blocker}. " + (final_res[:120] if final_res else "")
                    }
                    failed_applications.append(blocked_record)
                    batch_failed_buffer.append(blocked_record)
                else:
                    await update_application_status(url, "Ready to Apply (Reviewed)")
                    preview_record = {
                        "title": title,
                        "company": company,
                        "url": url,
                        "reason": "Preview Mode (Guardrails Enabled) — Filled form & ready to submit"
                    }
                    failed_applications.append(preview_record)
                    batch_failed_buffer.append(preview_record)

                # Batch notification check: Every 20 processed jobs, dispatch intermediate email and continue
                total_in_batch = len(batch_applied_buffer) + len(batch_failed_buffer)
                if total_in_batch >= EMAIL_BATCH_SIZE:
                    print(f"\n[Scanner] Processed {total_in_batch} jobs in current batch (limit: {EMAIL_BATCH_SIZE}). Dispatching progress email before continuing...")
                    try:
                        if batch_applied_buffer:
                            notify_user_of_applied_applications(list(batch_applied_buffer), to_email=cand_email)
                            batch_applied_buffer.clear()
                        if batch_failed_buffer:
                            notify_user_of_failed_applications(list(batch_failed_buffer), to_email=cand_email)
                            batch_failed_buffer.clear()
                    except Exception as b_mail_err:
                        print(f"[Scanner] Note: Batch notification error: {b_mail_err}")

    print(f"\n[Scanner] Scan complete! Discovered & processed {new_jobs_added} new postings ({direct_applied_count} direct applied, {tailored_count} tailored).")

    # End-of-run summary table (skipped when run standalone without the job_finder package)
    try:
        from job_finder import ui as _ui
        _ui.key_values("Scan summary", {
            "New postings processed": new_jobs_added,
            "Applied (submitted)": len(applied_applications),
            "Direct (master resume)": direct_applied_count,
            "Tailored resume": tailored_count,
            "Needs attention": len(failed_applications),
        })
        if failed_applications:
            _ui.print_table(
                "Needs attention (blocked, unsubmitted or ready for review)",
                ["Company", "Role", "Reason"],
                [[str(f.get("company", ""))[:26], str(f.get("title", ""))[:40], str(f.get("reason", ""))[:70]] for f in failed_applications],
            )
    except ImportError:
        pass

    cand_email = candidate.get("email") or os.getenv("NOTIFY_EMAIL", "")

    # Send final summary alerts for any remaining unnotified jobs in the buffers (or overall totals if none sent yet)
    if batch_applied_buffer:
        notify_user_of_applied_applications(batch_applied_buffer, to_email=cand_email)
    elif not (len(applied_applications) > len(batch_applied_buffer)) and applied_applications:
        notify_user_of_applied_applications(applied_applications, to_email=cand_email)

    if batch_failed_buffer:
        notify_user_of_failed_applications(batch_failed_buffer, to_email=cand_email)
    elif not (len(failed_applications) > len(batch_failed_buffer)) and failed_applications:
        notify_user_of_failed_applications(failed_applications, to_email=cand_email)


def main():
    """CLI entrypoint for autonomous scheduled scanner with comprehensive tuning options."""
    import argparse
    parser = argparse.ArgumentParser(
        prog="job-finder-scanner",
        description="Autonomous Scheduled Job Discovery & Application Pipeline",
    )
    parser.add_argument("url", nargs="?", default=None, help="Target specific job URL to process directly (optional)")
    parser.add_argument("--auto-apply", action="store_true", help="Enable automatic browser form submission")
    parser.add_argument("--timeout", type=float, default=300.0, help="Autofill session timeout in seconds (default: 300s)")
    parser.add_argument("--tailor-timeout", type=float, default=90.0, help="Resume tailoring timeout in seconds (default: 90s)")
    parser.add_argument("--max-steps", type=int, default=50, help="Max browser-use steps per application (default: 50)")
    parser.add_argument("--limit", type=int, default=0, help="Max applications to process per run (default: 0 = unlimited)")
    parser.add_argument("--min-ats", type=int, default=None, help="Minimum ATS compatibility score threshold (default: from profile)")
    parser.add_argument("--role", type=str, default=None, help="Target role override")
    parser.add_argument("--location", type=str, default=None, help="Target location override")
    parser.add_argument("--timeframe", type=str, default=None, help="Search freshness window override (e.g. 24h, 48h, 1w)")
    parser.add_argument("--model", type=str, default=None, help="Gemini LLM model override for browser-use")
    parser.add_argument("--headless", action="store_true", help="Run browser automation headlessly without GUI")
    parser.add_argument("--top-applicant", action="store_true", help="Scan LinkedIn specifically for Top Applicant postings and auto-apply without JD scoring")
    args = parser.parse_args()

    if args.auto_apply:
        os.environ["JOB_FINDER_DISABLE_GUARDRAILS"] = "1"

    asyncio.run(run_pipeline(
        target_url=args.url,
        timeout=args.timeout,
        tailor_timeout=args.tailor_timeout,
        max_steps=args.max_steps,
        max_apps=args.limit if args.limit > 0 else None,
        min_ats=args.min_ats,
        role=args.role,
        location_override=args.location,
        timeframe_override=args.timeframe,
        model_override=args.model,
        headless=True if args.headless else None,
        auto_submit_override=True if args.auto_apply else None,
        top_applicant_only=True if args.top_applicant else None
    ))


if __name__ == "__main__":
    main()
