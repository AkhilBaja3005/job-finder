"""
test_setup_master_resume.py
Unit test suite verifying master resume path prompting, .env persistence, and auto-sync in `job-finder setup`.
"""

import os
import sys
import json
try:
    import pytest
except ImportError:
    class PytestMock:
        def fixture(self, func):
            return func
    pytest = PytestMock()
repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

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


def test_setup_prompts_and_launches_automation_browser(fake_workspace, monkeypatch):
    """Verifies that the setup wizard prompts for dedicated automation browser setup and launches it when accepted."""
    ws = fake_workspace["root"]
    resume_file = str(fake_workspace["resume_path"])

    monkeypatch.setenv("JOB_FINDER_ROOT", str(ws))
    monkeypatch.delenv("MASTER_RESUME_PATH", raising=False)

    call_count = 0
    def mock_input(prompt=""):
        nonlocal call_count
        call_count += 1
        p_lower = prompt.lower()
        if "master resume path" in p_lower:
            return resume_file
        if "automation browser" in p_lower:
            return "y"
        if "finished logging in" in p_lower:
            return ""
        if "enter " in p_lower:
            return ""
        if prompt == "":
            return "n"
        return ""




    with patch("sys.stdin.isatty", return_value=True):
        with patch("builtins.input", side_effect=mock_input):
            with patch("backend.mcp.tools.profile_tools.handle_sync_candidate_profile_from_resume", return_value={"success": True, "skills_count": 5, "experience_count": 2, "education_count": 1}):
                with patch("backend.services.browser_use_agent.ensure_persistent_browser", return_value="http://127.0.0.1:9222") as mock_ensure:
                    with patch("urllib.request.urlopen") as mock_urlopen:
                        # Return dummy JSON response for CDP /json/new calls
                        from unittest.mock import MagicMock
                        mock_resp = MagicMock()
                        mock_resp.read.return_value = json.dumps({"id": "TAB_123"}).encode("utf-8")
                        mock_resp.__enter__.return_value = mock_resp
                        mock_urlopen.return_value = mock_resp

                        with patch.object(sys, "argv", ["job-finder", "setup", "--api-key", "AIzaTestKey"]):
                            main()

    mock_ensure.assert_called_once_with(headless=False)
    assert mock_urlopen.call_count >= 3




def test_setup_browser_prompt_skipped(fake_workspace, monkeypatch):
    """Verifies that declining the browser setup prompt skips browser launch cleanly."""
    ws = fake_workspace["root"]
    resume_file = str(fake_workspace["resume_path"])

    monkeypatch.setenv("JOB_FINDER_ROOT", str(ws))
    monkeypatch.delenv("MASTER_RESUME_PATH", raising=False)

    def mock_input(prompt=""):
        p_lower = prompt.lower()
        if "master resume path" in p_lower:
            return resume_file
        if "optimize your summary" in p_lower:
            return "n"
        if "automation browser" in p_lower:
            return "n"
        return ""

    with patch("sys.stdin.isatty", return_value=True):
        with patch("builtins.input", side_effect=mock_input):
            with patch("backend.mcp.tools.profile_tools.handle_sync_candidate_profile_from_resume", return_value={"success": True, "skills_count": 5, "experience_count": 2, "education_count": 1}):
                with patch("backend.services.browser_use_agent.ensure_persistent_browser") as mock_ensure:
                    with patch.object(sys, "argv", ["job-finder", "setup", "--api-key", "AIzaTestKey"]):
                        main()

    mock_ensure.assert_not_called()


if __name__ == "__main__":
    import tempfile
    import pathlib

    print("Running test_setup_master_resume suite...")
    # Run tests using a temporary directory
    class MonkeyPatch:
        def __init__(self):
            self._saved = {}
        def setenv(self, k, v):
            if k not in self._saved:
                self._saved[k] = os.environ.get(k)
            os.environ[k] = v
        def delenv(self, k, raising=False):
            if k not in self._saved:
                self._saved[k] = os.environ.get(k)
            os.environ.pop(k, None)
        def undo(self):
            for k, v in self._saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    with tempfile.TemporaryDirectory() as td:
        tmp_p = pathlib.Path(td)
        fw = fake_workspace(tmp_p)
        mp = MonkeyPatch()
        try:
            test_setup_prompts_and_launches_automation_browser(fw, mp)
            print("  ✅ test_setup_prompts_and_launches_automation_browser passed!")
        finally:
            mp.undo()

        mp = MonkeyPatch()
        try:
            test_setup_browser_prompt_skipped(fw, mp)
            print("  ✅ test_setup_browser_prompt_skipped passed!")
        finally:
            mp.undo()

    print("All tests passed successfully.")


