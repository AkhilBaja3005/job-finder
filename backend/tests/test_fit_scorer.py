"""Offline tests for the evidence-based fit scorer (a fake LLM stands in for Gemini)."""

import asyncio
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.services import fit_scorer as fs  # noqa: E402

CANDIDATE = {
    "name": "Test Person", "email": "secret@example.com", "phone": "+44 7000 000000",
    "gender": "Male", "ethnicity": "Asian", "veteran_status": "No", "disability_status": "No",
    "linkedin": "https://linkedin.com/in/x", "location": "London, UK", "citizenship": "Indian",
    "work_authorization": "Yes", "requires_sponsorship": False,
    "experience_summary": "AI engineer building multi-agent systems.",
    "education": [{"institution": "Example University", "degree": "MSc AI", "timeline": "Sep 2026 - Present", "highlights": ["Lab work"]}],
    "work_experience": [{"company": "Bank", "role": "Engineer", "timeline": "2024-2026", "technologies": ["LangGraph"],
                         "highlights": ["Built guardrails"]}],
    "projects": [{"title": "QAOA", "technologies": ["Qiskit"], "description": "Optimised portfolios"}],
    "core_skills": ["LangGraph", "Redis"], "skill_categories": {"AI": ["Mem0"]},
}
JD = ("Applied AI Intern. We need Python and PyTorch experience, and LLM agent frameworks. "
      "Nice to have: Rust. You must be enrolled on a Masters course. Applications close on 30 November 2026. ") * 2


def raw(**over):
    base = {
        "requirements": [
            {"text": "LLM agent frameworks", "importance": "must", "category": "skill", "verdict": "yes", "evidence": "LangGraph at Bank"},
            {"text": "PyTorch", "importance": "must", "category": "skill", "verdict": "no", "evidence": ""},
            {"text": "Rust", "importance": "nice", "category": "skill", "verdict": "partial", "evidence": "x"},
            {"text": "Enrolled on a Masters", "importance": "must", "category": "education", "verdict": "yes", "evidence": "MSc AI"},
        ],
        "knockouts": [{"text": "Must be enrolled student", "blocks_candidate": False}],
        "role_fit": 80, "summary": "Strong agent background, no PyTorch.",
        "closing_date": "2026-11-30", "closing_date_quote": "Applications close on 30 November 2026",
    }
    base.update(over)
    return base


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(fs, "_cache_path", lambda: str(tmp_path / "fit_cache.db"))
    fs.reset_circuit_breaker()
    yield
    fs.reset_circuit_breaker()


class FakeLLM:
    def __init__(self, payload=None, fail=False):
        self.calls, self.payload, self.fail, self.prompts = 0, payload or raw(), fail, []

    def __call__(self, prompt):
        self.calls += 1
        self.prompts.append(prompt)
        if self.fail:
            raise RuntimeError("429 quota")
        return json.dumps(self.payload)


# ─── what is sent to the LLM ──────────────────────────────────────────────────
def test_profile_text_has_evidence_but_no_pii():
    text = fs.candidate_profile_text(CANDIDATE)
    for wanted in ("MSc AI", "LangGraph", "QAOA", "Qiskit", "Mem0", "Redis", "London, UK", "Needs visa sponsorship: no"):
        assert wanted in text
    for secret in ("secret@example.com", "+44 7000", "Male", "Asian", "linkedin", "Test Person", "veteran", "disab"):
        assert secret not in text


def test_profile_text_handles_parsed_resume_shape():
    text = fs.candidate_profile_text({
        "experience": [{"role": "Dev", "company": "X", "start_date": "2020", "end_date": "2022", "description": ["Did things"]}],
        "skills": {"Languages": ["Python"]}})
    assert "Dev at X (2020 - 2022)" in text and "Did things" in text and "Python" in text


# ─── arithmetic ───────────────────────────────────────────────────────────────
def test_score_arithmetic():
    res = fs.score_from_analysis(fs.normalize_analysis(raw(), JD))
    assert res.skills_score == 50          # (3 + 0 + 0.5) / 7
    assert res.experience_score == 100     # education requirement met
    assert res.overall == 75               # 0.40*50 + 0.35*100 + 0.25*80
    assert res.missing == ["PyTorch"] and "Rust (partial)" in res.matched
    assert res.eligible and res.knockout_reason is None


def test_poor_skills_cap_the_overall_score():
    r = raw(requirements=[{"text": f"Skill {i}", "importance": "must", "category": "skill", "verdict": "no", "evidence": ""} for i in range(4)],
            role_fit=90)
    assert fs.score_from_analysis(fs.normalize_analysis(r, JD)).overall <= 20   # skills 0 -> capped at 0*1.5+20


def test_blocking_knockout_zeroes_the_score():
    r = raw(knockouts=[{"text": "Requires US citizenship", "blocks_candidate": True}])
    res = fs.score_from_analysis(fs.normalize_analysis(r, JD))
    assert not res.eligible and res.overall == 0 and "US citizenship" in res.knockout_reason


def test_no_experience_requirements_defaults_to_80():
    r = raw(requirements=[{"text": "Python", "importance": "must", "category": "skill", "verdict": "yes", "evidence": "x"},
                          {"text": "SQL", "importance": "must", "category": "skill", "verdict": "yes", "evidence": "x"}])
    assert fs.score_from_analysis(fs.normalize_analysis(r, JD)).experience_score == 80


# ─── trusting the LLM less ────────────────────────────────────────────────────
def test_unknown_vocabulary_is_coerced_conservatively():
    r = raw(requirements=[{"text": "Thing", "importance": "critical", "category": "vibes", "verdict": "definitely", "evidence": "e"},
                          {"text": "", "importance": "must", "category": "skill", "verdict": "yes", "evidence": ""}], role_fit=999)
    a = fs.normalize_analysis(r, JD)
    assert a["requirements"] == [{"text": "Thing", "importance": "must", "category": "skill", "verdict": "no", "evidence": "e"}]
    assert a["role_fit"] == 100


def test_closing_date_needs_a_verbatim_quote():
    assert fs.normalize_analysis(raw(), JD)["closing_date"] == "2026-11-30"
    assert fs.normalize_analysis(raw(closing_date_quote="closes on the 1st of never"), JD)["closing_date"] == ""
    assert fs.normalize_analysis(raw(closing_date_quote=""), JD)["closing_date"] == ""


# ─── analyze_fit: caching, failures, breaker ─────────────────────────────────
def test_analysis_is_cached_and_stable():
    llm = FakeLLM()
    a = fs.analyze_fit(CANDIDATE, "Applied AI Intern", "Acme", JD, "intern", llm=llm)
    b = fs.analyze_fit(CANDIDATE, "Applied AI Intern", "Acme", JD, "intern", llm=llm)
    assert llm.calls == 1 and b.from_cache and not a.from_cache and a.overall == b.overall == 75
    assert "seeking intern-level roles" in llm.prompts[0]
    changed = dict(CANDIDATE, core_skills=["LangGraph", "Redis", "PyTorch"])
    fs.analyze_fit(changed, "Applied AI Intern", "Acme", JD, "intern", llm=llm)
    assert llm.calls == 2                                                  # profile change -> re-analysed


def test_short_jd_and_bad_answers_raise_fit_unavailable():
    with pytest.raises(fs.FitUnavailable):
        fs.analyze_fit(CANDIDATE, "t", "c", "too short", llm=FakeLLM())
    with pytest.raises(fs.FitUnavailable):
        fs.analyze_fit(CANDIDATE, "t", "c", JD, llm=lambda p: "not json at all")
    with pytest.raises(fs.FitUnavailable):
        fs.analyze_fit(CANDIDATE, "t", "c", JD, llm=FakeLLM(raw(requirements=[])))


def test_fenced_json_is_accepted():
    res = fs.analyze_fit(CANDIDATE, "t", "c", JD, llm=lambda p: "```json\n" + json.dumps(raw()) + "\n```")
    assert res.overall == 75


def test_circuit_breaker_stops_calling_a_dead_llm():
    llm = FakeLLM(fail=True)
    for i in range(3):
        with pytest.raises(fs.FitUnavailable):
            fs.analyze_fit(CANDIDATE, f"t{i}", "c", JD, llm=llm)
    assert llm.calls == 3
    with pytest.raises(fs.FitUnavailable, match="temporarily disabled"):
        fs.analyze_fit(CANDIDATE, "t9", "c", JD, llm=llm)
    assert llm.calls == 3                                                  # no 4th call


# ─── scanner integration helper ──────────────────────────────────────────────
def test_score_job_updates_the_job_dict():
    job = {"title": "Applied AI Intern", "company": "Acme", "description": JD, "ats_score": 22, "estimated": True}
    assert asyncio.run(fs.score_job(job, CANDIDATE, "intern", llm=FakeLLM())) is True
    assert job["ats_score"] == 75 and job["scoring"] == "AI" and job["estimated"] is False
    assert job["missing_skills"] == ["PyTorch"] and "Gaps: PyTorch" in job["fit_summary"]
    assert job["llm_closing_date"] == "2026-11-30" and job["knockout"] is None


def test_score_job_leaves_job_untouched_on_failure():
    job = {"title": "t", "company": "c", "description": JD, "ats_score": 22}
    assert asyncio.run(fs.score_job(job, CANDIDATE, llm=FakeLLM(fail=True))) is False
    assert job == {"title": "t", "company": "c", "description": JD, "ats_score": 22}


def test_unmet_degree_gate_caps_the_score_despite_strong_skills():
    r = raw(requirements=[
        {"text": "Enrolled in a PhD", "importance": "must", "category": "education", "verdict": "no", "evidence": ""},
        {"text": "PyTorch", "importance": "must", "category": "skill", "verdict": "yes", "evidence": "x"},
        {"text": "Python", "importance": "must", "category": "skill", "verdict": "yes", "evidence": "x"},
        {"text": "ML research", "importance": "must", "category": "experience", "verdict": "yes", "evidence": "x"}],
        role_fit=95)
    res = fs.score_from_analysis(fs.normalize_analysis(r, JD))
    assert res.skills_score == 100 and res.overall == fs.GATE_CAP and res.eligible
    assert "Enrolled in a PhD" in res.missing
    # a partial match (right level, other subject) is not a gate
    r["requirements"][0]["verdict"] = "partial"
    assert fs.score_from_analysis(fs.normalize_analysis(r, JD)).overall > fs.GATE_CAP


def test_prompt_states_the_degree_level_rule():
    llm = FakeLLM()
    fs.analyze_fit(CANDIDATE, "t", "c", JD, llm=llm, use_cache=False)
    assert "DEGREE LEVEL IS A GATE" in llm.prompts[0] and "WORK ELIGIBILITY" in llm.prompts[0]
