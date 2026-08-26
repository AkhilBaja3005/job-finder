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
    """Generate and send matching job digest for a given subscribed user."""
    email = user.get("email")
    user_id = user.get("id")
    if not email:
        return False

    candidate_name = "Candidate"
    try:
        resume_str = user.get("resume_data")
        if resume_str:
            rdata = json.loads(resume_str) if isinstance(resume_str, str) else resume_str
            candidate_name = rdata.get("name", "").strip() or "Candidate"
    except Exception:
        pass

    backend_url = os.getenv("BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")
    tailor_url = f"{backend_url}/email_action/tailor?job_url=https://www.linkedin.com/jobs/view/4409263656&email={urllib.parse.quote(email)}"
    unsub_url = f"{backend_url}/email_action/unsubscribe?email={urllib.parse.quote(email)}"

    text_digest = (
        f"Hi {candidate_name},\n\n"
        "Here are your daily matching roles:\n\n"
        "1. AI Systems Engineer - Granola\n   Match Score: 85%\n"
        f"   Auto-Tailor: {tailor_url}\n\n"
        f"Manage subscription / unsubscribe: {unsub_url}\n"
    )

    html_digest = f"""
    <div style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; max-width: 600px; margin: 0 auto; padding: 25px; border: 1px solid #E2E8F0; border-radius: 16px; background-color: #FAFAFA;">
        <div style="text-align: center; margin-bottom: 24px;">
            <span style="font-size: 3rem;">📬</span>
            <h2 style="color: #0284C7; margin: 10px 0 5px; font-weight: 800; font-size: 1.5rem;">Daily Job Matches Digest</h2>
            <p style="color: #334155; font-size: 0.98rem; font-weight: 600; margin: 8px 0 4px;">Hi {candidate_name},</p>
            <p style="color: #64748B; font-size: 0.9rem; margin: 0;">Here are your top matching roles from the past 24 hours:</p>
        </div>
        <div style="background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 12px; padding: 18px; margin-bottom: 12px;">
            <table style="width: 100%; border-collapse: collapse;">
                <tr>
                    <td>
                        <h3 style="margin: 0 0 4px 0; color: #1E293B; font-size: 1.05rem; font-weight: 700;">AI Engineer - GenAI & Workflows</h3>
                        <p style="margin: 0; color: #64748B; font-size: 0.88rem;">Granola &bull; <span style="color: #10B981; font-weight: 700;">85% Match</span></p>
                    </td>
                </tr>
            </table>
            <div style="margin-top: 14px; text-align: center;">
                <a href="{tailor_url}" target="_blank" style="display: inline-block; background-color: #0284C7; color: #FFFFFF; padding: 10px 24px; border-radius: 6px; text-decoration: none; font-weight: bold; font-size: 0.9rem;">⚡ 1-Click Auto-Tailor Resume</a>
            </div>
        </div>
        <hr style="border: 0; border-top: 1px solid #E2E8F0; margin: 30px 0 20px;" />
        <p style="font-size: 0.8rem; color: #94A3B8; text-align: center; margin: 0;">
            <a href="{unsub_url}" target="_blank" style="color: #0284C7;">Unsubscribe</a> or manage preferences in your dashboard.
        </p>
    </div>
    """

    target_email = "akhilkumarbaja@gmail.com" if _is_local_deployment() else email
    sent = await async_send_notification_email(
        to_email=target_email,
        subject="📬 Daily Job Matches Digest",
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
    while True:
        try:
            res = supabase_request("users?cron_enabled=eq.true", "GET")
            if res and isinstance(res, list):
                for user in res:
                    try:
                        # Check last sent date to avoid multiple sends per day
                        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                        if user.get("cron_last_sent_date") == today_str:
                            continue
                        await process_and_send_user_digest(user, bypass_time_check=False)
                    except Exception as u_err:
                        print(f"[Daily Mailer] Error for user {user.get('id')}: {u_err}")
        except Exception as e:
            # Supabase not connected or offline
            pass

        await asyncio.sleep(300)
