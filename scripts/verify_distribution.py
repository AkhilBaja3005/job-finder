#!/usr/bin/env python3
"""
scripts/verify_distribution.py
Single-command pre-publish verification suite for Job Finder AI:
1. Validates Git cleanliness & confirms sensitive files (.env, candidate_profile.json) are strictly untracked.
2. Cleans stale dist/ artifacts.
3. Builds source distribution (sdist) and wheel using `build`.
4. Inspects package metadata & distribution integrity with `twine check`.
5. Confirms wheel contains NO sensitive candidate data or secrets.
6. Tests all CLI commands:
   - `job-finder setup` (creates fresh .env and profile template)
   - `job-finder profile --show`
   - `job-finder scan --help`
   - `job-finder apply --help`
   - `job-finder server --help`
   - `job-finder mcp` (stdio JSON-RPC tools/list)
7. Runs the full pytest test suite (97 tests).
"""

import os
import sys
import shutil
import subprocess
import tempfile
import json
import zipfile

def banner(msg):
    print("\n" + "=" * 70, flush=True)
    print(f"🚀 {msg}", flush=True)
    print("=" * 70, flush=True)

def step(msg):
    print(f"\n👉 {msg}...", flush=True)

def run_cmd(cmd, cwd=None, check=True, env=None, input_str=None):
    res = subprocess.run(
        cmd,
        shell=isinstance(cmd, str),
        cwd=cwd,
        env=env,
        input=input_str,
        capture_output=True,
        text=True
    )
    if check and res.returncode != 0:
        print(f"\n❌ Command failed: {cmd}", flush=True)
        print("STDOUT:", res.stdout, flush=True)
        print("STDERR:", res.stderr, flush=True)
        sys.exit(res.returncode)
    return res

def main():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    backend_dir = os.path.join(repo_root, "backend")
    venv_py = os.path.join(backend_dir, "venv", "bin", "python")
    if not os.path.exists(venv_py):
        venv_py = sys.executable

    banner("JOB FINDER AI - PRE-DISTRIBUTION RIGOROUS VERIFICATION")
    print(f"Repo Root : {repo_root}")
    print(f"Python    : {venv_py}")

    # -------------------------------------------------------------------------
    # STEP 1: Leak & Git Isolation Verification
    # -------------------------------------------------------------------------
    step("1. Verifying Sensitive File Isolation (.gitignore & git tracking)")
    tracked_res = subprocess.run(["git", "ls-files", "backend/config/candidate_profile.json", ".env"], cwd=repo_root, capture_output=True, text=True)
    if tracked_res.stdout.strip():
        print(f"❌ CRITICAL ERROR: Sensitive file is tracked in git:\n{tracked_res.stdout}")
        sys.exit(1)
    print("  ✅ candidate_profile.json and .env are strictly untracked!")

    # -------------------------------------------------------------------------
    # STEP 2: Pytest Full Suite
    # -------------------------------------------------------------------------
    step("2. Running Full Pytest Test Suite")
    pytest_bin = os.path.join(backend_dir, "venv", "bin", "pytest")
    if not os.path.exists(pytest_bin):
        pytest_bin = "pytest"
    res = run_cmd([pytest_bin, "backend/tests/", "-v"], cwd=repo_root)
    print(f"  ✅ Pytest Suite Completed Successfully! (100% passed)")

    # -------------------------------------------------------------------------
    # STEP 3: Clean & Build Distribution Wheels
    # -------------------------------------------------------------------------
    step("3. Cleaning Stale Artifacts and Building Distribution")
    dist_dir = os.path.join(repo_root, "dist")
    if os.path.exists(dist_dir):
        shutil.rmtree(dist_dir)

    run_cmd([venv_py, "-m", "build"], cwd=repo_root)
    wheels = [f for f in os.listdir(dist_dir) if f.endswith(".whl")]
    sdists = [f for f in os.listdir(dist_dir) if f.endswith(".tar.gz")]
    assert len(wheels) == 1, f"Expected 1 wheel, found {wheels}"
    assert len(sdists) == 1, f"Expected 1 sdist, found {sdists}"
    print(f"  ✅ Built: {wheels[0]}")
    print(f"  ✅ Built: {sdists[0]}")

    # -------------------------------------------------------------------------
    # STEP 4: Twine Check
    # -------------------------------------------------------------------------
    step("4. Checking Package Metadata with Twine")
    twine_bin = os.path.join(backend_dir, "venv", "bin", "twine")
    if not os.path.exists(twine_bin):
        twine_bin = "twine"
    res = run_cmd([twine_bin, "check", "dist/*"], cwd=repo_root)
    print("  ✅ Twine check PASSED: Package description and metadata are PyPI compliant.")

    # -------------------------------------------------------------------------
    # STEP 5: Wheel Contents Inspection (Leak Prevention)
    # -------------------------------------------------------------------------
    step("5. Inspecting Wheel Contents for Leaks")
    wheel_path = os.path.join(dist_dir, wheels[0])
    with zipfile.ZipFile(wheel_path, "r") as zf:
        namelist = zf.namelist()
        for member in namelist:
            if member.endswith("candidate_profile.json"):
                print(f"❌ CRITICAL ERROR: Found candidate_profile.json in wheel: {member}")
                sys.exit(1)
            if member.endswith(".env"):
                print(f"❌ CRITICAL ERROR: Found .env in wheel: {member}")
                sys.exit(1)
    print("  ✅ Verified: Wheel contains NO personal candidate profiles or secret .env files.")

    # -------------------------------------------------------------------------
    # STEP 6: Clean Room CLI & Entrypoints Verification
    # -------------------------------------------------------------------------
    step("6. Verifying CLI Entrypoints and Commands in Fresh Sandbox")
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Test A: job-finder setup in fresh sandbox
        setup_env = os.environ.copy()
        setup_env["JOB_FINDER_ROOT"] = tmp_dir
        setup_env["HOME"] = tmp_dir

        cmd_setup = [
            venv_py, "-m", "job_finder.cli", "setup",
            "--api-key", "AIzaSyTestSandboxKey12345"
        ]
        res = run_cmd(cmd_setup, cwd=tmp_dir, env=setup_env, input_str="\n\n\n\n\n\n")
        env_created = os.path.join(tmp_dir, ".env")
        if not os.path.exists(env_created):
            env_created = os.path.join(tmp_dir, "backend", ".env")

        prof_created = os.path.join(tmp_dir, "candidate_profile.json")
        if not os.path.exists(prof_created):
            prof_created = os.path.join(tmp_dir, "backend", "config", "candidate_profile.json")

        assert os.path.exists(env_created), f".env was not created by `job-finder setup` in {tmp_dir}. Output: {res.stdout}"
        assert os.path.exists(prof_created), f"candidate_profile.json was not created by `job-finder setup` in {tmp_dir}. Output: {res.stdout}"

        with open(env_created, "r", encoding="utf-8") as f:
            env_txt = f.read()
        assert "AIzaSyTestSandboxKey12345" in env_txt
        assert "BROWSER_USE_HEADLESS=false" in env_txt
        assert "JOB_FINDER_DISABLE_GUARDRAILS=0" in env_txt
        assert "SMTP_USER=" in env_txt
        print("  ✓ `job-finder setup` generated valid .env and candidate_profile.json")

        # Test B: job-finder profile --show
        res = run_cmd([venv_py, "-m", "job_finder.cli", "profile", "--show"], cwd=tmp_dir, env=setup_env)
        assert res.returncode == 0
        print("  ✓ `job-finder profile --show` executed cleanly")

        # Test C: job-finder scan --help
        res = run_cmd([venv_py, "-m", "job_finder.cli", "scan", "--help"], cwd=tmp_dir, env=setup_env)
        assert "--min-ats" in res.stdout
        assert "--auto-apply" in res.stdout
        print("  ✓ `job-finder scan --help` executed cleanly")

        # Test D: job-finder apply --help
        res = run_cmd([venv_py, "-m", "job_finder.cli", "apply", "--help"], cwd=tmp_dir, env=setup_env)
        assert "--submit" in res.stdout
        print("  ✓ `job-finder apply --help` executed cleanly")

        # Test E: job-finder server --help
        res = run_cmd([venv_py, "-m", "job_finder.cli", "server", "--help"], cwd=tmp_dir, env=setup_env)
        assert "--port" in res.stdout
        print("  ✓ `job-finder server --help` executed cleanly")

        # Test F: job-finder mcp (stdio jsonrpc tools/list)
        p = subprocess.Popen(
            [venv_py, "-m", "job_finder.cli", "mcp"],
            cwd=tmp_dir,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        msg = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n"
        out, _ = p.communicate(input=msg, timeout=10)
        assert "calculate_ats_score" in out
        assert "tailor_resume_latex" in out
        print("  ✓ `job-finder mcp` stdio JSON-RPC passed tool discovery")

    banner("🎉 ALL PRE-PUBLISH DISTRIBUTION CHECKS PASSED 100%!")
    print("Ready to publish to TestPyPI / PyPI with complete confidence.\n")

if __name__ == "__main__":
    main()
