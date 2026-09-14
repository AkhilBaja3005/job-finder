"""
test_setup_master_resume.py
Unit test suite verifying master resume path prompting, .env persistence, and auto-sync in `job-finder setup`.
"""

import os
import sys
import json
import pytest
from unittest.mock import patch
from job_finder.cli import main


@pytest.fixture
def fake_workspace(tmp_path):
    """Creates a temporary workspace structure simulating a clean user directory."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "backend" / "config").mkdir(parents=True)

    # Base templates
    (ws / ".env.example").write_text("PORT=8000\nSCRAPER_CONCURRENCY=5\n", encoding="utf-8")
    (ws / "backend" / "config" / "candidate_profile.example.json").write_text(
        json.dumps({
            "candidate": {
                "name": "Jane Doe",
                "email": "jane@example.com",
                "core_skills": [],
                "portals_password": "TestPassword123!"
            }
        }),
        encoding="utf-8"
    )

    dummy_resume = ws / "master_resume.pdf"
    dummy_resume.write_text("%PDF-1.4 dummy resume content", encoding="utf-8")

    return {
        "root": ws,
        "env_path": ws / ".env",
        "profile_path": ws / "backend" / "config" / "candidate_profile.json",
        "resume_path": dummy_resume
    }


def test_setup_prompts_and_persists_master_resume(fake_workspace, monkeypatch):
    """Verifies that an interactive session prompts the user for resume path and saves it to .env."""
    ws = fake_workspace["root"]
    resume_file = str(fake_workspace["resume_path"])

    monkeypatch.setenv("JOB_FINDER_ROOT", str(ws))
    monkeypatch.delenv("MASTER_RESUME_PATH", raising=False)

    with patch("sys.stdin.isatty", return_value=True):
        with patch("builtins.input", return_value=resume_file):
            with patch("backend.mcp.tools.profile_tools.handle_sync_candidate_profile_from_resume", return_value={"success": True, "skills_count": 8, "experience_count": 3, "education_count": 1}) as mock_sync:
                with patch.object(sys, "argv", ["job-finder", "setup", "--api-key", "AIzaTestKey"]):
                    main()

    # 1. Verify MASTER_RESUME_PATH was written to .env
    env_content = fake_workspace["env_path"].read_text(encoding="utf-8")
    assert f"MASTER_RESUME_PATH={resume_file}" in env_content

    # 2. Verify environment variable updated
    assert os.environ.get("MASTER_RESUME_PATH") == resume_file

    # 3. Verify sync was called with the specified resume
    mock_sync.assert_called_once_with({"resume_path": resume_file})


def test_setup_with_resume_cli_argument(fake_workspace, monkeypatch):
    """Verifies that --resume CLI argument persists path directly to .env without prompting."""
    ws = fake_workspace["root"]
    resume_file = str(fake_workspace["resume_path"])

    monkeypatch.setenv("JOB_FINDER_ROOT", str(ws))
    monkeypatch.delenv("MASTER_RESUME_PATH", raising=False)

    with patch("backend.mcp.tools.profile_tools.handle_sync_candidate_profile_from_resume", return_value={"success": True, "skills_count": 5, "experience_count": 2, "education_count": 1}) as mock_sync:
        with patch.object(sys, "argv", ["job-finder", "setup", "--resume", resume_file, "--api-key", "AIzaTestKey"]):
            main()

    env_content = fake_workspace["env_path"].read_text(encoding="utf-8")
    assert f"MASTER_RESUME_PATH={resume_file}" in env_content
    assert os.environ.get("MASTER_RESUME_PATH") == resume_file
    mock_sync.assert_called_once_with({"resume_path": resume_file})


def test_setup_interactive_accepts_detected_default(fake_workspace, monkeypatch):
    """Verifies that hitting Enter accepts the detected default resume path and saves it."""
    ws = fake_workspace["root"]
    resume_file = str(fake_workspace["resume_path"])

    monkeypatch.setenv("JOB_FINDER_ROOT", str(ws))
    monkeypatch.delenv("MASTER_RESUME_PATH", raising=False)

    with patch("applications_tracker.scheduled_job_scanner.find_master_resume_with_mac_tags", return_value=resume_file):
        with patch("sys.stdin.isatty", return_value=True):
            # User presses Enter without typing (empty string input)
            with patch("builtins.input", return_value=""):
                with patch("backend.mcp.tools.profile_tools.handle_sync_candidate_profile_from_resume", return_value={"success": True, "skills_count": 4, "experience_count": 1, "education_count": 1}) as mock_sync:
                    with patch.object(sys, "argv", ["job-finder", "setup", "--api-key", "AIzaTestKey"]):
                        main()

    env_content = fake_workspace["env_path"].read_text(encoding="utf-8")
    assert f"MASTER_RESUME_PATH={resume_file}" in env_content
    mock_sync.assert_called_once_with({"resume_path": resume_file})


def test_setup_warns_on_nonexistent_resume(fake_workspace, monkeypatch, capsys):
    """Verifies that providing an invalid path outputs a warning without crashing."""
    ws = fake_workspace["root"]
    bogus_path = str(ws / "does_not_exist.pdf")

    monkeypatch.setenv("JOB_FINDER_ROOT", str(ws))
    monkeypatch.delenv("MASTER_RESUME_PATH", raising=False)

    with patch.object(sys, "argv", ["job-finder", "setup", "--resume", bogus_path, "--api-key", "AIzaTestKey"]):
        main()

    captured = capsys.readouterr()
    assert "Provided resume file does not exist" in captured.out
