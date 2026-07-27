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
