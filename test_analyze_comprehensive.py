#!/usr/bin/env python3
"""
Comprehensive test script to validate the Analyze Job functionality.
Tests the complete flow with detailed error reporting.
"""

import requests
import json
import tempfile
import os
import sys

BASE_URL = "http://localhost:8000"

def create_valid_pdf():
    """Create a valid PDF."""
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
<< /Length 500 >>
stream
BT
/F1 12 Tf
50 750 Td
(John Doe) Tj
0 -20 Td
(john@example.com | 555-1234) Tj
0 -20 Td
(Senior Software Engineer) Tj
0 -40 Td
(SUMMARY) Tj
0 -20 Td
(Senior Software Engineer with 5+ years of experience) Tj
0 -40 Td
(SKILLS) Tj
0 -20 Td
(Python, FastAPI, PostgreSQL, AWS, Docker, Kubernetes) Tj
0 -40 Td
(EXPERIENCE) Tj
0 -20 Td
(Senior Engineer at TechCorp - 2020 to Present) Tj
0 -20 Td
(Led backend development for microservices) Tj
0 -40 Td
(EDUCATION) Tj
0 -20 Td
(BS Computer Science, University 2018) Tj
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
851
%%EOF
"""
    return pdf_content

def test_step(step_name, func):
    """Helper to run a test step and report results."""
    print(f"\n{'='*60}")
    print(f"STEP: {step_name}")
    print('='*60)
    try:
        result = func()
        print(f"✓ {step_name} PASSED")
        return result
    except Exception as e:
        print(f"✗ {step_name} FAILED")
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return None

def step_upload_resume():
    """Upload a resume."""
    pdf_content = create_valid_pdf()

    with tempfile.NamedTemporaryFile(mode='wb', suffix='.pdf', delete=False) as f:
        f.write(pdf_content)
        resume_path = f.name

    try:
        with open(resume_path, 'rb') as f:
            files = {'file': f}
            response = requests.post(
                f"{BASE_URL}/upload_resume",
                files=files,
                timeout=10
            )

        print(f"Upload response status: {response.status_code}")
        if response.status_code != 200:
            print(f"Response: {response.text}")
            raise Exception(f"Upload failed with status {response.status_code}")

        print("Resume uploaded successfully")
        return response.json()
    finally:
        if os.path.exists(resume_path):
            os.unlink(resume_path)

def step_analyze_job():
    """Test analyze job endpoint."""
    job_description = """
    Python and Machine Learning Engineer at TechCorp

    We're looking for a Python and Machine Learning Engineer to join our team at TechCorp.

    About TechCorp:
    TechCorp is a leading AI and machine learning company.

    Requirements:
    - 3+ years of Python experience
    - Experience with machine learning frameworks (TensorFlow, PyTorch)
    - Strong understanding of data structures and algorithms
    - Experience with cloud platforms (AWS, GCP)

    Responsibilities:
    - Develop and deploy ML models
    - Optimize model performance
    - Collaborate with data scientists
    - Participate in code reviews
    """

    payload = {
        "job_url": "https://example.com/job/123",
        "job_title": "Python and Machine Learning Engineer",
        "job_description": job_description,
        "skip_tailoring": True
    }

    print(f"Sending payload: {json.dumps(payload, indent=2)}")

    response = requests.post(
        f"{BASE_URL}/analyze_job",
        json=payload,
        headers={"Content-Type": "application/json"},
        stream=True,
        timeout=60
    )

    print(f"Response status: {response.status_code}")

    company_name = None
    analysis_result = None
    error_occurred = False
    events_received = []

    for line in response.iter_lines():
        if line:
            try:
                event = json.loads(line)
                events_received.append(event)
                event_type = event.get("type")

                if event_type == "log":
                    print(f"  LOG: {event.get('message')}")
                elif event_type == "result":
                    company_name = event.get("company")
                    analysis_result = event.get("analysis")
                    print(f"  ✓ Company: {company_name}")
                    print(f"  ✓ Analysis received: {bool(analysis_result)}")
                    if analysis_result:
                        print(f"    - Overall Score: {analysis_result.get('match_analysis', {}).get('overall_score')}")
                        print(f"    - Matched Skills: {analysis_result.get('match_analysis', {}).get('matched_skills', [])[:3]}")
                elif event_type == "error":
                    print(f"  ✗ ERROR: {event.get('message')}")
                    error_occurred = True
                    raise Exception(f"Backend error: {event.get('message')}")
            except json.JSONDecodeError as e:
                print(f"  ✗ Failed to parse JSON: {line}")
                error_occurred = True
                raise Exception(f"JSON parse error: {e}")

    print(f"\nTotal events received: {len(events_received)}")
    print(f"Events: {json.dumps(events_received, indent=2)}")

    if error_occurred:
        raise Exception("Error event received from backend")

    if not company_name or not analysis_result:
        raise Exception(f"Missing company ({company_name}) or analysis ({bool(analysis_result)})")

    return {
        "company": company_name,
        "analysis": analysis_result,
        "events": events_received
    }

def main():
    print("="*60)
    print("COMPREHENSIVE ANALYZE JOB TEST")
    print("="*60)

    # Step 1: Upload resume
    upload_result = test_step("Upload Resume", step_upload_resume)
    if not upload_result:
        print("\n✗ FAILED: Could not upload resume")
        return False

    # Step 2: Analyze job
    analyze_result = test_step("Analyze Job", step_analyze_job)
    if not analyze_result:
        print("\n✗ FAILED: Could not analyze job")
        return False

    print("\n" + "="*60)
    print("✓ ALL TESTS PASSED")
    print("="*60)
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
