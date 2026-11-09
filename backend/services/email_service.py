import os
import asyncio
import smtplib
# pyrefly: ignore [untyped-import]
import requests
import urllib.parse
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from typing import Optional, List, Dict, Any

def send_notification_email(
    to_email: str,
    subject: str,
    text_body: str,
    html_body: Optional[str] = None,
    attachment_path: Optional[str] = None,
    attachment_name: Optional[str] = None,
    sender_name: Optional[str] = None,
    reply_to: Optional[str] = None
) -> bool:
    """
    Sends an email to the recipient with purpose-based sender branding.
    - Security / OTP: sender_name="JobFinder Security"
    - Contact Inquiries: sender_name="JobFinder Enquiry" (with reply_to set to sender)
    - Daily Cadence Digest: sender_name="AI Job Finder"
    """
    effective_sender_name = (sender_name or "AI Job Finder").strip()

    # Smart Routing:
    # 1. Brevo allows sending 300 emails/day to ANY recipient email (perfect for all users!)
    # 2. Resend delivers in <2s for the account owner email (akhilkumarbaja@gmail.com)
    owner_email = os.getenv("SMTP_USER", "akhilkumarbaja@gmail.com").lower()
    is_owner = to_email.lower() == owner_email

    # Try Brevo first for general users, or as secondary fallback
    providers = []
    if is_owner:
        providers = ["resend", "brevo", "plunk"]
    else:
        providers = ["brevo", "resend", "plunk"]

    for provider in providers:
        if provider == "brevo":
            brevo_api_key = os.getenv("BREVO_API_KEY")
            if brevo_api_key:
                try:
                    url = "https://api.brevo.com/v3/smtp/email"
                    headers = {
                        "api-key": brevo_api_key,
                        "Content-Type": "application/json",
                        "User-Agent": "JobFinderApp/1.0"
                    }
                    from_addr = os.getenv("EMAIL_FROM") or "noreply@job-finder.space"
                    sender_dict = {
                        "name": effective_sender_name,
                        "email": from_addr
                    }

                    payload = {
                        "sender": sender_dict,
                        "to": [{"email": to_email}],
                        "subject": subject,
                        "textContent": text_body
                    }
                    if reply_to:
                        payload["replyTo"] = {"email": reply_to}
                    if html_body:
                        payload["htmlContent"] = html_body
                    
                    if attachment_path and os.path.exists(attachment_path):
                        import base64
                        with open(attachment_path, "rb") as f:
                            encoded_b64 = base64.b64encode(f.read()).decode("utf-8")
                        att_name = attachment_name or os.path.basename(attachment_path)
                        payload["attachment"] = [{"name": att_name, "content": encoded_b64}]

                    resp = requests.post(url, headers=headers, json=payload, timeout=15)
                    if resp.status_code in (200, 201):
                        print(f"[Mailer] Sent successfully to {to_email} via Brevo REST API ({effective_sender_name}).")
                        return True
                    print(f"[Mailer] Brevo API failed with status {resp.status_code}: {resp.text}. Trying next fallback...")
                except Exception as e:
                    print(f"[Mailer] Brevo API exception: {e}. Trying next fallback...")

        elif provider == "resend":
            resend_api_key = os.getenv("RESEND_API_KEY")
            if resend_api_key:
                try:
                    url = "https://api.resend.com/emails"
                    headers = {
                        "Authorization": f"Bearer {resend_api_key}",
                        "User-Agent": "JobFinderApp/1.0",
                        "Content-Type": "application/json"
                    }
                    from_env = os.getenv("EMAIL_FROM", "")
                    if from_env and "@gmail.com" not in from_env.lower():
                        from_addr = f"{effective_sender_name} <{from_env}>"
                    else:
                        from_addr = f"{effective_sender_name} <noreply@job-finder.space>"

                    payload: Dict[str, Any] = {
                        "from": from_addr,
                        "to": [to_email],
                        "subject": subject,
                        "text": text_body
                    }
                    if reply_to:
                        payload["reply_to"] = reply_to
                    if html_body:
                        payload["html"] = html_body

                    if attachment_path and os.path.exists(attachment_path):
                        import base64
                        with open(attachment_path, "rb") as f:
                            encoded_b64 = base64.b64encode(f.read()).decode("utf-8")
                        att_name = attachment_name or os.path.basename(attachment_path)
                        payload["attachments"] = [{"filename": att_name, "content": encoded_b64}]
                    resp = requests.post(url, headers=headers, json=payload, timeout=15)
                    if resp.status_code in (200, 201):
                        print(f"[Mailer] Sent successfully to {to_email} via Resend REST API ({effective_sender_name}).")
                        return True
                    print(f"[Mailer] Resend API failed with status {resp.status_code}: {resp.text}. Trying next fallback...")
                except Exception as e:
                    print(f"[Mailer] Resend API exception: {e}. Trying next fallback...")

    # 3. Backup 2: Plunk REST API (https://github.com/useplunk/plunk)
    plunk_api_key = os.getenv("PLUNK_API_KEY")
    if plunk_api_key:
        try:
            plunk_base_url = os.getenv("PLUNK_BASE_URL", "https://next-api.useplunk.com").rstrip("/")
            url = f"{plunk_base_url}/v1/send"
            headers = {
                "Authorization": f"Bearer {plunk_api_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "to": to_email,
                "subject": subject,
                "body": html_body or text_body,
                "name": effective_sender_name
            }
            if reply_to:
                payload["reply"] = reply_to
            resp = requests.post(url, headers=headers, json=payload, timeout=15)
            if resp.status_code in (200, 201, 202):
                print(f"[Mailer] Sent successfully via Plunk Open-Source API ({effective_sender_name}).")
                return True
            print(f"[Mailer] Plunk API failed with status {resp.status_code}: {resp.text}")
        except Exception as e:
            print(f"[Mailer] Plunk API exception: {e}")

    # 4. Backup 3: Cloudflare Email API
    cf_account = os.getenv("CLOUDFLARE_ACCOUNT_ID")
    cf_token = os.getenv("CLOUDFLARE_API_TOKEN")
    cf_from = os.getenv("CLOUDFLARE_EMAIL_FROM")

    if cf_account and cf_token and cf_from:
        try:
            url = f"https://api.cloudflare.com/client/v4/accounts/{cf_account}/email/sending/send"
            headers = {
                "Authorization": f"Bearer {cf_token}",
                "Content-Type": "application/json"
            }
            payload = {
                "from": {"address": cf_from, "name": effective_sender_name},
                "to": to_email,
                "subject": subject,
                "text": text_body
            }
            if html_body:
                payload["html"] = html_body
            resp = requests.post(url, headers=headers, json=payload, timeout=15)
            if resp.status_code == 200:
                print(f"[Mailer] Sent successfully via Cloudflare Email API ({effective_sender_name}).")
                return True
            print(f"[Mailer] Cloudflare API failed with status {resp.status_code}: {resp.text}")
        except Exception as e:
            print(f"[Mailer] Cloudflare API exception: {e}")

    # 5. Standard SMTP Fallback (Gmail App Password)
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASSWORD")
    email_from = os.getenv("EMAIL_FROM", smtp_user)

    if not smtp_user or not smtp_pass:
        print("[Mailer ERROR] No mail credentials found in environment variables.")
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{effective_sender_name} <{email_from or smtp_user}>"
        msg["To"] = to_email
        if reply_to:
            msg["Reply-To"] = reply_to

        msg.attach(MIMEText(text_body, "plain"))
        if html_body:
            msg.attach(MIMEText(html_body, "html"))

        # Attach PDF files (for tailored resume alerts)
        if attachment_path and os.path.exists(attachment_path):
            with open(attachment_path, "rb") as f:
                part = MIMEApplication(f.read(), _subtype="pdf")
                name = attachment_name or os.path.basename(attachment_path)
                part.add_header("Content-Disposition", "attachment", filename=name)
                msg.attach(part)

        # Connect and send with exponential retry & fallback
        # Gmail / Cloud hosts frequently drop rapid consecutive connections on 587/465.
        # We attempt Port 465 (SSL) and Port 587 (STARTTLS) with backoff before giving up.
        ports_to_try = [smtp_port]
        fallback_port = 465 if smtp_port != 465 else 587
        if fallback_port not in ports_to_try:
            ports_to_try.append(fallback_port)

        import time
        sent_ok = False
        last_error = None

        for attempt in range(1, 4):  # Up to 3 attempts with progressive backoff
            for port in ports_to_try:
                try:
                    if port == 465:
                        with smtplib.SMTP_SSL(smtp_host, 465, timeout=20) as server:
                            server.login(smtp_user, smtp_pass)
                            server.sendmail(email_from or smtp_user or "", [to_email], msg.as_string())
                    else:
                        with smtplib.SMTP(smtp_host, port, timeout=20) as server:
                            server.ehlo()
                            server.starttls()
                            server.ehlo()
                            server.login(smtp_user, smtp_pass)
                            server.sendmail(email_from or smtp_user or "", [to_email], msg.as_string())
                    sent_ok = True
                    break
                except (OSError, smtplib.SMTPException, Exception) as conn_err:
                    last_error = conn_err
                    print(f"[Mailer] Attempt {attempt} on port {port} failed ({conn_err}).")
            
            if sent_ok:
                break
            
            # Wait 2.5s before retry to let Google SMTP / network socket reset
            time.sleep(2.5 * attempt)

        if not sent_ok:
            raise last_error or Exception("All SMTP attempts failed.")

        print(f"[Mailer] Sent successfully via SMTP ({effective_sender_name}).")
        return True
    except Exception as e:
        print(f"[Mailer ERROR] SMTP delivery failed: {e}")
        return False


async def async_send_notification_email(
    to_email: str,
    subject: str,
    text_body: str,
    html_body: Optional[str] = None,
    attachment_path: Optional[str] = None,
    attachment_name: Optional[str] = None,
    sender_name: Optional[str] = None,
    reply_to: Optional[str] = None,
) -> bool:
    """
    Non-blocking wrapper around send_notification_email.
    Runs the synchronous HTTP/SMTP calls in a thread executor so the asyncio
    event loop is never blocked during email delivery (typically 300ms-2s).
    """
    return await asyncio.to_thread(
        send_notification_email,
        to_email, subject, text_body, html_body, attachment_path, attachment_name, sender_name, reply_to
    )

def build_digest_email_html(candidate_name: str, jobs: list, base_url: str, user_email: str) -> str:
    """
    Generates dynamic HTML body for Daily Job Digest emails.
    Renders Reed.co.uk platform badges in pink (#EC4899).
    """
    cards_html = ""
    for job in jobs:
        platform = str(job.get("platform", "")).strip()
        job_url = job.get("url", "") or job.get("job_url", "")
        
        is_reed = "reed" in platform.lower() or "reed.co.uk" in job_url.lower()
        is_linkedin = "linkedin" in platform.lower() or "linkedin.com" in job_url.lower()
        
        platform_name = "Reed" if is_reed else "LinkedIn" if is_linkedin else (platform or "Job")
        platform_color = "#EC4899" if is_reed else "#0A66C2" if is_linkedin else "#FF6F00"
        platform_bg = "#EC489915" if is_reed else "#0A66C215" if is_linkedin else "#FF6F0015"
        
        tailor_url = (
            f"{base_url}/email_action/tailor?job_url={urllib.parse.quote(job_url, safe='')}"
            f"&email={urllib.parse.quote(user_email, safe='')}"
            f"&title={urllib.parse.quote(str(job.get('title', '')), safe='')}"
            f"&company={urllib.parse.quote(str(job.get('company', '')), safe='')}"
        )
        
        cards_html += f"""
        <div style="background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 12px; padding: 18px; box-sizing: border-box; overflow: hidden; margin-bottom: 12px;">
            <table style="width: 100%; border-collapse: collapse;">
                <tr>
                    <td>
                        <h3 style="margin: 0 0 4px 0; color: #1E293B; font-size: 1.05rem; font-weight: 700; font-family: 'Segoe UI', Arial, sans-serif;">{job.get('title', 'Job Listing')}</h3>
                        <p style="margin: 0; color: #64748B; font-size: 0.88rem; font-weight: 500; font-family: 'Segoe UI', Arial, sans-serif;">
                            {job.get('company', 'Hiring Company')} &bull; <span style="color: {platform_color}; font-weight: 700; background-color: {platform_bg}; padding: 2px 6px; border-radius: 4px;">{platform_name}</span>
                        </p>
                    </td>
                    <td style="text-align: right; vertical-align: top; width: 90px;">
                        <span style="display: inline-block; background-color: #10B98115; color: #10B981; padding: 4px 8px; border-radius: 6px; font-size: 0.78rem; font-weight: 700; font-family: 'Segoe UI', Arial, sans-serif; white-space: nowrap;">{job.get('score', 80)}% match</span>
                    </td>
                </tr>
            </table>
            
            <table style="width: 100%; border-collapse: collapse; margin-top: 14px;">
                <tr>
                    <td style="width: 50%; padding-right: 5px;">
                        <a href="{job_url}" target="_blank" style="display: block; box-sizing: border-box; text-align: center; padding: 9px 12px; font-size: 0.82rem; color: #64748B; background-color: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 6px; text-decoration: none; font-weight: 600; font-family: 'Segoe UI', Arial, sans-serif; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">View Listing</a>
                    </td>
                    <td style="width: 50%; padding-left: 5px;">
                        <a href="{tailor_url}" target="_blank" style="display: block; box-sizing: border-box; text-align: center; padding: 9px 12px; font-size: 0.82rem; color: #FFFFFF; background-color: #0284C7; border-radius: 6px; text-decoration: none; font-weight: bold; font-family: 'Segoe UI', Arial, sans-serif; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">⚡ Auto-Tailor</a>
                    </td>
                </tr>
            </table>
        </div>
        """

    return f"""
    <div style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; max-width: 600px; margin: 0 auto; padding: 25px; border: 1px solid #E2E8F0; border-radius: 16px; background-color: #FAFAFA; box-shadow: 0 4px 20px rgba(0,0,0,0.03); box-sizing: border-box;">
        <div style="text-align: center; margin-bottom: 24px;">
            <span style="font-size: 3rem;">📬</span>
            <h2 style="color: #0284C7; margin: 10px 0 5px; font-weight: 800; font-size: 1.5rem; font-family: 'Segoe UI', Arial, sans-serif;">Daily Job Matches Digest</h2>
            <p style="color: #334155; font-size: 0.98rem; font-weight: 600; margin: 8px 0 4px; font-family: 'Segoe UI', Arial, sans-serif;">Hi {candidate_name},</p>
            <p style="color: #64748B; font-size: 0.9rem; margin: 0; font-family: 'Segoe UI', Arial, sans-serif;">Here are your top matching roles from the past 24 hours:</p>
        </div>
        {cards_html}
    </div>
    """
