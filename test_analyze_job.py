#!/usr/bin/env python3
"""
Test script to validate the Analyze Job functionality.
Tests just the analyze job endpoint without tailoring.
"""

import requests
import json
import tempfile
import os

BASE_URL = "http://localhost:8000"

def test_analyze_job_only():
    """Test job analysis without tailoring."""
    print("\n=== Testing Analyze Job (No Tailoring) ===")

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
            return False
        print("  ✓ Resume uploaded")
    except Exception as e:
        print(f"  ✗ Resume upload error: {e}")
        os.unlink(resume_path)
        return False
    finally:
        if os.path.exists(resume_path):
            os.unlink(resume_path)

    # Now test analyze job with skip_tailoring=True
    payload = {
        "job_url": "https://example.com/job/123",
        "job_title": "Senior Software Engineer",
        "job_description": job_description,
        "skip_tailoring": True
    }

    try:
        print("\n  Calling /analyze_job endpoint...")
        response = requests.post(
            f"{BASE_URL}/analyze_job",
            json=payload,
            headers={"Content-Type": "application/json"},
            stream=True,
            timeout=30
        )

        print(f"  Status Code: {response.status_code}")

        company_name = None
        analysis_result = None
        error_occurred = False

        for line in response.iter_lines():
            if line:
                try:
                    event = json.loads(line)
                    event_type = event.get("type")

                    if event_type == "log":
                        print(f"    LOG: {event.get('message')}")
                    elif event_type == "result":
                        company_name = event.get("company")
                        analysis_result = event.get("analysis")
                        print(f"    ✓ Company: {company_name}")
                        print(f"    ✓ Analysis received: {bool(analysis_result)}")
                        if analysis_result:
                            print(f"      - Overall Score: {analysis_result.get('match_analysis', {}).get('overall_score')}")
                            print(f"      - Matched Skills: {analysis_result.get('match_analysis', {}).get('matched_skills', [])[:3]}")
                    elif event_type == "error":
                        print(f"    ✗ ERROR: {event.get('message')}")
                        error_occurred = True
                except json.JSONDecodeError as e:
                    print(f"    ✗ Failed to parse JSON: {line}")
                    error_occurred = True

        if error_occurred:
            return False

        if not company_name or not analysis_result:
            print("  ✗ Missing company or analysis result")
            return False

        print("\n  ✓ Analyze Job test PASSED")
        return True

    except Exception as e:
        print(f"  ✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    print("=" * 60)
    print("Analyze Job Feature Test")
    print("=" * 60)

    success = test_analyze_job_only()

    if success:
        print("\n" + "=" * 60)
        print("✓ TEST PASSED")
        print("=" * 60)
        return True
    else:
        print("\n" + "=" * 60)
        print("✗ TEST FAILED")
        print("=" * 60)
        return False


if __name__ == "__main__":
    main()
