"""The only way a skill the resume does not show reaches the CV: the candidate confirms it with their own sentence."""
import json
import sys
from pathlib import Path

import pytest

from backend.services import cv_master, cv_tailor

PROFILE = {
    "name": "Ada", "email": "ada@example.org", "phone": "+44 7700 900123",
    "experience_summary": "Applied AI/ML engineer with 3+ years of experience, systems used by 1,000+ engineers.",
    "work_experience": [{"company": "Acme", "role": "Engineer", "timeline": "Jan 2022 - Dec 2024", "technologies": ["Python"],
                         "highlights": ["Built a RAG assistant for 1,300+ employees, cutting support time by 70%."]}],
    "education": [], "projects": [], "skill_categories": {"Languages": ["Python"]},
}


def with_swift(**over):
    item = {"skill": "Swift", "evidence": "Built an iOS prototype in Swift during my MSc coursework.", "group": ""}
    item.update(over)
    return dict(PROFILE, confirmed_experience=[item])


def test_nothing_is_added_without_a_confirmation():
    m = cv_master.build_structured_master(PROFILE, resume_path="/nonexistent")
    assert "Swift" not in m["skills"] and "confirmed_experience" not in m
    assert cv_master.has_evidence("Swift", m)["evidenced"] is False


def test_a_confirmed_skill_is_listed_and_counts_as_evidence():
    m = cv_master.build_structured_master(with_swift(), resume_path="/nonexistent")
    assert "Swift" in m["skills"]
    assert "Swift" in m["skill_groups"]["Additional skills"]
    assert m["confirmed_experience"][0]["evidence"].startswith("Built an iOS prototype")
    assert cv_master.has_evidence("Swift", m)["evidenced"] is True


def test_the_candidates_own_group_is_used():
    m = cv_master.build_structured_master(with_swift(group="Languages"), resume_path="/nonexistent")
    assert "Swift" in m["skill_groups"]["Languages"] and "Additional skills" not in m["skill_groups"]


def test_a_confirmation_without_a_real_sentence_is_ignored():
    m = cv_master.build_structured_master(with_swift(evidence="yes"), resume_path="/nonexistent")
    assert "Swift" not in m["skills"]


def test_the_evidence_sentence_is_not_printed_on_the_cv():
    m = cv_master.build_structured_master(with_swift(), resume_path="/nonexistent")
    assert "iOS prototype" not in cv_tailor.cv_text(m)
    assert "iOS prototype" in cv_master.confirmed_evidence_text(m)


def test_a_rewrite_using_the_confirmed_skill_passes_the_checks_but_an_unconfirmed_one_does_not():
    m = cv_master.build_structured_master(with_swift(), resume_path="/nonexistent")
    plan = {"summary": m["summary"], "experience": [{"exp_index": 0, "keep": [0]}], "rewrites": [], "project_order": [],
            "skills": ["Swift", "Python"], "keywords": ["Swift"]}
    out, problems = cv_tailor._apply_plan(m, plan)
    assert "Swift" in out.cv["skills"]
    plan["skills"] = ["Kotlin", "Python"]
    out2, _ = cv_tailor._apply_plan(m, plan)
    assert "Kotlin" not in out2.cv["skills"] and any("Kotlin" in w for w in out2.warnings)    # a skill nobody confirmed is not added


def test_the_prompt_allows_more_rewrites_but_still_forbids_inventing():
    prompt = cv_tailor._build_prompt(cv_master.build_structured_master(PROFILE, resume_path="/nonexistent"), "Need Python.", "Eng", "Co", None)
    assert "at most 6" in prompt and "Never write a requirement the CV does not show" in prompt
    assert cv_tailor.PROMPT_VERSION == "t3"


@pytest.fixture
def api(tmp_path, monkeypatch):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "macapp"))
    import scan_panel as panel
    monkeypatch.setattr(panel, "GATE_ENABLED", False)
    monkeypatch.setenv("JOB_FINDER_APP_HOME", str(tmp_path / "support"))
    (tmp_path / "support").mkdir()
    ws = panel.workspace_dir()
    panel.profile_path(ws).write_text(json.dumps({"candidate": dict(PROFILE), "search_preferences": {"level": "any"}}))
    return panel.Api([sys.executable]), panel, ws


def test_api_saves_a_confirmation_to_the_profile_and_keeps_the_rest(api):
    a, panel, ws = api
    r = a.confirm_experience("Swift", "Built an iOS prototype in Swift during my MSc coursework.", "Languages")
    assert r["ok"] and r["items"][0]["skill"] == "Swift" and r["items"][0]["confirmed_on"]
    saved = json.loads(panel.profile_path(ws).read_text())
    assert saved["search_preferences"] == {"level": "any"} and saved["candidate"]["name"] == "Ada"
    assert saved["candidate"]["confirmed_experience"][0]["group"] == "Languages"
    assert a.list_confirmed_experience()["items"][0]["skill"] == "Swift"


def test_api_confirming_again_replaces_and_removing_works(api):
    a, panel, ws = api
    a.confirm_experience("Swift", "Built an iOS prototype in Swift during my MSc coursework.")
    r = a.confirm_experience("swift", "Wrote two SwiftUI screens for a student project last year.")
    assert len(r["items"]) == 1 and "SwiftUI" in r["items"][0]["evidence"]
    assert a.remove_confirmed_experience("Swift")["items"] == []


@pytest.mark.parametrize("skill,evidence", [("", "Built an iOS prototype in Swift."), ("x", "Built an iOS prototype in Swift."),
                                            ("Swift", "yes"), ("Swift", "x" * 501), ("Sw\nift", "Built an iOS prototype in Swift.")])
def test_api_rejects_empty_or_thin_confirmations(api, skill, evidence):
    a, panel, ws = api
    r = a.confirm_experience(skill, evidence)
    assert r["ok"] is False and r["error"]
    assert not json.loads(panel.profile_path(ws).read_text())["candidate"].get("confirmed_experience")


def test_a_new_draft_asks_the_model_again_but_a_plain_regenerate_does_not(api, monkeypatch):
    a, panel, ws = api
    seen = {}
    monkeypatch.setattr(a._runner, "start", lambda args, env, ws_, kind: seen.update(args=args, env=env, kind=kind) or {"ok": True})
    monkeypatch.setattr(panel.Api, "_ws_env", lambda self, w: __import__("contextlib").nullcontext(), raising=False)
    import types, sys as _sys
    fake = types.SimpleNamespace(resolve_current=lambda: types.SimpleNamespace(is_main=True, name="main"))
    monkeypatch.setitem(_sys.modules, "services.searches", fake)
    monkeypatch.setattr(__import__("services"), "searches", fake, raising=False)
    a.prepare_packs({"ids": [3], "redo": True})
    assert "JOB_FINDER_NO_TAILOR_CACHE" not in seen["env"] and "--redo" in seen["args"]
    a.prepare_packs({"ids": [3], "redo": True, "fresh": True})
    assert seen["env"]["JOB_FINDER_NO_TAILOR_CACHE"] == "1"
