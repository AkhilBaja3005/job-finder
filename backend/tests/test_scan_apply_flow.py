"""
Offline end-to-end tests of `scan` (discover -> Excel) and `apply` (Excel -> result written back).
Search, JD fetching and the browser agent are mocked: no network, no LLM, nothing is submitted.
"""

import argparse
import asyncio
import os
import sys
from datetime import date, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

sc = pytest.importorskip("applications_tracker.scheduled_job_scanner")
from backend.services.excel_tracker import ExcelTracker  # noqa: E402

PROFILE = {
    "candidate": {"name": "T", "location": "London, UK", "email": "", "core_skills": ["Python"], "work_experience": []},
    "search_preferences": {"target_roles": ["Applied AI Intern"], "target_locations": ["London, UK"],
                           "timeframe": "48h", "min_ats_score_threshold": 70},
}
FUTURE = date.today() + timedelta(days=20)


def _isolate_role_spec(monkeypatch, tmp_path, family=None):
    """role_spec is importable as `services.role_spec` (scanner) and `backend.services.role_spec`: isolate BOTH from the
    real cache file and from the real LLM."""
    import importlib
    for name in ("services.role_spec", "backend.services.role_spec"):
        mod = importlib.import_module(name)
        monkeypatch.setattr(mod, "_cache_path", lambda: str(tmp_path / "topic_terms.json"))
        monkeypatch.setattr(mod, "_llm_terms", family or (lambda topic: {}))


@pytest.fixture
def env(tmp_path, monkeypatch):
    _isolate_role_spec(monkeypatch, tmp_path)
    path = tmp_path / "tracker.xlsx"
    monkeypatch.setenv("JOB_FINDER_TRACKER_XLSX", str(path))
    monkeypatch.setattr(sc, "load_profile_data", lambda: PROFILE)
    monkeypatch.setattr(sc, "get_existing_tracked_urls", lambda: ExcelTracker().known_urls())
    return ExcelTracker(str(path))


def _fake_jobs():
    return [
        {"title": "Applied AI Intern", "company": "Acme", "location": "London", "url": "https://acme.io/jobs/1",
         "platform": "Greenhouse", "ats_score": 80, "description": f"x" * 120 + f"\nClosing date: {FUTURE.strftime('%d %B %Y')}"},
        {"title": "Applied AI Intern", "company": "Acme", "location": "London", "url": "https://acme.io/jobs/1/?utm=dup",
         "platform": "Greenhouse", "ats_score": 80, "description": "x" * 120},                      # duplicate URL
        {"title": "Registered Nurse", "company": "NHS", "location": "London", "url": "https://nhs.uk/1", "ats_score": 90},
        {"title": "Agentic AI Intern", "company": "Beta", "location": "London", "url": "https://beta.ai/j/2",
         "platform": "Lever", "ats_score": 55, "estimated": True, "description": ""},              # stub -> needs JD
        {"title": "Recent Applied AI Intern hiring discussions", "company": "Reddit / Hacker News Community",
         "url": "https://www.reddit.com/r/forhire/search/?q=x", "platform": "Reddit / Agent-Reach", "ats_score": 85},
        {"title": "Quantum Intern", "company": "Gamma", "location": "London", "url": "https://gamma.co/q",
         "platform": "Ashby", "ats_score": 40, "description": "y" * 150},
    ]


def _patch_discovery(monkeypatch, jobs):
    async def fake_discover(**kwargs):
        return [dict(j) for j in jobs], 0
    monkeypatch.setattr(sc, "discover_jobs", fake_discover)

    async def fake_fetch_live(job, candidate, timeout=30.0):
        job.update({"description": "z" * 200, "ats_score": 88, "score": 88, "skills_score": 85,
                    "exp_score": 90, "role_fit_score": 80, "matched_skills": ["python"], "missing_skills": ["rust"],
                    "estimated": False})
        return True
    monkeypatch.setattr(sc, "fetch_live_jd_and_score", fake_fetch_live)

    async def fake_cd(url, client, today=None):
        return FUTURE + timedelta(days=5) if "beta.ai" in url else None
    monkeypatch.setattr(sc.closing_date_utils, "fetch_closing_date", fake_cd)

    async def no_ai(job, candidate, level=None, **kw):      # AI scoring unavailable -> keyword fallback
        return False
    monkeypatch.setattr(sc.fit_scorer, "score_job", no_ai)


def test_scan_saves_deduped_scored_jobs_with_closing_dates(env, monkeypatch):
    _patch_discovery(monkeypatch, _fake_jobs())
    out = asyncio.run(sc.run_scan(enrich=True))
    rows = {r["Company"]: r for r in env.rows()}
    assert set(rows) == {"Acme", "Beta", "Gamma"}                       # nurse, duplicate and Reddit thread dropped
    assert out["added"] == 3 and out["duplicates"] == 1
    assert rows["Acme"]["Closing Date"].date() == FUTURE                  # from JD text
    assert rows["Beta"]["Closing Date"].date() == FUTURE + timedelta(days=5)   # from page metadata
    assert rows["Gamma"]["Closing Date"] is None
    assert rows["Beta"]["ATS %"] == 88 and rows["Beta"]["Matched Skills"] == "python"   # real JD scored
    assert all(r["Status"] == "New" and r["Applied"] == "No" for r in rows.values())
    assert [r["Company"] for r in env.rows()] == ["Beta", "Acme", "Gamma"]  # best ATS first -> IDs 1..3
    assert {r["Scored By"] for r in rows.values()} == {"Keyword"}           # AI mocked as unavailable
    assert "keyword engine" in rows["Acme"]["Notes"]


def test_scan_twice_adds_nothing_new(env, monkeypatch):
    _patch_discovery(monkeypatch, _fake_jobs())
    asyncio.run(sc.run_scan(enrich=True))
    out = asyncio.run(sc.run_scan(enrich=True))
    assert out["added"] == 0 and len(env.rows()) == 3


def test_scan_min_ats_and_limit(env, monkeypatch):
    _patch_discovery(monkeypatch, _fake_jobs())
    asyncio.run(sc.run_scan(enrich=True, min_ats=60, limit=1))
    assert [r["Company"] for r in env.rows()] == ["Beta"]               # 88 beats Acme 80; Gamma 40 filtered


def test_scan_without_enrichment_marks_estimates(env, monkeypatch):
    _patch_discovery(monkeypatch, _fake_jobs())
    asyncio.run(sc.run_scan(enrich=False))
    beta = next(r for r in env.rows() if r["Company"] == "Beta")
    assert beta["ATS %"] == 55 and "estimate" in beta["Notes"].lower()
    assert beta["Scored By"] == "Listing estimate"


# ─── apply (works ONLY from the approved queue) ──────────────────────────────
from backend.services.approval import approve_jobs  # noqa: E402
from backend.services.excel_tracker import approved_path  # noqa: E402


def _seed(env):
    """Scanned: ids 1-5. Approved: 1, 2, 3, 4 (3 later expires). Row 5 is scanned but never approved."""
    future = (date.today() + timedelta(days=3)).isoformat()
    mk = lambda n, ats, **kw: {"Company": f"Co{n}", "Job Role": f"Intern {n}", "Location": "London",   # noqa: E731
                               "ATS %": ats, "Job URL": f"https://co{n}.io/j", "Status": "New", **kw}
    env.add_jobs([mk(1, 90), mk(2, 60), mk(3, 85, **{"Closing Date": future}), mk(4, 95), mk(5, 99)])
    queue = ExcelTracker(approved_path(env.path))
    approve_jobs(env, queue, ids=[1, 2, 3, 4])
    queue.update(row_id=3, closing_date=(date.today() - timedelta(days=1)).isoformat())   # expires after approval
    return queue


def _apply_args(**kw):
    base = dict(target=None, ids=None, min_ats=None, limit=0, company=None, submit=False, yes=True, dry_run=False,
                retry=False, no_pack=True, resume=None, model=None, headless=True, max_steps=5, timeout=10)
    base.update(kw)
    return argparse.Namespace(**base)


@pytest.fixture
def agent(monkeypatch, tmp_path):
    """Mock the browser agent; `results` maps URL -> result dict. Records which URLs were opened."""
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4 test")
    from backend.job_finder_mcp.tools import profile_tools
    monkeypatch.setattr(profile_tools, "load_profile_data", lambda: PROFILE)
    monkeypatch.setattr(sc, "find_master_resume_with_mac_tags", lambda: str(resume))
    monkeypatch.setattr(sc, "notify_user_of_applied_applications", lambda *a, **k: True)
    monkeypatch.setattr(sc, "notify_user_of_failed_applications", lambda *a, **k: True)
    state = {"opened": [], "results": {}, "submit_flags": []}

    async def fake_autofill(job_url, **kw):
        state["opened"].append(job_url)
        state.setdefault("calls", []).append({"url": job_url, **kw})
        state["submit_flags"].append(kw.get("auto_submit"))
        return state["results"].get(job_url, {"status": "success", "auto_submit": kw.get("auto_submit"), "final_result": "ok"})
    monkeypatch.setattr(sc, "run_browser_use_autofill", fake_autofill)
    return state


def test_apply_with_nothing_approved_opens_nothing_even_if_jobs_were_scanned(env, agent):
    from job_finder.commands import apply as apply_cmd
    env.add_jobs([{"Company": "Co", "Job Role": "Intern", "Location": "L", "ATS %": 99, "Job URL": "https://co.io/j", "Status": "New"}])
    apply_cmd.run(_apply_args(submit=True))
    apply_cmd.run(_apply_args(min_ats=0))
    assert agent["opened"] == []


def test_apply_preview_uses_only_the_approved_queue_and_never_marks_applied(env, agent):
    from job_finder.commands import apply as apply_cmd
    queue = _seed(env)
    agent["results"] = {u: {"status": "preview_ready", "auto_submit": False, "final_result": "form filled"}
                        for u in ("https://co1.io/j", "https://co2.io/j", "https://co4.io/j")}
    apply_cmd.run(_apply_args())
    assert agent["opened"] == ["https://co4.io/j", "https://co1.io/j", "https://co2.io/j"]   # best ATS first; 3 expired; 5 never approved
    assert agent["submit_flags"] == [False, False, False]
    q = {r["ID"]: r for r in queue.rows()}
    assert q[1]["Applied"] == "No" and q[1]["Status"] == "Approved" and "Previewed" in q[1]["Notes"]
    assert {r["ID"]: r["Status"] for r in env.rows()}[5] == "New"                          # untouched in scanned


def test_apply_submit_updates_both_workbooks_and_keeps_old_notes(env, agent):
    from job_finder.commands import apply as apply_cmd
    queue = _seed(env)
    env.update(row_id=1, notes="ATS is an estimate")
    agent["results"] = {
        "https://co4.io/j": {"status": "success", "auto_submit": True, "final_result": "SUBMISSION_CONFIRMED"},
        "https://co1.io/j": {"status": "needs_review", "auto_submit": True, "blocker": "captcha", "final_result": "stuck"},
    }
    apply_cmd.run(_apply_args(submit=True, min_ats=70))                    # --min-ats still narrows the queue if you ask
    for book in (queue, env):
        rows = {r["ID"]: r for r in book.rows()}
        assert rows[4]["Status"] == "Applied" and rows[4]["Applied"] == "Yes" and rows[4]["Date Applied"] is not None
        assert rows[1]["Status"] == "Needs Review" and "captcha" in rows[1]["Notes"] and rows[1]["Applied"] == "No"
        assert rows[2]["Status"] == ("Approved" if book is queue else "Approved")   # 60% < --min-ats 70: left in the queue
    assert "ATS is an estimate" in {r["ID"]: r for r in env.rows()}[1]["Notes"]       # appended, not overwritten
    assert {r["ID"]: r["Status"] for r in queue.rows()}[3] == "Closed"                # expired while waiting
    # re-run: applied row not repeated; Needs Review only comes back with --retry
    agent["opened"].clear()
    apply_cmd.run(_apply_args(submit=True))
    assert "https://co4.io/j" not in agent["opened"] and "https://co1.io/j" not in agent["opened"]
    agent["opened"].clear()
    apply_cmd.run(_apply_args(submit=True, retry=True))
    assert "https://co1.io/j" in agent["opened"]


def test_apply_ids_limit_and_closed_posting(env, agent):
    from job_finder.commands import apply as apply_cmd
    queue = _seed(env)
    agent["results"] = {"https://co2.io/j": {"status": "failed", "final_result": "Job unavailable: posting removed"}}
    apply_cmd.run(_apply_args(ids="2", submit=True))
    assert agent["opened"] == ["https://co2.io/j"]
    assert {r["ID"]: r["Status"] for r in queue.rows()}[2] == "Closed"
    assert {r["ID"]: r["Status"] for r in env.rows()}[2] == "Closed"
    agent["opened"].clear()
    apply_cmd.run(_apply_args(limit=1))
    assert len(agent["opened"]) == 1
    agent["opened"].clear()
    apply_cmd.run(_apply_args(ids="5"))                                     # scanned but not approved: not in the queue
    assert agent["opened"] == []


def test_apply_url_mode_skips_applied_and_records_unknown_urls(env, agent):
    from job_finder.commands import apply as apply_cmd
    queue = _seed(env)
    env.update(row_id=1, status="Applied")
    apply_cmd.run(_apply_args(target="https://co1.io/j", submit=True))
    assert agent["opened"] == []                                          # already applied -> skipped
    apply_cmd.run(_apply_args(target="https://newco.io/jobs/9", submit=True))
    new = [r for r in queue.rows() if "newco.io" in str(r["Job URL"])][0]
    assert new["Status"] == "Applied" and new["Applied"] == "Yes"


# ─── scan with a topic / level ────────────────────────────────────────────────
def test_scan_topic_and_level_filters_titles_and_sets_queries(env, monkeypatch, tmp_path):
    _isolate_role_spec(monkeypatch, tmp_path, lambda topic: {"include": ["agentic", "llm"], "exclude": [], "search": []}
                       if "agentic" in topic.lower() else {})
    seen = {}

    async def fake_discover(**kwargs):
        seen.update(kwargs)
        mk = lambda t, u: {"title": t, "company": "C" + u, "location": "London", "url": f"https://c.io/{u}",   # noqa: E731
                           "platform": "Greenhouse", "ats_score": 70, "description": "d" * 150}
        return [mk("Agentic AI Intern", "1"), mk("Quantum Computing Internship", "2"),
                mk("Agentic AI Engineer", "3"), mk("Tax Technology Intern", "4")], 0
    monkeypatch.setattr(sc, "discover_jobs", fake_discover)
    asyncio.run(sc.run_scan(request="agentic AI internships", enrich=False))
    assert seen["target_roles"] == ["agentic AI Intern", "agentic AI Internship"]
    assert [r["Job Role"] for r in env.rows()] == ["Agentic AI Intern"]


def test_scan_uses_profile_topic_and_level_when_nothing_typed(env, monkeypatch):
    prefs = dict(PROFILE["search_preferences"], topics=["robotics"], level="graduate")
    monkeypatch.setattr(sc, "load_profile_data", lambda: {**PROFILE, "search_preferences": prefs})

    async def fake_discover(**kwargs):
        mk = lambda t, u: {"title": t, "company": "C" + u, "location": "London", "url": f"https://c.io/{u}",   # noqa: E731
                           "platform": "Lever", "ats_score": 70, "description": "d" * 150}
        return [mk("Robotics Graduate Engineer", "1"), mk("Robotics Intern", "2"), mk("Graduate Accountant", "3")], 0
    monkeypatch.setattr(sc, "discover_jobs", fake_discover)
    asyncio.run(sc.run_scan(enrich=False))
    assert [r["Job Role"] for r in env.rows()] == ["Robotics Graduate Engineer"]


def test_scan_ai_scores_override_keyword_scores_and_record_the_reasoning(env, monkeypatch):
    _patch_discovery(monkeypatch, _fake_jobs())

    async def fake_ai(job, candidate, level=None, **kw):
        if job["company"] == "Gamma":                          # fails a hard requirement
            job.update(ats_score=0, score=0, scoring="AI", knockout="Requires US citizenship", fit_summary="Not eligible.",
                       matched_skills=[], missing_skills=[], estimated=False)
            return True
        job.update(ats_score=91, score=91, skills_score=90, exp_score=88, role_fit_score=95, scoring="AI",
                   fit_summary="Strong agent background. Gaps: PyTorch.", matched_skills=["LLM agents"],
                   missing_skills=["PyTorch"], estimated=False,
                   llm_closing_date=(FUTURE + timedelta(days=9)).isoformat() if job["company"] == "Beta" else None)
        return True
    monkeypatch.setattr(sc.fit_scorer, "score_job", fake_ai)
    out = asyncio.run(sc.run_scan(enrich=True))
    rows = {r["Company"]: r for r in env.rows()}
    assert rows["Acme"]["ATS %"] == 91 and rows["Acme"]["Scored By"] == "AI"
    assert rows["Acme"]["Fit Summary"].endswith("Gaps: PyTorch.") and rows["Acme"]["Missing Skills"] == "PyTorch"
    assert rows["Acme"]["Skills %"] == 90 and rows["Acme"]["Role Fit %"] == 95
    assert rows["Gamma"]["Status"] == "Skipped" and "US citizenship" in rows["Gamma"]["Notes"] and rows["Gamma"]["ATS %"] == 0
    # closing-date precedence: text in the JD > AI-extracted (quoted) > page metadata
    assert rows["Acme"]["Closing Date"].date() == FUTURE
    assert rows["Beta"]["Closing Date"].date() == FUTURE + timedelta(days=9)
    # a knocked-out job is never picked up by `apply`
    assert all(r["Company"] != "Gamma" for r in env.pending())


def test_no_ai_flag_path_never_calls_the_llm(env, monkeypatch):
    _patch_discovery(monkeypatch, _fake_jobs())

    async def boom(*a, **k):
        raise AssertionError("AI scorer must not run with ai_score=False")
    monkeypatch.setattr(sc.fit_scorer, "score_job", boom)
    asyncio.run(sc.run_scan(enrich=True, ai_score=False))
    assert {r["Scored By"] for r in env.rows()} == {"Keyword"}


def test_a_job_you_applied_to_by_hand_is_never_applied_to_again(env, agent):
    """You apply manually and mark it Applied in the scanned file; the approved queue must not re-apply."""
    from job_finder.commands import apply as apply_cmd
    queue = _seed(env)
    env.update(row_id=1, status="Applied")            # done by hand, scanned file only
    env.update(row_id=2, status="Skipped")            # changed your mind in Excel
    apply_cmd.run(_apply_args(submit=True))
    assert agent["opened"] == ["https://co4.io/j"]
    q = {r["ID"]: r["Status"] for r in queue.rows()}
    assert q[1] == "Applied" and q[2] == "Skipped"     # queue synced from the scanned file


def test_apply_refuses_to_start_without_a_real_resume_file(env, agent, monkeypatch):
    from job_finder.commands import apply as apply_cmd
    _seed(env)
    monkeypatch.setattr(sc, "find_master_resume_with_mac_tags", lambda: "/nonexistent/resume.pdf")
    with pytest.raises(SystemExit) as e:
        apply_cmd.run(_apply_args(submit=True))
    assert e.value.code == 1 and agent["opened"] == []


def test_scan_finds_the_whole_field_and_drops_look_alikes(env, monkeypatch, tmp_path):
    """'cyber security' must bring in software / AI / LLM / system security, and drop 'security guard'."""
    _isolate_role_spec(monkeypatch, tmp_path, lambda topic: {
        "include": ["security", "cyber", "software security", "ai security", "llm security", "system security", "pentest"],
        "exclude": ["security guard", "social security"], "search": ["application security", "ai security"]})
    seen = {}

    async def fake_discover(**kwargs):
        seen.update(kwargs)
        titles = ["Software Security Intern", "AI Security Research Intern", "LLM Security Intern", "System Security Intern",
                  "Cyber Security Intern", "Security Guard Intern", "Social Security Intern", "Marketing Intern"]
        return [{"title": t, "company": f"C{i}", "location": "London", "url": f"https://c.io/{i}", "platform": "Lever",
                 "ats_score": 70, "description": "d" * 150} for i, t in enumerate(titles)], 0
    monkeypatch.setattr(sc, "discover_jobs", fake_discover)
    asyncio.run(sc.run_scan(request="cyber security internships", enrich=False, expand=0))
    kept = sorted(r["Job Role"] for r in env.rows())
    assert kept == ["AI Security Research Intern", "Cyber Security Intern", "LLM Security Intern",
                    "Software Security Intern", "System Security Intern"]
    assert "application security Intern" in seen["target_roles"]          # sub-fields are searched, not only filtered


# ─── search-only dry run + skip-portals ───────────────────────────────────────
def test_dry_run_prints_the_whole_funnel_and_writes_nothing(env, monkeypatch, capsys):
    async def fake_discover(**kwargs):
        mk = lambda t, u, src: {"title": t, "company": "C" + u, "location": "London", "url": f"https://c.io/{u}",   # noqa: E731
                                "platform": src, "ats_score": 70, "description": "d" * 150}
        return [mk("Applied AI Intern", "1", "LinkedIn"), mk("Senior AI Engineer", "2", "Jobserve"),
                mk("AI Engineer", "3", "Jobserve"), mk("Marketing Intern", "4", "LinkedIn"),
                mk("Applied AI Intern", "1", "LinkedIn")], 0
    monkeypatch.setattr(sc, "discover_jobs", fake_discover)

    async def boom(*a, **k):
        raise AssertionError("a dry run must not fetch descriptions or call the scorer")
    monkeypatch.setattr(sc.fit_scorer, "score_job", boom)
    monkeypatch.setattr(sc, "fetch_live_jd_and_score", boom)
    out = asyncio.run(sc.run_scan(request="applied AI internships", dry_run=True))
    text = capsys.readouterr().out
    assert not os.path.exists(env.path)                                   # nothing written
    assert out["would_save"] == 1 and out["added"] == 0
    assert "SEARCH-ONLY DRY RUN" in text and "DISCOVERED 5 postings" in text
    assert "Jobserve" in text and "LinkedIn" in text                      # per-source counts
    assert "senior title" in text and "title has no intern keyword" in text and "off topic" in text
    assert "x Senior AI Engineer" in text and "x Marketing Intern" in text   # every dropped title is listed
    assert "same job seen twice" in text                                   # in-scan duplicate shown as a drop


def test_skip_portals_none_really_skips_nothing(monkeypatch):
    seen = []

    async def fake_search(args):
        seen.append(args.get("exclude_portals"))
        return {"jobs": [], "est_jobs": []}
    monkeypatch.setattr(sc, "handle_search_jobs", fake_search)
    run = lambda **kw: asyncio.run(sc.discover_jobs(target_roles=["x"], location="L", timeframe="1w", **kw))  # noqa: E731
    run(prefs={}, skip_portals="none")
    run(prefs={"skip_portals": []})
    run(prefs={})
    run(prefs={"skip_portals": ["indeed"]})
    assert seen == [[], [], ["targetjobs"], ["indeed"]]                    # explicit "none" -> []; default still skips TargetJobs
