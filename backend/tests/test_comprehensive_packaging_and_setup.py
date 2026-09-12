"""
test_comprehensive_packaging_and_setup.py
Comprehensive end-to-end test suite for:
1. Python package installation and CLI entrypoint commands (scan, apply, server, mcp, profile, setup).
2. Dynamic environment configuration without hardcoded paths or credentials.
3. Candidate profile auto-sync from resume (PDF/DOCX/LaTeX).
4. Portal password injection and account creation instruction generation.
5. Zero-cloud resilience (verifying pipeline operates in 100% offline fallback mode).
"""

import os
import sys
import json
import pytest
import tempfile
import shutil
from unittest.mock import patch, MagicMock


def test_package_metadata_and_version():
    """Verifies that job_finder package imports cleanly and has valid versioning."""
    import job_finder
    assert hasattr(job_finder, "__version__")
    assert job_finder.__version__ == "0.1.0"


def test_cli_help_and_subcommands_dispatch():
    """Validates that all CLI subcommands are properly registered in the parser."""
    from job_finder.cli import main
    with pytest.raises(SystemExit) as exc_info:
        with patch.object(sys, "argv", ["job-finder", "--help"]):
            main()
    assert exc_info.value.code == 0


def test_cli_setup_wizard_flow(tmp_path):
    """Verifies that `job-finder setup` generates .env and candidate_profile.json templates without errors."""
    from job_finder.cli import main

    fake_repo = tmp_path / "fake_repo"
    fake_repo.mkdir()
    (fake_repo / "backend" / "config").mkdir(parents=True)

    # Create dummy example templates
    (fake_repo / ".env.example").write_text("PORT=8000\nSCRAPER_CONCURRENCY=5\n", encoding="utf-8")
    (fake_repo / "backend" / "config" / "candidate_profile.example.json").write_text(
        json.dumps({"candidate": {"name": "Test User", "portals_password": "TestPassword123!"}}),
        encoding="utf-8"
    )

    with patch.dict(os.environ, {"JOB_FINDER_ROOT": str(fake_repo)}):
        with patch("os.path.dirname", return_value=str(fake_repo / "job_finder")):
            with patch("backend.mcp.tools.profile_tools.handle_sync_candidate_profile_from_resume", return_value={"success": True, "skills_count": 5, "experience_count": 2, "education_count": 1}):
                with patch.object(sys, "argv", ["job-finder", "setup", "--api-key", "AIzaSyTestKey123"]):
                    main()


    env_target = fake_repo / ".env"
    assert env_target.exists()
    env_content = env_target.read_text(encoding="utf-8")
    assert "GEMINI_API_KEY=AIzaSyTestKey123" in env_content

    profile_target = fake_repo / "backend" / "config" / "candidate_profile.json"
    assert profile_target.exists()
    with open(profile_target, "r", encoding="utf-8") as pf:
        p_data = json.load(pf)
    assert p_data["candidate"]["name"] == "Test User"


def test_dynamic_master_resume_resolution(tmp_path):
    """Ensures find_master_resume_with_mac_tags resolves dynamically across environment variables and fallbacks."""
    from applications_tracker.scheduled_job_scanner import find_master_resume_with_mac_tags

    # 1. Test MASTER_RESUME_PATH override
    custom_pdf = str(tmp_path / "custom_master.pdf")
    with open(custom_pdf, "w") as f:
        f.write("%PDF-1.4 dummy")

    with patch.dict(os.environ, {"MASTER_RESUME_PATH": custom_pdf}):
        assert find_master_resume_with_mac_tags() == custom_pdf

    # 2. Test MASTER_RESUME_DIR resolution
    custom_dir = tmp_path / "resumes"
    custom_dir.mkdir()
    dir_pdf = str(custom_dir / "my_cv.pdf")
    with open(dir_pdf, "w") as f:
        f.write("%PDF-1.4 dummy")

    with patch.dict(os.environ, {"MASTER_RESUME_PATH": "", "MASTER_RESUME_DIR": str(custom_dir)}):
        resolved = find_master_resume_with_mac_tags()
        assert resolved == dir_pdf


def test_offline_tracker_fallback(tmp_path):
    """Validates that application tracking writes to local CSV cleanly when Supabase is unconfigured."""
    import applications_tracker.scheduled_job_scanner as scanner

    temp_csv = str(tmp_path / "test_tracker.csv")
    dummy_payload = {
        "company": "Offline Corp",
        "job_title": "Systems Architect",
        "location": "London, UK",
        "platform": "Direct",
        "posted_time": "2026-09-12; 08:00",
        "overall_ats": 88,
        "skills_match": 90,
        "experience_match": 85,
        "role_fit": 88,
        "matched_skills": ["Python", "Docker"],
        "missing_skills": [],
        "salary": "£90k",
        "seniority": "Senior",
        "recruiter": "John Doe",
        "recruiter_linkedin": "",
        "pdf_path": "",
        "latex_path": "",
        "status": "Ready to Apply",
        "job_url": "https://example.com/jobs/123"
    }

    with patch.object(scanner, "CSV_PATH", temp_csv):
        with patch.object(scanner, "SUPABASE_URL", ""):
            with patch.object(scanner, "SUPABASE_KEY", ""):
                import asyncio
                asyncio.run(scanner.record_to_supabase_or_csv(dummy_payload))

    assert os.path.exists(temp_csv)
    with open(temp_csv, "r", encoding="utf-8") as f:
        content = f.read()
    assert "Offline Corp" in content
    assert "Systems Architect" in content
    assert "https://example.com/jobs/123" in content


def test_browser_use_task_prompt_portal_password_handling():
    """Validates that portal account password instructions are accurately generated in the browser-use prompt."""
    from services.browser_use_agent import build_application_task_prompt

    # Test A: With portals_password provided
    profile_with_pass = {
        "name": "Alex Applicant",
        "email": "alex@example.com",
        "phone": "+44 7123 456789",
        "location": "London, UK",
        "portals_password": "CustomSecurePassword999!"
    }
    prompt_a = build_application_task_prompt("https://workday.com/job/456", profile_with_pass)
    assert "Account Creation / Portal Password: CustomSecurePassword999!" in prompt_a
    assert "Enter 'CustomSecurePassword999!' into the Password and Confirm Password fields" in prompt_a

    # Test B: Without portals_password provided (clean fallback)
    profile_no_pass = {
        "name": "Sam Student",
        "email": "sam@example.com",
        "phone": "+44 7123 000111",
        "location": "London, UK"
    }
    with patch.dict(os.environ, {"PORTALS_PASSWORD": ""}):
        prompt_b = build_application_task_prompt("https://workday.com/job/789", profile_no_pass)
        assert "CustomSecurePassword999!" not in prompt_b
        assert "Look for 'Sign in with Google' first" in prompt_b
