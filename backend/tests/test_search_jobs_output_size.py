"""search_jobs must return a result small enough for MCP clients, however many jobs match."""
import asyncio
import json

from job_finder_mcp.tools import discovery_tools as dt


def _fake_search(n_jobs, desc_len=5000):
    jobs = [{"title": f"ML Intern {i}", "company": f"Co{i}", "location": "London", "url": f"https://x/{i}",
             "platform": "LinkedIn", "ats_score": 90 - i % 40, "full_description": "word " * (desc_len // 5)}
            for i in range(n_jobs)]

    async def gen(**kwargs):
        yield json.dumps({"type": "result", "jobs": jobs, "est_jobs": jobs[:60]}) + "\n"
    return gen


def _run(monkeypatch, n_jobs, **args):
    monkeypatch.setattr(dt, "find_matching_jobs", _fake_search(n_jobs))
    monkeypatch.setattr(dt, "load_profile_data", lambda: {})
    return asyncio.run(dt.handle_search_jobs({"keywords": "ml intern", "location": "London", **args}))


def test_default_result_is_compact(monkeypatch):
    res = _run(monkeypatch, 150)
    assert len(json.dumps(res)) < dt.MAX_PAYLOAD_CHARS
    assert res["count"] == 150 and res["returned"] == dt.DEFAULT_RESULT_LIMIT == len(res["jobs"])
    assert all(len(j["full_description"]) <= dt.MAX_TEXT_CHARS + 1 for j in res["jobs"])
    assert "Showing 25 of 150" in res["note"]


def test_limit_is_respected_and_clamped(monkeypatch):
    assert len(_run(monkeypatch, 150, limit=5)["jobs"]) == 5
    big = _run(monkeypatch, 300, limit=10_000)
    assert big["returned"] <= dt.MAX_RESULT_LIMIT
    assert len(json.dumps(big)) < dt.MAX_PAYLOAD_CHARS


def test_payload_cap_applies_even_with_large_limit(monkeypatch):
    res = _run(monkeypatch, 150, limit=100)
    assert len(json.dumps(res)) < dt.MAX_PAYLOAD_CHARS


def test_few_results_have_no_note(monkeypatch):
    res = _run(monkeypatch, 3)
    assert res["returned"] == 3 and "note" not in res
