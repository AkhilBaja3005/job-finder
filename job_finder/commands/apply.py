"""`job-finder apply` command."""

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
    import re
    from applications_tracker.scheduled_job_scanner import run_browser_use_autofill, find_master_resume_with_mac_tags
    from backend.job_finder_mcp.tools.profile_tools import load_profile_data

    urls_to_process = []
    target_path = args.target.strip()

    if os.path.exists(target_path) and os.path.isfile(target_path):
        print(f"[Apply Batch] Reading URLs from file: {target_path}")
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                content = f.read()

            if target_path.lower().endswith(".json"):
                data = json.loads(content)
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, str) and item.startswith("http"):
                            urls_to_process.append(item)
                        elif isinstance(item, dict):
                            u = item.get("url") or item.get("job_url") or item.get("link")
                            if u:
                                urls_to_process.append(u)
                elif isinstance(data, dict):
                    u_list = data.get("urls") or data.get("jobs") or []
                    for item in u_list:
                        if isinstance(item, str):
                            urls_to_process.append(item)
                        elif isinstance(item, dict):
                            u = item.get("url") or item.get("job_url")
                            if u:
                                urls_to_process.append(u)
            else:
                # Parse .txt or .csv files by extracting HTTP/HTTPS links
                found = re.findall(r'https?://[^\s,"]+', content)
                urls_to_process = [u.rstrip(")") for u in found]
        except Exception as fe:
            print(f"[Error] Failed to parse batch file '{target_path}': {fe}")
            sys.exit(1)
    elif target_path.startswith("http://") or target_path.startswith("https://"):
        urls_to_process = [target_path]
    else:
        print(f"[Error] '{target_path}' is neither a valid HTTP/HTTPS URL nor an existing file path.")
        sys.exit(1)

    if not urls_to_process:
        print(f"[Warning] No valid HTTP/HTTPS job URLs found in '{target_path}'.")
        sys.exit(0)

    # Deduplicate preserving order
    urls_to_process = list(dict.fromkeys(urls_to_process))

    # Check against local tracker & Supabase to skip previously applied roles
    try:
        from applications_tracker.scheduled_job_scanner import get_existing_tracked_urls, normalize_job_url
        existing_tracked = get_existing_tracked_urls()
        unapplied_urls = []
        skipped_count = 0
        for u in urls_to_process:
            norm_u = normalize_job_url(u)
            if norm_u and norm_u in existing_tracked:
                skipped_count += 1
            else:
                unapplied_urls.append(u)

        if skipped_count > 0:
            print(f"[Tracker] ⏭Skipped {skipped_count} URL(s) that were already applied/tracked in database.")
        urls_to_process = unapplied_urls
    except Exception as te:
        print(f"[Tracker] Note: Tracker duplicate check skipped: {te}")

    if not urls_to_process:
        print(f"[Apply] All URLs in '{target_path}' have already been applied to!")
        sys.exit(0)

    print(f"[Apply] Ready to process {len(urls_to_process)} job application URL(s).")

    prof = load_profile_data() or {}
    cand = prof.get("candidate", {})
    target_resume = args.resume or find_master_resume_with_mac_tags()

    failed_jobs = []
    successful_jobs = []

    batch_applied_buffer = []
    batch_failed_buffer = []
    BATCH_SIZE = int(os.getenv("JOB_FINDER_EMAIL_BATCH_SIZE", "20"))
    cand_email = cand.get("email") or os.getenv("NOTIFY_EMAIL", "")

    async def _batch_apply():
        nonlocal failed_jobs, successful_jobs, batch_applied_buffer, batch_failed_buffer
        from job_finder_mcp.tools.tracking_tools import handle_track_application

        for idx, url in enumerate(urls_to_process, 1):
            print(f"\n========================================================")
            print(f"[{idx}/{len(urls_to_process)}] Processing Application: {url}")
            print(f"========================================================\n")
            status = "failed"
            err_text = ""
            try:
                res = await asyncio.wait_for(
                    run_browser_use_autofill(
                        url,
                        resume_data=cand,
                        resume_pdf_path=target_resume,
                        auto_submit=args.submit,
                        model_name=args.model,
                        headless=args.headless,
                        max_steps=args.max_steps
                    ),
                    timeout=args.timeout
                )
                res_status = str(res.get("status", "")).lower() if isinstance(res, dict) else ""
                final_res = str(res.get("final_result", "")) if isinstance(res, dict) else str(res)

                if "submitted" in res_status or "confirmed" in final_res.lower() or "applied" in final_res.lower():
                    status = "applied"
                    successful_jobs.append(url)
                    batch_applied_buffer.append({"url": url, "title": "Target Role", "company": "Company"})
                    print(f"[{idx}/{len(urls_to_process)} Success] Application completed for: {url}")
                else:
                    status = "failed"
                    err_text = res.get("error") or final_res or "Autofill incomplete"
                    failed_jobs.append({"url": url, "reason": err_text})
                    batch_failed_buffer.append({"url": url, "title": "Target Role", "company": "Company", "reason": err_text})
                    print(f"[{idx}/{len(urls_to_process)} Failed] {err_text}")
            except asyncio.TimeoutError:
                err_text = f"Application timed out after {int(args.timeout)}s"
                status = "failed"
                failed_jobs.append({"url": url, "reason": err_text})
                batch_failed_buffer.append({"url": url, "title": "Target Role", "company": "Company", "reason": err_text})
                print(f"[{idx}/{len(urls_to_process)} Error] {err_text}")
            except Exception as ex:
                err_text = str(ex)
                status = "failed"
                failed_jobs.append({"url": url, "reason": err_text})
                batch_failed_buffer.append({"url": url, "title": "Target Role", "company": "Company", "reason": err_text})
                print(f"[{idx}/{len(urls_to_process)} Error] Failed to process {url}: {ex}")

            # Formally record the application state (failed or applied) into the database & CSV tracker
            try:
                await handle_track_application({
                    "job_url": url,
                    "status": status,
                    "job_title": "Target Role",
                    "company": "Company",
                    "score": 0
                })
            except Exception as trk_err:
                print(f"[Tracker] Note: Could not record application state: {trk_err}")

            # Intermediate batch notification: dispatch email every 20 jobs
            if (len(batch_applied_buffer) + len(batch_failed_buffer)) >= BATCH_SIZE:
                print(f"\n[Email Alert] Processed {BATCH_SIZE} jobs in batch. Dispatching intermediate email alert...")
                try:
                    from applications_tracker.scheduled_job_scanner import notify_user_of_failed_applications, notify_user_of_applied_applications
                    if batch_applied_buffer:
                        notify_user_of_applied_applications(list(batch_applied_buffer), to_email=cand_email)
                        batch_applied_buffer.clear()
                    if batch_failed_buffer:
                        notify_user_of_failed_applications(list(batch_failed_buffer), to_email=cand_email)
                        batch_failed_buffer.clear()
                except Exception as b_mail_err:
                    print(f"[Email Alert] Note: Batch notification error: {b_mail_err}")

    asyncio.run(_batch_apply())

    # Trigger final email alerts for any remaining unnotified jobs
    try:
        from applications_tracker.scheduled_job_scanner import notify_user_of_failed_applications, notify_user_of_applied_applications
        if batch_failed_buffer:
            notify_user_of_failed_applications(batch_failed_buffer, to_email=cand_email)
        if batch_applied_buffer:
            notify_user_of_applied_applications(batch_applied_buffer, to_email=cand_email)
    except Exception as mail_err:
        print(f"[Email Alert] Note: Could not send summary email alert: {mail_err}")

    ui.key_values("Batch application summary", {
        "Total processed": len(urls_to_process),
        "Successful": len(successful_jobs),
        "Failed": len(failed_jobs),
    })
    if failed_jobs:
        ui.print_table(
            "Failed applications",
            ["URL", "Reason"],
            [[f_item["url"], str(f_item["reason"])[:120]] for f_item in failed_jobs],
        )
