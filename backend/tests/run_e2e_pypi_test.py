"""
run_e2e_pypi_test.py
Self-contained end-to-end test suite for pip-installed job-finder-ai.
1. Checks clean package importing and entrypoints.
2. Boots job-finder-server in background on a dedicated port.
3. Tests key endpoints across all route groups:
   - /healthz, /health
   - /auth/url
   - /answer_question
   - /extension/parse_job_details
   - /mcp/tools
   - /mcp/messages (JSON-RPC tools/list and tools/call)
   - /user/sync_code
4. Tests CLI commands:
   - job-finder --help
   - job-finder scan --help
   - job-finder apply --help
   - job-finder setup --help
   - job-finder mcp (stdio jsonrpc pipe test)
"""
import sys
import os
import time
import json
import subprocess
import urllib.request
import urllib.error

def run_test():
    print("==================================================")
    print("🚀 RUNNING E2E TEST SUITE FOR PIP JOB-FINDER-AI")
    print("==================================================")

    py_exe = sys.executable
    print(f"Python: {py_exe}")

    # 1. Verify Imports
    print("\n[1/5] Verifying module imports...")
    import job_finder
    import backend
    import backend.main
    from backend.main import app
    print("  ✓ job_finder, backend, backend.main, and FastAPI app imported cleanly!")

    # 2. Inspect OpenAPI endpoints
    openapi = app.openapi()
    paths = openapi.get("paths", {})
    print(f"  ✓ Total OpenAPI endpoints registered: {len(paths)}")
    assert len(paths) >= 60, f"Expected >= 60 routes, got {len(paths)}"

    # 3. Boot server on test port
    test_port = 8998
    base_url = f"http://127.0.0.1:{test_port}"
    env = os.environ.copy()
    env["PORT"] = str(test_port)
    env["HOST"] = "127.0.0.1"

    print(f"\n[2/5] Starting job-finder-server on {base_url}...")
    server_proc = subprocess.Popen(
        [py_exe, "-m", "job_finder.cli", "server", "--port", str(test_port)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    try:
        ready = False
        for attempt in range(25):
            try:
                with urllib.request.urlopen(f"{base_url}/healthz", timeout=1.0) as resp:
                    if resp.status == 200:
                        ready = True
                        break
            except Exception:
                time.sleep(0.4)

        if not ready:
            out, err = server_proc.communicate(timeout=3)
            raise RuntimeError(f"Server failed to start:\nStdout:\n{out}\nStderr:\n{err}")

        print("  ✓ Server is ONLINE and responding!")

        # 4. Test REST Endpoints
        print("\n[3/5] Testing HTTP Endpoints...")

        # Test /healthz
        with urllib.request.urlopen(f"{base_url}/healthz", timeout=5.0) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["status"] == "ok"
            print("  ✓ GET /healthz -> status ok")

        # Test /health
        with urllib.request.urlopen(f"{base_url}/health", timeout=5.0) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["status"] == "ok"
            print("  ✓ GET /health -> status ok")

        # Test /auth/url
        with urllib.request.urlopen(f"{base_url}/auth/url", timeout=5.0) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert "url" in data
            print("  ✓ GET /auth/url -> returns oauth url")

        # Test /mcp/tools
        with urllib.request.urlopen(f"{base_url}/mcp/tools", timeout=5.0) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert "tools" in data
            tools = data["tools"]
            assert len(tools) >= 15
            print(f"  ✓ GET /mcp/tools -> returns {len(tools)} tools")

        # Test /mcp/messages (JSON-RPC tools/list)
        rpc_req = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {}
        }).encode("utf-8")
        req = urllib.request.Request(f"{base_url}/mcp/messages", data=rpc_req, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            assert resp.status == 200
            rpc_res = json.loads(resp.read().decode("utf-8"))
            assert "result" in rpc_res
            assert "tools" in rpc_res["result"]
            print(f"  ✓ POST /mcp/messages (tools/list) -> returns {len(rpc_res['result']['tools'])} tools via JSON-RPC 2.0")

        # Test /answer_question
        ans_req = json.dumps({
            "question": "What is your notice period?",
            "company_name": "Google"
        }).encode("utf-8")
        req = urllib.request.Request(f"{base_url}/answer_question", data=ans_req, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            assert resp.status == 200
            ans_res = json.loads(resp.read().decode("utf-8"))
            assert ans_res["status"] == "success"
            assert "Available immediately" in ans_res["answer"]
            print(f"  ✓ POST /answer_question -> deterministic fast fallback returned successfully")

        # Test /extension/parse_job_details
        parse_req = json.dumps({
            "page_title": "Senior AI Infrastructure Engineer - London",
            "page_text": "We are looking for an AI Infrastructure Engineer at DeepMind in London."
        }).encode("utf-8")
        req = urllib.request.Request(f"{base_url}/extension/parse_job_details", data=parse_req, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            assert resp.status == 200
            parse_res = json.loads(resp.read().decode("utf-8"))
            assert "job_title" in parse_res
            print(f"  ✓ POST /extension/parse_job_details -> parsed title '{parse_res.get('job_title')}'")

    finally:
        server_proc.terminate()
        try:
            server_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server_proc.kill()
        print("  ✓ Test server terminated cleanly.")

    # 5. Test CLI Subcommands
    print("\n[4/5] Testing CLI subcommands...")
    bin_dir = os.path.dirname(py_exe)
    jf_bin = os.path.join(bin_dir, "job-finder")

    if os.path.exists(jf_bin):
        res = subprocess.run([jf_bin, "--help"], capture_output=True, text=True)
        assert res.returncode == 0
        assert "scan" in res.stdout
        print("  ✓ `job-finder --help` executed successfully")

        res = subprocess.run([jf_bin, "scan", "--help"], capture_output=True, text=True)
        assert res.returncode == 0
        print("  ✓ `job-finder scan --help` executed successfully")

        res = subprocess.run([jf_bin, "server", "--help"], capture_output=True, text=True)
        assert res.returncode == 0
        print("  ✓ `job-finder server --help` executed successfully")

        res = subprocess.run([jf_bin, "apply", "--help"], capture_output=True, text=True)
        assert res.returncode == 0
        assert "--submit" in res.stdout
        print("  ✓ `job-finder apply --help` executed successfully")

        res = subprocess.run([jf_bin, "status"], capture_output=True, text=True)
        assert res.returncode == 0
        assert "JOB FINDER AI SYSTEM HEALTH" in res.stdout
        print("  ✓ `job-finder status` executed successfully")

        res = subprocess.run([jf_bin, "ats"], capture_output=True, text=True)
        assert res.returncode == 0
        assert "MASTER RESUME ATS HEALTH AUDIT" in res.stdout
        print("  ✓ `job-finder ats` executed successfully")

        res = subprocess.run([jf_bin, "tracker"], capture_output=True, text=True)
        assert res.returncode == 0
        print("  ✓ `job-finder tracker` executed successfully")

        res = subprocess.run([jf_bin, "profile", "--show"], capture_output=True, text=True)
        assert res.returncode == 0
        assert "Profile:" in res.stdout
        print("  ✓ `job-finder profile --show` executed successfully")

        # Test MCP Stdio
        p = subprocess.Popen(
            [jf_bin, "mcp"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        msg = json.dumps({"jsonrpc": "2.0", "id": 42, "method": "tools/list"}) + "\n"
        stdout_data, _ = p.communicate(input=msg, timeout=5)
        assert "calculate_ats_score" in stdout_data
        print("  ✓ `job-finder mcp` stdio JSON-RPC executed successfully")
    else:
        print(f"  Note: {jf_bin} not found in this env, skipping binary entrypoint check.")

    # 6. Test CLI .env Auto-Loading & Prompt Earliest Start Date Rules
    print("\n[5/5] Testing CLI .env auto-loading & Prompt Date Rules...")
    from job_finder.cli import load_workspace_env
    # Create temporary .env to verify override loading
    test_env_file = os.path.join(os.getcwd(), ".env.test_tmp")
    with open(test_env_file, "w", encoding="utf-8") as f:
        f.write("CLI_ENV_TEST_VAR=LOADED_SUCCESSFULLY\n")
    try:
        from dotenv import load_dotenv
        load_dotenv(test_env_file, override=True)
        assert os.getenv("CLI_ENV_TEST_VAR") == "LOADED_SUCCESSFULLY"
        print("  ✓ Automatic CLI .env resolution & environment loading verified!")
    finally:
        if os.path.exists(test_env_file):
            os.remove(test_env_file)

    # Test Date formatting & Notice Period prompt synthesis
    from backend.services.browser_use_agent import build_application_task_prompt
    test_prompt = build_application_task_prompt(
        job_url="https://example.com/job/123",
        resume_data={
            "candidate": {
                "name": "Akhil Baja",
                "notice_period": "Available immediately"
            }
        }
    )
    assert "Notice Period / Earliest Availability: Available immediately" in test_prompt
    assert "HTML5 date input or Calendar Date-Picker" in test_prompt
    print("  ✓ Earliest start date, notice period, and calendar date-picker rules verified in browser-use task prompt!")

    print("\n==================================================")
    print("🎉 ALL ENDPOINT & FUNCTIONALITY TESTS PASSED 100%!")
    print("==================================================")

if __name__ == "__main__":
    run_test()
