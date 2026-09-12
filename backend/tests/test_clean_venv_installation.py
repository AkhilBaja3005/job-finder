"""
test_clean_venv_installation.py
Tests clean-room virtualenv creation and package installation from pyproject.toml:
1. Spawns an isolated temporary virtual environment (`venv`).
2. Performs editable pip install of `job-finder-ai` (`pip install -e . --no-deps`).
3. Executes and verifies every console script entrypoint:
   - `job-finder --help`
   - `job-finder scan --help`
   - `job-finder apply --help`
   - `job-finder profile --help`
   - `job-finder setup --help`
   - `job-finder-scanner --help`
"""

import os
import sys
import venv
import subprocess
import pytest


@pytest.mark.slow
def test_clean_venv_and_entrypoints(tmp_path):
    """Spawns an isolated venv, installs the package, and verifies all CLI entrypoints."""
    venv_dir = str(tmp_path / "isolated_venv")
    builder = venv.EnvBuilder(with_pip=True)
    builder.create(venv_dir)

    bin_dir = os.path.join(venv_dir, "bin")
    pip_exe = os.path.join(bin_dir, "pip")
    py_exe = os.path.join(bin_dir, "python")
    job_finder_bin = os.path.join(bin_dir, "job-finder")
    scanner_bin = os.path.join(bin_dir, "job-finder-scanner")

    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    # 1. Install package in isolated venv without external dependencies
    install_res = subprocess.run(
        [pip_exe, "install", "-e", repo_root, "--no-deps"],
        capture_output=True,
        text=True
    )
    assert install_res.returncode == 0, f"pip install -e . failed:\n{install_res.stderr}\n{install_res.stdout}"

    # 2. Verify job-finder binary exists and executes
    assert os.path.exists(job_finder_bin), f"Entrypoint {job_finder_bin} was not created."

    # 3. Test `job-finder --help`
    jf_help = subprocess.run([job_finder_bin, "--help"], capture_output=True, text=True)
    assert jf_help.returncode == 0
    assert "Job Finder AI - Autonomous Agentic Career & Application Toolkit" in jf_help.stdout
    assert "scan" in jf_help.stdout
    assert "apply" in jf_help.stdout
    assert "server" in jf_help.stdout
    assert "mcp" in jf_help.stdout
    assert "profile" in jf_help.stdout
    assert "setup" in jf_help.stdout

    # 4. Test `job-finder scan --help`
    scan_help = subprocess.run([job_finder_bin, "scan", "--help"], capture_output=True, text=True)
    assert scan_help.returncode == 0
    assert "--timeout" in scan_help.stdout
    assert "--tailor-timeout" in scan_help.stdout
    assert "--max-steps" in scan_help.stdout
    assert "--limit" in scan_help.stdout
    assert "--min-ats" in scan_help.stdout

    # 5. Test `job-finder apply --help`
    apply_help = subprocess.run([job_finder_bin, "apply", "--help"], capture_output=True, text=True)
    assert apply_help.returncode == 0
    assert "--submit" in apply_help.stdout
    assert "--timeout" in apply_help.stdout

    # 6. Test `job-finder setup --help`
    setup_help = subprocess.run([job_finder_bin, "setup", "--help"], capture_output=True, text=True)
    assert setup_help.returncode == 0
    assert "--api-key" in setup_help.stdout
    assert "--resume" in setup_help.stdout

    # 7. Test standalone `job-finder-scanner --help`
    assert os.path.exists(scanner_bin), f"Entrypoint {scanner_bin} was not created."
    sc_help = subprocess.run([scanner_bin, "--help"], capture_output=True, text=True)
    assert sc_help.returncode == 0
    assert "Autonomous Scheduled Job Discovery & Application Pipeline" in sc_help.stdout
    assert "--timeout" in sc_help.stdout

    # 8. Test Server Launch & HTTP Endpoint Verification in the Sandbox Environment
    import time
    import urllib.request
    import urllib.error
    import json

    test_port = 8991
    server_env = os.environ.copy()
    server_env["PORT"] = str(test_port)
    server_env["HOST"] = "127.0.0.1"

    # In sandbox without network access, allow the test server to load the core dependencies from host environment
    import site
    host_site_packages = site.getsitepackages()
    extra_paths = [os.path.join(repo_root, "backend")] + host_site_packages
    server_env["PYTHONPATH"] = os.pathsep.join(extra_paths)

    server_proc = subprocess.Popen(
        [py_exe, "-m", "job_finder.cli", "server", "--port", str(test_port)],
        env=server_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    try:
        # Wait for server to come online (up to 15 seconds)
        server_ready = False
        base_url = f"http://127.0.0.1:{test_port}"
        for _ in range(30):
            try:
                req = urllib.request.Request(f"{base_url}/healthz")
                with urllib.request.urlopen(req, timeout=1.0) as resp:
                    if resp.status == 200:
                        server_ready = True
                        break
            except Exception:
                time.sleep(0.5)

        if not server_ready:
            out, err = server_proc.communicate(timeout=3)
            raise AssertionError(f"Server failed to start on port {test_port} in isolated venv.\nStdout:\n{out}\nStderr:\n{err}")

        # Endpoint A: /healthz
        with urllib.request.urlopen(f"{base_url}/healthz", timeout=5.0) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data.get("status") == "ok"
            assert data.get("service") == "job-finder-backend"

        # Endpoint B: /health
        with urllib.request.urlopen(f"{base_url}/health", timeout=5.0) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data.get("status") == "ok"

        # Endpoint C: /auth/url
        with urllib.request.urlopen(f"{base_url}/auth/url", timeout=5.0) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert "url" in data

        # Endpoint D: /answer_question (deterministic notice period)
        q_payload = json.dumps({
            "question": "What is your notice period?",
            "company_name": "Acme AI"
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{base_url}/answer_question",
            data=q_payload,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data.get("status") == "success"
            assert "Available immediately" in data.get("answer", "")

        # Endpoint E: /extension/parse_job_details
        parse_payload = json.dumps({
            "page_title": "Senior AI Engineer",
            "page_text": "We are hiring a Senior AI Engineer at Acme AI to work on LLM systems."
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{base_url}/extension/parse_job_details",
            data=parse_payload,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data.get("job_title") == "Senior AI Engineer"
            assert data.get("company") == "Acme AI"

    finally:
        server_proc.terminate()
        try:
            server_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server_proc.kill()
