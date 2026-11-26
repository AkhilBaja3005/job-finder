import importlib
import json
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
