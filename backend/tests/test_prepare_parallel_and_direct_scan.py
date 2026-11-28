"""Tests for parallel prepare_jobs and direct `job-finder scan --auto-apply / --direct`."""
from __future__ import annotations

import os
import threading
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from job_finder import cli_parser
from job_finder.commands import prepare as prepare_cmd
from job_finder.commands import scan as scan_cmd


def test_prepare_jobs_runs_in_parallel_and_isolates_failures():
    rows = [
        {"ID": 1, "Company": "Acme", "Job Role": "AI Eng", "Job URL": "https://a.test/1"},
        {"ID": 2, "Company": "Beta", "Job Role": "ML Eng", "Job URL": "https://b.test/2"},
        {"ID": 3, "Company": "Gamma", "Job Role": "Bad", "Job URL": "https://c.test/3"},
    ]
    approved = MagicMock()
    scanned = MagicMock()
    active_threads = set()
    lock = threading.Lock()

    def fake_build(row, candidate, desc, **_kw):
        with lock:
            active_threads.add(threading.get_ident())
        time.sleep(0.05)
        if row["ID"] == 3:
            raise RuntimeError("boom")
        return SimpleNamespace(folder=f"/tmp/pack_{row['ID']}", cover_letter="Yes", status="Ready for review", warnings=[])

    with patch.object(prepare_cmd, "fetch_descriptions", return_value={r["Job URL"]: "jd" for r in rows}), \
         patch("backend.services.application_pack.build_pack", side_effect=fake_build):
        results = prepare_cmd.prepare_jobs(rows, scanned, approved, {"name": "Ada"}, max_workers=3)

    assert [r["ID"] for r, _ in results] == [1, 2]
    assert len(active_threads) >= 2
    assert approved.update_many.call_count == 1
    assert scanned.update_many.call_count == 1


def test_scan_auto_apply_parses_and_calls_run_pipeline(monkeypatch):
    parser = cli_parser.build_parser("1.9.6")
    args = parser.parse_args([
        "scan",
        "--skip-portals", "targetjobs,workday,bamboohr,reed,jobserve",
        "--timeframe", "24h",
        "--auto-apply",
    ])
    assert args.auto_apply is True
    assert args.timeframe == "24h"
    assert args.skip_portals == "targetjobs,workday,bamboohr,reed,jobserve"

    called = {}

    async def fake_run_pipeline(**kwargs):
        called.update(kwargs)

    monkeypatch.delenv("JOB_FINDER_DISABLE_GUARDRAILS", raising=False)
    with patch("applications_tracker.scheduled_job_scanner.run_pipeline", side_effect=fake_run_pipeline):
        scan_cmd.run(args)

    assert called["auto_submit_override"] is True
    assert called["timeframe_override"] == "24h"
    assert called["skip_portals"] == "targetjobs,workday,bamboohr,reed,jobserve"
    assert os.environ.get("JOB_FINDER_DISABLE_GUARDRAILS") == "1"


def test_scan_direct_without_auto_apply_keeps_guardrails(monkeypatch):
    parser = cli_parser.build_parser("1.9.6")
    args = parser.parse_args(["scan", "--direct", "--timeframe", "24h"])
    called = {}

    async def fake_run_pipeline(**kwargs):
        called.update(kwargs)

    monkeypatch.delenv("JOB_FINDER_DISABLE_GUARDRAILS", raising=False)
    with patch("applications_tracker.scheduled_job_scanner.run_pipeline", side_effect=fake_run_pipeline):
        scan_cmd.run(args)

    assert called["auto_submit_override"] is None
    assert called["timeframe_override"] == "24h"
    assert "JOB_FINDER_DISABLE_GUARDRAILS" not in os.environ
