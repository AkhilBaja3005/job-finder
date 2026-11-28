"""Offline tests: CV tailoring can only re-order / trim / re-phrase what is already in the profile."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.services import cv_tailor as ct  # noqa: E402

PROFILE = {
    "name": "Test Person", "email": "t@example.org", "phone": "Not provided",
    "linkedin": "https://linkedin.com/in/test", "github": "https://github.com/test", "portfolio": "https://janedoe.dev",
    "experience_summary": "AI engineer building multi-agent systems and guardrails for 100+ production agents at a large bank.",
    "education": [{"institution": "Example University", "degree": "MSc AI", "timeline": "Sep 2026 - Present"}],
    "work_experience": [
        {"company": "Bank", "role": "Senior Engineer", "timeline": "Jan 2026 – Jul 2026", "technologies": ["LangGraph", "Redis"],
         "highlights": ["Built the AgentSDK on LangGraph adopted by 89% of teams", "Wrote guardrails for 100+ agents using Redis",
                        "Cut time to production from 2 months to 3 days", "Organised the team offsite"]},
        {"company": "Bank", "role": "Engineer", "timeline": "Aug 2024 – Dec 2025", "technologies": ["Neo4j"],
         "highlights": ["Built a Graph-RAG system on Neo4j raising precision from 72% to 94%", "Maintained internal wiki"]},
    ],
    "projects": [
        {"title": "EEG seizure prediction", "technologies": ["TensorFlow", "Python"], "description": "RNN predicting seizure onset"},
        {"title": "LLM serving", "technologies": ["vLLM", "LoRA"], "description": "Fine-tuned with LoRA and served on vLLM"},
        {"title": "Quantum QAOA", "technologies": ["QAOA"], "description": "Portfolio optimisation with QAOA"},
    ],
    "core_skills": ["Python", "LangGraph", "Redis", "Neo4j", "TensorFlow", "vLLM", "LoRA"],
}
JD = ("Applied AI Intern. You will build LLM agents with LangGraph and Python, serve models with vLLM and evaluate Kubernetes "
      "deployments. Experience with PyTorch is a plus. " * 3)


def plan(**over):
    base = {
        "summary": "Multi-agent systems and guardrails for 100+ production agents, built as an AI engineer at a large bank.",
        "experience": [{"exp_index": 0, "keep": [0, 1, 2]}, {"exp_index": 1, "keep": [0]}],
        "rewrites": [], "project_order": [1, 0], "skills": ["vLLM", "LangGraph", "Python"],
        "keywords": ["LangGraph", "Python", "vLLM", "Kubernetes", "PyTorch"],
    }
    base.update(over)
    return json.dumps(base)


def tailor(**over):
    return ct.tailor_cv(ct.master_cv_from_profile(PROFILE), JD, "Applied AI Intern", "Acme", "intern", llm=lambda p: plan(**over))


def test_master_cv_comes_straight_from_the_profile():
    m = ct.master_cv_from_profile(PROFILE)
    assert m["phone"] == "" and m["links"] == ["https://linkedin.com/in/test", "https://github.com/test"]   # placeholder + 'Not provided' dropped
    assert m["experience"][0]["start_date"] == "Jan 2026" and m["experience"][0]["end_date"] == "Jul 2026"
    assert m["education"][0]["graduation_date"] == "Present" and m["skills"][0] == "Python"
    assert len(m["experience"][0]["description"]) == 4


def test_a_valid_plan_selects_orders_and_keeps_every_role():
    r = tailor()
    exp = r.cv["experience"]
    assert [len(e["description"]) for e in exp] == [3, 1]                         # offsite + wiki bullets left out, both roles kept
    assert "Organised the team offsite" not in " ".join(exp[0]["description"])
    assert [p["title"] for p in r.cv["projects"]] == ["LLM serving", "EEG seizure prediction"]
    assert r.cv["skills"][:3] == ["vLLM", "LangGraph", "Python"] and set(r.cv["skills"]) == set(ct.master_cv_from_profile(PROFILE)["skills"])
    assert [e["company"] + e["role"] for e in exp] == ["BankSenior Engineer", "BankEngineer"]    # roles/dates untouched
    assert any(c.startswith("SUMMARY") for c in r.changes) and any("left out" in c for c in r.changes)


def test_invented_numbers_and_tools_are_rejected_everywhere():
    r = tailor(summary="AI engineer who cut costs by 45% and deployed agents on Kubernetes with PyTorch for 100+ agents at a bank.")
    assert r.cv["summary"] == PROFILE["experience_summary"]                         # fell back to the original
    assert any("summary rejected" in w for w in r.warnings)
    r = tailor(rewrites=[{"exp_index": 0, "bullet_index": 1, "new_text": "Wrote guardrails for 500+ agents using Redis"}])
    assert "500+" not in " ".join(r.cv["experience"][0]["description"]) and any("Reworded bullet rejected" in w for w in r.warnings)
    r = tailor(rewrites=[{"exp_index": 0, "bullet_index": 1, "new_text": "Wrote guardrails for 100+ agents using Redis and PyTorch"}])
    assert "PyTorch" not in " ".join(r.cv["experience"][0]["description"])


def test_a_safe_rewording_is_accepted_and_logged():
    r = tailor(rewrites=[{"exp_index": 0, "bullet_index": 1, "new_text": "Designed guardrails for 100+ agents using Redis"}])
    assert "Designed guardrails for 100+ agents using Redis" in r.cv["experience"][0]["description"]
    assert any(c.startswith("REWORDED") and "before:" in c and "after:" in c for c in r.changes)


def test_bad_indices_are_ignored_and_a_role_is_never_emptied():
    r = tailor(experience=[{"exp_index": 0, "keep": [99, -1]}, {"exp_index": 1, "keep": []}], project_order=[7, 8])
    assert len(r.cv["experience"][0]["description"]) >= 1 and len(r.cv["experience"][1]["description"]) >= 1
    assert 1 <= len(r.cv["projects"]) <= ct.MAX_PROJECTS


def test_skills_not_in_the_profile_are_never_shown():
    r = tailor(skills=["Kubernetes", "PyTorch", "vLLM", "Graph-RAG"])
    assert "Kubernetes" not in r.cv["skills"] and "PyTorch" not in r.cv["skills"]
    assert any("Kubernetes" in w for w in r.warnings)
    assert "Graph-RAG" in r.cv["skills"]                                             # evidenced in a bullet, so allowed


def test_keyword_visibility_before_and_after_and_honest_gaps():
    r = tailor()
    k = {x["term"]: x for x in r.keywords}
    assert k["vLLM"]["evidenced"] and k["vLLM"]["before"] and k["vLLM"]["after"]
    assert not k["Kubernetes"]["evidenced"] and not k["Kubernetes"]["after"]         # never claimed
    assert not k["PyTorch"]["evidenced"]
    md = ct.render_changes_md(r, "Applied AI Intern", "Acme")
    assert "do NOT have evidence" in md and "Kubernetes" in md and "Nothing here was invented" in md
    s = ct.keyword_summary(r)
    assert s["evidenced"] == 3 and s["after"] >= s["before"] and set(s["gaps"]) == {"Kubernetes", "PyTorch"}


def test_unusable_model_output_raises_instead_of_guessing():
    m = ct.master_cv_from_profile(PROFILE)
    for bad in (lambda p: "not json", lambda p: "[]"):
        with pytest.raises(ct.TailorUnavailable):
            ct.tailor_cv(m, JD, llm=bad)
    with pytest.raises(ct.TailorUnavailable):
        ct.tailor_cv(m, "too short", llm=lambda p: plan())


# ─── regressions from the first live run ─────────────────────────────────────
LIVE_BAD_SUMMARY = ("Highly motivated Computer Science student with extensive experience in agentic AI and distributed systems. "
                    "Passionate about leveraging AI-powered tools to drive operational excellence in fast-paced environments.")


def test_filler_is_rejected_in_the_summary():
    r = ct.tailor_cv(ct.master_cv_from_profile(PROFILE), JD, llm=lambda p: plan(summary=LIVE_BAD_SUMMARY))
    assert r.cv["summary"] == PROFILE["experience_summary"]
    assert "filler 'highly motivated'" in " ".join(r.warnings)


def test_a_job_keyword_you_have_no_evidence_for_cannot_be_slipped_into_the_summary():
    summary = "AI engineer building multi-agent systems and guardrails for 100+ production agents with operational excellence at a bank."
    r = ct.tailor_cv(ct.master_cv_from_profile(PROFILE), JD, llm=lambda p: plan(summary=summary, keywords=["LangGraph", "Operational Excellence"]))
    assert r.cv["summary"] == PROFILE["experience_summary"]
    assert "operational excellence" in " ".join(r.warnings).lower()
    ok = ct.tailor_cv(ct.master_cv_from_profile(PROFILE), JD, llm=lambda p: plan(keywords=["LangGraph", "Operational Excellence"]))
    assert ok.cv["summary"].startswith("Multi-agent systems")                              # same keywords, clean summary: accepted
    assert not next(k for k in ok.keywords if k["term"] == "Operational Excellence")["after"]


def test_a_reworded_bullet_must_keep_its_numbers_and_stay_in_the_profile_vocabulary():
    master = ct.master_cv_from_profile(PROFILE)
    bad = [  # shaped like the live failure: lost the specifics, added soft-skill claims
        "Collaborated with cross-disciplinary teams to build a scalable agent framework, driving adoption across the organization",
        "Built the AgentSDK on LangGraph adopted by many teams",                           # drops 89%
    ]
    for rw in bad:
        r = ct.tailor_cv(master, JD, llm=lambda p, rw=rw: plan(rewrites=[{"exp_index": 0, "bullet_index": 0, "new_text": rw}]))
        assert master["experience"][0]["description"][0] in r.cv["experience"][0]["description"], rw
        assert any("Reworded bullet rejected" in w for w in r.warnings)
    ok = "Built the AgentSDK on LangGraph, adopted by 89% of teams"
    r = ct.tailor_cv(master, JD, llm=lambda p: plan(rewrites=[{"exp_index": 0, "bullet_index": 0, "new_text": ok}]))
    assert ok in r.cv["experience"][0]["description"]


def test_the_model_gets_one_chance_to_fix_what_was_rejected():
    prompts = []

    def llm(p):
        prompts.append(p)
        return plan(summary=LIVE_BAD_SUMMARY) if len(prompts) == 1 else plan()
    r = ct.tailor_cv(ct.master_cv_from_profile(PROFILE), JD, llm=llm)
    assert len(prompts) == 2 and "YOUR PREVIOUS PLAN HAD THESE PROBLEMS" in prompts[1] and "filler" in prompts[1]
    assert r.cv["summary"].startswith("Multi-agent systems and guardrails")            # the corrected plan was used


def test_no_second_call_when_the_first_plan_is_clean_or_the_retry_is_no_better():
    prompts = []
    ct.tailor_cv(ct.master_cv_from_profile(PROFILE), JD, llm=lambda p: prompts.append(p) or plan())
    assert len(prompts) == 1
    prompts.clear()
    r = ct.tailor_cv(ct.master_cv_from_profile(PROFILE), JD, llm=lambda p: prompts.append(p) or plan(summary=LIVE_BAD_SUMMARY))
    assert len(prompts) == 2 and r.cv["summary"] == PROFILE["experience_summary"]       # still bad: your original wording stays


def test_a_summary_must_keep_the_original_headline_number():
    generic = "Software engineer building agentic systems and guardrails for production agents at a large bank, contributing to frameworks."
    r = tailor(summary=generic)
    assert r.cv["summary"] == PROFILE["experience_summary"] and "drops the proof point" in " ".join(r.warnings)


def test_title_honesty_rejects_unsupported_target_role_claim():
    bad_summary = "Principal ML Scientist with 4 years building AgentSDK and guardrails for 1200 engineers in banking."
    r = ct.tailor_cv(
        ct.master_cv_from_profile(PROFILE),
        JD,
        title="Principal ML Scientist",
        llm=lambda p: plan(summary=bad_summary),
    )
    assert r.cv["summary"] == PROFILE["experience_summary"]
    assert any("target role" in w for w in r.warnings)


def test_never_say_and_always_keep_controls_in_selection():
    prof = json.loads(json.dumps(PROFILE))
    prof["never_say"] = ["telemetry"]
    prof["always_keep"] = ["AgentSDK"]
    master = ct.master_cv_from_profile(prof)
    # Model tries to keep bullet 1 (telemetry) and drop bullet 0 (AgentSDK)
    r = ct.tailor_cv(
        master,
        JD,
        llm=lambda p: plan(experience=[{"exp_index": 0, "keep": [1, 2]}]),
    )
    kept = r.cv["experience"][0]["description"]
    assert not any("telemetry" in b.lower() for b in kept)
    assert any("AgentSDK" in b for b in kept)


def test_selector_protects_highest_scoring_must_have_bullet():
    master = ct.master_cv_from_profile(PROFILE)
    # Bullet 0 mentions LangGraph & guardrails (must-haves in JD). Model drops bullet 0 and only keeps bullet 1 & 2.
    r = ct.tailor_cv(
        master,
        "Required: LangGraph, Python, vLLM.\n" + JD,
        title="AI Engineer",
        llm=lambda p: plan(experience=[{"exp_index": 0, "keep": [1, 2]}, {"exp_index": 1, "keep": [0]}]),
    )
    kept = r.cv["experience"][0]["description"]
    assert any("AgentSDK" in b and "LangGraph" in b for b in kept)
    assert any("KEPT highest-scoring must-have bullet" in c for c in r.changes)
