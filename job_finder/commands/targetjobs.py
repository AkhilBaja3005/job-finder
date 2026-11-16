"""`job-finder targetjobs` command."""

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
    from services.job_searcher import search_targetjobs_uk
    from utils.location_resolver import resolve_location_country
    from backend.job_finder_mcp.tools.profile_tools import load_profile_data

    # 1. Resolve keyword from candidate profile if not explicitly passed
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
            keyword = "Software Engineer"

    country = resolve_location_country(args.location)
    if country != "GB":
        print(f"\n[Warning] TargetJobs only serves jobs in the United Kingdom. '{args.location}' resolved to country code '{country}'.")
        print("   Please provide a UK location (e.g. London, Manchester, Leeds, Edinburgh, or UK).\n")
        sys.exit(1)

    print(f"\n========================================================")
    print(f"   TARGETJOBS UK: Graduate & Early Career IT Search")
    print(f"   Keyword: '{keyword}' (from {'CLI arg' if args.keyword else 'candidate profile'}) | Location: '{args.location}'")
    if args.auto_apply:
        print(f"   Mode: Auto-Submit Enabled (Guardrails Disabled)")
    print(f"========================================================\n")

    results = asyncio.run(search_targetjobs_uk(
        keyword=keyword,
        location=args.location,
        timeframe=args.timeframe
    ))

    if not results:
        print(f"No active graduate tech jobs found on TargetJobs.co.uk matching '{keyword}' in {args.location}.\n")
    else:
        display_limit = args.limit or 15
        selected_jobs = results[:display_limit]
        print(f"Found {len(results)} graduate technology postings on TargetJobs (showing top {len(selected_jobs)}):\n")
        for idx, job in enumerate(selected_jobs, start=1):
            print(f"[{idx}] {job.title}")
            print(f"    Company  : {job.company}")
            print(f"    Location : {job.location}")
            print(f"    Apply URL: {job.url}")
            if hasattr(job, 'full_description') and job.full_description:
                snippet = job.full_description.replace('\n', ' ')[:140]
                print(f"    Summary  : {snippet}...")
            print()

        if args.auto_apply:
            from applications_tracker.scheduled_job_scanner import apply_to_job, find_master_resume_with_mac_tags, notify_user_of_failed_applications, notify_user_of_applied_applications
            from job_finder_mcp.tools.tracking_tools import handle_track_application
            os.environ["JOB_FINDER_DISABLE_GUARDRAILS"] = "1"
            master_resume_pdf = find_master_resume_with_mac_tags()
            print(f"Starting automatic submission for {len(selected_jobs)} TargetJobs role(s)...")

            failed_tj_jobs = []
            applied_tj_jobs = []

            async def _apply_all():
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
                            applied_tj_jobs.append({"url": j.url, "title": j.title, "company": j.company})
                            print(f"[{idx}/{len(selected_jobs)} Success] Application submitted for: {j.title}")
                        else:
                            err_reason = res.get("error") or final_res or "Autofill incomplete / unconfirmed"
                            failed_tj_jobs.append({"url": j.url, "title": j.title, "company": j.company, "reason": err_reason})
                            print(f"[{idx}/{len(selected_jobs)} Failed] {err_reason}")
                    except Exception as app_err:
                        err_reason = str(app_err)
                        failed_tj_jobs.append({"url": j.url, "title": j.title, "company": j.company, "reason": err_reason})
                        print(f"[Warning] Auto-submit failed for {j.title}: {app_err}")

                    # Track application state in database
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

            asyncio.run(_apply_all())

            # Send email alerts for failed and applied jobs
            try:
                if failed_tj_jobs:
                    notify_user_of_failed_applications(failed_tj_jobs)
                if applied_tj_jobs:
                    notify_user_of_applied_applications(applied_tj_jobs)
            except Exception as m_err:
                print(f"[Email Alert] Note: Could not send notification email: {m_err}")
        else:
            print(f"Tip: Run `job-finder targetjobs --auto-submit --limit 3` to auto-apply to these roles!")
            print(f"Or run `job-finder scan --location London, UK` for full unified scanning & tailoring.\n")
