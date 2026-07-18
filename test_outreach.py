#!/usr/bin/env python3
"""
Test script to validate the Generate Outreach functionality.
Tests the complete flow: analyze job -> generate outreach message.
"""

import requests
import json
import time
import tempfile
import os

BASE_URL = "http://localhost:8000"

def test_analyze_job():
    """Test job analysis to get company name."""
    print("\n=== Testing Job Analysis ===")

    job_description = """
    Senior Software Engineer - Backend

    We're looking for a Senior Software Engineer to join our backend team at TechCorp.

    Requirements:
    - 5+ years of Python experience
    - Experience with FastAPI or similar frameworks
    - Strong understanding of databases and caching
    - Experience with cloud platforms (AWS, GCP, Azure)

    Responsibilities:
    - Design and implement scalable backend systems
    - Mentor junior engineers
    - Participate in code reviews
    - Collaborate with product and frontend teams
    """

    # First, upload a minimal resume as a PDF
    print("  Uploading minimal resume...")

    # Create a simple PDF using reportlab
    try:
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import letter
    except ImportError:
        print("  ✗ reportlab not installed, trying pypdf instead...")
        # Create a minimal PDF manually
        with tempfile.NamedTemporaryFile(mode='wb', suffix='.pdf', delete=False) as f:
            # Minimal PDF structure
            pdf_content = b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 4 0 R >> >> /MediaBox [0 0 612 792] /Contents 5 0 R >>
endobj
4 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>
endobj
5 0 obj
<< /Length 200 >>
stream
BT
/F1 12 Tf
50 750 Td
(John Doe) Tj
0 -20 Td
(john@example.com | 555-1234) Tj
0 -40 Td
(Senior Software Engineer with 5+ years experience) Tj
0 -20 Td
(Skills: Python, FastAPI, PostgreSQL, AWS) Tj
ET
endstream
endobj
xref
0 6
0000000000 65535 f
0000000009 00000 n
0000000058 00000 n
0000000115 00000 n
0000000214 00000 n
0000000301 00000 n
trailer
<< /Size 6 /Root 1 0 R >>
startxref
551
%%EOF
"""
            f.write(pdf_content)
            resume_path = f.name
    else:
        with tempfile.NamedTemporaryFile(mode='wb', suffix='.pdf', delete=False) as f:
            c = canvas.Canvas(f.name, pagesize=letter)
            c.drawString(50, 750, "John Doe")
            c.drawString(50, 730, "john@example.com | 555-1234")
            c.drawString(50, 690, "Senior Software Engineer with 5+ years experience")
            c.drawString(50, 670, "Skills: Python, FastAPI, PostgreSQL, AWS")
            c.save()
            resume_path = f.name

    try:
        with open(resume_path, 'rb') as f:
            files = {'file': f}
            upload_response = requests.post(
                f"{BASE_URL}/upload_resume",
                files=files,
                timeout=10
            )

        if upload_response.status_code != 200:
            print(f"  ✗ Resume upload failed: {upload_response.text}")
            os.unlink(resume_path)
            return None, None
        print("  ✓ Resume uploaded")
    except Exception as e:
        print(f"  ✗ Resume upload error: {e}")
        os.unlink(resume_path)
        return None, None
    finally:
        if os.path.exists(resume_path):
            os.unlink(resume_path)

    payload = {
        "job_url": "https://example.com/job/123",
        "job_title": "Senior Software Engineer",
        "job_description": job_description,
        "skip_tailoring": True
    }

    try:
        response = requests.post(
            f"{BASE_URL}/analyze_job",
            json=payload,
            headers={"Content-Type": "application/json"},
            stream=True,
            timeout=30
        )

        print(f"Status Code: {response.status_code}")

        company_name = None
        analysis_result = None

        for line in response.iter_lines():
            if line:
                event = json.loads(line)
                event_type = event.get("type")

                if event_type == "log":
                    print(f"  LOG: {event.get('message')}")
                elif event_type == "result":
                    company_name = event.get("company")
                    analysis_result = event.get("analysis")
                    print(f"  ✓ Company: {company_name}")
                    print(f"  ✓ Analysis received: {bool(analysis_result)}")
                elif event_type == "error":
                    print(f"  ERROR: {event.get('message')}")
                    return None, None

        return company_name, analysis_result

    except Exception as e:
        print(f"  ✗ Error: {e}")
        return None, None


def test_generate_outreach(company_name):
    """Test outreach message generation."""
    print("\n=== Testing Generate Outreach ===")

    if not company_name:
        print("  ✗ Skipping: No company name from analysis")
        return False

    payload = {
        "job_url": "https://example.com/job/123",
        "job_description": "Senior Software Engineer at TechCorp",
        "job_title": "Senior Software Engineer",
        "company_name": company_name,
        "recruiter_name": None,
        "platform": "unknown"
    }

    try:
        response = requests.post(
            f"{BASE_URL}/generate_outreach",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30
        )

        print(f"Status Code: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            print(f"  ✓ Recruiter Info: {data.get('recruiter_info')}")
            print(f"  ✓ Message generated:")
            message = data.get('message', {})
            print(f"    - Why applying: {message.get('why_applying', '')[:50]}...")
            print(f"    - Why fit: {message.get('why_fit', '')[:50]}...")
            print(f"    - Questions: {len(message.get('questions', []))} questions")
            print(f"    - Email subject: {message.get('email_subject', '')[:50]}...")
            return True
        else:
            print(f"  ✗ Error: {response.text}")
            return False

    except Exception as e:
        print(f"  ✗ Error: {e}")
        return False


def main():
    print("=" * 60)
    print("Generate Outreach Feature Test")
    print("=" * 60)

    # Test 1: Analyze job
    company_name, analysis = test_analyze_job()

    if not company_name:
        print("\n✗ FAILED: Could not extract company name from job analysis")
        return False

    # Test 2: Generate outreach
    success = test_generate_outreach(company_name)

    if success:
        print("\n" + "=" * 60)
        print("✓ ALL TESTS PASSED")
        print("=" * 60)
        return True
    else:
        print("\n" + "=" * 60)
        print("✗ TESTS FAILED")
        print("=" * 60)
        return False


if __name__ == "__main__":
    main()
