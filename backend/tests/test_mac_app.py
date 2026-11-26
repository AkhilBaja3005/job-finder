import importlib
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

MACAPP = Path(__file__).resolve().parents[2] / "macapp"
sys.path.insert(0, str(MACAPP))
panel = importlib.import_module("scan_panel")


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("JOB_FINDER_APP_HOME", str(tmp_path / "support"))
    return tmp_path


# ── folders ─────────────────────────────────────────────────────────────────────
def test_workspace_defaults_to_the_app_folder_and_can_be_pointed_elsewhere(home):
    assert panel.workspace_dir() == home / "support"
    existing = home / "my-jobs"
    existing.mkdir()
    panel.save_app_config({"workspace": str(existing)})
    assert panel.workspace_dir() == existing
    panel.save_app_config({"workspace": str(home / "gone")})  # a folder that no longer exists is ignored
    assert panel.workspace_dir() == home / "support"


# ── preferences ─────────────────────────────────────────────────────────────────
def _profile(ws, **prefs):
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "candidate_profile.json").write_text(json.dumps({
        "candidate": {"name": "Ada", "email": "a@b.c"},
        "search_preferences": {"target_roles": ["ML Intern"], "target_locations": ["London, UK", "UK"], "timeframe": "48h",
                               "min_ats_score_threshold": 70, "skip_portals": ["targetjobs"], **prefs},
        "networking_and_references": {"keep": "me"},
    }))


def test_read_preferences(home):
    ws = home / "ws"
    _profile(ws)
    p = panel.read_preferences(ws)
    assert p["profile_exists"] and p["candidate_name"] == "Ada"
    assert p["roles"] == ["ML Intern"] and p["location"] == "London, UK" and p["timeframe"] == "48h"
    assert p["min_ats"] == 70 and p["skip_portals"] == ["targetjobs"]


def test_missing_profile_is_reported(home):
    assert panel.read_preferences(home / "empty")["profile_exists"] is False


def test_write_preferences_changes_only_search_preferences(home):
    ws = home / "ws"
    _profile(ws)
    panel.write_preferences(ws, {"roles": "Data Intern\nAI Intern", "location": "Leeds", "timeframe": "24h", "min_ats": "80",
                                 "title_keywords": "intern, placement", "skip_portals": "reed"})
    data = json.loads((ws / "candidate_profile.json").read_text())
    assert data["search_preferences"]["target_roles"] == ["Data Intern", "AI Intern"]
    assert data["search_preferences"]["target_locations"] == ["Leeds", "UK"]  # first one replaced, the rest kept
    assert data["search_preferences"]["min_ats_score_threshold"] == 80
    assert data["search_preferences"]["required_title_keywords"] == ["intern", "placement"]
    assert data["candidate"]["name"] == "Ada" and data["networking_and_references"] == {"keep": "me"}
    assert ((ws / "candidate_profile.json").stat().st_mode & 0o777) == 0o600


# ── .env and keys ───────────────────────────────────────────────────────────────
def test_env_values_are_written_privately_and_replaced(home):
    ws = home / "ws"
    panel.write_env_value(ws, "OPENAI_API_KEY", "sk-first-1234567890")
    panel.write_env_value(ws, "GEMINI_API_KEY", "AIza-abcdef123456")
    panel.write_env_value(ws, "OPENAI_API_KEY", "sk-second-0987654321")
    env = panel.read_env(ws)
    assert env["OPENAI_API_KEY"] == "sk-second-0987654321" and env["GEMINI_API_KEY"] == "AIza-abcdef123456"
    assert ((ws / ".env").stat().st_mode & 0o777) == 0o600
    status = panel.key_status(ws)
    assert status["openai"] == {"set": True, "hint": "4321"} and status["anthropic"]["set"] is False
    assert "sk-second" not in json.dumps(status)  # the window never receives a full key


# ── the command ─────────────────────────────────────────────────────────────────
def test_practice_run_never_submits():
    args = panel.build_scan_args({"mode": "dry_run", "limit": "5", "min_ats": "70", "timeframe": "24h",
                                  "location": "London, UK", "skip_portals": "reed, indeed", "headless": True})
    assert args[:2] == ["scan", "--dry-run"] and "--auto-apply" not in args
    assert ["--limit", "5"] == args[args.index("--limit"):args.index("--limit") + 2]
    assert "--skip-portals" in args and args[args.index("--skip-portals") + 1] == "reed,indeed" and "--headless" in args


def test_apply_for_real_is_explicit():
    assert "--auto-apply" in panel.build_scan_args({"mode": "auto_apply"})
    assert "--dry-run" not in panel.build_scan_args({"mode": "auto_apply"})


def test_unknown_mode_falls_back_to_practice_run():
    assert panel.build_scan_args({})[:2] == ["scan", "--dry-run"]
    assert "--limit" not in panel.build_scan_args({"limit": "0"})


def test_run_env_sets_workspace_and_provider_order(tmp_path):
    env = panel.build_run_env({"primary_ai": "anthropic"}, tmp_path, base={"PATH": "/usr/bin"})
    assert env["JOB_FINDER_ROOT"] == str(tmp_path) and env["PYTHONUNBUFFERED"] == "1"
    assert env["BROWSER_USE_PROVIDERS"] == "anthropic,gemini,openai"
    assert "BROWSER_USE_PROVIDERS" not in panel.build_run_env({"primary_ai": "auto"}, tmp_path, base={})


# ── progress counters ───────────────────────────────────────────────────────────
def test_counts_read_the_scanner_messages():
    lines = [
        "[3/26] EXCELLENT MATCH (93% >= 80%): X @ Y",
        "   Application verified & submitted successfully for X @ Y",
        "[4/26] Skipping existing: A @ B (84% ATS)",
        "   Submission verification failed for C @ D: reason",
        "[5/26] Skipping title without required keyword (intern): Quant @ E",
    ]
    assert panel.count_progress(lines) == {"found": 26, "position": 5, "submitted": 1, "needs_review": 1, "skipped": 2}


# ── running a child process ─────────────────────────────────────────────────────
def _wait(runner, seconds=10):
    deadline = time.time() + seconds
    while time.time() < deadline and runner.running:
        time.sleep(0.05)


def test_runner_streams_output_without_colour_codes(tmp_path):
    runner = panel.ScanRunner([sys.executable, "-c", "import sys; print('\\x1b[31mhello\\x1b[0m'); print('world'); sys.exit(3)", "--"])
    assert runner.start([], {"PATH": "/usr/bin"}, tmp_path)["ok"]
    _wait(runner)
    time.sleep(0.2)
    result = runner.poll(0)
    assert result["lines"] == ["hello", "world"] and result["exit_code"] == 3 and result["running"] is False
    assert runner.poll(result["next"])["lines"] == []  # only new lines after the offset


def test_runner_refuses_a_second_run_and_stop_ends_the_first(tmp_path):
    runner = panel.ScanRunner([sys.executable, "-c", "import time; print('up', flush=True); time.sleep(60)", "--"])
    assert runner.start([], {"PATH": "/usr/bin"}, tmp_path)["ok"]
    time.sleep(0.5)
    assert runner.start([], {}, tmp_path)["ok"] is False
    assert runner.stop()["ok"]
    _wait(runner, 5)
    assert runner.running is False


# ── results ─────────────────────────────────────────────────────────────────────
def test_tracker_rows_newest_first(home):
    ws = home / "ws"
    (ws / "applications_tracker").mkdir(parents=True)
    (ws / "applications_tracker" / "job_applications_tracker.csv").write_text(
        "Company,Job Title,Platform,Overall ATS,Status,Job URL\nOld Co,Dev,LinkedIn,70%,applied,http://a\nNew Co,ML Intern,LinkedIn,88%,Tailored & Ready,http://b\n")
    rows = panel.read_tracker(ws)
    assert [r["company"] for r in rows] == ["New Co", "Old Co"]
    assert rows[0]["url"] == "http://b" and rows[0]["ats"] == "88%"
    assert panel.read_tracker(home / "none") == []


# ── what the window may call ────────────────────────────────────────────────────
def test_api_refuses_to_start_without_a_profile(home):
    api = panel.Api([sys.executable])
    result = api.start_scan({"mode": "dry_run"})
    assert result["ok"] is False and "profile" in result["error"].lower()


def test_api_only_opens_web_links(home):
    api = panel.Api([sys.executable])
    assert api.open_url("file:///etc/passwd") == {"ok": False}
    assert api.open_path("../../etc") == {"ok": False}
    assert api.run_command("rm", ["-rf", "/"])["ok"] is False


# ── Supabase ────────────────────────────────────────────────────────────────────
def _env(ws, **values):
    for k, v in values.items():
        panel.write_env_value(ws, k, v)


def test_supabase_is_off_without_url_and_key(home):
    ws = home / "ws"
    assert panel.supabase_settings(ws) is None
    _env(ws, SUPABASE_URL="https://abc.supabase.co/")
    assert panel.supabase_settings(ws) is None  # a URL alone is not enough
    _env(ws, SUPABASE_KEY="publishable-key")
    assert panel.supabase_settings(ws) == {"url": "https://abc.supabase.co", "key": "publishable-key"}
    _env(ws, SUPABASE_SERVICE_KEY="secret-key")
    assert panel.supabase_settings(ws)["key"] == "secret-key"  # the secret key wins


def test_status_without_supabase_is_local_only(home):
    assert panel.supabase_status(home / "ws") == {"configured": False, "reachable": False}


def test_merge_shows_cloud_status_and_cloud_only_rows():
    local = [{"company": "A", "title": "x", "status": "Tailored & Ready", "ats": "80%", "platform": "LinkedIn", "url": "u1"},
             {"company": "B", "title": "y", "status": "applied", "ats": "70%", "platform": "LinkedIn", "url": "u2"}]
    cloud = [{"company": "A", "title": "x", "status": "applied", "ats": "80%", "platform": "LinkedIn", "url": "u1"},
             {"company": "C", "title": "z", "status": "applied", "ats": "90%", "platform": "web", "url": "u3"}]
    merged = panel.merge_results(local, cloud)
    by_url = {r["url"]: r for r in merged}
    assert by_url["u1"]["status"] == "applied" and by_url["u1"]["synced"] is True
    assert by_url["u2"]["synced"] is False and by_url["u3"]["synced"] is True and len(merged) == 3


def test_sync_adds_only_missing_rows(home, monkeypatch):
    ws = home / "ws"
    _env(ws, SUPABASE_URL="https://abc.supabase.co", SUPABASE_KEY="k")
    (ws / "applications_tracker").mkdir(parents=True)
    (ws / "applications_tracker" / "job_applications_tracker.csv").write_text(
        "Company,Job Title,Platform,Overall ATS,Status,Job URL\n"
        "Known Co,Dev,LinkedIn,70%,applied,http://known\n"
        "New Co,ML Intern,LinkedIn,88%,Tailored & Ready,http://new\n"
        "New Co,ML Intern,LinkedIn,88%,Tailored & Ready,http://new\n"  # a duplicate line
        "No Url,Dev,LinkedIn,50%,saved,\n")
    posted = []

    def fake(cfg, path, method="GET", body=None, headers=None, timeout=20.0):
        if method == "GET":
            return [{"job_url": "http://known"}]
        posted.extend(body or [])
        return None

    monkeypatch.setattr(panel, "_supabase_request", fake)
    result = panel.sync_missing_to_supabase(ws)
    assert result == {"ok": True, "pushed": 1, "already": 1}
    assert posted[0]["job_url"] == "http://new" and posted[0]["score"] == 88 and posted[0]["user_id"] == 34
    assert posted[0]["status"] == "Tailored & Ready" and posted[0]["company"] == "New Co"


def test_sync_reports_a_failure_without_raising(home, monkeypatch):
    ws = home / "ws"
    _env(ws, SUPABASE_URL="https://abc.supabase.co", SUPABASE_KEY="k")
    def boom(*a, **k):
        raise OSError("offline")
    monkeypatch.setattr(panel, "_supabase_request", boom)
    result = panel.sync_missing_to_supabase(ws)
    assert result["ok"] is False and "offline" in result["error"]
    assert panel.sync_missing_to_supabase(home / "other")["ok"] is False  # not configured


def test_results_fall_back_to_the_local_list_when_the_cloud_fails(home, monkeypatch):
    ws = home / "ws"
    _env(ws, SUPABASE_URL="https://abc.supabase.co", SUPABASE_KEY="k")
    (ws / "applications_tracker").mkdir(parents=True)
    (ws / "applications_tracker" / "job_applications_tracker.csv").write_text("Company,Job Title,Status,Job URL\nA,B,applied,http://a\n")
    monkeypatch.setenv("JOB_FINDER_APP_HOME", str(ws))
    def boom(*a, **k):
        raise OSError("offline")
    monkeypatch.setattr(panel, "_supabase_request", boom)
    rows = panel.Api([sys.executable]).get_results()
    assert [r["company"] for r in rows] == ["A"] and rows[0]["synced"] is False


# ── the page scraper's browser ──────────────────────────────────────────────────
def test_browser_ready_needs_the_finished_marker(home, monkeypatch):
    root = home / "browsers"
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(root))
    assert panel.browser_ready() is False  # no folder
    (root / "chromium_headless_shell-1255").mkdir(parents=True)
    assert panel.browser_ready() is False  # a half-finished download has no marker
    (root / "chromium_headless_shell-1255" / "INSTALLATION_COMPLETE").write_text("")
    assert panel.browser_ready() is True


def test_ensure_browser_runs_the_installer_once_and_reports_failure(home, monkeypatch):
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(home / "browsers"))
    monkeypatch.delenv("JOB_FINDER_SKIP_BROWSER_INSTALL", raising=False)
    ok_script = ("import os,pathlib;p=pathlib.Path(os.environ['PLAYWRIGHT_BROWSERS_PATH'])/'chromium-1';"
                 "p.mkdir(parents=True,exist_ok=True);(p/'INSTALLATION_COMPLETE').write_text('');print('done')")
    api = panel.Api([sys.executable, "-c", ok_script, "--"])
    api.ensure_browser()
    for _ in range(100):
        if not api._browser["installing"]:
            break
        time.sleep(0.05)
    assert panel.browser_ready() and api._browser["error"] == ""
    assert api.ensure_browser() == {"ok": True}  # already there: nothing to do

    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(home / "other"))
    failing = panel.Api([sys.executable, "-c", "import sys; print('no network'); sys.exit(1)", "--"])
    failing.ensure_browser()
    for _ in range(100):
        if not failing._browser["installing"]:
            break
        time.sleep(0.05)
    assert failing._browser["error"] == "no network"
    assert failing.get_state()["browser"] == {"ready": False, "installing": False, "error": "no network"}


# ── updates, preferences, logs, error guard ─────────────────────────────────────
def test_update_check_compares_versions():
    newer = panel.check_for_update("1.9.1", fetch=lambda: {"tag_name": "v1.10.0", "html_url": "https://example/rel"})
    assert newer == {"ok": True, "current": "1.9.1", "latest": "1.10.0", "newer": True, "url": "https://example/rel"}
    assert panel.check_for_update("1.9.1", fetch=lambda: {"tag_name": "v1.9.1"})["newer"] is False
    assert panel.check_for_update("1.9.1", fetch=lambda: {"tag_name": "v1.8.9"})["newer"] is False
    assert panel.check_for_update("1.9.1", fetch=lambda: {})["newer"] is False  # no release published yet


def test_update_check_failure_is_a_message_not_an_exception():
    def offline():
        raise OSError("offline")
    result = panel.check_for_update("1.0.0", fetch=offline)
    assert result["ok"] is False and "offline" in result["error"]


def test_app_prefs_keep_only_known_keys(home):
    api = panel.Api([sys.executable])
    assert panel.load_app_prefs() == {"primary_ai": "auto", "headless": False}
    api.save_app_prefs({"primary_ai": "anthropic", "headless": True, "workspace": "/etc", "evil": 1})
    assert panel.load_app_prefs() == {"primary_ai": "anthropic", "headless": True}
    assert panel.load_app_config().get("workspace") != "/etc"  # a window call cannot repoint the folder


def test_state_reports_what_the_window_needs(home):
    state = panel.Api([sys.executable]).get_state()
    for key in ("workspace", "prefs", "keys", "supabase", "browser", "app_prefs", "chrome_found", "version"):
        assert key in state
    assert state["supabase"] == {"configured": False, "reachable": False}


def test_runs_are_logged_to_files_and_old_logs_pruned(home, tmp_path):
    runner = panel.ScanRunner([sys.executable, "-c", "print('line one'); print('line two')", "--"])
    assert runner.start([], {"PATH": "/usr/bin"}, tmp_path, "scan")["ok"]
    _wait(runner)
    time.sleep(0.3)
    files = list(panel.logs_dir().glob("scan-*.log"))
    assert len(files) == 1 and files[0].read_text().splitlines() == ["line one", "line two"]
    for i in range(30):
        (panel.logs_dir() / f"scan-old-{i:02d}.log").write_text("x")
    panel.prune_logs(panel.logs_dir(), keep=5)
    assert len(list(panel.logs_dir().glob("scan-*.log"))) == 5


def test_a_failing_api_call_returns_an_error_instead_of_raising(home, monkeypatch):
    api = panel.Api([sys.executable])
    def boom(*a, **k):
        raise RuntimeError("disk full")
    monkeypatch.setattr(panel, "read_preferences", boom)
    result = api.get_state()
    assert result["ok"] is False and "disk full" in result["error"]


def test_notify_never_raises(monkeypatch):
    monkeypatch.setattr(panel.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError("no osascript")))
    panel.notify("Job Finder", "done")  # must not raise


# ── the window's files ──────────────────────────────────────────────────────────
PANEL = MACAPP / "panel"


def test_every_file_the_page_loads_exists():
    html = (PANEL / "index.html").read_text()
    refs = re.findall(r'(?:src|href)="([^"#]+)"', html)
    assert refs, "index.html should load its stylesheet and scripts"
    for ref in refs:
        assert (PANEL / ref).is_file(), f"index.html refers to {ref}, which is missing"


def test_page_has_a_strict_content_security_policy():
    html = (PANEL / "index.html").read_text()
    match = re.search(r'Content-Security-Policy" content="([^"]+)"', html)
    assert match, "index.html needs a Content-Security-Policy"
    policy = match.group(1)
    assert "default-src 'self'" in policy and "connect-src 'none'" in policy and "object-src 'none'" in policy
    assert "http" not in policy  # nothing is allowed to load from the network
    assert "'unsafe-inline'" not in policy.split("script-src")[1].split(";")[0]  # scripts: no inline code


def test_page_has_no_inline_scripts_and_no_remote_assets():
    html = (PANEL / "index.html").read_text()
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>\s*\S", html)
    assert not re.search(r'(?:src|href)="https?://', html)
    for name in ("app.js", "icons.js", "styles.css"):
        assert not re.search(r"https?://", (PANEL / name).read_text().replace("http://www.w3.org", "")), f"{name} reaches for the network"


def test_scripts_are_valid_javascript():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    for name in ("app.js", "icons.js"):
        assert subprocess.run([node, "--check", str(PANEL / name)], capture_output=True).returncode == 0, name


def test_every_api_method_the_page_calls_exists():
    called = set(re.findall(r'call\("([a-z_]+)"', (PANEL / "app.js").read_text()))
    exposed = {n for n in dir(panel.Api) if not n.startswith("_")}
    assert called, "the page should call the Python side"
    assert called <= exposed, f"the page calls methods Python does not have: {sorted(called - exposed)}"


def test_every_icon_the_page_uses_is_defined():
    icons = set(re.findall(r"^\s{4}([a-zA-Z]+):", (PANEL / "icons.js").read_text(), re.M))
    used = set(re.findall(r'icon\("([a-zA-Z]+)"', (PANEL / "app.js").read_text())) | set(re.findall(r'\["(?:run|apps|settings)", "[A-Za-z]+", "([a-zA-Z]+)"\]', (PANEL / "app.js").read_text()))
    assert icons and used <= icons, f"icons used but not defined: {sorted(used - icons)}"


def test_app_icon_and_logo_are_in_place():
    assert (MACAPP / "icon.icns").stat().st_size > 10_000 and (MACAPP / "icon.svg").is_file()
    assert "M14 2H6a2 2 0 0 0-2 2v16" in (PANEL / "icons.js").read_text()  # the Job Finder logo path


def test_app_version_prefers_baked_file(tmp_path, monkeypatch):
    import sys
    import scan_panel
    (tmp_path / "VERSION").write_text("9.9.9\n")
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert scan_panel._app_version() == "9.9.9"


def test_update_check_uses_certifi_context(monkeypatch):
    import ssl
    import scan_panel
    assert isinstance(scan_panel._ssl_context(), ssl.SSLContext)
    seen = {}

    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"tag_name": "v9.0.0", "html_url": "u"}'

    def fake_urlopen(request, timeout=None, context=None):
        seen["context"] = context
        return Resp()

    monkeypatch.setattr(scan_panel.urllib.request, "urlopen", fake_urlopen)
    out = scan_panel.check_for_update("1.0.0")
    assert out["ok"] and out["newer"] and seen["context"] is not None


def test_browser_install_command_has_no_cli_flag(monkeypatch):
    import scan_panel
    calls = []

    class P:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(scan_panel.subprocess, "run", lambda cmd, **kw: calls.append(cmd) or P())
    api = scan_panel.Api.__new__(scan_panel.Api)
    api._launcher = ["/app/Job Finder", "--cli"]
    api._browser = {"installing": True, "error": ""}
    api._install_browser()
    assert calls[0] == ["/app/Job Finder", "--install-browser"]


# ── job-finder.space sync ────────────────────────────────────────────────────────
def _ws(tmp_path):
    (tmp_path / "applications_tracker").mkdir()
    (tmp_path / "applications_tracker" / "job_applications_tracker.csv").write_text(
        "Company,Job Title,Job URL,Status,Overall ATS,Platform\n"
        "Acme,AI Engineer,https://boards.greenhouse.io/acme/jobs/1,Applied,82%,Greenhouse\n"
        "Acme,AI Engineer,https://boards.greenhouse.io/acme/jobs/1,Applied,82%,Greenhouse\n"
        "Beta,ML Engineer,https://jobs.lever.co/beta/2,Needs Review,,Lever\n")
    return tmp_path


def test_sync_code_is_validated_then_saved(tmp_path, monkeypatch):
    import scan_panel
    ws = _ws(tmp_path)
    monkeypatch.setattr(scan_panel, "_server_request", lambda *a, **k: {"email": "me@example.com"})
    assert scan_panel.save_sync_code(ws, "!!")["ok"] is False
    out = scan_panel.save_sync_code(ws, " ab-12 cd ")
    assert out == {"ok": True, "email": "me@example.com"}
    assert scan_panel.sync_code(ws) == "AB12CD"
    assert scan_panel.disconnect_sync(ws)["ok"] and scan_panel.sync_code(ws) == ""


def test_wrong_sync_code_is_not_saved(tmp_path, monkeypatch):
    import urllib.error
    import scan_panel
    ws = _ws(tmp_path)

    def reject(*a, **k):
        raise urllib.error.HTTPError("u", 401, "no", {}, None)

    monkeypatch.setattr(scan_panel, "_server_request", reject)
    out = scan_panel.save_sync_code(ws, "ABCDEF")
    assert out["ok"] is False and "not recognised" in out["error"]
    assert scan_panel.sync_code(ws) == ""


def test_push_sends_each_url_once_and_reports_counts(tmp_path, monkeypatch):
    import scan_panel
    ws = _ws(tmp_path)
    scan_panel.write_env_value(ws, "JOB_FINDER_SYNC_CODE", "ABCDEF")
    sent = []

    def fake(ws_, code, path, method="GET", body=None, timeout=20.0):
        sent.append((code, path, body))
        return {"added": len(body["applications"]), "already": 0}

    monkeypatch.setattr(scan_panel, "_server_request", fake)
    out = scan_panel.sync_to_cloud(ws)
    assert out == {"ok": True, "pushed": 2, "already": 0}
    assert sent[0][1] == "/applications/sync" and sent[0][0] == "ABCDEF"
    urls = [r["job_url"] for r in sent[0][2]["applications"]]
    assert urls == ["https://boards.greenhouse.io/acme/jobs/1", "https://jobs.lever.co/beta/2"]


def test_push_without_code_and_server_url_rules(tmp_path):
    import scan_panel
    ws = _ws(tmp_path)
    assert scan_panel.sync_to_cloud(ws)["ok"] is False
    scan_panel.write_env_value(ws, "JOB_FINDER_SERVER_URL", "http://evil.example.com")
    assert scan_panel.server_url(ws) == scan_panel.DEFAULT_SERVER  # clear-text remote servers are refused
    scan_panel.write_env_value(ws, "JOB_FINDER_SERVER_URL", "http://localhost:7860")
    assert scan_panel.server_url(ws) == "http://localhost:7860"
