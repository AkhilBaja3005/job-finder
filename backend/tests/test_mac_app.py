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
    assert panel.load_app_prefs() == {"primary_ai": "auto", "headless": False, "tour_done": False}
    api.save_app_prefs({"primary_ai": "anthropic", "headless": True, "workspace": "/etc", "evil": 1})
    assert panel.load_app_prefs() == {"primary_ai": "anthropic", "headless": True, "tour_done": False}
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


# ── profile check and import ─────────────────────────────────────────────────────
GOOD_PROFILE = {"candidate": {"name": "Ada", "email": "ada@example.com", "phone": "", "requires_sponsorship": False,
                              "work_experience": [{"company": "X"}], "core_skills": []},
                "search_preferences": {"target_roles": ["AI Engineer"]}}


def test_profile_check_lists_only_empty_fields(tmp_path):
    import scan_panel
    assert scan_panel.profile_check(tmp_path)["exists"] is False
    scan_panel.profile_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    scan_panel.profile_path(tmp_path).write_text(json.dumps(GOOD_PROFILE))
    check = scan_panel.profile_check(tmp_path)
    labels = [m["label"] for m in check["missing"]]
    assert "Phone" in labels and "Skills" in labels and "Locations to search" in labels
    assert "Full name" not in labels and "Needs visa sponsorship" not in labels  # False is a real answer
    assert check["missing"][0]["needed"] is True and check["filled"] + len(check["missing"]) == check["total"]


def test_import_profile_validates_and_backs_up(tmp_path):
    import scan_panel
    src = tmp_path / "in.json"
    src.write_text("not json")
    assert scan_panel.import_profile_file(tmp_path, src)["ok"] is False
    src.write_text(json.dumps({"hello": 1}))
    assert "candidate" in scan_panel.import_profile_file(tmp_path, src)["error"]
    src.write_text(json.dumps(GOOD_PROFILE))
    out = scan_panel.import_profile_file(tmp_path, src)
    assert out["ok"] and out["name"] == "Ada"
    src.write_text(json.dumps({**GOOD_PROFILE, "candidate": {"name": "Grace"}}))
    assert scan_panel.import_profile_file(tmp_path, src)["ok"]
    backup = scan_panel.profile_path(tmp_path).with_name(scan_panel.profile_path(tmp_path).name + ".bak")
    assert json.loads(backup.read_text())["candidate"]["name"] == "Ada"
    assert json.loads(scan_panel.profile_path(tmp_path).read_text())["candidate"]["name"] == "Grace"


# ── statuses, review queue ───────────────────────────────────────────────────────
def test_set_stage_changes_only_that_rows_status(tmp_path):
    import scan_panel
    ws = _ws(tmp_path)
    out = scan_panel.set_application_stage(ws, "https://jobs.lever.co/beta/2", "interview")
    assert out == {"ok": True, "status": "Interview"}
    rows = scan_panel._csv_all(ws)
    assert [r["Status"] for r in rows] == ["Applied", "Applied", "Interview"]
    assert rows[2]["Company"] == "Beta" and rows[2]["Job Title"] == "ML Engineer"
    assert not list((ws / "applications_tracker").glob("*.tmp"))


def test_set_stage_rejects_unknown_status_and_url(tmp_path):
    import scan_panel
    ws = _ws(tmp_path)
    assert scan_panel.set_application_stage(ws, "https://jobs.lever.co/beta/2", "hacked")["ok"] is False
    assert scan_panel.set_application_stage(ws, "https://nowhere.example/x", "offer")["ok"] is False
    assert scan_panel.set_application_stage(tmp_path / "empty", "u", "offer")["ok"] is False


def test_stage_counts_and_last_attempt_without_ledger(tmp_path):
    import scan_panel
    ws = _ws(tmp_path)
    scan_panel.set_application_stage(ws, "https://jobs.lever.co/beta/2", "replied")
    counts = scan_panel.stage_counts(scan_panel.read_tracker(ws))
    assert counts["replied"] == 1 and counts["interview"] == 0
    assert scan_panel.last_attempt(ws, "https://jobs.lever.co/beta/2") == {}


def test_problem_report_removes_keys_and_home_folder(tmp_path, monkeypatch):
    import scan_panel
    monkeypatch.setenv("HOME", str(tmp_path))
    text = scan_panel.redact(f"key sk-ant-abcdefgh12345678 and AIza{'x' * 30} and sb_secret_abcdefgh1234 at {tmp_path}/Library/x")
    assert "sk-ant" not in text and "AIza" not in text and "sb_secret" not in text and str(tmp_path) not in text
    assert "~/Library/x" in text


def test_review_in_chrome_only_opens_web_addresses():
    import scan_panel
    api = scan_panel.Api.__new__(scan_panel.Api)
    assert api.review_in_chrome("file:///etc/passwd")["ok"] is False
    assert api.review_in_chrome("javascript:alert(1)")["ok"] is False


# ── daily schedule ───────────────────────────────────────────────────────────────
def test_schedule_plist_holds_time_command_and_folder(tmp_path):
    import plistlib
    import scheduler
    data = plistlib.loads(scheduler.build_plist(7, 30, ["/App/Job Finder", "--cli", "scan", "--dry-run"], tmp_path, tmp_path / "s.log", {"X": "1"}))
    assert data["Label"] == "space.job-finder.daily"
    assert data["StartCalendarInterval"] == {"Hour": 7, "Minute": 30}
    assert data["ProgramArguments"][-2:] == ["scan", "--dry-run"]
    assert data["EnvironmentVariables"]["JOB_FINDER_ROOT"] == str(tmp_path) and data["EnvironmentVariables"]["X"] == "1"
    assert data["RunAtLoad"] is False


def test_schedule_install_status_remove(tmp_path, monkeypatch):
    import subprocess
    import scheduler
    calls = []
    monkeypatch.setattr(scheduler, "_launchctl", lambda *a: calls.append(a) or subprocess.CompletedProcess(a, 0, "", ""))
    assert scheduler.install(8, 15, ["/p", "--cli", "scan", "--dry-run"], tmp_path, tmp_path / "log" / "s.log", home=tmp_path) == {"ok": True}
    assert scheduler.status(home=tmp_path) == {"enabled": True, "hour": 8, "minute": 15, "real": False}
    assert any(c[0] == "bootstrap" for c in calls)
    assert scheduler.remove(home=tmp_path)["ok"] and scheduler.status(home=tmp_path) == {"enabled": False}


def test_schedule_rejects_bad_times_and_reports_launchctl_failure(tmp_path, monkeypatch):
    import subprocess
    import scheduler
    assert scheduler.install(25, 0, ["/p"], tmp_path, tmp_path / "s.log", home=tmp_path)["ok"] is False
    monkeypatch.setattr(scheduler, "_launchctl", lambda *a: subprocess.CompletedProcess(a, 5, "", "Bootstrap failed"))
    out = scheduler.install(8, 0, ["/p"], tmp_path, tmp_path / "s.log", home=tmp_path)
    assert out["ok"] is False and "Bootstrap failed" in out["error"]


def test_set_schedule_defaults_to_a_practice_run(tmp_path, monkeypatch):
    import scan_panel
    import scheduler
    seen = {}
    monkeypatch.setattr(scheduler, "install", lambda hour, minute, program, ws, log, env=None, home=None: seen.update(program=program, env=env) or {"ok": True})
    monkeypatch.setattr(scan_panel, "workspace_dir", lambda: tmp_path)
    api = scan_panel.Api.__new__(scan_panel.Api)
    api._launcher = ["/App/Job Finder", "--cli"]
    assert api.set_schedule(True, 9, 0)["ok"]
    assert "--dry-run" in seen["program"] and "--auto-apply" not in seen["program"]
    assert seen["env"]["JOB_FINDER_ROOT"] == str(tmp_path)


# ── Windows support ──────────────────────────────────────────────────────────────
def _as_platform(monkeypatch, name):
    import platform_support as ps
    monkeypatch.setattr(ps, "IS_MAC", name == "mac")
    monkeypatch.setattr(ps, "IS_WINDOWS", name == "windows")
    return ps


def test_folders_follow_each_platforms_conventions(monkeypatch, tmp_path):
    ps = _as_platform(monkeypatch, "windows")
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    assert ps.app_support_dir("Job Finder") == tmp_path / "Roaming" / "Job Finder"
    assert ps.logs_base("Job Finder") == tmp_path / "Local" / "Job Finder" / "Logs"
    ps = _as_platform(monkeypatch, "mac")
    assert ps.app_support_dir("Job Finder").parts[-3:] == ("Library", "Application Support", "Job Finder")
    assert ps.logs_base("Job Finder").parts[-3:] == ("Library", "Logs", "Job Finder")


def test_open_command_per_platform(monkeypatch):
    ps = _as_platform(monkeypatch, "mac")
    assert ps.open_command("/x/.env", as_text=True) == ["open", "-t", "/x/.env"] and ps.open_command("/x") == ["open", "/x"]
    ps = _as_platform(monkeypatch, "windows")
    assert ps.open_command("C:\\x\\.env", as_text=True) == ["notepad.exe", "C:\\x\\.env"]
    assert ps.open_command("C:\\x") is None  # opened with os.startfile
    ps = _as_platform(monkeypatch, "linux")
    assert ps.open_command("/x") == ["xdg-open", "/x"]


def test_chrome_is_looked_for_in_the_right_places(monkeypatch, tmp_path):
    ps = _as_platform(monkeypatch, "windows")
    chrome = tmp_path / "Google" / "Chrome" / "Application"
    chrome.mkdir(parents=True)
    (chrome / "chrome.exe").write_text("")
    monkeypatch.setenv("PROGRAMFILES", str(tmp_path))
    monkeypatch.delenv("PROGRAMFILES(X86)", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr(ps.shutil, "which", lambda name: None)
    assert ps.chrome_found() is True
    monkeypatch.setenv("PROGRAMFILES", str(tmp_path / "nowhere"))
    assert ps.chrome_found() is False


def test_second_copy_of_the_app_is_refused(tmp_path):
    import platform_support as ps
    first = open(tmp_path / "lock", "w")
    second = open(tmp_path / "lock", "w")
    try:
        assert ps.lock_file(first) is True
        assert ps.lock_file(second) is False
    finally:
        first.close()
        second.close()


def test_windows_schedule_writes_script_and_calls_task_scheduler(tmp_path, monkeypatch):
    import subprocess
    import scheduler
    calls = []
    monkeypatch.setattr(scheduler, "_schtasks", lambda *a: calls.append(a) or subprocess.CompletedProcess(a, 0, "", ""))
    out = scheduler.install_windows(7, 5, ["C:\\Apps\\Job Finder\\Job Finder.exe", "--cli", "scan", "--dry-run"], tmp_path, tmp_path / "logs" / "s.log", {"PLAYWRIGHT_BROWSERS_PATH": "C:\\b"})
    assert out == {"ok": True}
    script = (tmp_path / "run_daily.cmd").read_text()
    assert 'set "JOB_FINDER_ROOT=' in script and 'set "PLAYWRIGHT_BROWSERS_PATH=C:\\b"' in script
    assert '"C:\\Apps\\Job Finder\\Job Finder.exe" --cli scan --dry-run' in script and "s.log" in script
    create = next(c for c in calls if c[0] == "/Create")
    assert "/SC" in create and "DAILY" in create and "07:05" in create and "/F" in create
    assert scheduler.status_windows(tmp_path) == {"enabled": True, "hour": 7, "minute": 5, "real": False}
    assert scheduler.remove_windows(tmp_path)["ok"] and scheduler.status_windows(tmp_path) == {"enabled": False}
    assert scheduler.install_windows(25, 0, ["x"], tmp_path, tmp_path / "s.log")["ok"] is False


def test_desktop_workflow_builds_mac_and_windows_and_keeps_stable_download_names():
    from pathlib import Path
    text = (Path(__file__).resolve().parents[2] / ".github" / "workflows" / "build_desktop_apps.yml").read_text()
    for needle in ("macos-latest", "macos-15-intel", "windows-latest", "desktop-latest", "Job-Finder-arm64.dmg", "Job-Finder-x86_64.dmg",
                   "Job-Finder-windows.zip", "APPLE_CERT_P12_BASE64", "paths: &app_paths", "pull_request:"):
        assert needle in text, needle


# ── mailbox reply check ──────────────────────────────────────────────────────────
def test_mailbox_login_is_checked_before_it_is_saved(tmp_path, monkeypatch):
    import imaplib
    import scan_panel
    assert scan_panel.save_mailbox(tmp_path, "nobody", "short")["ok"] is False

    class Bad:
        def __init__(self, *a, **k): pass
        def login(self, u, p): raise imaplib.IMAP4.error("AUTHENTICATIONFAILED")

    monkeypatch.setattr(imaplib, "IMAP4_SSL", Bad)
    out = scan_panel.save_mailbox(tmp_path, "me@example.com", "abcd efgh ijkl mnop")
    assert out["ok"] is False and "app password" in out["error"]
    assert scan_panel.mailbox_status(tmp_path)["configured"] is False

    class Good(Bad):
        def login(self, u, p): self.p = p
        def logout(self): pass

    monkeypatch.setattr(imaplib, "IMAP4_SSL", Good)
    assert scan_panel.save_mailbox(tmp_path, "me@example.com", "abcd efgh ijkl mnop")["ok"] is True
    assert scan_panel.read_env(tmp_path)["REPLY_IMAP_PASSWORD"] == "abcdefghijklmnop"  # spaces from the Google page are dropped
    assert scan_panel.mailbox_status(tmp_path) == {"configured": True, "user": "me@example.com"}
    assert scan_panel.disconnect_mailbox(tmp_path)["ok"] and scan_panel.mailbox_status(tmp_path)["configured"] is False


def test_check_replies_updates_matching_rows(tmp_path, monkeypatch):
    import scan_panel
    from applications_tracker import replies
    ws = _ws(tmp_path)
    assert scan_panel.check_replies(ws)["ok"] is False
    for k, v in (("REPLY_IMAP_USER", "me@example.com"), ("REPLY_IMAP_PASSWORD", "abcdefghijkl")):
        scan_panel.write_env_value(ws, k, v)
    monkeypatch.setattr(replies, "fetch_messages", lambda *a, **k: [{"from": "jo@beta.io", "subject": "Interview with Beta", "body": "Can we schedule a call?"}])
    out = scan_panel.check_replies(ws)
    assert out["ok"] and out["updated"] == 1 and out["changes"] == [{"company": "Beta", "stage": "interview"}]
    assert [r["Status"] for r in scan_panel._csv_all(ws)] == ["Applied", "Applied", "Interview"]
    assert scan_panel.check_replies(ws)["updated"] == 0  # a second check changes nothing


def test_saved_answers_form_goes_through_the_app_bridge(tmp_path, monkeypatch):
    import scan_panel
    monkeypatch.setattr(scan_panel, "workspace_dir", lambda: tmp_path)
    api = scan_panel.Api.__new__(scan_panel.Api)
    first = api.get_saved_answers()
    assert first["ok"] and first["items"] == [] and first["suggestions"] and first["max_entries"] == 40
    assert api.save_saved_answers([{"question": "Start date", "answer": "1 March"}]) == {"ok": True, "saved": 1}
    assert api.get_saved_answers()["items"] == [{"question": "Start date", "answer": "1 March"}]


def test_tour_covers_the_account_replies_answers_and_schedule_rows():
    from pathlib import Path
    js = (Path(__file__).resolve().parents[2] / "macapp" / "panel" / "app.js").read_text()
    for selector in ('"#c-sync"', '"#c-mailbox"', "edit-answers", '"#sched-time"'):
        assert selector in js, selector


def test_locked_supabase_project_gets_a_clear_message(tmp_path, monkeypatch):
    import urllib.error
    import scan_panel
    scan_panel.write_env_value(tmp_path, "SUPABASE_URL", "https://abc.supabase.co")
    scan_panel.write_env_value(tmp_path, "SUPABASE_KEY", "sb_publishable_example")

    def locked(*a, **k):
        raise urllib.error.HTTPError("u", 401, "permission denied", {}, None)

    monkeypatch.setattr(scan_panel, "_supabase_request", locked)
    status = scan_panel.supabase_status(tmp_path)
    assert status["configured"] and not status["reachable"] and status["denied"] is True
    assert "SUPABASE_SERVICE_KEY" in status["error"] and "sync code" in status["error"]


def test_dmg_holds_the_app_and_an_applications_shortcut():
    from pathlib import Path
    script = (Path(__file__).resolve().parents[2] / "macapp" / "build_mac.sh").read_text()
    assert 'ln -s /Applications "$STAGE/Applications"' in script
    assert 'ditto "dist-mac/Job Finder.app" "$STAGE/Job Finder.app"' in script
    assert '-srcfolder "$STAGE"' in script  # the image is made from the staged folder, not the bare app


# ── background processes stay out of the Dock ────────────────────────────────────
def test_dock_helper_is_safe_everywhere(monkeypatch):
    from utils import dock
    assert isinstance(dock.hide_dock_icon(), bool)
    assert dock.hide_dock_icon() == dock.hide_dock_icon()   # calling it twice is fine
    monkeypatch.setattr(dock.sys, "platform", "linux")
    assert dock.hide_dock_icon() is False


def test_window_runs_its_children_through_the_console_build(tmp_path, monkeypatch):
    import sys
    import job_finder_app
    gui = tmp_path / "Job Finder"
    cli = tmp_path / "job-finder-cli"
    gui.write_text("")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(gui))
    assert job_finder_app.launcher_command() == [str(gui), "--cli"]            # older bundle without the console build
    cli.write_text("")
    assert job_finder_app.launcher_command() == [str(cli), "--cli"]


def test_bundle_builds_a_console_program_and_ci_checks_it():
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    spec = (root / "macapp" / "job_finder.spec").read_text()
    assert 'name="job-finder-cli", console=True' in spec and "COLLECT(exe, exe_cli" in spec
    assert "job-finder-cli" in (root / ".github" / "workflows" / "build_desktop_apps.yml").read_text()
