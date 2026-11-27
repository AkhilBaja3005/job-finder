import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

MACAPP = Path(__file__).resolve().parents[2] / "macapp"
sys.path.insert(0, str(MACAPP))
sys.path.insert(0, str(MACAPP.parent / "backend"))  # the app adds this too, so `services.*` imports work
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
def test_scan_never_applies_and_practice_is_search_only():
    args = panel.build_scan_args({"mode": "practice", "limit": "5", "min_ats": "70", "timeframe": "24h",
                                  "location": "London, UK", "skip_portals": "reed, indeed", "headless": True})
    assert args[:2] == ["scan", "--dry-run"] and "--auto-apply" not in args
    assert ["--limit", "5"] == args[args.index("--limit"):args.index("--limit") + 2]
    assert "--skip-portals" in args and args[args.index("--skip-portals") + 1] == "reed,indeed" and "--headless" in args


def test_old_dry_run_mode_is_practice_and_auto_apply_is_a_saving_scan():
    assert panel.build_scan_args({"mode": "dry_run"}) == ["scan", "--dry-run"]
    for mode in ("auto_apply", "", None):
        args = panel.build_scan_args({"mode": mode})
        assert args == ["scan"]
        assert "--auto-apply" not in args and "--dry-run" not in args


def test_scan_args_carry_topic_level_search_and_into():
    args = panel.build_scan_args({"topic": " applied AI ", "level": "Intern", "search": "ai-intern", "into": "x.xlsx"})
    assert args[args.index("--topic") + 1] == "applied AI"
    assert args[args.index("--level") + 1] == "intern"
    assert args[args.index("--search") + 1] == "ai-intern" and args[args.index("--into") + 1] == "x.xlsx"
    assert "--level" not in panel.build_scan_args({"level": "wizard"})
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


def _make_workbook(ws, name, rows):
    from services.excel_tracker import ExcelTracker, record_from_payload
    folder = ws / "applications_tracker" / "searches" / name
    folder.mkdir(parents=True)
    t = ExcelTracker(str(folder / "scanned_jobs.xlsx"))
    t.add_jobs([record_from_payload(r) for r in rows])
    return t


def test_tracker_reads_excel_workbooks(home):
    ws = home / "ws"
    _make_workbook(ws, "ai-intern", [{"company": "Acme", "job_title": "AI Intern", "job_url": "http://acme.example/1", "overall_ats": 82, "platform": "LinkedIn"}])
    _make_workbook(ws, "cyber", [{"company": "Zed", "job_title": "SOC Analyst", "job_url": "http://zed.example/2", "overall_ats": 60}])
    rows = panel.read_tracker(ws)
    assert {r["company"] for r in rows} == {"Acme", "Zed"}
    acme = next(r for r in rows if r["company"] == "Acme")
    assert acme["title"] == "AI Intern" and acme["ats"] == "82%" and acme["url"] == "http://acme.example/1" and acme["status"] == "New"


def test_stage_change_writes_the_excel(home):
    ws = home / "ws"
    t = _make_workbook(ws, "ai-intern", [{"company": "Acme", "job_title": "AI Intern", "job_url": "http://acme.example/1"}])
    assert panel.set_application_stage(ws, "http://acme.example/1", "interview")["ok"]
    assert t.rows()[0]["Status"] == "Interview"
    assert panel.set_application_stage(ws, "http://acme.example/1", "replied")["ok"]
    assert "Replied" in str(t.rows()[0]["Notes"])
    assert panel.set_application_stage(ws, "http://nope.example", "applied")["ok"] is False
    assert panel.set_application_stage(ws, "http://acme.example/1", "bogus")["ok"] is False
    assert panel.stage_counts(panel.read_tracker(ws))["interview"] == 1


def test_stage_change_on_csv_fallback(home):
    ws = home / "ws"
    (ws / "applications_tracker").mkdir(parents=True)
    path = ws / "applications_tracker" / "job_applications_tracker.csv"
    path.write_text("Company,Job Title,Status,Job URL\nOld,Dev,saved,http://a\n")
    assert panel.set_application_stage(ws, "http://a", "applied")["status"] == "Applied (manual)"
    assert "Applied (manual)" in path.read_text()
    assert panel.set_application_stage(ws, "http://zzz", "applied")["ok"] is False


def test_workspace_env_is_restored(home, monkeypatch):
    monkeypatch.delenv("JOB_FINDER_ROOT", raising=False)
    with panel._workspace_env(home):
        assert os.environ["JOB_FINDER_ROOT"] == str(home)
    assert "JOB_FINDER_ROOT" not in os.environ


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


def test_merge_shows_cloud_status_and_cloud_only_rows():
    local = [{"company": "A", "title": "x", "status": "Tailored & Ready", "ats": "80%", "platform": "LinkedIn", "url": "u1"},
             {"company": "B", "title": "y", "status": "applied", "ats": "70%", "platform": "LinkedIn", "url": "u2"}]
    cloud = [{"company": "A", "title": "x", "status": "applied", "ats": "80%", "platform": "LinkedIn", "url": "u1"},
             {"company": "C", "title": "z", "status": "applied", "ats": "90%", "platform": "web", "url": "u3"}]
    merged = panel.merge_results(local, cloud)
    by_url = {r["url"]: r for r in merged}
    assert by_url["u1"]["status"] == "applied" and by_url["u1"]["synced"] is True
    assert by_url["u2"]["synced"] is False and by_url["u3"]["synced"] is True and len(merged) == 3


def test_results_fall_back_to_the_local_list_when_the_account_cannot_be_reached(home, monkeypatch):
    ws = home / "ws"
    (ws / "applications_tracker").mkdir(parents=True)
    (ws / "applications_tracker" / "job_applications_tracker.csv").write_text("Company,Job Title,Status,Job URL\nA,B,applied,http://a\n")
    monkeypatch.setenv("JOB_FINDER_APP_HOME", str(ws))
    panel._store_account("11111111-2222-3333-4444-555555555555", "me@example.com")
    panel._cloud_cache.clear()

    def boom(*a, **k):
        raise OSError("offline")

    monkeypatch.setattr(panel, "_server_request", boom)
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
    assert panel.load_app_prefs() == {"primary_ai": "auto", "headless": False, "tour_done": False, "dock_browser": False}
    api.save_app_prefs({"primary_ai": "anthropic", "headless": True, "workspace": "/etc", "evil": 1})
    assert panel.load_app_prefs() == {"primary_ai": "anthropic", "headless": True, "tour_done": False, "dock_browser": False}
    assert panel.load_app_config().get("workspace") != "/etc"  # a window call cannot repoint the folder


def test_state_reports_what_the_window_needs(home):
    state = panel.Api([sys.executable]).get_state()
    for key in ("workspace", "prefs", "keys", "cloud", "session", "browser", "app_prefs", "chrome_found", "version"):
        assert key in state
    assert "supabase" not in state
    assert state["cloud"] == {"configured": False, "connected": False, "signing_in": False}


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
@pytest.fixture(autouse=True)
def _open_lock_and_private_app_folder(tmp_path_factory, monkeypatch):
    """Most tests are about something else, so the sign-in lock is open for them and the app folder is a temporary one (never the real one)."""
    import scan_panel
    monkeypatch.setenv("JOB_FINDER_APP_HOME", str(tmp_path_factory.mktemp("apphome")))
    monkeypatch.setattr(scan_panel, "GATE_ENABLED", False)
    scan_panel._session.update(ok=False, checked=0.0, token="")
    scan_panel._signin_state.update(state="idle", error="", email="")
    yield


def _ws(tmp_path):
    (tmp_path / "applications_tracker").mkdir()
    (tmp_path / "applications_tracker" / "job_applications_tracker.csv").write_text(
        "Company,Job Title,Job URL,Status,Overall ATS,Platform\n"
        "Acme,AI Engineer,https://boards.greenhouse.io/acme/jobs/1,Applied,82%,Greenhouse\n"
        "Acme,AI Engineer,https://boards.greenhouse.io/acme/jobs/1,Applied,82%,Greenhouse\n"
        "Beta,ML Engineer,https://jobs.lever.co/beta/2,Needs Review,,Lever\n")
    return tmp_path


def test_push_sends_each_url_once_and_reports_counts(tmp_path, monkeypatch):
    import scan_panel
    ws = _ws(tmp_path)
    scan_panel._store_account("ABCDEF", "me@example.com")
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


def test_scheduled_run_scans_then_previews_unless_real(tmp_path, monkeypatch):
    import scan_panel
    import scheduler
    seen = {}
    monkeypatch.setattr(scheduler, "install", lambda hour, minute, program, ws, log, env, **kw: seen.update(program=program, env=env, then=kw.get("then")) or {"ok": True})
    monkeypatch.setattr(scan_panel, "workspace_dir", lambda: tmp_path)
    api = scan_panel.Api.__new__(scan_panel.Api)
    api._launcher = ["/App/Job Finder", "--cli"]
    assert api.set_schedule(True, 9, 0)["ok"]
    assert seen["program"][2] == "scan" and "--auto-apply" not in seen["program"] and "--dry-run" not in seen["program"]
    assert seen["then"][:3] == ["/App/Job Finder", "--cli", "apply"] and "--submit" not in seen["then"]
    assert api.set_schedule(True, 9, 0, real=True)["ok"] and "--submit" in seen["then"] and "--yes" in seen["then"]
    assert seen["env"]["JOB_FINDER_ROOT"] == str(tmp_path)


def test_apply_args_preview_by_default_and_submit_is_explicit():
    assert panel.build_apply_args({}) == ["apply"]
    assert panel.build_apply_args({"mode": "preview", "limit": 5, "headless": True}) == ["apply", "--limit", "5", "--headless"]
    args = panel.build_apply_args({"mode": "submit", "limit": "3", "search": " ai-intern "})
    assert args == ["apply", "--search", "ai-intern", "--submit", "--yes", "--limit", "3"]
    assert "--limit" not in panel.build_apply_args({"limit": "0"}) and "--limit" not in panel.build_apply_args({"limit": "x"})


def test_sync_reads_excel_applied_rows_only(home):
    ws = home / "ws"
    t = _make_workbook(ws, "ai-intern", [{"company": "Acme", "job_title": "AI Intern", "job_url": "http://acme.example/1", "overall_ats": 82},
                                         {"company": "Zed", "job_title": "SOC", "job_url": "http://zed.example/2"}])
    t.update(url="http://acme.example/1", Status="Applied")
    rows = panel._csv_all(ws)
    assert [r["Company"] for r in rows] == ["Acme"] and rows[0]["Overall ATS"] == "82" and rows[0]["Job URL"] == "http://acme.example/1"


def test_scheduler_two_commands_mac_and_windows(tmp_path):
    import plistlib
    import scheduler
    data = plistlib.loads(scheduler.build_plist(7, 0, ["/App/Job Finder", "--cli", "scan"], tmp_path, tmp_path / "s.log", then=["/App/Job Finder", "--cli", "apply", "--submit", "--yes"]))
    assert data["ProgramArguments"][:2] == ["/bin/sh", "-c"]
    assert data["ProgramArguments"][2] == "'/App/Job Finder' --cli scan; '/App/Job Finder' --cli apply --submit --yes"
    assert scheduler.is_real(data["ProgramArguments"]) and not scheduler.is_real(["x", "apply"])
    script = scheduler.build_cmd_script(["C:\\J F\\j.exe", "scan"], tmp_path, tmp_path / "s.log", {"A": "1"}, then=["C:\\J F\\j.exe", "apply"])
    assert script.count(">>") == 2 and script.index("scan") < script.index("apply")



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


# ── the Applications list shows everything, and the account's applications too ──
def test_tracker_is_read_in_full_not_just_the_latest_300(tmp_path):
    import scan_panel
    folder = tmp_path / "applications_tracker"
    folder.mkdir()
    lines = ["Company,Job Title,Job URL,Status,Overall ATS,Platform"] + [f"Co{i},Role,https://x.example/{i},Applied,70%,LinkedIn" for i in range(4464)]
    (folder / "job_applications_tracker.csv").write_text("\n".join(lines) + "\n")
    assert len(scan_panel.read_tracker(tmp_path)) == 4464


def test_account_applications_are_read_with_the_sync_code_and_cached(tmp_path, monkeypatch):
    import scan_panel
    scan_panel._cloud_cache.clear()
    assert scan_panel.read_account_applications(tmp_path) == []          # no sync code: nothing to ask
    scan_panel._store_account("ABCDEF", "me@example.com")
    calls = []

    def fake(ws, code, path, method="GET", body=None, timeout=20.0):
        calls.append((code, path))
        return {"applications": [{"company": "Acme", "job_title": "AI Engineer", "job_url": "https://x.example/1", "score": 81, "status": "applied", "source_mode": "website"},
                                 {"company": "NoLink", "job_title": "x", "job_url": ""}]}

    monkeypatch.setattr(scan_panel, "_server_request", fake)
    rows = scan_panel.read_account_applications(tmp_path)
    assert rows == [{"company": "Acme", "title": "AI Engineer", "status": "applied", "ats": "81%", "platform": "website", "url": "https://x.example/1"}]
    scan_panel.read_account_applications(tmp_path)
    assert calls == [("ABCDEF", "/applications")]                         # the second call came from the 30 second cache


def test_results_merge_folder_and_account_rows(tmp_path, monkeypatch):
    import scan_panel
    scan_panel._cloud_cache.clear()
    ws = _ws(tmp_path)
    scan_panel._store_account("ABCDEF", "me@example.com")
    monkeypatch.setattr(scan_panel, "workspace_dir", lambda: ws)
    monkeypatch.setattr(scan_panel, "_server_request", lambda *a, **k: {"applications": [
        {"company": "Beta", "job_title": "ML Engineer", "job_url": "https://jobs.lever.co/beta/2", "status": "Interview"},
        {"company": "Elsewhere", "job_title": "Dev", "job_url": "https://x.example/other", "status": "applied"}]})
    rows = scan_panel.Api.__new__(scan_panel.Api).get_results()
    urls = {r["url"]: r for r in rows}
    assert urls["https://jobs.lever.co/beta/2"]["status"] == "Interview" and urls["https://jobs.lever.co/beta/2"]["synced"] is True
    assert urls["https://x.example/other"]["synced"] is True              # only on the account: it still shows
    assert len(rows) == 4                                                  # 3 in the folder (one job listed twice) + 1 only on the account


# ── moving the window by its top bar ─────────────────────────────────────────────
def test_window_moves_by_the_distance_the_pointer_moved():
    import scan_panel
    moves = []

    class Win:
        x, y = 200, 150
        def move(self, x, y): moves.append((x, y))

    api = scan_panel.Api.__new__(scan_panel.Api)
    api._window = Win()
    assert api.drag_to(10, 10) == {"ok": False}            # no press yet
    assert api.drag_start() == {"ok": True}
    api.drag_to(40, -25)
    assert moves == [(240, 125)]


def test_top_bar_and_sidebar_are_drag_areas_and_the_page_handles_the_drag():
    from pathlib import Path
    panel = Path(__file__).resolve().parents[2] / "macapp" / "panel"
    html, js = (panel / "index.html").read_text(), (panel / "app.js").read_text()
    assert html.count("data-drag") >= 3 and "enableWindowDrag" in js and '"drag_to"' in js


# ── Sign in with Google, and the email next to a sync code ───────────────────────
def test_google_sign_in_saves_the_token_and_email(tmp_path, monkeypatch):
    import account_login
    import scan_panel
    ws = _ws(tmp_path)
    monkeypatch.setattr(account_login, "run_google_sign_in", lambda post_json, open_browser, timeout, cancelled: {"token": "11111111-2222-3333-4444-555555555555", "email": "me@example.com"})
    scan_panel.google_sign_in_worker(ws)
    assert scan_panel._signin_state["state"] == "done" and scan_panel._signin_state["email"] == "me@example.com"
    assert scan_panel.account_kind(ws) == "google" and scan_panel.account_email(ws) == "me@example.com"


def test_a_failed_or_cancelled_google_sign_in_saves_nothing(tmp_path, monkeypatch):
    import account_login
    import scan_panel
    ws = _ws(tmp_path)

    def fail(post_json, open_browser, timeout, cancelled):
        raise RuntimeError("Signing in took too long. Click Sign in with Google to try again.")

    monkeypatch.setattr(account_login, "run_google_sign_in", fail)
    scan_panel.google_sign_in_worker(ws)
    assert scan_panel._signin_state["state"] == "error" and "too long" in scan_panel._signin_state["error"]
    assert scan_panel.account_secret(ws) == ""

    def cancel(post_json, open_browser, timeout, cancelled):
        raise account_login.SignInCancelled()

    monkeypatch.setattr(account_login, "run_google_sign_in", cancel)
    scan_panel.google_sign_in_worker(ws)
    assert scan_panel._signin_state["state"] == "idle" and scan_panel.account_secret(ws) == ""


def test_sign_in_server_errors_become_readable_messages(tmp_path, monkeypatch):
    import urllib.error
    import account_login
    import scan_panel
    ws = _ws(tmp_path)
    captured = {}

    def run(post_json, open_browser, timeout, cancelled):
        captured["post"] = post_json
        return {"token": "t", "email": "e@x.co"}

    monkeypatch.setattr(account_login, "run_google_sign_in", run)
    scan_panel.google_sign_in_worker(ws)

    def busy(*a, **k):
        raise urllib.error.HTTPError("u", 429, "slow down", {}, None)

    monkeypatch.setattr(scan_panel, "_server_request", busy)
    with pytest.raises(RuntimeError, match="Too many attempts"):
        captured["post"]("/auth/app/begin", {})

    def offline(*a, **k):
        raise OSError("down")

    monkeypatch.setattr(scan_panel, "_server_request", offline)
    with pytest.raises(RuntimeError, match="Could not reach"):
        captured["post"]("/auth/app/begin", {})




# ── the lock: the app does nothing until a valid Google sign-in exists ───────────
@pytest.fixture
def locked(monkeypatch):
    import scan_panel
    monkeypatch.setattr(scan_panel, "GATE_ENABLED", True)
    return scan_panel


def _answers(monkeypatch, scan_panel, **by_path):
    """Plays job-finder.space: by_path maps a path to a dict (answer) or an exception (failure)."""
    calls = []

    def fake(ws, code, path, method="GET", body=None, timeout=20.0, email=None):
        calls.append((code, path))
        result = by_path[path]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(scan_panel, "_server_request", fake)
    return calls


def test_nothing_works_without_a_google_sign_in(locked, tmp_path, monkeypatch):
    monkeypatch.setattr(locked, "workspace_dir", lambda: tmp_path)
    api = locked.Api([sys.executable])
    for call in (lambda: api.get_results(), lambda: api.start_scan({"mode": "dry_run"}), lambda: api.open_signin(), lambda: api.sync_cloud_now(),
                 lambda: api.save_key("gemini", "AIza" + "x" * 30), lambda: api.set_status("https://x.example/1", "applied"), lambda: api.poll(0)):
        out = call()
        assert out["ok"] is False and out["signed_out"] is True and "Sign in with Google" in out["error"]
    assert not (tmp_path / ".env").exists() or "AIza" not in (tmp_path / ".env").read_text()      # nothing was written


def test_the_sign_in_screen_can_still_work_while_signed_out(locked, tmp_path, monkeypatch):
    monkeypatch.setattr(locked, "workspace_dir", lambda: tmp_path)
    api = locked.Api([sys.executable])
    state = api.get_state()
    assert state["session"]["signed_in"] is False and state["session"]["reason"] == "none"
    for open_call in (lambda: api.google_sign_in_status(), lambda: api.cancel_google_sign_in(), lambda: api.drag_start(), lambda: api.zoom_window()):
        assert open_call().get("signed_out") is None


def test_a_valid_sign_in_opens_the_app(locked, tmp_path, monkeypatch):
    monkeypatch.setattr(locked, "workspace_dir", lambda: tmp_path)
    locked._store_account("11111111-2222-3333-4444-555555555555", "me@example.com")
    _answers(monkeypatch, locked, **{"/user/me": {"email": "me@example.com", "is_guest": False}})
    status = locked.session_status(tmp_path)
    assert status == {"signed_in": True, "reason": "", "email": "me@example.com"}
    assert locked.Api([sys.executable]).get_results() == []                                         # a normal call goes through


def test_an_ended_sign_in_closes_the_app_again(locked, tmp_path, monkeypatch):
    import urllib.error
    monkeypatch.setattr(locked, "workspace_dir", lambda: tmp_path)
    locked._store_account("11111111-2222-3333-4444-555555555555", "me@example.com")
    _answers(monkeypatch, locked, **{"/user/me": urllib.error.HTTPError("u", 401, "no", {}, None)})
    assert locked.session_status(tmp_path)["reason"] == "expired"
    assert locked.Api([sys.executable]).get_results()["signed_out"] is True
    _answers(monkeypatch, locked, **{"/user/me": {"email": "", "is_guest": True}})                  # the server answers with a guest
    locked._session.update(ok=False, checked=0.0, token="")
    assert locked.session_status(tmp_path, fresh=True)["reason"] == "expired"


def test_the_server_being_down_keeps_the_app_open_for_a_week_after_a_good_check(locked, tmp_path, monkeypatch):
    import time
    monkeypatch.setattr(locked, "workspace_dir", lambda: tmp_path)
    locked._store_account("11111111-2222-3333-4444-555555555555", "me@example.com")
    _answers(monkeypatch, locked, **{"/user/me": OSError("offline")})
    assert locked.session_status(tmp_path)["signed_in"] is False and locked.session_status(tmp_path)["reason"] == "offline"   # never verified
    cfg = locked.load_app_config()
    cfg["session_verified"] = time.time() - 3 * 24 * 3600
    locked.save_app_config(cfg)
    locked._session.update(ok=False, checked=0.0, token="")
    assert locked.session_status(tmp_path) == {"signed_in": True, "reason": "offline", "email": "me@example.com"}
    cfg["session_verified"] = time.time() - 8 * 24 * 3600
    locked.save_app_config(cfg)
    locked._session.update(ok=False, checked=0.0, token="")
    assert locked.session_status(tmp_path)["signed_in"] is False


def test_a_good_check_is_remembered_for_ten_minutes_so_the_app_stays_quick(locked, tmp_path, monkeypatch):
    monkeypatch.setattr(locked, "workspace_dir", lambda: tmp_path)
    locked._store_account("11111111-2222-3333-4444-555555555555", "me@example.com")
    calls = _answers(monkeypatch, locked, **{"/user/me": {"email": "me@example.com"}})
    for _ in range(5):
        assert locked.session_status(tmp_path)["signed_in"]
    assert len(calls) == 1
    locked.session_status(tmp_path, fresh=True)
    assert len(calls) == 2


def test_the_token_is_stored_with_the_app_readable_only_by_the_user(tmp_path):
    import os
    import scan_panel
    scan_panel._store_account("11111111-2222-3333-4444-555555555555", "me@example.com")
    path = scan_panel.app_support_dir() / "app.json"
    assert oct(os.stat(path).st_mode)[-3:] == "600"
    assert scan_panel.account_token() == "11111111-2222-3333-4444-555555555555" and scan_panel.account_email() == "me@example.com"
    ws = tmp_path / "other-folder"
    assert scan_panel.account_token(ws) == scan_panel.account_token()                                 # a different folder does not sign you out
    assert "11111111" not in (tmp_path / ".env").read_text() if (tmp_path / ".env").exists() else True


def test_sign_in_saves_the_token_with_the_app_and_marks_the_check(tmp_path, monkeypatch):
    import account_login
    import scan_panel
    ws = _ws(tmp_path)
    monkeypatch.setattr(account_login, "run_google_sign_in", lambda post_json, open_browser, timeout, cancelled: {"token": "11111111-2222-3333-4444-555555555555", "email": "me@example.com"})
    scan_panel.google_sign_in_worker(ws)
    assert scan_panel._signin_state["state"] == "done"
    assert scan_panel.account_kind() == "google" and scan_panel.account_email() == "me@example.com"
    assert scan_panel.load_app_config()["session_verified"] > 0 and scan_panel._session["ok"] is True


def test_requests_carry_the_token_and_the_email_and_the_first_call_carries_neither(tmp_path, monkeypatch):
    import scan_panel
    ws = _ws(tmp_path)
    sent = {}

    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"ok": true}'

    def fake_urlopen(request, timeout=None, context=None):
        sent["headers"] = {k.lower(): v for k, v in request.header_items()}
        return Resp()

    monkeypatch.setattr(scan_panel.urllib.request, "urlopen", fake_urlopen)
    assert scan_panel.account_secret(ws) == ""
    scan_panel._store_account("11111111-2222-3333-4444-555555555555", "google@example.com")
    scan_panel._server_request(ws, scan_panel.account_secret(ws), "/user/me")
    assert sent["headers"]["authorization"] == "Bearer 11111111-2222-3333-4444-555555555555" and sent["headers"]["x-account-email"] == "google@example.com"
    scan_panel._server_request(ws, None, "/auth/app/begin", "POST", {})
    assert "authorization" not in sent["headers"] and "x-account-email" not in sent["headers"]


def test_signing_out_ends_the_session_on_the_server_and_forgets_everything(tmp_path, monkeypatch):
    import scan_panel
    ws = _ws(tmp_path)
    scan_panel._store_account("11111111-2222-3333-4444-555555555555", "me@example.com")
    scan_panel.write_env_value(ws, "JOB_FINDER_SYNC_CODE", "OLDCODE")           # left by an older version
    calls = _answers(monkeypatch, scan_panel, **{"/auth/app/revoke": {}})
    assert scan_panel.disconnect_sync(ws) == {"ok": True}
    assert calls == [("11111111-2222-3333-4444-555555555555", "/auth/app/revoke")]
    assert scan_panel.account_secret(ws) == "" and scan_panel.account_email(ws) == "" and scan_panel.load_app_config().get("session_verified") is None
    assert scan_panel.read_env(ws).get("JOB_FINDER_SYNC_CODE", "") == ""


def test_signing_out_works_even_when_the_server_is_unreachable(tmp_path, monkeypatch):
    import scan_panel
    ws = _ws(tmp_path)
    scan_panel._store_account("11111111-2222-3333-4444-555555555555", "me@example.com")
    _answers(monkeypatch, scan_panel, **{"/auth/app/revoke": OSError("down")})
    assert scan_panel.disconnect_sync(ws) == {"ok": True} and scan_panel.account_token() == ""


def test_the_sign_in_screen_is_in_the_page_and_there_is_no_sync_code_option():
    from pathlib import Path
    root = Path(__file__).resolve().parents[2] / "macapp" / "panel"
    js, html = (root / "app.js").read_text(), (root / "index.html").read_text()
    for needle in ("renderGate", "google-signin", "google_sign_in_status", "cancel_google_sign_in", "retry-session", "Sign in with Google", "onSignedIn"):
        assert needle in js, needle
    assert 'id="gate"' in html
    assert "Use a sync code" not in js and "save_sync_code" not in js and "si-email" not in js
    import scan_panel
    assert not hasattr(scan_panel, "save_sync_code") and not hasattr(scan_panel.Api, "save_sync_code")


def test_supabase_is_gone_from_the_app():
    from pathlib import Path
    import scan_panel
    root = Path(__file__).resolve().parents[2] / "macapp"
    for name in ("supabase_settings", "supabase_status", "sync_missing_to_supabase", "read_cloud_applications", "_supabase_request"):
        assert not hasattr(scan_panel, name), name
    assert not hasattr(scan_panel.Api, "sync_now")
    assert "supabase" not in (root / "panel" / "app.js").read_text().lower()


def test_the_applications_page_syncs_to_the_account(tmp_path, monkeypatch):
    from pathlib import Path
    js = (Path(__file__).resolve().parents[2] / "macapp" / "panel" / "app.js").read_text()
    assert 'case "sync":' in js and 'call("sync_cloud_now")' in js and "to your account" in js
    assert "Synced with job-finder.space" in js


# ── About you: the questions a resume cannot answer ──────────────────────────────
def _profile_file(ws):
    path = scan_panel_profile_path(ws)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"candidate": {"name": "Ada", "email": "ada@example.com"}, "search_preferences": {"target_roles": ["AI Engineer Intern"]}}))
    return path


def scan_panel_profile_path(ws):
    import scan_panel
    return scan_panel.profile_path(ws)


def test_the_bridge_reads_and_saves_the_answers(tmp_path, monkeypatch):
    import scan_panel
    monkeypatch.setattr(scan_panel, "workspace_dir", lambda: tmp_path)
    api = scan_panel.Api.__new__(scan_panel.Api)
    assert api.get_about_you()["exists"] is False                                           # no profile yet
    assert api.save_about_you({"notice_period": "2 weeks"})["ok"] is False and "Create your profile" in api.save_about_you({"notice_period": "2 weeks"})["error"]
    path = _profile_file(tmp_path)
    got = api.get_about_you()
    assert got["exists"] and {"work_authorization", "requires_sponsorship", "notice_period", "seniority"} <= set(got["unanswered"])
    out = api.save_about_you({"work_authorization": "Authorised to work in the UK without restriction", "requires_sponsorship": False, "notice_period": "1 month", "seniority": ["Intern"]})
    assert out == {"ok": True, "unanswered": []}
    data = json.loads(path.read_text())
    assert data["candidate"]["requires_sponsorship"] is False and data["search_preferences"]["seniority"] == ["Intern"] and data["candidate"]["name"] == "Ada"
    bad = api.save_about_you({"requires_sponsorship": "perhaps"})
    assert bad["ok"] is False and "Yes or No" in bad["error"]


def test_state_says_which_questions_are_still_open(tmp_path, monkeypatch):
    import scan_panel
    monkeypatch.setattr(scan_panel, "workspace_dir", lambda: tmp_path)
    api = scan_panel.Api([sys.executable])
    assert api.get_state()["about_you"] == {"exists": False, "unanswered": []}
    _profile_file(tmp_path)
    state = api.get_state()["about_you"]
    assert state["exists"] and "work_authorization" in state["unanswered"]


def test_missing_fields_card_lists_notice_period_as_needed(tmp_path):
    import scan_panel
    _profile_file(tmp_path)
    notice = next(m for m in scan_panel.profile_check(tmp_path)["missing"] if m["field"] == "notice_period")
    assert notice["needed"] is True


def test_the_page_asks_the_questions_in_the_tour_in_settings_and_before_applying_for_real():
    from pathlib import Path
    js = (Path(__file__).resolve().parents[2] / "macapp" / "panel" / "app.js").read_text()
    for needle in ("openAboutYou", "get_about_you", "save_about_you", 'data-act="edit-about"', "Tell us what your resume cannot", 'cta: "Answer now"',
                   "closeLayer(); openAboutYou().then(() => startTour(resumeAt))", "Before applying for real, answer the questions"):
        assert needle in js, needle


def test_staged_api_workflow_end_to_end(tmp_path, monkeypatch):
    import scan_panel
    from services import searches
    from services.excel_tracker import ExcelTracker

    monkeypatch.setattr(scan_panel, "workspace_dir", lambda: tmp_path)
    monkeypatch.setenv("JOB_FINDER_ROOT", str(tmp_path))
    api = scan_panel.Api([sys.executable])

    # 1. Empty workspace -> next_step says search
    ns = api.next_step()
    assert ns["ok"] and ns["stage"] == "search" and ns["counts"]["scanned"] == 0

    # 2. Create a saved search and populate scanned_jobs.xlsx
    s, _ = searches.get_or_create("ai-intern", topic="applied AI", level="intern", location="London")
    searches.set_current(s.name)
    ExcelTracker(s.scanned).add_jobs([
        {"Company": "Acme", "Job Role": "AI Intern", "ATS %": 88, "Match": "Core", "Role Level": "intern", "Job URL": "https://example.com/1"},
        {"Company": "Beta", "Job Role": "ML Intern", "ATS %": 72, "Match": "Related", "Role Level": "intern", "Job URL": "https://example.com/2"},
    ])
    ls = api.list_searches()
    assert ls["ok"] and ls["current"] == "ai-intern" and ls["searches"][0]["jobs"] == 2
    assert api.next_step()["stage"] == "review"

    jobs = api.list_jobs("ai-intern")
    assert jobs["ok"] and len(jobs["jobs"]) == 2 and jobs["jobs"][0]["fit"] == 88

    # 3. Approve >= 80% -> 1 approved -> next_step says packs
    app_res = api.approve_jobs({"min_ats": 80})
    assert app_res == {"ok": True, "approved": 1}
    assert api.next_step()["stage"] == "packs"

    # Approve and revoke by ID
    assert api.approve_jobs({"ids": ["2"]}) == {"ok": True, "approved": 1}
    assert api.revoke_jobs({"ids": ["2"]}) == {"ok": True, "revoked": 1}

    # 4. Packs & Documents
    packs = api.list_packs()
    assert packs["ok"] and len(packs["packs"]) == 1 and packs["packs"][0]["state"] == "not_started"

    called_cmds = []
    monkeypatch.setattr(api._runner, "start", lambda args, env, cwd, title="scan": (called_cmds.append((args, title)) or {"ok": True}))
    assert api.prepare_packs({"ids": ["1"]}) == {"ok": True}
    assert called_cmds[-1][1] == "prepare" and "--ids" in called_cmds[-1][0] and ["--cover-letter", "always"] == called_cmds[-1][0][1:3]

    # Simulate generated pack files
    row = ExcelTracker(s.approved).rows()[0]
    folder = api._pack_folder(s, row)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "REVIEW.md").write_text("# Checklist\n- ok", encoding="utf-8")
    (folder / "cover_letter.txt").write_text("Dear Acme,", encoding="utf-8")
    (folder / "fit_analysis.md").write_text("Fit 88%", encoding="utf-8")
    (folder / "cv.pdf").write_bytes(b"%PDF-1.4")

    assert api.next_step()["stage"] == "documents"
    docs = api.pack_documents("1")
    assert docs["ok"] and "Dear Acme" in docs["cover_letter"] and "Checklist" in docs["review_md"]
    assert api.pack_documents("999")["ok"] is False

    opened = []
    monkeypatch.setattr(scan_panel.platform_support, "open_path", lambda p, as_text: opened.append((p, as_text)))
    assert api.open_pack_file("1", "cv") == {"ok": True}
    assert api.open_pack_file("1", "review") == {"ok": True}
    assert api.open_pack_file("1", "bad")["ok"] is False
    assert len(opened) == 2

    # 5. Sign off & Apply
    assert api.signoff_pack("1") == {"ok": True}
    assert api.signoff_pack("999")["ok"] is False
    assert api.next_step()["stage"] == "apply"

    ready = api.list_ready()
    assert ready["ok"] and len(ready["jobs"]) == 1 and ready["cap"]["limit"] == 20
    # Verify list_ready sorts signed-off jobs by descending fit score
    ExcelTracker(s.approved).add_jobs([
        {"Company": "TopCo", "Job Role": "Staff AI", "ATS %": 96, "Status": "Approved", "Approve": "Yes", "Docs OK": "Yes", "Job URL": "https://example.com/top"},
    ])
    top_ready = api.list_ready()
    assert [j["company"] for j in top_ready["jobs"]] == ["TopCo", "Acme"]
    api.save_app_prefs({"daily_cap": 35})
    assert api.list_ready()["cap"]["limit"] == 35

    # start_apply requires profile
    assert api.start_apply({"mode": "preview"})["ok"] is False
    _profile_file(tmp_path)
    assert api.start_apply({"mode": "submit", "limit": 3, "headless": True}) == {"ok": True}
    assert called_cmds[-1][1] == "apply" and "--submit" in called_cmds[-1][0] and "--yes" in called_cmds[-1][0]

    # Verify poll() surfaces apply_run_audit.jsonl as applied_rows when apply finishes
    (tmp_path / "applications_tracker").mkdir(parents=True, exist_ok=True)
    (tmp_path / "applications_tracker" / "apply_run_audit.jsonl").write_text(
        json.dumps({"id": "1", "role": "AI Intern", "company": "Acme", "status": "Applied",
                    "grounding": {"answered_from_profile": 5, "verified": True}, "questions": []}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(api._runner, "poll", lambda offset=0: {"lines": [], "next": 0, "running": False, "exit_code": 0, "title": "apply", "counts": {}})
    polled = api.poll(0)
    assert polled["applied_rows"][0]["grounding"]["answered_from_profile"] == 5

    # Verify delete_account calls DELETE /user/account and clears local token
    called_del = []
    monkeypatch.setattr(scan_panel, "account_token", lambda ws=None: "tok-123")
    monkeypatch.setattr(scan_panel, "_server_request", lambda ws, tok, path, method="GET", body=None, timeout=20: called_del.append((path, method, body)) or {"status": "deleted"})
    assert api.delete_account("")["ok"] is False
    assert api.delete_account("ada@example.com") == {"ok": True}
    assert called_del == [("/user/account", "DELETE", {"confirm_email": "ada@example.com"})]

    # Verify boards_status, refresh_boards, prepare_packs redo, and cv_html
    assert api.get_state()["boards"]["ready"] is False
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "board_index.db").write_bytes(b"sqlite")
    assert api.get_state()["boards"]["ready"] is True
    assert api.refresh_boards() == {"ok": True}
    assert called_cmds[-1][1] == "boards" and called_cmds[-1][0] == ["boards", "refresh"]
    assert api.prepare_packs({"ids": ["1"], "redo": True}) == {"ok": True}
    assert "--redo" in called_cmds[-1][0]
    (folder / "cv.html").write_text("<html><body>CV</body></html>", encoding="utf-8")
    assert "<body>CV</body>" in api.pack_documents("1")["cv_html"]

    # 6. Portal password stored in .env + scan_args flags + closing date cleanup
    assert api.get_state()["portal_password"]["set"] is False
    pw_res = api.save_portal_password("SuperSecret#99")
    assert pw_res["ok"] and pw_res["portal_password"]["set"] is True
    assert "PORTALS_PASSWORD" in (tmp_path / ".env").read_text()
    scan_args = scan_panel.build_scan_args({"score_all": True, "sponsor_only": True})
    assert "--score-all" in scan_args and "--sponsor-only" in scan_args
    assert api._job_dict({"Closing Date": "2026-12-02 00:00:00", "Scored By": "AI"})["closing"] == "2026-12-02"
    assert api._job_dict({"Scored By": "Keyword"})["scored_by"] == "Keyword"
