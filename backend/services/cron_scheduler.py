import os
import json
import asyncio
import urllib.parse
from datetime import datetime, timezone, timedelta
from typing import Optional

from services.auth import supabase_request, _is_local_deployment
from services.email_service import async_send_notification_email

# India Standard Time (IST = UTC + 5:30)
IST_TZ = timezone(timedelta(hours=5, minutes=30))


async def process_and_send_user_digest(user: dict, bypass_time_check: bool = False) -> bool:
    """Generate and send real matching job digest for a given subscribed user."""
    email = user.get("email")
    user_id = user.get("id")
    if not email:
        return False

    candidate_name = "Candidate"
    rdata = {}
    try:
        resume_str = user.get("resume_data")
        if resume_str:
            rdata = json.loads(resume_str) if isinstance(resume_str, str) else resume_str
            candidate_name = rdata.get("name", "").strip() or "Candidate"
    except Exception:
        pass

    # If resume data is missing from user record, check user_resumes table
    if not rdata and user_id and not str(user_id).startswith("guest_"):
        try:
            res_rows = supabase_request(f"user_resumes?user_id=eq.{user_id}", "GET")
            if res_rows and res_rows[0].get("resume_data"):
                raw_rd = res_rows[0]["resume_data"]
                rdata = json.loads(raw_rd) if isinstance(raw_rd, str) else raw_rd
                if rdata.get("name"):
                    candidate_name = rdata.get("name").strip()
        except Exception:
            pass

    backend_url = os.getenv("BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")
    unsub_url = f"{backend_url}/email_action/unsubscribe?email={urllib.parse.quote(email)}"

    # Search preferences configured by user
    cron_role = user.get("cron_role") or ""
    cron_location = user.get("cron_location") or "Remote"

    # Fetch real matching jobs dynamically
    matching_jobs = []
    try:
        from services.job_searcher import find_matching_jobs
        async for chunk in find_matching_jobs(
            resume_data=rdata,
            location=cron_location,
            keywords=cron_role or None,
            timeframe="24h"
        ):
            try:
                parsed = json.loads(chunk.strip())
                if parsed.get("type") == "result" and parsed.get("jobs"):
                    matching_jobs = parsed["jobs"]
            except Exception:
                pass
    except Exception as search_err:
        print(f"[Daily Mailer] Job search error for {email}: {search_err}")

    # Fallback to 48h search if 24h returned no fresh postings
    if not matching_jobs:
        try:
            from services.job_searcher import find_matching_jobs
            async for chunk in find_matching_jobs(
                resume_data=rdata,
                location=cron_location,
                keywords=cron_role or None,
                timeframe="48h"
            ):
                try:
                    parsed = json.loads(chunk.strip())
                    if parsed.get("type") == "result" and parsed.get("jobs"):
                        matching_jobs = parsed["jobs"]
                except Exception:
                    pass
        except Exception:
            pass

    # Build dynamic cards and text digest
    top_jobs = matching_jobs[:5] if matching_jobs else []

    text_digest_lines = [f"Hi {candidate_name},\n", "Here are your top daily matching roles:\n"]
    if top_jobs:
        for idx, job in enumerate(top_jobs, 1):
            j_title = job.get("title", "Job Role")
            j_company = job.get("company", "Company")
            j_score = job.get("score", 80)
            j_url = job.get("url", "")
            t_url = f"{backend_url}/email_action/tailor?job_url={urllib.parse.quote(j_url)}&email={urllib.parse.quote(email)}&title={urllib.parse.quote(j_title)}&company={urllib.parse.quote(j_company)}"
            text_digest_lines.append(f"{idx}. {j_title} @ {j_company} (Match Score: {j_score}%)\n   View: {j_url}\n   Auto-Tailor: {t_url}\n")
    else:
        text_digest_lines.append("No new high-match postings found in the last 24 hours. We will keep scanning for you.\n")

    text_digest_lines.append(f"\nManage subscription / unsubscribe: {unsub_url}\n")
    text_digest = "\n".join(text_digest_lines)

    # Build Rich HTML Digest
    cards_html = ""
    if top_jobs:
        for job in top_jobs:
            platform = str(job.get("platform", "")).strip()
            job_url = job.get("url", "")
            is_reed = "reed" in platform.lower()
            is_linkedin = "linkedin" in platform.lower()
            is_indeed = "indeed" in platform.lower()
            platform_name = "Reed" if is_reed else "LinkedIn" if is_linkedin else "Indeed" if is_indeed else (platform or "Direct ATS")
            platform_color = "#EC4899" if is_reed else "#0A66C2" if is_linkedin else "#2164F3" if is_indeed else "#10B981"
            platform_bg = "#EC489915" if is_reed else "#0A66C215" if is_linkedin else "#2164F315" if is_indeed else "#10B98115"
            tailor_url = f"{backend_url}/email_action/tailor?job_url={urllib.parse.quote(job_url)}&email={urllib.parse.quote(email)}&title={urllib.parse.quote(str(job.get('title', '')))}&company={urllib.parse.quote(str(job.get('company', '')))}"

            cards_html += f"""
            <div style="background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 12px; padding: 18px; margin-bottom: 12px;">
                <table style="width: 100%; border-collapse: collapse;">
                    <tr>
                        <td>
                            <h3 style="margin: 0 0 4px 0; color: #1E293B; font-size: 1.05rem; font-weight: 700;">{job.get('title', 'Job Listing')}</h3>
                            <p style="margin: 0; color: #64748B; font-size: 0.88rem; font-weight: 500;">
                                {job.get('company', 'Company')} &bull; <span style="color: {platform_color}; font-weight: 700; background-color: {platform_bg}; padding: 2px 6px; border-radius: 4px;">{platform_name}</span>
                            </p>
                        </td>
                        <td style="text-align: right; vertical-align: top; width: 90px;">
                            <span style="display: inline-block; background-color: #10B98115; color: #10B981; padding: 4px 8px; border-radius: 6px; font-size: 0.78rem; font-weight: 700;">{job.get('score', 80)}% match</span>
                        </td>
                    </tr>
                </table>
                <table style="width: 100%; border-collapse: collapse; margin-top: 14px;">
                    <tr>
                        <td style="width: 50%; padding-right: 5px;">
                            <a href="{job_url}" target="_blank" style="display: block; text-align: center; padding: 9px 12px; font-size: 0.82rem; color: #64748B; background-color: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 6px; text-decoration: none; font-weight: 600;">View Listing</a>
                        </td>
                        <td style="width: 50%; padding-left: 5px;">
                            <a href="{tailor_url}" target="_blank" style="display: block; text-align: center; padding: 9px 12px; font-size: 0.82rem; color: #FFFFFF; background-color: #0284C7; border-radius: 6px; text-decoration: none; font-weight: bold;">⚡ 1-Click Auto-Tailor</a>
                        </td>
                    </tr>
                </table>
            </div>
            """
    else:
        cards_html = """
        <div style="background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 12px; padding: 24px; text-align: center; color: #64748B;">
            <p style="margin: 0; font-size: 0.95rem;">No new postings found matching your exact profile in the last 24h. We will keep scanning daily for you.</p>
        </div>
        """

    html_digest = f"""
    <div style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; max-width: 600px; margin: 0 auto; padding: 25px; border: 1px solid #E2E8F0; border-radius: 16px; background-color: #FAFAFA; box-shadow: 0 4px 20px rgba(0,0,0,0.03);">
        <div style="text-align: center; margin-bottom: 24px;">
            <span style="font-size: 3rem;">📬</span>
            <h2 style="color: #0284C7; margin: 10px 0 5px; font-weight: 800; font-size: 1.5rem;">Daily Job Matches Digest</h2>
            <p style="color: #334155; font-size: 0.98rem; font-weight: 600; margin: 8px 0 4px;">Hi {candidate_name},</p>
            <p style="color: #64748B; font-size: 0.9rem; margin: 0;">Here are your top matching roles from the past 24 hours ({cron_location}):</p>
        </div>
        {cards_html}
        <hr style="border: 0; border-top: 1px solid #E2E8F0; margin: 30px 0 20px;" />
        <p style="font-size: 0.8rem; color: #94A3B8; text-align: center; margin: 0;">
            <a href="{unsub_url}" target="_blank" style="color: #0284C7;">Unsubscribe</a> or manage preferences in your dashboard.
        </p>
    </div>
    """

    target_email = "akhilkumarbaja@gmail.com" if _is_local_deployment() else email
    sent = await async_send_notification_email(
        to_email=target_email,
        subject=f"📬 Daily Job Matches Digest: {len(top_jobs)} new roles found" if top_jobs else "📬 Daily Job Matches Digest",
        text_body=text_digest,
        html_body=html_digest
    )

    if sent and user_id and not str(user_id).startswith("guest_"):
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        try:
            supabase_request(f"users?id=eq.{user_id}", "PATCH", {"cron_last_sent_date": today_str})
        except Exception:
            pass

    return sent


async def background_cron_worker():
    """Background loop that executes scheduled email digests for subscribed users."""
    print("⏰ [Daily Mailer] Background cron worker started.")
    while True:
        try:
            res = supabase_request("users?cron_enabled=eq.true", "GET")
            if res and isinstance(res, list):
                now_ist = datetime.now(IST_TZ)
                current_hhmm = now_ist.strftime("%H:%M")
                today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

                for user in res:
                    try:
                        # Check last sent date to avoid multiple sends per day
                        if user.get("cron_last_sent_date") == today_str:
                            continue

                        # Check scheduled time (defaults to 09:00 IST if unspecified)
                        user_cron_time = (user.get("cron_time") or "09:00").strip()
                        # If current time is within +/- 15 mins of scheduled time, or scheduled time has passed today
                        user_hh = int(user_cron_time.split(":")[0]) if ":" in user_cron_time else 9
                        user_mm = int(user_cron_time.split(":")[1]) if ":" in user_cron_time else 0
                        user_sched_dt = now_ist.replace(hour=user_hh, minute=user_mm, second=0, microsecond=0)

                        # Trigger if current time is past or at scheduled time
                        if now_ist >= user_sched_dt:
                            print(f"📬 [Daily Mailer] Triggering scheduled digest for {user.get('email')} (scheduled: {user_cron_time} IST)")
                            await process_and_send_user_digest(user, bypass_time_check=False)
                    except Exception as u_err:
                        print(f"[Daily Mailer] Error processing user {user.get('id')}: {u_err}")
        except Exception as e:
            # Supabase not connected or offline
            pass

        # Check every 60 seconds
        await asyncio.sleep(60)
