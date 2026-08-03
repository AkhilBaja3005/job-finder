import os
import smtplib
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from typing import Optional, List

def send_notification_email(
    to_email: str,
    subject: str,
    text_body: str,
    html_body: Optional[str] = None,
    attachment_path: Optional[str] = None,
    attachment_name: Optional[str] = None
) -> bool:
    """
    Sends an email to the recipient.
    Tries Cloudflare Email Sending REST API first.
    If credentials are not verified or fail, it automatically falls back to Gmail SMTP.
    """
    # 1. Try Cloudflare REST API first
    cf_account = os.getenv("CLOUDFLARE_ACCOUNT_ID")
    cf_token = os.getenv("CLOUDFLARE_API_TOKEN")
    cf_from = os.getenv("CLOUDFLARE_EMAIL_FROM")  # Verified domain email required for Cloudflare

    if cf_account and cf_token and cf_from:
        try:
            url = f"https://api.cloudflare.com/client/v4/accounts/{cf_account}/email/sending/send"
            headers = {
                "Authorization": f"Bearer {cf_token}",
                "Content-Type": "application/json"
            }
            payload = {
                "from": {"address": cf_from, "name": "Job Finder Digest"},
                "to": to_email,
                "subject": subject,
                "text": text_body
            }
            if html_body:
                payload["html"] = html_body
            
            if attachment_path and os.path.exists(attachment_path):
                import base64
                with open(attachment_path, "rb") as f:
                    encoded_b64 = base64.b64encode(f.read()).decode("utf-8")
                name = attachment_name or os.path.basename(attachment_path)
                payload["attachments"] = [
                    {
                        "filename": name,
                        "content": encoded_b64,
                        "type": "application/pdf"
                    }
                ]
            
            resp = requests.post(url, headers=headers, json=payload, timeout=15)
            if resp.status_code == 200:
                print("[Mailer] Sent successfully via Cloudflare Email API.")
                return True
            print(f"[Mailer] Cloudflare API failed with status {resp.status_code}: {resp.text}")
        except Exception as e:
            print(f"[Mailer] Cloudflare API exception: {e}. Falling back to SMTP.")

    # 2. SMTP Fallback (Gmail App Password)
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
        msg["From"] = email_from
        msg["To"] = to_email

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

        # Connect and send (support both Port 587 STARTTLS and Port 465 SSL)
        if smtp_port == 465:
            with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=15) as server:
                server.login(smtp_user, smtp_pass)
                server.sendmail(email_from, [to_email], msg.as_string())
        else:
            try:
                with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
                    server.starttls()
                    server.login(smtp_user, smtp_pass)
                    server.sendmail(email_from, [to_email], msg.as_string())
            except (OSError, smtplib.SMTPException) as e:
                # If Port 587 fails (common outbound block on cloud platforms), try Port 465 SSL fallback
                print(f"[Mailer] Port {smtp_port} failed ({e}). Trying Port 465 SSL fallback...")
                with smtplib.SMTP_SSL(smtp_host, 465, timeout=15) as server:
                    server.login(smtp_user, smtp_pass)
                    server.sendmail(email_from, [to_email], msg.as_string())

        print("[Mailer] Sent successfully via SMTP.")
        return True
    except Exception as e:
        print(f"[Mailer ERROR] SMTP delivery failed: {e}")
        return False


def build_digest_email_html(candidate_name: str, jobs: list, base_url: str, user_email: str) -> str:
    """
    Generates dynamic HTML body for Daily Job Digest emails.
    Renders Reed.co.uk platform badges in pink (#EC4899).
    """
    cards_html = ""
    for job in jobs:
        platform = job.get("platform", "Unknown")
        platform_color = "#0A66C2" if platform == "LinkedIn" else "#EC4899" if platform in ("Reed", "Reed.co.uk") else "#FF6F00"
        platform_bg = "rgba(10,102,194,0.1)" if platform == "LinkedIn" else "rgba(236,72,153,0.12)" if platform in ("Reed", "Reed.co.uk") else "rgba(255,111,0,0.1)"
        
        job_url = job.get("url", "")
        tailor_url = f"{base_url}/email_action/tailor?job_url={requests.utils.quote(job_url)}&email={requests.utils.quote(user_email)}"
        
        cards_html += f"""
        <div style="background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 12px; padding: 18px; box-sizing: border-box; overflow: hidden; margin-bottom: 12px;">
            <table style="width: 100%; border-collapse: collapse;">
                <tr>
                    <td>
                        <h3 style="margin: 0 0 4px 0; color: #1E293B; font-size: 1.05rem; font-weight: 700; font-family: 'Segoe UI', Arial, sans-serif;">{job.get('title', 'Job Listing')}</h3>
                        <p style="margin: 0; color: #64748B; font-size: 0.88rem; font-weight: 500; font-family: 'Segoe UI', Arial, sans-serif;">
                            {job.get('company', 'Hiring Company')} &bull; <span style="color: {platform_color}; font-weight: 700; background-color: {platform_bg}; padding: 2px 6px; border-radius: 4px;">{platform}</span>
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
