"""Offline tests: company-board index (mocked network) and the Adzuna adapter."""

import asyncio
import importlib
import os
import sys

import httpx
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.services import aggregators as ag  # noqa: E402
from backend.services import board_index as bi  # noqa: E402


@pytest.mark.parametrize("loc,ok", [
    ("London, UK", True), ("Hybrid - London", True), ("London", True), ("Remote - UK", True), ("Remote (United Kingdom)", True),
    ("United Kingdom", False), ("New York, NY", False), ("Remote - US", False), ("Londonderry, Northern Ireland", False),
    ("Manchester, UK", False), ("", False), ("San Francisco | London", True),
])
def test_location_matching(loc, ok):
    assert bi.location_matches(loc, "London, UK") is ok


def test_location_follows_the_users_city():
    assert bi.location_matches("Manchester, England", "Manchester, UK")
    assert not bi.location_matches("London, UK", "Manchester, UK")


GH = {"jobs": [{"id": 1, "title": "ML Engineer Intern", "location": {"name": "London, UK"}, "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
                "updated_at": "2026-11-01T00:00:00Z", "company_name": "Acme AI"},
               {"id": 2, "title": "Sales Lead", "location": {"name": "New York"}, "absolute_url": "https://boards.greenhouse.io/acme/jobs/2"}]}
LEVER = [{"id": "L1", "text": "Applied Scientist Intern", "hostedUrl": "https://jobs.lever.co/beta/L1", "createdAt": 1760000000000,
          "categories": {"location": "Paris", "allLocations": ["Paris", "London"]}}]
ASHBY = {"jobs": [{"id": "A1", "title": "AI Research Intern", "location": "London", "jobUrl": "https://jobs.ashbyhq.com/gamma/A1", "isListed": True},
                  {"id": "A2", "title": "Hidden Role", "location": "London", "jobUrl": "https://jobs.ashbyhq.com/gamma/A2", "isListed": False}]}


def handler(request: httpx.Request) -> httpx.Response:
    u = str(request.url)
    if "greenhouse.io" in u and "/acme/" in u:
        return httpx.Response(200, json=GH)
    if "greenhouse.io" in u:
        return httpx.Response(404, json={})
    if "lever.co" in u:
        return httpx.Response(200, json=LEVER)
    if "ashbyhq.com" in u:
        return httpx.Response(200, json=ASHBY)
    return httpx.Response(500)


def run_refresh(tmp_path, **kw):
    seeds = {"greenhouse": ["acme", "ghost"], "lever": ["beta"], "ashby": ["gamma"]}
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return asyncio.run(bi.refresh(client=client, path=str(tmp_path / "idx.db"), seeds=seeds, progress=None, **kw))


def test_refresh_keeps_only_local_open_jobs_and_records_dead_boards(tmp_path):
    st = run_refresh(tmp_path)
    assert (st["visited"], st["ok"], st["dead"]) == (4, 3, 1)
    assert st["jobs_total"] == 2 + 1 + 1 and st["jobs_local"] == 3          # NY job and the unlisted Ashby job are not kept
    jobs, meta = bi.search(path=str(tmp_path / "idx.db"))
    titles = sorted(j["title"] for j in jobs)
    assert titles == ["AI Research Intern", "Applied Scientist Intern", "ML Engineer Intern"]
    assert meta == {"boards": 3, "local_jobs": 3, "matched": 3}
    gh = next(j for j in jobs if j["title"].startswith("ML Engineer"))
    assert gh["company"] == "Acme AI" and gh["platform"] == "Greenhouse" and gh["estimated"] is True and "boards" in gh["source"]
    lever = next(j for j in jobs if j["platform"] == "Lever")
    assert lever["location"] == "Paris | London" and lever["company"] == "Beta"


def test_fresh_boards_are_not_revisited_unless_forced(tmp_path):
    run_refresh(tmp_path)
    again = run_refresh(tmp_path)
    assert again["visited"] == 0
    assert run_refresh(tmp_path, force=True)["visited"] == 4


def test_search_applies_the_title_filter_and_reports_index_size(tmp_path):
    run_refresh(tmp_path)
    jobs, meta = bi.search(lambda t: "scientist" in t.lower(), path=str(tmp_path / "idx.db"))
    assert [j["title"] for j in jobs] == ["Applied Scientist Intern"] and meta["local_jobs"] == 3 and meta["matched"] == 1
    assert bi.search(path=str(tmp_path / "missing.db")) == ([], {"boards": 0, "local_jobs": 0, "matched": 0})
    assert bi.status(str(tmp_path / "idx.db"))["by_ats"]["lever"]["jobs"] == 1


def test_rate_limited_boards_are_retried_once(tmp_path):
    calls = {"n": 0}

    def flaky(request):
        calls["n"] += 1
        return httpx.Response(429) if calls["n"] == 1 else httpx.Response(200, json=GH)
    client = httpx.AsyncClient(transport=httpx.MockTransport(flaky))
    status, jobs = asyncio.run(bi.fetch_board(client, "greenhouse", "acme"))
    assert status == "ok" and len(jobs) == 2 and calls["n"] == 2


# ─── Adzuna ───────────────────────────────────────────────────────────────────
def test_adzuna_is_silent_without_keys(monkeypatch):
    monkeypatch.delenv("ADZUNA_APP_ID", raising=False)
    assert asyncio.run(ag.search_adzuna(["ai intern"], "London, UK")) == []


def test_adzuna_maps_results_and_dedupes(monkeypatch):
    monkeypatch.setenv("ADZUNA_APP_ID", "id")
    monkeypatch.setenv("ADZUNA_APP_KEY", "key")
    seen = []

    def adz(request):
        seen.append(dict(request.url.params))
        return httpx.Response(200, json={"results": [
            {"title": "<strong>AI</strong> Intern", "company": {"display_name": "Acme"}, "location": {"display_name": "London"},
             "redirect_url": "https://adzuna.co.uk/x/1", "created": "2026-11-18T10:00:00Z"},
            {"title": "No link", "company": {}, "redirect_url": ""}]})
    client = httpx.AsyncClient(transport=httpx.MockTransport(adz))
    out = asyncio.run(ag.search_adzuna(["ai intern", "ml intern"], "London, UK", "1w", client=client))
    assert len(out) == 1 and out[0]["title"] == "AI Intern" and out[0]["platform"] == "Adzuna" and out[0]["estimated"]
    assert seen[0]["where"] == "London" and seen[0]["max_days_old"] == "7" and seen[0]["what"] in ("ai intern", "ml intern")


# ─── wired into discovery ─────────────────────────────────────────────────────
def test_discovery_merges_board_jobs_and_dedupes_by_url(monkeypatch, tmp_path):
    sc = pytest.importorskip("applications_tracker.scheduled_job_scanner")
    sbi = importlib.import_module("services.board_index")

    async def fake_search(args):
        return {"jobs": [{"title": "Applied AI Intern", "company": "Acme", "url": "https://boards.greenhouse.io/acme/jobs/1",
                          "platform": "LinkedIn", "ats_score": 70}], "est_jobs": []}
    monkeypatch.setattr(sc, "handle_search_jobs", fake_search)
    board_jobs = [{"title": "Applied AI Intern", "company": "Acme", "url": "https://boards.greenhouse.io/acme/jobs/1", "platform": "Greenhouse"},
                  {"title": "ML Intern", "company": "Beta", "url": "https://jobs.lever.co/beta/9", "platform": "Lever"}]
    monkeypatch.setattr(sbi, "search", lambda f, loc, path=None: (board_jobs, {"boards": 500, "local_jobs": 900, "matched": 2}))
    monkeypatch.delenv("ADZUNA_APP_ID", raising=False)
    jobs, merged = asyncio.run(sc.discover_jobs(target_roles=["applied AI Intern"], location="London, UK", timeframe="1w", prefs={},
                                                title_filter=lambda t: True))
    urls = [j["url"] for j in jobs]
    assert urls.count("https://boards.greenhouse.io/acme/jobs/1") == 1 and "https://jobs.lever.co/beta/9" in urls
    off = asyncio.run(sc.discover_jobs(target_roles=["x"], location="London, UK", timeframe="1w", prefs={}, use_boards=False))[0]
    assert all("lever.co/beta" not in j["url"] for j in off)


def test_the_same_job_on_linkedin_and_a_company_board_is_saved_once_with_the_direct_link(monkeypatch, tmp_path):
    sc = pytest.importorskip("applications_tracker.scheduled_job_scanner")
    monkeypatch.setenv("JOB_FINDER_TRACKER_XLSX", str(tmp_path / "t.xlsx"))
    monkeypatch.setattr(sc, "load_profile_data", lambda: {"candidate": {}, "search_preferences": {"target_roles": ["AI Intern"], "target_locations": ["London, UK"], "timeframe": "1m"}})
    monkeypatch.setattr(sc, "get_existing_tracked_urls", lambda: set())

    async def fake_discover(**kw):
        mk = lambda t, c, u, src: {"title": t, "company": c, "url": u, "platform": src, "location": "London", "ats_score": 60, "description": "d" * 150}  # noqa: E731
        return [mk("ML Intern", "Epic Games", "https://uk.linkedin.com/jobs/view/111", "LinkedIn"),
                mk("ML Intern", "Epic Games", "https://boards.greenhouse.io/epicgames/jobs/9", "Greenhouse"),
                mk("AI Intern", "Beta", "https://beta.com/careers?gh_jid=77", "Greenhouse"),
                mk("AI Intern", "Beta", "https://uk.linkedin.com/jobs/view/222", "LinkedIn")], 0
    monkeypatch.setattr(sc, "discover_jobs", fake_discover)
    out = asyncio.run(sc.run_scan(enrich=False, dry_run=True))
    assert out["would_save"] == 2
    asyncio.run(sc.run_scan(enrich=False))
    from backend.services.excel_tracker import ExcelTracker
    urls = sorted(r["Job URL"] for r in ExcelTracker().rows())
    assert urls == ["https://beta.com/careers?gh_jid=77", "https://boards.greenhouse.io/epicgames/jobs/9"]   # direct links won, even on the employer's own domain
