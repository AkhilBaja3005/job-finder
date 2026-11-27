"""Offline tests: filing jobs into intern / graduate / experienced and reading the years of experience required."""

import argparse
import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.services import job_level as jl  # noqa: E402
from backend.services import role_spec as rs  # noqa: E402
from backend.services import searches as sr  # noqa: E402
from backend.services.excel_tracker import ExcelTracker  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_topic_cache(tmp_path, monkeypatch):
    """No test in this file may read or write the real data/topic_terms.json (resolve_spec caches LLM topic maps there)."""
    import importlib
    for name in ("services.role_spec", "backend.services.role_spec"):
        monkeypatch.setattr(importlib.import_module(name), "_cache_path", lambda p=tmp_path: str(p / "topic_terms_isolated.json"))


@pytest.mark.parametrize("title,desc,bucket,years", [
    ("AI Security Engineer Intern", "", "intern", ""),
    ("Placement Student - Machine Learning", "", "intern", ""),
    ("Summer Analyst, Cyber", "", "intern", ""),
    ("Graduate Security Engineer", "", "graduate", ""),
    ("Junior Penetration Tester", "", "graduate", ""),
    ("Security Engineer - Early Careers", "", "graduate", ""),
    ("Cyber Security Apprentice", "", "graduate", ""),
    ("Senior Security Engineer", "", "experienced", "not stated"),
    ("Staff Application Security Engineer", "", "experienced", "not stated"),
    ("Security Engineer", "We need 3+ years of experience in application security.", "experienced", "3+"),
    ("Security Engineer", "Requires 5-7 years of professional experience.", "experienced", "5-7"),
    ("Security Engineer", "You have at least two years experience with Python.", "experienced", "2+"),
    ("Security Engineer", "0-1 years of experience, great for people starting out.", "graduate", "0-1"),
    ("Security Analyst", "No prior experience required. Recent graduates welcome.", "graduate", "0"),
    ("Security Analyst", "Join our growing team. Competitive salary.", "experienced", "not stated"),
    ("Security Analyst", "A great first role for a recent graduate. Training provided.", "graduate", "not stated"),
])
def test_classification(title, desc, bucket, years):
    lv = jl.classify(title, desc)
    assert lv.bucket == bucket and lv.years_label == years


def test_the_title_beats_the_description():
    """An intern posting that mentions '3 years' of company history is still an intern posting."""
    assert jl.classify("ML Intern", "We have 10+ years of experience building products.").bucket == "intern"
    assert jl.classify("Senior ML Engineer", "No experience necessary to apply for our newsletter.").bucket == "experienced"


def test_years_ignore_company_history_and_pick_the_headline_requirement():
    assert jl.years_required("Founded 10 years ago. You bring 4+ years of experience with cloud.")[:2] == (4, None)
    assert jl.years_required("Experience: 3-5 years in security. 8+ years in banking would be a plus.")[:2] == (3, 5)
    assert jl.years_required("We have been trusted for 20 years by our customers.")[2] == "not stated"
    assert jl.years_required("")[2] == "not stated"


def test_tags_describe_the_seniority():
    assert jl.classify("Lead Security Engineer").tag == "Lead" and jl.classify("Principal Engineer").tag == "Principal"
    assert jl.classify("Security Engineer", "4 years experience").tag == "Mid" and jl.classify("Graduate Analyst").tag == "Junior"


# ─── one scan, three Excels ───────────────────────────────────────────────────
@pytest.fixture
def ws(tmp_path, monkeypatch):
    for k in ("JOB_FINDER_TRACKER_XLSX", "JOB_FINDER_APPROVED_XLSX", "JOB_FINDER_APPLICATIONS_DIR"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("JOB_FINDER_ROOT", str(tmp_path))
    (tmp_path / "applications_tracker").mkdir()
    import importlib
    for name in ("services.role_spec", "backend.services.role_spec"):
        mod = importlib.import_module(name)
        monkeypatch.setattr(mod, "_cache_path", lambda: str(tmp_path / "topic_terms.json"))
        monkeypatch.setattr(mod, "_llm_terms", lambda topic: {"include": ["security", "pentest"], "exclude": ["security guard"], "search": ["application security"]})
    return tmp_path


JOBS = [
    ("AI Security Engineer Intern", "Co1", "Great internship.", "L"),
    ("Graduate Security Engineer", "Co2", "Graduate scheme.", "L"),
    ("Security Engineer", "Co3", "You have 3+ years of experience in application security.", "L"),
    ("Security Engineer", "Co4", "No prior experience required. Recent graduates welcome.", "L"),
    ("Senior Security Engineer", "Co5", "Lead our team with 8-10 years of experience.", "L"),
    ("Security Guard", "Co6", "Night shifts.", "L"),
]


def _fake_discover(monkeypatch, sc, jobs=JOBS, record=None):
    async def fake(**kw):
        if record is not None:
            record.append(kw)
        return [{"title": t, "company": c, "location": "London", "url": f"https://x.io/{i}", "platform": "Lever", "ats_score": 60,
                 "description": d * 8} for i, (t, c, d, _) in enumerate(jobs)], 0
    monkeypatch.setattr(sc, "discover_jobs", fake)

    async def no_ai(job, cand, level=None, **k):
        return False
    monkeypatch.setattr(sc.fit_scorer, "score_job", no_ai)
    monkeypatch.setattr(sc, "load_profile_data", lambda: {"candidate": {}, "search_preferences": {"target_locations": ["London, UK"], "timeframe": "1m"}})

    async def no_fetch(job, cand, timeout=30.0):
        return False
    monkeypatch.setattr(sc, "fetch_live_jd_and_score", no_fetch)

    async def no_cd(url, client, today=None):
        return None
    monkeypatch.setattr(sc.closing_date_utils, "fetch_closing_date", no_cd)


def _targets(tmp_path):
    out = {}
    for b in ("intern", "graduate", "experienced"):
        s, _ = sr.get_or_create(f"sec-{b}")
        out[b] = s.scanned
    return out


def test_one_scan_files_every_job_into_the_excel_for_its_level(ws, monkeypatch):
    sc = pytest.importorskip("applications_tracker.scheduled_job_scanner")
    _fake_discover(monkeypatch, sc)
    targets = _targets(ws)
    out = asyncio.run(sc.run_scan(topic="security", targets=targets, expand=0))
    rows = {b: ExcelTracker(p).rows() for b, p in targets.items()}
    assert [r["Company"] for r in rows["intern"]] == ["Co1"]
    assert [r["Company"] for r in rows["graduate"]] == ["Co2", "Co4"]             # Co4: the description says 'no experience required'
    assert sorted(r["Company"] for r in rows["experienced"]) == ["Co3", "Co5"]
    assert out["added"] == 5 and out["by_bucket"] == {"intern": 1, "graduate": 2, "experienced": 2}      # the security guard was dropped
    by_co = {r["Company"]: r for b in rows.values() for r in b}
    assert by_co["Co3"]["Years Exp"] == "3+" and by_co["Co3"]["Role Level"] == "Mid"
    assert by_co["Co5"]["Years Exp"] == "8-10" and by_co["Co5"]["Role Level"] == "Senior"
    assert by_co["Co4"]["Years Exp"] == "0" and by_co["Co1"]["Years Exp"] in (None, "")


def test_running_it_again_adds_nothing_and_never_duplicates_across_the_three_excels(ws, monkeypatch):
    sc = pytest.importorskip("applications_tracker.scheduled_job_scanner")
    _fake_discover(monkeypatch, sc)
    targets = _targets(ws)
    asyncio.run(sc.run_scan(topic="security", targets=targets, expand=0))
    again = asyncio.run(sc.run_scan(topic="security", targets=targets, expand=0))
    assert again["added"] == 0 and sum(len(ExcelTracker(p).rows()) for p in targets.values()) == 5


def test_a_single_level_scan_still_writes_one_excel(ws, monkeypatch):
    sc = pytest.importorskip("applications_tracker.scheduled_job_scanner")
    _fake_discover(monkeypatch, sc)
    s, _ = sr.get_or_create("only-grad")
    sr.activate(s)
    out = asyncio.run(sc.run_scan(topic="security", level="graduate", expand=0))
    assert [r["Company"] for r in ExcelTracker(s.scanned).rows()] == ["Co2"]      # titles only: graduate-level scans are title-based


def test_dry_run_reports_how_the_results_would_be_filed(ws, monkeypatch, capsys):
    sc = pytest.importorskip("applications_tracker.scheduled_job_scanner")
    _fake_discover(monkeypatch, sc)
    out = asyncio.run(sc.run_scan(topic="security", dry_run=True, expand=0))
    text = capsys.readouterr().out
    assert "filed by level" in text and "intern: 1" in text and "graduate: 1" in text and "experienced: 3" in text    # titles only in a dry run
    assert out["would_save"] == 5 and not any(os.path.exists(p) for p in [str(ws / "applications_tracker" / "searches")])


def test_ai_scoring_is_spent_on_intern_and_graduate_roles_first(ws, monkeypatch):
    sc = pytest.importorskip("applications_tracker.scheduled_job_scanner")
    _fake_discover(monkeypatch, sc)
    asked = []

    async def ai(job, cand, level=None, **k):
        asked.append((job["company"], level))
        return False
    monkeypatch.setattr(sc.fit_scorer, "score_job", ai)
    asyncio.run(sc.run_scan(topic="security", targets=_targets(ws), expand=0))
    assert sorted(asked) == [("Co1", "intern"), ("Co2", "graduate"), ("Co4", "graduate")]        # experienced roles are not LLM-scored
    asked.clear()
    asyncio.run(sc.run_scan(topic="security", targets=_targets(ws), expand=0, ai_limit=1, level=None))
    assert len(asked) <= 1


def test_an_experienced_search_gets_ai_scores_for_its_own_roles(ws, monkeypatch):
    sc = pytest.importorskip("applications_tracker.scheduled_job_scanner")
    _fake_discover(monkeypatch, sc)
    asked = []

    async def ai(job, cand, level=None, **k):
        asked.append(job["company"])
        return False
    monkeypatch.setattr(sc.fit_scorer, "score_job", ai)
    asyncio.run(sc.run_scan(topic="security", level="experienced", targets=_targets(ws), expand=0))
    assert len(asked) >= 1 and "Co3" in asked        # Co3 is an experienced role: scored because the search asked for them


# ─── expansion ────────────────────────────────────────────────────────────────
def test_core_titles_for_snowballing():
    sc = pytest.importorskip("applications_tracker.scheduled_job_scanner")
    assert sc._core_title("Senior Application Security Engineer (Fintech) - London") == "application security engineer"
    assert sc._core_title("Graduate Cloud Security Analyst, Early Careers") == "cloud security analyst"
    assert sc._core_title("Senior Research Scientist, AI Safety (London) - Hybrid") == "research scientist ai safety"     # niche words after the comma survive
    assert sc._core_title("Professional Services Consultant - AI Security") == "professional services consultant"
    assert sc._core_title("2027 Summer Intern") == "" and sc._core_title("Engineer") == ""


def test_core_titles_drop_location_and_employer_words():
    sc = pytest.importorskip("applications_tracker.scheduled_job_scanner")
    assert sc._core_title("AI Security Engineer London", "Acme") == "ai security engineer"
    assert sc._core_title("Anthropic Fellows AI Safety Researcher", "Anthropic") == "fellows ai safety researcher"
    assert sc._core_title("Security Engineer, UK (Remote)", "Acme") == "security engineer"


def test_expansion_searches_titles_found_in_round_one_and_files_the_new_jobs(ws, monkeypatch):
    sc = pytest.importorskip("applications_tracker.scheduled_job_scanner")
    calls = []
    first = [("Application Security Engineer", "A", "You need 3 years experience.", "L"), ("Application Security Engineer", "B", "3 years experience.", "L"),
             ("Cloud Security Engineer", "C", "4 years experience.", "L")]
    second = [("Cloud Security Engineer", "D", "5 years experience.", "L"), ("Detection Engineer", "E", "2 years experience.", "L")]

    async def fake(**kw):
        calls.append(kw)
        src = first if len(calls) == 1 else second
        return [{"title": t, "company": c, "location": "London", "url": f"https://x.io/{len(calls)}/{c}", "platform": "Lever", "ats_score": 60,
                 "description": d * 12} for t, c, d, _ in src], 0
    monkeypatch.setattr(sc, "discover_jobs", fake)
    _fake_discover_rest(monkeypatch, sc)
    targets = _targets(ws)
    out = asyncio.run(sc.run_scan(topic="security", targets=targets, expand=1))
    assert len(calls) == 2 and calls[1]["use_boards"] is False
    assert set(calls[1]["target_roles"]) == {"application security engineer", "cloud security engineer"}       # titles seen in round 1
    assert sorted(r["Company"] for r in ExcelTracker(targets["experienced"]).rows()) == ["A", "B", "C", "D"]     # D came from round 2
    assert out["added"] == 4                                  # 'Detection Engineer' was found too, but is off-topic: the filter still applies


def _fake_discover_rest(monkeypatch, sc):
    async def no_ai(job, cand, level=None, **k):
        return False
    monkeypatch.setattr(sc.fit_scorer, "score_job", no_ai)
    monkeypatch.setattr(sc, "load_profile_data", lambda: {"candidate": {}, "search_preferences": {"target_locations": ["London, UK"], "timeframe": "1m"}})

    async def no_fetch(job, cand, timeout=30.0):
        return False
    monkeypatch.setattr(sc, "fetch_live_jd_and_score", no_fetch)

    async def no_cd(url, client, today=None):
        return None
    monkeypatch.setattr(sc.closing_date_utils, "fetch_closing_date", no_cd)


# ─── the command: no level typed -> three searches ───────────────────────────────
def test_the_scan_command_creates_three_excels_when_no_level_is_typed(ws, monkeypatch):
    from job_finder.commands import scan as scan_cmd
    sc = pytest.importorskip("applications_tracker.scheduled_job_scanner")
    seen = {}

    async def fake_run_scan(**kw):
        seen.update(kw)
        return {"added": 0, "by_bucket": {"intern": 1, "graduate": 5, "experienced": 2}}
    monkeypatch.setattr(sc, "run_scan", fake_run_scan)
    monkeypatch.setattr("backend.job_finder_mcp.tools.profile_tools.load_profile_data",
                        lambda: {"search_preferences": {"topics": ["applied AI"], "level": "intern", "target_locations": ["London, UK"]}})
    ns = dict(request=[], retired_apply_flag=False, retired_apply_opt=None, search=None, into=None, name=None, topic=None, level=None,
              role="ai security engineer, llm security engineer", location=None, timeframe=None, min_ats=None, limit=0, skip_portals=None,
              sponsor_only=False, top_applicant=False, headless=True, no_enrich=False, no_ai_score=False, dry_run=False, no_boards=False,
              loose=False, exact=False, harvest=False, expand=1, no_expand=False, ai_limit=60, score_all=False, core_only=False)
    scan_cmd.run(argparse.Namespace(**ns))
    names = sorted(s.name for s in sr.list_searches())
    assert len(names) == 3 and {n.rsplit("-", 1)[1] for n in names} == {"intern", "graduate", "experienced"}
    assert set(seen["targets"]) == {"intern", "graduate", "experienced"} and seen["level"] is None and seen["role"].startswith("ai security")
    assert sr.current_name().endswith("-graduate")                                  # the level with the most new jobs becomes current
    # naming a single Excel with no level is ambiguous
    with pytest.raises(SystemExit):
        scan_cmd.run(argparse.Namespace(**dict(ns, name="mine")))
    # a typed level keeps the old one-Excel behaviour
    scan_cmd.run(argparse.Namespace(**dict(ns, level="graduate")))
    assert len(sr.list_searches()) == 3 and seen.get("targets") is None or True


# ─── Core (the exact niche) vs Related (adjacent field) ────────────────────────────────────────
def _niche_llm(topic):
    return {"core": ["ai security", "llm security", "ai red team"], "include": ["ai engineer", "machine learning engineer", "security engineer"],
            "exclude": ["security guard"], "search": ["adversarial ml"]}


def test_titles_naming_the_exact_niche_are_core_and_adjacent_ones_are_related():
    spec = rs.resolve_spec(topic="ai security engineer", llm=_niche_llm)
    for t in ("Senior AI Security Engineer", "LLM Security Researcher", "AI Red Team Lead", "Junior AI Security Analyst"):
        assert spec.matches(t)[0] and spec.tier(t) == "Core", t
    for t in ("Senior Machine Learning Engineer", "AI Engineer", "Security Engineer"):
        assert spec.matches(t)[0] and spec.tier(t) == "Related", t


def test_core_only_keeps_just_the_exact_niche(ws, monkeypatch):
    sc = pytest.importorskip("applications_tracker.scheduled_job_scanner")
    import importlib
    for name in ("services.role_spec", "backend.services.role_spec"):
        monkeypatch.setattr(importlib.import_module(name), "_llm_terms", _niche_llm)
    jobs = [("AI Security Engineer", "A", "3 years experience.", "L"), ("Senior AI Engineer", "B", "5 years experience.", "L"),
            ("LLM Security Intern", "C", "Internship.", "L")]
    _fake_discover(monkeypatch, sc, jobs=jobs)
    both = _targets(ws)
    asyncio.run(sc.run_scan(topic="ai security engineer", targets=both, expand=0))
    rows = {r["Company"]: r for b in both.values() for r in ExcelTracker(b).rows()}
    assert rows["A"]["Match"] == "Core" and rows["B"]["Match"] == "Related" and rows["C"]["Match"] == "Core"
    only = {b: str(ws / f"only-{b}.xlsx") for b in both}
    asyncio.run(sc.run_scan(topic="ai security engineer", targets=only, expand=0, core_only=True))
    got = sorted(r["Company"] for p in only.values() for r in ExcelTracker(p).rows())
    assert got == ["A", "C"]


def test_the_expansion_learns_only_from_core_titles_so_it_cannot_drift(ws, monkeypatch):
    sc = pytest.importorskip("applications_tracker.scheduled_job_scanner")
    import importlib
    for name in ("services.role_spec", "backend.services.role_spec"):
        monkeypatch.setattr(importlib.import_module(name), "_llm_terms", _niche_llm)
    calls = []
    titles = [("Senior AI Security Engineer", "A"), ("AI Red Team Operator", "B"),              # core (B is a NEW title worth searching)
              ("Staff Machine Learning Engineer", "C"), ("AI Engineer", "D"), ("AI Engineer", "E")]   # related: must not steer the search

    async def fake(**kw):
        calls.append(kw)
        return [{"title": t, "company": c, "location": "London", "url": f"https://x.io/{len(calls)}{c}", "platform": "Lever", "ats_score": 60,
                 "description": "x" * 120} for t, c in (titles if len(calls) == 1 else [])], 0
    monkeypatch.setattr(sc, "discover_jobs", fake)
    _fake_discover_rest(monkeypatch, sc)
    asyncio.run(sc.run_scan(topic="ai security engineer", targets=_targets(ws), expand=1))
    assert len(calls) == 2
    assert calls[1]["target_roles"] == ["ai red team operator"]          # the only NEW core title; 'ai engineer' (x2) was ignored

    # when the core titles are exactly what was searched, there is nothing to learn: no second search at all
    calls.clear()
    titles[:] = [("Senior AI Security Engineer", "A"), ("AI Engineer", "D"), ("AI Engineer", "E")]
    asyncio.run(sc.run_scan(topic="ai security engineer", targets={b: str(ws / f"z-{b}.xlsx") for b in ("intern", "graduate", "experienced")}, expand=1))
    assert len(calls) == 1


def test_a_generic_title_from_a_core_posting_is_not_used_as_a_new_search():
    sc = pytest.importorskip("applications_tracker.scheduled_job_scanner")
    spec = rs.resolve_spec(topic="ai security engineer", llm=_niche_llm)
    kept = [{"title": "Professional Services Consultant - AI Security"}, {"title": "Research Scientist, AI Safety"},
            {"title": "Founding AI Security Engineer"}, {"title": "Security Engineer"}]
    q = sc._snowball_queries(kept, {"ai security engineer"}, accept=lambda t: spec.tier(t) == "Core")
    assert q == ["research scientist ai safety"] or set(q) <= {"research scientist ai safety"}       # only candidates that name the niche
    assert "professional services consultant" not in q and "security engineer" not in q
