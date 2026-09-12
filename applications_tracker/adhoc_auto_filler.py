#!/usr/bin/env python3
"""
adhoc_auto_filler.py
--------------------
Standalone CLI tool to autonomously auto-fill job applications using the candidate's
master resume directly (zero tailoring compilation overhead).

Supported inputs:
  1. CSV file (e.g. applications tracker or custom job list)
  2. Excel file (.xlsx / .xls)
  3. Direct job URL(s) passed via CLI
  4. LinkedIn Job ID(s) passed via CLI (--job-ids)

Usage:
  # 1. Apply to LinkedIn job IDs (space- or comma-separated)
  python applications_tracker/adhoc_auto_filler.py --job-ids 4455334729 4465614142 4464616151

  # 2. Apply to a single or comma-separated URLs
  python applications_tracker/adhoc_auto_filler.py --url "https://job-boards.greenhouse.io/buildkite/jobs/5415583008"

  # 3. Process jobs from tracker CSV matching a status filter (defaults to 'Ready to Apply' and 'Saved & Scored')
  python applications_tracker/adhoc_auto_filler.py --csv applications_tracker/job_applications_tracker.csv --limit 5

  # 4. Process jobs from an Excel file
  python applications_tracker/adhoc_auto_filler.py --excel my_jobs.xlsx --limit 10

  # 5. Enable auto-submit (guardrails disabled)
  python applications_tracker/adhoc_auto_filler.py --job-ids 4455334729 --auto-submit
"""

import os
import sys
import csv
import asyncio
import argparse
import re
from typing import List, Dict, Any, Optional

# Ensure backend is on sys.path
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
    get_tracker_csv_path
)

JOB_FINDER_ROOT = resolve_workspace_root()
BACKEND_DIR = os.path.join(JOB_FINDER_ROOT, "backend")
TRACKER_DIR = get_applications_tracker_dir()
DEFAULT_CSV_PATH = get_tracker_csv_path()

sys.path.insert(0, JOB_FINDER_ROOT)
if os.path.isdir(BACKEND_DIR):
    sys.path.insert(0, BACKEND_DIR)
sys.path.insert(0, TRACKER_DIR)

# pyrefly: ignore [missing-import]
from dotenv import load_dotenv
load_dotenv()
if os.path.exists(".env"):
    load_dotenv(".env")


from mcp.tools.profile_tools import load_profile_data
from services.browser_use_agent import run_browser_use_autofill
# pyrefly: ignore [missing-import]
from scheduled_job_scanner import (
    find_master_resume_with_mac_tags,
    get_existing_tracked_urls,
    record_to_supabase_or_csv,
    format_posted_date_time,
    notify_user_of_failed_applications,
)


def load_jobs_from_csv(csv_path: str, status_filter: Optional[str] = None) -> List[Dict[str, Any]]:
    """Reads job entries from a CSV file."""
    if not os.path.exists(csv_path):
        print(f"[Ad-hoc Filler] ❌ CSV file not found: {csv_path}")
        return []

    jobs = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            url = row.get("Job URL") or row.get("url") or row.get("URL") or row.get("apply_url") or ""
            if not url:
                continue

            status = row.get("Status") or row.get("status") or ""
            if status_filter:
                if status_filter.lower() != "all" and status.strip().lower() != status_filter.strip().lower():
                    continue

            jobs.append({
                "company": row.get("Company") or row.get("company") or "Company",
                "title": row.get("Job Title") or row.get("job_title") or row.get("title") or "Role",
                "url": url.strip(),
                "location": row.get("Location") or row.get("location") or "UK",
                "platform": row.get("Platform") or row.get("platform") or "Web",
                "status": status,
                "overall_ats": row.get("Overall ATS") or row.get("score") or "80%",
                "raw_row": row
            })
    return jobs


def load_jobs_from_excel(excel_path: str, status_filter: Optional[str] = None) -> List[Dict[str, Any]]:
    """Reads job entries from an Excel (.xlsx / .xls) file."""
    if not os.path.exists(excel_path):
        print(f"[Ad-hoc Filler] ❌ Excel file not found: {excel_path}")
        return []

    try:
        # pyrefly: ignore [missing-import]
        import pandas as pd  # type: ignore[import-untyped,import-not-found]
        df = pd.read_excel(excel_path)
        jobs = []
        for _, row in df.iterrows():
            row_dict = row.to_dict()
            url = (
                row_dict.get("Job URL") or row_dict.get("url") or
                row_dict.get("URL") or row_dict.get("apply_url") or ""
            )
            if not url or str(url).strip() == "" or str(url).lower() == "nan":
                continue

            status = str(row_dict.get("Status") or row_dict.get("status") or "")
            if status_filter and status_filter.lower() != "all":
                if status.strip().lower() != status_filter.strip().lower():
                    continue

            jobs.append({
                "company": str(row_dict.get("Company") or row_dict.get("company") or "Company"),
                "title": str(row_dict.get("Job Title") or row_dict.get("job_title") or "Role"),
                "url": str(url).strip(),
                "location": str(row_dict.get("Location") or "UK"),
                "platform": str(row_dict.get("Platform") or "Excel"),
                "status": status,
                "overall_ats": str(row_dict.get("Overall ATS") or "80%"),
                "raw_row": row_dict
            })
        return jobs
    except ImportError:
        print("[Ad-hoc Filler] ⚠️ pandas/openpyxl not installed. Please install pandas & openpyxl or supply a CSV file.")
        return []
    except Exception as e:
        print(f"[Ad-hoc Filler] ❌ Error parsing Excel file: {e}")
        return []


async def apply_job_adhoc(
    job: Dict[str, Any],
    candidate: dict,
    resume_path: str,
    auto_submit: bool = False,
    headless: bool = False
) -> Dict[str, Any]:
    """Runs browser-use autofill using master resume directly without tailoring."""
    title = job.get("title", "Target Role")
    company = job.get("company", "Company")
    url = job.get("url", "")

    print(f"\n===========================================================")
    print(f"🚀 [Ad-hoc Apply] {title} @ {company}")
    print(f"🔗 URL: {url}")
    print(f"📄 Resume: {resume_path} (Master Resume - No Tailoring)")
    print(f"⚡ Mode: {'Auto-Submit (Guardrails OFF)' if auto_submit else 'Review / Preview (Guardrails ON)'}")
    print(f"===========================================================")

    from config.constants import get_best_flash_lite_model
    selected_model = get_best_flash_lite_model()

    res = await run_browser_use_autofill(
        job_url=url,
        resume_data=candidate,
        resume_pdf_path=resume_path,
        headless=headless,
        model_name=selected_model,
        auto_submit=auto_submit,
        max_steps=50
    )

    print(f"[Ad-hoc Apply] Result: {res.get('status')} | Message: {res.get('message', '')}")
    return res


async def main():
    parser = argparse.ArgumentParser(description="Ad-hoc Job Application Auto-Filler using Master Resume")
    parser.add_argument("--job-ids", nargs="+", type=str, help="List of LinkedIn job IDs (e.g. 4455334729 4465614142 or comma-separated)")
    parser.add_argument("--url", type=str, help="Direct job URL (or comma-separated list of URLs)")
    parser.add_argument("--csv", type=str, default=None, help=f"Path to CSV file (defaults to {DEFAULT_CSV_PATH} if --excel or --url not set)")
    parser.add_argument("--excel", type=str, default=None, help="Path to Excel (.xlsx) file")
    parser.add_argument("--filter", type=str, default=None, help="Status filter when reading CSV/Excel (e.g. 'Ready to Apply', 'Saved & Scored', or 'all')")
    parser.add_argument("--limit", type=int, default=5, help="Maximum number of applications to run (default: 5)")
    parser.add_argument("--auto-submit", action="store_true", help="Automatically submit without stopping at the review step")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    parser.add_argument("--resume", type=str, default=None, help="Path to custom resume PDF (overrides Red-tagged master resume)")
    parser.add_argument("--skip-duplicate-check", action="store_true", help="Ignore previously applied URLs check")

    args = parser.parse_args()

    # Load profile data
    profile = load_profile_data()
    candidate = profile.get("candidate", {})

    # Determine master resume
    if args.resume and os.path.exists(args.resume):
        master_resume = args.resume
        print(f"[Master Resume] 📄 Using explicitly specified resume: {master_resume}")
    else:
        master_resume = find_master_resume_with_mac_tags()

    if not master_resume or not os.path.exists(master_resume):
        print(f"[Master Resume] ❌ Master resume not found at {master_resume}. Please verify file path.")
        return

    # Check guardrails env or CLI flag
    auto_submit = args.auto_submit or os.getenv("BROWSER_USE_DISABLE_GUARDRAILS") in ("1", "true", "True")

    # Collect jobs list
    jobs_to_process: List[Dict[str, Any]] = []

    if args.job_ids:
        # Flatten space-separated or comma-separated LinkedIn job IDs
        raw_ids: List[str] = []
        for item in args.job_ids:
            for sub_id in item.replace(",", " ").split():
                clean_id = sub_id.strip()
                # If a user passes a full URL by accident into --job-ids, extract the digits
                id_match = re.search(r"(\d{8,})", clean_id)
                if id_match:
                    raw_ids.append(id_match.group(1))
                elif clean_id.isdigit():
                    raw_ids.append(clean_id)

        # Deduplicate while preserving order
        unique_ids = list(dict.fromkeys(raw_ids))
        print(f"[Ad-hoc Filler] 🎯 Received {len(unique_ids)} LinkedIn Job ID(s): {', '.join(unique_ids)}")
        for jid in unique_ids:
            job_url = f"https://www.linkedin.com/jobs/view/{jid}/"
            jobs_to_process.append({
                "title": f"LinkedIn Job #{jid}",
                "company": "LinkedIn Listing",
                "url": job_url,
                "location": "UK",
                "platform": "LinkedIn",
                "status": "Ready to Apply",
                "overall_ats": 85
            })
    elif args.url:
        urls = [u.strip() for u in args.url.split(",") if u.strip()]
        for u in urls:
            jobs_to_process.append({
                "title": "Target Role",
                "company": "Target Company",
                "url": u,
                "location": "UK",
                "platform": "Direct CLI",
                "status": "Ready to Apply",
                "overall_ats": 85
            })
    elif args.excel:
        jobs_to_process = load_jobs_from_excel(args.excel, status_filter=args.filter)
    else:
        csv_target = args.csv or DEFAULT_CSV_PATH
        jobs_to_process = load_jobs_from_csv(csv_target, status_filter=args.filter)

    if not jobs_to_process:
        print("[Ad-hoc Filler] ℹ️ No jobs found matching the criteria.")
        return

    # Filter out duplicates if requested
    existing_urls = set() if args.skip_duplicate_check else get_existing_tracked_urls()
    filtered_jobs = []
    for j in jobs_to_process:
        norm = j["url"].strip().split("?")[0].rstrip("/").lower()
        if not args.skip_duplicate_check and norm in existing_urls and j.get("status") == "applied":
            print(f"[Ad-hoc Filler] ⏭️ Skipping already applied URL: {j['title']} @ {j['company']} ({j['url']})")
            continue
        filtered_jobs.append(j)

    total_to_run = min(len(filtered_jobs), args.limit)
    print(f"\n[Ad-hoc Filler] 📋 Found {len(jobs_to_process)} jobs ({len(filtered_jobs)} actionable). Processing top {total_to_run} jobs.")

    completed = 0
    failed_applications = []
    for idx, job in enumerate(filtered_jobs[:total_to_run], start=1):
        print(f"\n[{idx}/{total_to_run}] Starting application for {job['title']} @ {job['company']}")
        res = await apply_job_adhoc(
            job=job,
            candidate=candidate,
            resume_path=master_resume,
            auto_submit=auto_submit,
            headless=args.headless
        )

        # Update record status in Supabase/CSV with post-submission verification
        res_status = res.get("status") if isinstance(res, dict) else ""
        final_res = str(res.get("final_result", "")) if isinstance(res, dict) else ""

        if auto_submit:
            if res_status == "success":
                new_status = "applied"
                print(f"   ✅ Application verified & submitted successfully for {job['title']} @ {job['company']}")
            else:
                new_status = "Needs Review (Unsubmitted)"
                fail_reason = final_res or "Form validation error or unconfirmed submission"
                print(f"   ⚠️ Submission verification failed for {job['title']} @ {job['company']}: {fail_reason}")
                failed_applications.append({
                    "title": job.get("title", "Role"),
                    "company": job.get("company", "Company"),
                    "url": job["url"],
                    "reason": fail_reason[:150]
                })
        else:
            new_status = "Reviewed & Ready"

        record_payload = {
            "company": job.get("company", "Company"),
            "job_title": job.get("title", "Role"),
            "location": job.get("location", "UK"),
            "platform": job.get("platform", "Ad-hoc"),
            "posted_time": format_posted_date_time(job.get("posted_date") or job.get("post_date_raw") or "Recent"),
            "overall_ats": job.get("overall_ats", 80),
            "skills_match": 80,
            "experience_match": 80,
            "role_fit": 80,
            "matched_skills": "Direct Master Resume Apply",
            "missing_skills": "",
            "salary": "",
            "seniority": "",
            "recruiter": "",
            "recruiter_linkedin": "",
            "pdf_path": master_resume,
            "latex_path": "",
            "status": new_status,
            "job_url": job["url"]
        }
        await record_to_supabase_or_csv(record_payload)
        completed += 1

    print(f"\n✨ [Ad-hoc Filler] Completed processing {completed} applications!")

    # Alert user via email if any applications failed/need review
    if failed_applications:
        cand_email = candidate.get("email") or "akhilbaja.work@gmail.com"
        notify_user_of_failed_applications(failed_applications, to_email=cand_email)


if __name__ == "__main__":
    asyncio.run(main())
