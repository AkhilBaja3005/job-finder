import json
import subprocess
import sys

from job_finder import tracker_view, ui

APPS = [
    {"company": "Acme", "job_title": "AI Engineer", "score": 90, "status": "applied", "updated_at": "2026-11-01T10:00:00", "job_url": "https://a/1"},
    {"company": "Beta", "job_title": "ML Engineer", "score": "80%", "status": "Needs Review (Blocked: captcha)", "updated_at": "2026-11-02"},
    {"company": "Gamma", "job_title": "Data Scientist", "score": None, "status": "Ready to Apply (Reviewed)"},
]


def test_summarize_counts_and_average():
    s = tracker_view.summarize(APPS)
    assert s["total"] == 3
    assert s["avg_ats"] == 85.0
    assert s["by_status"]["applied"] == 1


def test_filter_apps_is_case_insensitive_substring():
    assert len(tracker_view.filter_apps(APPS, "BLOCKED")) == 1
    assert len(tracker_view.filter_apps(APPS, "all")) == 3
    assert len(tracker_view.filter_apps(APPS, None)) == 3


def test_tracker_json_output(capsys):
    assert tracker_view.render_tracker(APPS, status="applied", as_json=True) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["summary"]["total"] == 3
    assert data["matched"] == 1
    assert data["applications"][0]["company"] == "Acme"
    assert data["applications"][0]["ats"] == 90


def test_tracker_limit_and_empty(capsys):
    ui.configure(no_color=True)
    assert tracker_view.render_tracker([], as_json=False) == 0
    assert "No tracked job applications" in capsys.readouterr().out
    tracker_view.render_tracker(APPS, limit=1, as_json=True)
    assert len(json.loads(capsys.readouterr().out)["applications"]) == 1


def test_ui_table_plain_fallback(monkeypatch, capsys):
    monkeypatch.setattr(ui, "HAS_RICH", False)
    ui.configure(no_color=True)
    ui.print_table("T", ["A", "B"], [["x", "yy"]])
    out = capsys.readouterr().out
    assert "T" in out and "x" in out and "yy" in out


def test_quiet_suppresses_info_but_not_errors(capsys):
    ui.configure(quiet=True)
    ui.info("hello")
    ui.error("boom")
    cap = capsys.readouterr()
    assert "hello" not in cap.out
    assert "boom" in cap.err
    ui.configure(quiet=False)


def _run(*args):
    return subprocess.run([sys.executable, "-m", "job_finder.cli", *args], capture_output=True, text=True,
                          env={"JOB_FINDER_NO_UPDATE_CHECK": "1", "PATH": "/usr/bin:/bin", "NO_COLOR": "1"})


def test_unknown_flag_is_rejected():
    res = _run("doctor", "--nope")
    assert res.returncode == 2
    assert "unrecognized arguments" in res.stderr


def test_help_lists_examples_and_new_commands():
    res = _run("--help")
    assert res.returncode == 0
    assert "tracker" in res.stdout and "doctor" in res.stdout and "examples:" in res.stdout


def test_shell_completion_suggests_subcommands():
    pytest = __import__("pytest")
    pytest.importorskip("argcomplete")
    import os
    import shlex
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    code = "import sys; sys.argv=['job-finder']; from job_finder.cli import main; main()"
    # argcomplete writes completions to fd 8, so redirect it to stdout in a shell
    cmd = f"{shlex.quote(sys.executable)} -c {shlex.quote(code)} 8>&1 2>/dev/null"
    env = {"PATH": "/usr/bin:/bin", "_ARGCOMPLETE": "1", "_ARGCOMPLETE_IFS": "\n", "COMP_LINE": "job-finder cov",
           "COMP_POINT": "14", "JOB_FINDER_NO_UPDATE_CHECK": "1"}
    res = subprocess.run(["sh", "-c", cmd], env=env, cwd=root, capture_output=True, text=True)
    assert "cover-letter" in res.stdout, res.stdout


def test_dry_run_flags_are_accepted_by_scan_and_apply():
    for cmd in (["scan", "--help"], ["apply", "--help"]):
        res = _run(*cmd)
        assert res.returncode == 0 and "--dry-run" in res.stdout
