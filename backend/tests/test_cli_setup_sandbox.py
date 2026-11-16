"""`job-finder setup` must create .env and candidate_profile.json in a fresh workspace.

Regression test: moving the setup command into job_finder/commands/ broke its __file__-relative
lookup of the example profile, so no profile was created (found by the distribution check in CI).
"""

import os
import subprocess
import sys


def test_setup_creates_env_and_profile_in_fresh_workspace(tmp_path):
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONPATH": root,
        "JOB_FINDER_ROOT": str(tmp_path),
        "HOME": str(tmp_path),
        "JOB_FINDER_NO_UPDATE_CHECK": "1",
    }
    res = subprocess.run(
        [sys.executable, "-m", "job_finder.cli", "setup", "--api-key", "AIzaSyTestSandboxKey12345"],
        cwd=str(tmp_path), env=env, input="\n\n\n\n\n\n", capture_output=True, text=True, timeout=120,
    )
    assert res.returncode == 0, res.stderr[-500:]
    env_file = tmp_path / ".env"
    assert env_file.exists() and "AIzaSyTestSandboxKey12345" in env_file.read_text(encoding="utf-8")
    profile = tmp_path / "candidate_profile.json"
    alt = tmp_path / "backend" / "config" / "candidate_profile.json"
    assert profile.exists() or alt.exists(), res.stdout[-500:]
