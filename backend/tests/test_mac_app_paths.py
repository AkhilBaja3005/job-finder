"""The less travelled paths of the desktop app: failures, the second platform, dialogs, processes. These are the ones that break quietly."""
import json
import signal
import subprocess
import sys
import threading
import time
import types
import urllib.error
from pathlib import Path

import pytest

MACAPP = Path(__file__).resolve().parents[2] / "macapp"
sys.path.insert(0, str(MACAPP))
import platform_support as ps  # noqa: E402
import scan_panel as sp  # noqa: E402


@pytest.fixture(autouse=True)
def isolated(tmp_path_factory, monkeypatch):
    monkeypatch.setenv("JOB_FINDER_APP_HOME", str(tmp_path_factory.mktemp("apphome")))
    monkeypatch.setattr(sp, "GATE_ENABLED", False)
    sp._session.update(ok=False, checked=0.0, token="")
    sp._cloud_cache.clear()
    sp._signin_state.update(state="idle", error="", email="")
    yield


def make_api(monkeypatch, ws):
    monkeypatch.setattr(sp, "workspace_dir", lambda: ws)
    return sp.Api([sys.executable, "--cli"])


def http_error(code):
    return urllib.error.HTTPError("https://x", code, "msg", {}, None)


def fake_webview(monkeypatch, picked):
    """A stand-in for pywebview whose file dialog returns `picked`."""
    module = types.ModuleType("webview")
    module.FOLDER_DIALOG, module.OPEN_DIALOG = 20, 10
    monkeypatch.setitem(sys.modules, "webview", module)
    calls = []

    class Window:
        def create_file_dialog(self, kind, file_types=()):
            calls.append((kind, file_types))
            return picked

    return Window(), calls


# ── messages and the account status ──────────────────────────────────────────────
def test_explain_covers_every_kind_of_failure():
    assert "sign-in has ended" in sp._explain(http_error(401))
    assert "Too many attempts" in sp._explain(http_error(429))
    assert "(503)" in sp._explain(http_error(503))
    assert "Could not reach" in sp._explain(OSError("down"))


def test_cloud_status_signed_out_connected_cached_guest_and_failing(tmp_path, monkeypatch):
    assert sp.cloud_status(tmp_path) == {"configured": False, "connected": False, "signing_in": False}
    sp._signin_state["state"] = "waiting"
    assert sp.cloud_status(tmp_path)["signing_in"] is True
    sp._store_account("11111111-2222-3333-4444-555555555555", "me@example.com")
    calls = []

    def answer(ws, code, path, **kw):
        calls.append(path)
        return {"email": "me@example.com"}

    monkeypatch.setattr(sp, "_server_request", answer)
    first = sp.cloud_status(tmp_path)
    assert first == {"configured": True, "connected": True, "email": "me@example.com", "kind": "google"}
    sp.cloud_status(tmp_path)
    assert calls == ["/user/me"]                                   # the second answer came from the one-minute cache
    sp.cloud_status(tmp_path, fresh=True)
    assert len(calls) == 2
    monkeypatch.setattr(sp, "_server_request", lambda *a, **k: {"is_guest": True})
    assert sp.cloud_status(tmp_path, fresh=True)["connected"] is False
    monkeypatch.setattr(sp, "_server_request", lambda *a, **k: (_ for _ in ()).throw(OSError("down")))
    down = sp.cloud_status(tmp_path, fresh=True)
    assert down["connected"] is False and "Could not reach" in down["error"]


# ── finishing a run ──────────────────────────────────────────────────────────────
class InlineThread:
    """Runs the work at once so a test can look at the result."""
    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self.target, self.args, self.kwargs = target, args, kwargs or {}

    def start(self):
        self.target(*self.args, **self.kwargs)


def test_a_finished_scan_notifies_once_and_syncs_once(tmp_path, monkeypatch):
    api = make_api(monkeypatch, tmp_path)
    sp._store_account("11111111-2222-3333-4444-555555555555", "me@example.com")
    sent, lines, notes = [], [], []
    monkeypatch.setattr(sp, "notify", lambda title, message: notes.append(message))
    monkeypatch.setattr(sp, "sync_to_cloud", lambda ws: sent.append(ws) or {"ok": True, "pushed": 3})
    monkeypatch.setattr(sp.threading, "Thread", InlineThread)
    monkeypatch.setattr(api._runner, "add_line", lines.append)
    api._runner.poll = lambda offset: {"running": False, "title": "scan", "exit_code": 0, "counts": {"submitted": 2, "needs_review": 1}, "lines": [], "offset": 0}
    api._notified = api._synced_after_run = False
    api.poll(0)
    api.poll(0)                                                     # a second look must not repeat anything
    assert notes == ["Run finished: 2 submitted, 1 to review."] and len(sent) == 1
    assert lines == ["Synced with job-finder.space: 3 new application(s) added."]


def test_a_failed_scan_says_so_and_a_sync_error_is_shown(tmp_path, monkeypatch):
    api = make_api(monkeypatch, tmp_path)
    sp._store_account("11111111-2222-3333-4444-555555555555", "me@example.com")
    notes, lines = [], []
    monkeypatch.setattr(sp, "notify", lambda title, message: notes.append(message))
    monkeypatch.setattr(sp, "sync_to_cloud", lambda ws: {"ok": False, "error": "Your sign-in has ended."})
    monkeypatch.setattr(sp.threading, "Thread", InlineThread)
    monkeypatch.setattr(api._runner, "add_line", lines.append)
    api._runner.poll = lambda offset: {"running": False, "title": "scan", "exit_code": 1, "counts": {"submitted": 0, "needs_review": 0}}
    api._notified = api._synced_after_run = False
    api.poll(0)
    assert notes == ["The run ended with an error."] and lines == ["Your sign-in has ended."]


def test_other_commands_and_running_scans_do_not_notify_or_sync(tmp_path, monkeypatch):
    api = make_api(monkeypatch, tmp_path)
    notes = []
    monkeypatch.setattr(sp, "notify", lambda title, message: notes.append(message))
    api._runner.poll = lambda offset: {"running": True, "title": "scan", "exit_code": None, "counts": {}}
    api._notified = api._synced_after_run = False
    api.poll(0)
    api._runner.poll = lambda offset: {"running": False, "title": "profile", "exit_code": 0, "counts": {}}
    api.poll(0)
    assert notes == []


def test_the_mailbox_check_after_a_run_reports_moved_applications(tmp_path, monkeypatch):
    api = make_api(monkeypatch, tmp_path)
    lines = []
    monkeypatch.setattr(sp, "mailbox_status", lambda ws: {"configured": True, "user": "me@example.com"})
    monkeypatch.setattr(sp, "check_replies", lambda ws: {"ok": True, "updated": 2})
    monkeypatch.setattr(api._runner, "add_line", lines.append)
    api._sync_and_report()
    assert lines == ["Mailbox: 2 application(s) moved forward after replies."]


# ── window and platform handling ─────────────────────────────────────────────────
def test_the_title_bar_theme_is_only_touched_on_a_mac_and_never_fails(tmp_path, monkeypatch):
    api = make_api(monkeypatch, tmp_path)
    monkeypatch.setattr(ps, "IS_MAC", False)
    assert api.set_theme(True) == {"ok": True}
    monkeypatch.setattr(ps, "IS_MAC", True)
    seen = []
    monkeypatch.setitem(sys.modules, "native", types.SimpleNamespace(set_titlebar_theme=lambda window, dark: seen.append(dark)))
    assert api.set_theme(1) == {"ok": True} and seen == [True]
    monkeypatch.setitem(sys.modules, "native", types.SimpleNamespace(set_titlebar_theme=lambda window, dark: (_ for _ in ()).throw(RuntimeError("no window"))))
    assert api.set_theme(False) == {"ok": True}


def test_zoom_uses_the_native_call_on_a_mac_and_fullscreen_elsewhere(tmp_path, monkeypatch):
    api = make_api(monkeypatch, tmp_path)
    zoomed, toggled = [], []
    monkeypatch.setitem(sys.modules, "native", types.SimpleNamespace(toggle_zoom=lambda window: zoomed.append(window)))
    api._window = types.SimpleNamespace(toggle_fullscreen=lambda: toggled.append(True), x=0, y=0)
    monkeypatch.setattr(ps, "IS_MAC", True)
    api.zoom_window()
    monkeypatch.setattr(ps, "IS_MAC", False)
    api.zoom_window()
    assert len(zoomed) == 1 and toggled == [True]
    api._window = None
    assert api.zoom_window() == {"ok": True}


def test_folder_resume_and_profile_dialogs(tmp_path, monkeypatch):
    api = make_api(monkeypatch, tmp_path)
    window, calls = fake_webview(monkeypatch, None)
    api._window = window
    assert api.choose_workspace() == {"ok": False} and api.choose_resume_and_build_profile() == {"ok": False} and api.choose_profile_and_import() == {"ok": False}
    api._window = None
    assert api.choose_workspace() == {"ok": False}
    window, calls = fake_webview(monkeypatch, [str(tmp_path / "chosen")])
    api._window = window
    out = api.choose_workspace()
    assert out["ok"] and sp.load_app_config()["workspace"] == str(tmp_path / "chosen")
    assert api.use_default_workspace()["ok"] and "workspace" not in sp.load_app_config()
    started = []
    monkeypatch.setattr(api, "run_command", lambda name, extra=None: started.append((name, extra)) or {"ok": True})
    fake_webview_window, _ = fake_webview(monkeypatch, [str(tmp_path / "resume.pdf")])
    api._window = fake_webview_window
    assert api.choose_resume_and_build_profile() == {"ok": True}
    assert started == [("profile", ["--sync", str(tmp_path / "resume.pdf")])]
    assert sp.read_env(tmp_path)["MASTER_RESUME_PATH"] == str(tmp_path / "resume.pdf")


def test_importing_a_profile_through_the_dialog(tmp_path, monkeypatch):
    api = make_api(monkeypatch, tmp_path)
    source = tmp_path / "mine.json"
    source.write_text(json.dumps({"candidate": {"name": "Ada"}, "search_preferences": {}}))
    window, _ = fake_webview(monkeypatch, [str(source)])
    api._window = window
    out = api.choose_profile_and_import()
    assert out["ok"] and out["name"] == "Ada"


def test_import_refuses_bad_files_and_keeps_a_backup(tmp_path):
    ws = tmp_path / "ws"
    big = tmp_path / "big.json"
    big.write_text("x" * 2_000_100)
    assert "too large" in sp.import_profile_file(ws, big)["error"]
    assert "not valid JSON" in sp.import_profile_file(ws, tmp_path / "missing.json")["error"]
    notjson = tmp_path / "t.json"
    notjson.write_text("{nope")
    assert "not valid JSON" in sp.import_profile_file(ws, notjson)["error"]
    odd = tmp_path / "odd.json"
    odd.write_text(json.dumps({"candidate": {"name": "A"}, "search_preferences": [1]}))
    assert "must be an object" in sp.import_profile_file(ws, odd)["error"]
    odd.write_text(json.dumps({"candidate": {"name": "A"}}))
    assert sp.import_profile_file(ws, odd)["ok"]
    odd.write_text(json.dumps({"candidate": {"name": "B"}}))
    assert sp.import_profile_file(ws, odd)["ok"]
    assert json.loads(sp.profile_path(ws).with_name("candidate_profile.json.bak").read_text())["candidate"]["name"] == "A"


# ── opening files and the signed-in Chrome ───────────────────────────────────────
def test_open_path_targets_and_unknown_names(tmp_path, monkeypatch):
    api = make_api(monkeypatch, tmp_path)
    opened = []
    monkeypatch.setattr(ps, "open_path", lambda path, as_text=False: opened.append((Path(path).name, as_text)))
    monkeypatch.setenv("JOB_FINDER_APP_HOME", str(tmp_path / "home"))
    for name in ("workspace", "profile", "env", "tracker", "logs", "answers"):
        assert api.open_path(name) == {"ok": True}
    assert api.open_path("../../etc") == {"ok": False} and api.open_path("") == {"ok": False}
    assert ("candidate_profile.json", True) in opened and (".env", True) in opened and ("saved_answers.json", True) in opened
    assert sp.logs_dir().is_dir()                                    # "logs" creates the folder first


def run_result(code, **kw):
    return subprocess.CompletedProcess(["x"], code, "", "")


def test_sign_in_chrome_refuses_while_running_without_chrome_and_reports_failures(tmp_path, monkeypatch):
    api = make_api(monkeypatch, tmp_path)
    monkeypatch.setattr(sp, "chrome_found", lambda: False)
    assert "not found" in api.open_signin()["error"]
    monkeypatch.setattr(sp, "chrome_found", lambda: True)
    seen = []
    monkeypatch.setattr(sp.subprocess, "run", lambda cmd, **kw: seen.append(cmd) or run_result(0))
    assert api.open_signin()["ok"] is True and seen[0][-1] == "--signin" and "--cli" not in seen[0]
    monkeypatch.setattr(sp.subprocess, "run", lambda cmd, **kw: run_result(1))
    assert api.open_signin() == {"ok": False, "error": "Chrome did not start. See the log files."}
    monkeypatch.setattr(sp.subprocess, "run", lambda cmd, **kw: (_ for _ in ()).throw(subprocess.TimeoutExpired("x", 1)))
    assert api.open_signin()["ok"] is False
    monkeypatch.setattr(type(api._runner), "running", property(lambda self: True))
    assert "in progress" in api.open_signin()["error"]


def test_review_in_chrome_opens_the_job_and_reports_failures(tmp_path, monkeypatch):
    api = make_api(monkeypatch, tmp_path)
    seen = []
    monkeypatch.setattr(sp.subprocess, "run", lambda cmd, **kw: seen.append(cmd) or run_result(0))
    assert api.review_in_chrome("https://jobs.example/1")["ok"] and seen[0][-2:] == ["--open", "https://jobs.example/1"]
    monkeypatch.setattr(sp.subprocess, "run", lambda cmd, **kw: run_result(2))
    assert "did not open" in api.review_in_chrome("https://jobs.example/1")["error"]
    monkeypatch.setattr(sp.subprocess, "run", lambda cmd, **kw: (_ for _ in ()).throw(OSError("gone")))
    assert api.review_in_chrome("https://jobs.example/1")["ok"] is False
    monkeypatch.setattr(type(api._runner), "running", property(lambda self: True))
    assert "in progress" in api.review_in_chrome("https://jobs.example/1")["error"]


def test_the_review_screenshot_is_only_opened_when_it_is_inside_the_folder(tmp_path, monkeypatch):
    from applications_tracker.outcomes import append_outcome
    api = make_api(monkeypatch, tmp_path)
    monkeypatch.setenv("JOB_FINDER_ROOT", str(tmp_path))
    inside = tmp_path / "shot.png"
    inside.write_bytes(b"png")
    outside = tmp_path.parent / "elsewhere.png"
    outside.write_bytes(b"png")
    append_outcome({"url": "https://a.example/1", "status": "needs_review", "screenshot": str(inside), "final_result": "BLOCKED: needs your answer"})
    append_outcome({"url": "https://a.example/2", "status": "needs_review", "screenshot": str(outside), "reason": "odd"})
    append_outcome({"url": "https://a.example/3", "status": "failed"})
    opened = []
    monkeypatch.setattr(ps, "open_path", lambda path, as_text=False: opened.append(path))
    assert api.review_info("https://a.example/1") == {"ok": True, "reason": "BLOCKED: needs your answer", "outcome": "needs_review", "screenshot": str(inside)}
    assert api.review_info("https://a.example/2")["screenshot"] == ""                                      # a path outside the folder is ignored
    assert api.review_info("https://a.example/3")["screenshot"] == "" and api.review_info("https://nope.example/")["ok"] is True
    assert api.open_screenshot("https://a.example/1") == {"ok": True} and opened == [str(inside)]
    assert api.open_screenshot("https://a.example/2")["ok"] is False and api.open_screenshot("https://nope.example/")["ok"] is False


# ── the report people send us ────────────────────────────────────────────────────
def test_problem_report_reads_the_log_hides_secrets_and_copes_without_one(tmp_path, monkeypatch):
    api = make_api(monkeypatch, tmp_path)
    assert "(no log yet)" in api.problem_report()["text"]
    sp.logs_dir().mkdir(parents=True, exist_ok=True)
    (sp.logs_dir() / "app.log").write_text("\n".join(f"line {i}" for i in range(100)) + f"\nkey sk-ant-abcdefgh12345678 at {Path.home()}/x\n")
    text = api.problem_report()["text"]
    assert "line 99" in text and "line 10\n" not in text and "sk-ant" not in text and str(Path.home()) not in text and "~/x" in text
    assert "Account connected: no" in text


# ── saving and starting ──────────────────────────────────────────────────────────
def test_save_key_rejects_unknown_providers_and_empty_values(tmp_path, monkeypatch):
    api = make_api(monkeypatch, tmp_path)
    assert api.save_key("nobody", "abc")["ok"] is False and api.save_key("gemini", "   ")["ok"] is False
    out = api.save_key("gemini", "  AIza" + "x" * 30 + "  ")
    assert out["ok"] and out["keys"]["gemini"]["set"] and sp.read_env(tmp_path)["GEMINI_API_KEY"] == "AIza" + "x" * 30


def test_start_scan_needs_a_profile_and_saves_the_form(tmp_path, monkeypatch):
    api = make_api(monkeypatch, tmp_path)
    assert "No profile yet" in api.start_scan({"roles": ["AI Engineer"]})["error"]
    sp.profile_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    sp.profile_path(tmp_path).write_text(json.dumps({"candidate": {"name": "Ada"}, "search_preferences": {}}))
    started = []
    monkeypatch.setattr(api._runner, "start", lambda args, env, cwd, title: started.append((args, title)) or {"ok": True})
    out = api.start_scan({"roles": ["AI Engineer"], "location": "London", "mode": "dry_run", "min_ats": "75"})
    assert out == {"ok": True} and started[0][1] == "scan" and "--dry-run" in started[0][0]
    prefs = json.loads(sp.profile_path(tmp_path).read_text())["search_preferences"]
    assert prefs["target_roles"] == ["AI Engineer"] and prefs["target_locations"] == ["London"] and prefs["min_ats_score_threshold"] == 75
    monkeypatch.setattr(api._runner, "start", lambda *a, **k: {"ok": False, "error": "busy"})
    assert api.start_scan({"roles": ["x"]})["ok"] is False and api._synced_after_run is True and api._notified is True


def test_preferences_survive_a_missing_or_broken_profile_file(tmp_path):
    sp.write_preferences(tmp_path, {"roles": ["A", "B"], "location": "Leeds", "timeframe": "2d", "min_ats": "oops", "title_keywords": "Intern", "skip_portals": ["x"]})
    data = json.loads(sp.profile_path(tmp_path).read_text())["search_preferences"]
    assert data["target_roles"] == ["A", "B"] and data["timeframe"] == "2d" and "min_ats_score_threshold" not in data and data["required_title_keywords"] == ["Intern"]
    sp.profile_path(tmp_path).write_text("{broken")
    sp.write_preferences(tmp_path, {"roles": ["C"], "location": "", "timeframe": ""})
    assert json.loads(sp.profile_path(tmp_path).read_text())["search_preferences"]["target_roles"] == ["C"]
    sp.write_preferences(tmp_path, {"location": "York"})
    sp.write_preferences(tmp_path, {"location": "Hull"})
    assert json.loads(sp.profile_path(tmp_path).read_text())["search_preferences"]["target_locations"] == ["Hull"]


def test_status_changes_tell_the_account_but_never_fail_without_it(tmp_path, monkeypatch):
    csv_dir = tmp_path / "applications_tracker"
    csv_dir.mkdir()
    (csv_dir / "job_applications_tracker.csv").write_text("Company,Job Title,Job URL,Status\nAcme,AI,https://jobs.example/1,Applied\n")
    sent = []
    monkeypatch.setattr(sp, "_server_request", lambda ws, code, path, method="GET", body=None, timeout=20.0, email=None: sent.append((code, path, body)) or {})
    assert sp.set_application_stage(tmp_path, "https://jobs.example/1", "offer")["status"] == "Offer" and sent == []           # signed out: nothing is sent
    sp._store_account("11111111-2222-3333-4444-555555555555", "me@example.com")
    sp.set_application_stage(tmp_path, "https://jobs.example/1", "interview")
    assert sent == [("11111111-2222-3333-4444-555555555555", "/applications/status", {"job_url": "https://jobs.example/1", "status": "Interview"})]
    monkeypatch.setattr(sp, "_server_request", lambda *a, **k: (_ for _ in ()).throw(OSError("down")))
    assert sp.set_application_stage(tmp_path, "https://jobs.example/1", "rejected")["ok"] is True                              # the file is the record
    (csv_dir / "job_applications_tracker.csv").write_text("Company,Job URL\nAcme,https://jobs.example/1\n")
    assert "no Status column" in sp.set_application_stage(tmp_path, "https://jobs.example/1", "offer")["error"]


# ── the process that runs a scan ─────────────────────────────────────────────────
def run_python(code):
    return sp.ScanRunner([sys.executable, "-c", code, "--"])


def wait_until(predicate, seconds=10):
    end = time.time() + seconds
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_a_second_start_is_refused_and_a_missing_program_is_reported(tmp_path):
    runner = run_python("import time; time.sleep(30)")
    assert runner.start([], {"PATH": "/usr/bin:/bin"}, tmp_path)["ok"]
    assert runner.start([], {}, tmp_path) == {"ok": False, "error": "A run is already in progress."}
    runner.stop()
    assert wait_until(lambda: not runner.running)
    broken = sp.ScanRunner(["/definitely/not/here"])
    assert "Could not start" in broken.start([], {}, tmp_path)["error"]


def test_stop_ends_a_run_with_a_message_and_is_harmless_when_idle(tmp_path):
    runner = run_python("import time; print('working', flush=True); time.sleep(30)")
    assert runner.stop() == {"ok": True, "message": "Nothing is running."}
    assert runner.start([], {"PATH": "/usr/bin:/bin"}, tmp_path)["ok"]
    assert wait_until(lambda: "working" in runner.poll(0)["lines"])
    assert runner.stop()["ok"] and wait_until(lambda: not runner.running)
    assert any("Stopped" in line for line in runner.poll(0)["lines"])


@pytest.mark.skipif(sys.platform == "win32", reason="signals work differently on Windows")
def test_a_run_that_ignores_the_stop_request_is_killed(tmp_path):
    runner = run_python("import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); print('stubborn', flush=True); time.sleep(60)")
    assert runner.start([], {"PATH": "/usr/bin:/bin"}, tmp_path)["ok"]
    assert wait_until(lambda: "stubborn" in runner.poll(0)["lines"])
    started = time.time()
    runner.stop()
    assert wait_until(lambda: not runner.running, 15) and time.time() - started < 15


def test_on_windows_stop_uses_taskkill(tmp_path, monkeypatch):
    runner = run_python("import time; time.sleep(30)")
    assert runner.start([], {"PATH": "/usr/bin:/bin"}, tmp_path)["ok"]
    calls = []
    monkeypatch.setattr(ps, "IS_WINDOWS", True)
    real_run = sp.subprocess.run
    monkeypatch.setattr(sp.subprocess, "run", lambda cmd, **kw: calls.append(cmd) or run_result(0))
    runner.stop()
    assert calls[0][:2] == ["taskkill", "/PID"] and "/T" in calls[0] and "/F" in calls[0]
    monkeypatch.setattr(ps, "IS_WINDOWS", False)
    monkeypatch.setattr(sp.subprocess, "run", real_run)
    runner.stop()
    assert wait_until(lambda: not runner.running)


def test_the_log_file_is_written_and_a_broken_log_folder_does_not_stop_a_run(tmp_path, monkeypatch):
    runner = run_python("print('hello'); print('\\x1b[31mred\\x1b[0m')")
    assert runner.start([], {"PATH": "/usr/bin:/bin"}, tmp_path)["ok"]
    assert wait_until(lambda: not runner.running) and wait_until(lambda: runner._exit_code == 0)
    logs = list(sp.logs_dir().glob("scan-*.log"))
    assert logs and logs[0].read_text().splitlines() == ["hello", "red"]                  # colour codes are removed
    blocker = tmp_path / "not-a-folder"
    blocker.write_text("file")
    monkeypatch.setattr(sp, "logs_dir", lambda: blocker / "inside")
    runner2 = run_python("print('still runs')")
    assert runner2.start([], {"PATH": "/usr/bin:/bin"}, tmp_path)["ok"]
    assert wait_until(lambda: "still runs" in runner2.poll(0)["lines"])


def test_a_very_long_run_keeps_only_the_latest_lines(tmp_path):
    runner = run_python("for i in range(6000): print(f'row {i}')")
    assert runner.start([], {"PATH": "/usr/bin:/bin"}, tmp_path)["ok"]
    assert wait_until(lambda: runner._exit_code == 0, 30)
    polled = runner.poll(0)
    assert len(polled["lines"]) <= 5000 and polled["lines"][-1] == "row 5999"
