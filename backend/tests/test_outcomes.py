import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from applications_tracker import outcomes as o  # noqa: E402


def test_sites_are_recognised_from_the_job_url():
    assert o.site_of("https://boards.greenhouse.io/acme/jobs/1") == "Greenhouse"
    assert o.site_of("https://uk.linkedin.com/jobs/view/123") == "LinkedIn"
    assert o.site_of("https://acme.wd3.myworkdayjobs.com/en/x") == "Workday"
    assert o.site_of("https://www.example.org/careers") == "example.org"
    assert o.site_of("") == "unknown"


def test_statuses_map_to_three_outcomes():
    assert [o.classify(s) for s in ("success", "needs_review", "preview_ready", "failed", "", "weird")] == \
        ["submitted", "needs_review", "needs_review", "failed", "failed", "failed"]


def test_attempts_are_appended_one_json_line_each(tmp_path):
    o.append_outcome({"url": "https://boards.greenhouse.io/a/1", "status": "success", "final_result": "SUBMISSION_CONFIRMED"}, str(tmp_path))
    o.append_outcome({"url": "https://jobs.ashbyhq.com/b/2", "status": "needs_review", "final_result": "x" * 900}, str(tmp_path))
    lines = (tmp_path / "applications_tracker" / "run_outcomes.jsonl").read_text().splitlines()
    assert len(lines) == 2
    first, second = json.loads(lines[0]), json.loads(lines[1])
    assert first["site"] == "Greenhouse" and first["outcome"] == "submitted"
    assert second["site"] == "Ashby" and second["outcome"] == "needs_review" and len(second["final_result"]) == 400


def test_a_damaged_line_does_not_hide_the_rest(tmp_path):
    path = tmp_path / "applications_tracker" / "run_outcomes.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text('{"site": "Lever", "outcome": "submitted"}\nnot json\n{"site": "Lever", "outcome": "failed"}\n')
    assert len(o.read_outcomes(str(tmp_path))) == 2


def test_recording_never_raises(tmp_path):
    blocker = tmp_path / "applications_tracker"
    blocker.write_text("a file where the folder should be")
    o.append_outcome({"url": "https://x", "status": "success"}, str(tmp_path))  # must not raise


def test_summary_gives_a_rate_and_the_top_reason_per_site():
    rows = [
        {"site": "Ashby", "outcome": "needs_review", "final_result": "Node is not a file input element"},
        {"site": "Ashby", "outcome": "needs_review", "final_result": "Node is not a file input element"},
        {"site": "Ashby", "outcome": "submitted", "final_result": "SUBMISSION_CONFIRMED"},
        {"site": "LinkedIn", "outcome": "submitted"},
    ]
    summary = {s["site"]: s for s in o.summarize(rows)}
    assert summary["Ashby"]["attempts"] == 3 and summary["Ashby"]["rate"] == 33
    assert summary["Ashby"]["top_reason"] == "Node is not a file input element"
    assert summary["LinkedIn"]["rate"] == 100 and summary["LinkedIn"]["top_reason"] == ""
    assert o.summarize(rows)[0]["site"] == "Ashby"  # most attempts first


def test_the_command_prints_a_table_and_json(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("JOB_FINDER_ROOT", str(tmp_path))
    from job_finder.commands.outcomes import run
    import argparse
    run(argparse.Namespace(json=False, recent=0))
    assert "No application attempts recorded yet" in capsys.readouterr().out
    o.append_outcome({"url": "https://boards.greenhouse.io/a/1", "status": "success", "company": "Acme", "title": "ML Intern"})
    run(argparse.Namespace(json=False, recent=1))
    out = capsys.readouterr().out
    assert "Greenhouse" in out and "100%" in out and "Acme: ML Intern" in out
    run(argparse.Namespace(json=True, recent=0))
    assert json.loads(capsys.readouterr().out)["attempts"] == 1


def test_usage_today_adds_up_todays_attempts(tmp_path, monkeypatch):
    from applications_tracker import outcomes
    monkeypatch.setenv("JOB_FINDER_ROOT", str(tmp_path))
    outcomes.append_outcome({"url": "https://a.example/1", "status": "success", "usage": {"total_tokens": 1200, "total_cost": 0.01}})
    outcomes.append_outcome({"url": "https://a.example/2", "status": "failed", "usage": {"total_tokens": 800}})
    outcomes.append_outcome({"url": "https://a.example/3", "status": "failed"})
    assert outcomes.usage_today() == {"tokens": 2000, "cost": 0.01}


def test_usage_summary_reads_what_the_library_offers_and_never_raises():
    from services.browser_use_agent import usage_summary

    class Usage:
        total_prompt_tokens = 900
        total_completion_tokens = 100
        total_tokens = 1000
        total_cost = 0.02

    class WithUsage:
        usage = Usage()

    class Old:
        def total_input_tokens(self):
            return 500

    class Broken:
        @property
        def usage(self):
            raise RuntimeError("no")

    assert usage_summary(WithUsage())["total_tokens"] == 1000
    assert usage_summary(Old()) == {"total_tokens": 500}
    assert usage_summary(Broken()) == {}
    assert usage_summary(object()) == {}


def test_daily_cap_counts_only_todays_submissions(tmp_path, monkeypatch):
    from applications_tracker import outcomes
    monkeypatch.setenv("JOB_FINDER_ROOT", str(tmp_path))
    outcomes.append_outcome({"url": "https://boards.greenhouse.io/a/jobs/1", "status": "success"})
    outcomes.append_outcome({"url": "https://boards.greenhouse.io/a/jobs/2", "status": "needs_review"})
    outcomes.append_outcome({"url": "https://boards.greenhouse.io/a/jobs/3", "status": "failed"})
    old = outcomes.ledger_path()
    old.write_text(old.read_text() + '{"time": "2020-01-01T10:00:00", "outcome": "submitted"}\n')
    assert outcomes.submitted_today() == 1
    monkeypatch.setenv("MAX_APPLICATIONS_PER_DAY", "3")
    assert outcomes.daily_cap() == 3
    monkeypatch.setenv("MAX_APPLICATIONS_PER_DAY", "0")
    assert outcomes.daily_cap() == 0
    monkeypatch.delenv("MAX_APPLICATIONS_PER_DAY")
    assert outcomes.daily_cap() == 25
