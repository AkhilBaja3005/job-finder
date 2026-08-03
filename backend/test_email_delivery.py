import os
from dotenv import load_dotenv
load_dotenv()

from services.email_service import send_notification_email

def test_smtp_delivery():
    email = "Akhilkumarbaja@gmail.com"
    subject = "🧪 Job Finder SMTP Test Email"
    text_body = "Hello! This is a test email verifying that the SMTP fallback configuration works successfully for your daily matching job cron digests."
    html_body = "<h3>🧪 Job Finder SMTP Test Email</h3><p>Hello! This is a test email verifying that your <strong>SMTP configuration works successfully</strong> for your daily matching job digests.</p>"
    
    print(f"Attempting to send test email to {email}...")
    success = send_notification_email(
        to_email=email,
        subject=subject,
        text_body=text_body,
        html_body=html_body
    )
    
    if success:
         print("✅ SMTP TEST EMAIL SENT: Check your inbox at Akhilkumarbaja@gmail.com!")
    else:
         print("❌ SMTP TEST EMAIL FAILED: Check your credentials in backend/.env")

if __name__ == "__main__":
    test_smtp_delivery()
