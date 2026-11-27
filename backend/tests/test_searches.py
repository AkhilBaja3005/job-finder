"""Offline tests: one Excel per search, choosing/updating them, moving jobs, and never applying twice across searches."""

import argparse
import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.services import role_spec as rs  # noqa: E402
from backend.services import searches as sr  # noqa: E402
from backend.services.excel_tracker import ExcelTracker  # noqa: E402


@pytest.fixture
def ws(tmp_path, monkeypatch):
    for k in ("JOB_FINDER_TRACKER_XLSX", "JOB_FINDER_APPROVED_XLSX", "JOB_FINDER_APPLICATIONS_DIR"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("JOB_FINDER_ROOT", str(tmp_path))
    (tmp_path / "applications_tracker").mkdir()
    return tmp_path


def job(n, **kw):
    base = {"Company": f"Co{n}", "Job Role": f"Role {n}", "Location": "London", "ATS %": 80, "Job URL": f"https://x.io/{n}", "Status": "New"}
    base.update(kw)
    return base


# ─── naming ───────────────────────────────────────────────────────────────────
def test_same_search_same_name_different_search_different_name():
    a = sr.auto_name(["cyber security"], "graduate")
    assert a == sr.auto_name(["Cyber Security"], "graduate")                  # case-insensitive: repeating a search reuses its Excel
    assert a != sr.auto_name(["cyber security"], "intern") and a != sr.auto_name(["applied AI"], "graduate")
    assert a.startswith("cyber-security-") and a.endswith("-graduate") and sr.slug(a, 60) == a       # already a clean folder name
    long = sr.auto_name(["information security engineer", "cybersecurity engineer", "red teaming", "agentic ai security"], "graduate")
    assert len(long) < 70 and long.endswith("-graduate")


def test_parse_inputs_matches_the_scan_precedence_without_calling_an_llm():
    prefs = {"topics": ["applied AI"], "level": "intern"}
    assert rs.parse_inputs(request="cyber security graduate roles", prefs=prefs) == (["cyber security"], "graduate")
    assert rs.parse_inputs(prefs=prefs) == (["applied AI"], "intern")
    assert rs.parse_inputs(topic="a, b", level="junior", prefs=prefs) == (["a", "b"], "junior")
    assert rs.parse_inputs(role="Exact Role, Other", prefs=prefs) == (["Exact Role", "Other"], "all")      # titles typed, no level -> all levels
    assert rs.parse_inputs(topic="x", prefs=prefs) == (["x"], "all")


# ─── create / reuse / choose ──────────────────────────────────────────────────
def test_a_new_search_gets_its_own_folder_and_an_existing_one_is_reused(ws):
    s, created = sr.get_or_create("cyber-graduate", topics=["cyber security"], level="graduate")
    assert created and s.folder.endswith(os.path.join("searches", "cyber-graduate")) and os.path.isfile(os.path.join(s.folder, "search.json"))
    ExcelTracker(s.scanned).add_jobs([job(1)])
    again, created2 = sr.get_or_create("cyber-graduate")
    assert not created2 and again.scanned == s.scanned and again.meta["topics"] == ["cyber security"]
    assert [x.name for x in sr.list_searches()] == ["cyber-graduate"]            # no 'main' until the original workbook exists


def test_main_is_the_original_workbook_pair_and_listed_when_present(ws):
    ExcelTracker(sr._paths(sr.MAIN).scanned).add_jobs([job(1)])
    sr.get_or_create("cyber")
    ExcelTracker(sr._paths("cyber").scanned).add_jobs([job(2)])
    assert [s.name for s in sr.list_searches()] == ["main", "cyber"]
    assert sr.get("cyb").name == "cyber"                                         # unique prefix works
    with pytest.raises(KeyError):
        sr.get("nope")
    sr.get_or_create("cyber-two")
    assert sr.get("cyber").name == "cyber"                                       # an exact name always wins
    with pytest.raises(KeyError, match="several"):
        sr.get("cy")                                                             # ambiguous prefix is refused


def test_a_new_searchs_excel_starts_empty_even_if_an_old_csv_exists(ws):
    (ws / "applications_tracker" / "job_applications_tracker.csv").write_text("Company,Job Title,Job URL,Status\nOld,R,https://o.io/1,New\n")
    s, _ = sr.get_or_create("fresh")
    assert ExcelTracker(s.scanned).rows() == []


def test_current_search_pointer_and_activation(ws):
    s, _ = sr.get_or_create("cyber")
    assert sr.resolve_current().is_main                                          # nothing chosen yet -> the original pair
    sr.set_current("cyber")
    assert sr.resolve_current().name == "cyber" and sr.resolve_current("cyber").name == "cyber"
    sr.activate(s)
    assert os.environ["JOB_FINDER_TRACKER_XLSX"] == s.scanned and os.environ["JOB_FINDER_APPLICATIONS_DIR"] == s.packs
    from backend.services.excel_tracker import approved_path
    assert approved_path() == os.path.join(s.folder, "approved_jobs.xlsx")
    assert s.packs.endswith(os.path.join("applications", "cyber"))              # packs are separated per search too


def test_into_accepts_an_excel_file_path(ws, tmp_path):
    s = sr.get(str(tmp_path / "my_list.xlsx"))
    assert s.scanned.endswith("my_list.xlsx") and s.approved.endswith("my_list_approved.xlsx")


# ─── never apply twice ────────────────────────────────────────────────────────
def test_a_job_applied_to_in_another_search_is_known_everywhere(ws):
    a, _ = sr.get_or_create("ai-intern")
    b, _ = sr.get_or_create("cyber-grad")
    ta = ExcelTracker(a.scanned)
    ta.add_jobs([job(1), job(2)])
    ta.update(row_id=1, status="Applied")
    seen = sr.handled_elsewhere(exclude_scanned=b.scanned)
    assert list(seen.values()) == ["ai-intern"] and "x.io/1" in list(seen)[0]
    assert sr.handled_elsewhere(exclude_scanned=a.scanned) == {}                 # not 'elsewhere' from its own point of view


def test_scan_skips_jobs_applied_in_another_search(ws, monkeypatch):
    sc = pytest.importorskip("applications_tracker.scheduled_job_scanner")
    other, _ = sr.get_or_create("ai-intern")
    ExcelTracker(other.scanned).add_jobs([job(1)])
    ExcelTracker(other.scanned).update(row_id=1, status="Applied")
    mine, _ = sr.get_or_create("cyber-grad")
    sr.activate(mine)
    monkeypatch.setattr(sc, "load_profile_data", lambda: {"candidate": {}, "search_preferences": {"target_roles": ["x"], "target_locations": ["London, UK"], "timeframe": "1m"}})

    async def fake_discover(**kw):
        mk = lambda n: {"title": f"Role {n}", "company": f"Co{n}", "url": f"https://x.io/{n}", "platform": "LinkedIn", "location": "London", "ats_score": 70, "description": "d" * 150}  # noqa: E731
        return [mk(1), mk(2)], 0
    monkeypatch.setattr(sc, "discover_jobs", fake_discover)
    out = asyncio.run(sc.run_scan(enrich=False, dry_run=True))
    assert out["would_save"] == 1                                                # only job 2; job 1 was applied to in 'ai-intern'


# ─── moving jobs between searches ─────────────────────────────────────────────
def test_move_new_jobs_to_another_search_and_refuse_approved_ones(ws, capsys):
    from job_finder.commands import searches as cmd
    main = sr._paths(sr.MAIN)
    t = ExcelTracker(main.scanned)
    t.add_jobs([job(i) for i in range(1, 6)])
    t.update(row_id=4, status="Approved")
    ns = lambda **kw: argparse.Namespace(**{**dict(action="move", name=None, source="main", to="cyber-grad", ids="2-5,99"), **kw})  # noqa: E731
    cmd.run(ns())
    dst = ExcelTracker(sr._paths("cyber-grad").scanned)
    assert sorted(r["Company"] for r in dst.rows()) == ["Co2", "Co3", "Co5"] and [r["ID"] for r in dst.rows()] == [1, 2, 3]   # renumbered
    assert [r["ID"] for r in ExcelTracker(main.scanned).rows()] == [1, 4]        # Co1 stays; Co4 was approved so it could not move
    out = capsys.readouterr()
    assert "only jobs that are not approved" in (out.out + out.err) and "no such ID" in (out.out + out.err)


def test_listing_shows_counts_and_the_current_marker(ws, capsys):
    from job_finder.commands import searches as cmd
    s, _ = sr.get_or_create("cyber-grad", topics=["cyber security"], level="graduate")
    ExcelTracker(s.scanned).add_jobs([job(1), job(2)])
    sr.set_current("cyber-grad")
    cmd.run(argparse.Namespace(action="list", name=None, source=None, to=None, ids=None))
    import re
    text = re.sub(r"[│┃┏┓┗┛━─┡┩╇┳┻╇\s]+", " ", capsys.readouterr().out)          # the table wraps at narrow terminal widths
    assert "* cyber" in text and "security" in text and "graduate" in text and "current" in text


def test_graduate_level_accepts_junior_but_not_plain_associate_titles():
    """'Associate' is not a graduate marker: company boards are full of 'Operations Associate' roles."""
    spec = rs.resolve_spec(topic="security", level="graduate", exact=True)
    for t in ("Junior Security Engineer", "Graduate Security Analyst", "Security Engineer, Early Careers"):
        assert spec.matches(t)[0], t
    for t in ("Associate Security Engineer", "Senior Associate Security Engineer", "Security Engineer"):
        assert not spec.matches(t)[0], t


# ─── regression: `scan --search NAME` must actually search the saved criteria ─────────────
def test_scan_with_search_repeats_the_saved_criteria_not_the_profile_defaults(ws, monkeypatch):
    from job_finder.commands import scan as scan_cmd
    sc = pytest.importorskip("applications_tracker.scheduled_job_scanner")
    s, _ = sr.get_or_create("cyber-grad", topics=["cyber security", "red teaming"], level="graduate")
    sr.save_meta(s, location="Manchester, UK")
    seen = {}

    async def fake_run_scan(**kw):
        seen.update(kw)
        return {"added": 0}
    monkeypatch.setattr(sc, "run_scan", fake_run_scan)
    monkeypatch.setattr("backend.job_finder_mcp.tools.profile_tools.load_profile_data",
                        lambda: {"search_preferences": {"topics": ["applied AI"], "level": "intern", "target_locations": ["London, UK"]}})
    monkeypatch.setattr(scan_cmd, "_exists", lambda *a: False)
    ns = dict(request=[], retired_apply_flag=False, retired_apply_opt=None, search="cyber-grad", into=None, name=None, topic=None, level=None,
              role=None, location=None, timeframe=None, min_ats=None, limit=0, skip_portals=None, sponsor_only=False, top_applicant=False,
              headless=True, no_enrich=False, no_ai_score=False, dry_run=False, no_boards=False, loose=False, exact=False, harvest=False,
              expand=1, no_expand=False, ai_limit=60, score_all=False, core_only=False)
    monkeypatch.setattr(scan_cmd, "logger", scan_cmd.logger)
    monkeypatch.setenv("JOB_FINDER_NO_HARVEST", "1")
    try:
        scan_cmd.run(argparse.Namespace(**ns))
    except Exception:
        pass
    assert seen["topic"] == "cyber security, red teaming" and seen["level"] == "graduate" and seen["location_override"] == "Manchester, UK"
    assert os.environ["JOB_FINDER_TRACKER_XLSX"] == s.scanned                   # and it writes to THAT search's Excel
    assert seen["request"] is None
    # typing something new overrides the saved criteria
    seen.clear()
    ns2 = dict(ns, request=["quantum", "computing", "internships"])
    monkeypatch.delenv("JOB_FINDER_TRACKER_XLSX", raising=False)
    try:
        scan_cmd.run(argparse.Namespace(**ns2))
    except Exception:
        pass
    assert seen["request"] == "quantum computing internships" and seen["topic"] is None
