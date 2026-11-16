"""`job-finder jobserve` command."""

import argparse
import json
import logging
import os
import re
import sys

from job_finder import ui

logger = logging.getLogger(__name__)


def run(args: argparse.Namespace):
    import asyncio
    from services.job_searcher import search_jobserve_jobs
    from backend.job_finder_mcp.tools.profile_tools import load_profile_data

    keyword = args.keyword
    profile = load_profile_data() or {}
    search_prefs = profile.get("search_preferences", {})
    cand_info = profile.get("candidate", {})

    if not keyword:
        target_roles = search_prefs.get("target_roles", [])
        if target_roles:
            keyword = target_roles[0]
        elif cand_info.get("headline"):
            keyword = cand_info["headline"]
        else:
            keyword = "AI Engineer"

    print(f"\n========================================================")
    print(f"   JOBSERVE.COM: Tech, AI & Contract Search")
    print(f"   Keyword: '{keyword}' (from {'CLI arg' if args.keyword else 'candidate profile'}) | Location: '{args.location}' | Timeframe: '{args.timeframe}'")
    if args.auto_apply:
        print(f"   Mode: Auto-Submit Enabled (Guardrails Disabled)")
    print(f"========================================================\n")

    results = asyncio.run(search_jobserve_jobs(
        keyword=keyword,
        location=args.location,
        timeframe=args.timeframe
    ))

    if not results:
        print(f"No active tech jobs found on Jobserve matching '{keyword}' in {args.location} within {args.timeframe}.\n")
    else:
        display_limit = args.limit or 15
        selected_jobs = results[:display_limit]
        print(f"Found {len(results)} active tech postings on Jobserve (showing top {len(selected_jobs)}):\n")
        for idx, job in enumerate(selected_jobs, start=1):
            print(f"[{idx}] {job.title}")
            print(f"    Company  : {job.company}")
            print(f"    Location : {job.location}")
            print(f"    Apply URL: {job.url}")
            if hasattr(job, 'full_description') and job.full_description:
                snippet = job.full_description.replace('\n', ' ')[:160]
                print(f"    Summary  : {snippet}...")
            print()

        if args.auto_apply:
            from applications_tracker.scheduled_job_scanner import apply_to_job, find_master_resume_with_mac_tags, notify_user_of_failed_applications, notify_user_of_applied_applications
            from job_finder_mcp.tools.tracking_tools import handle_track_application
            os.environ["JOB_FINDER_DISABLE_GUARDRAILS"] = "1"
            master_resume_pdf = find_master_resume_with_mac_tags()
            print(f"Starting automatic submission for {len(selected_jobs)} Jobserve role(s)...")

            failed_js_jobs = []
            applied_js_jobs = []

            async def _apply_all_js():
                for idx, j in enumerate(selected_jobs, 1):
                    print(f"\n[{idx}/{len(selected_jobs)}] Auto-submitting application: {j.title} @ {j.company}")
                    status = "failed"
                    err_reason = ""
                    try:
                        res = await apply_to_job(
                            url=j.url,
                            candidate=cand_info,
                            resume_path=master_resume_pdf,
                            title=j.title,
                            company=j.company,
                            auto_submit=True,
                            timeout_seconds=args.timeout,
                            headless_override=args.headless
                        )
                        res_status = str(res.get("status", "")).lower() if isinstance(res, dict) else ""
                        final_res = str(res.get("final_result", "")) if isinstance(res, dict) else str(res)

                        if "submitted" in res_status or "confirmed" in final_res.lower() or "applied" in final_res.lower():
                            status = "applied"
                            applied_js_jobs.append({"url": j.url, "title": j.title, "company": j.company})
                            print(f"[{idx}/{len(selected_jobs)} Success] Application submitted for: {j.title}")
                        else:
                            err_reason = res.get("error") or final_res or "Autofill incomplete / unconfirmed"
                            failed_js_jobs.append({"url": j.url, "title": j.title, "company": j.company, "reason": err_reason})
                            print(f"[{idx}/{len(selected_jobs)} Failed] {err_reason}")
                    except Exception as app_err:
                        err_reason = str(app_err)
                        failed_js_jobs.append({"url": j.url, "title": j.title, "company": j.company, "reason": err_reason})
                        print(f"[Warning] Auto-submit failed for {j.title}: {app_err}")

                    try:
                        await handle_track_application({
                            "job_url": j.url,
                            "status": status,
                            "job_title": j.title,
                            "company": j.company,
                            "score": 0
                        })
                    except Exception:
                        pass

                cand_email = cand_info.get("email") or os.getenv("NOTIFY_EMAIL", "")
                if applied_js_jobs:
                    notify_user_of_applied_applications(applied_js_jobs, to_email=cand_email)
                if failed_js_jobs:
                    notify_user_of_failed_applications(failed_js_jobs, to_email=cand_email)

            asyncio.run(_apply_all_js())
        else:
            print(f"Tip: Run `job-finder jobserve \"{keyword}\" --auto-submit --limit 3` to auto-apply to these roles!")
            print(f"Or run `job-finder scan --location {args.location}` for full unified scanning & tailoring.\n")
