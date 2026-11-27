"""Offline tests for the AI master-resume audit and `ats --add-skills` (fake LLM, no network)."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.services import fit_scorer as fs  # noqa: E402
from backend.services import resume_audit as ra  # noqa: E402

CAND = {
    "experience_summary": "Production AI engineer building multi-agent systems and safety guardrails across enterprise teams worldwide today.",
    "education": [{"degree": "MSc AI", "institution": "Example University", "timeline": "Sep 2026 - Present"}],
    "work_experience": [
        {"company": "Bank", "role": "Engineer", "timeline": "Jan 2024 - Jul 2026", "technologies": ["LangGraph", "Redis"],
         "highlights": ["Cut time to production from 2 months to 3 days", "Built guardrails in Python for 100+ agents", "Wrote docs"]}],
    "projects": [{"title": "LLM serving", "technologies": ["vLLM", "LoRA"], "description": "Fine-tuned models with LoRA and served them on vLLM in Python"}],
    "core_skills": ["LangGraph", "Redis", "Mem0"],
}
PREFS = {"topics": ["applied AI"], "level": "intern"}


def llm_answer(**over):
    base = {
        "target_field": "Applied AI engineering",
        "expected_skills": [
            {"skill": "LangGraph", "status": "absent", "evidence": ""},          # model wrong: it IS listed
            {"skill": "Python", "status": "listed", "evidence": ""},             # model wrong: not in skills line, but evidenced
            {"skill": "LoRA", "status": "evidenced", "evidence": "fine-tuned with LoRA"},
            {"skill": "Quantum Approximate Optimisation Algorithm", "status": "evidenced", "evidence": "made up"},     # hallucinated: profile never mentions Rust
            {"skill": "PyTorch", "status": "absent", "evidence": ""},
        ],
        "other_evidenced_skills": ["vLLM", "Kubernetes", "Redis"],               # Kubernetes unsupported, Redis already listed
        "suggestions": ["Add Python to the skills line."],
    }
    base.update(over)
    return json.dumps(base)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(fs, "_cache_path", lambda: str(tmp_path / "cache.db"))


def _patch_gemini(monkeypatch, fn):
    """The module is importable as both `services.gemini_client` and `backend.services.gemini_client`."""
    import importlib
    for name in ("services.gemini_client", "backend.services.gemini_client"):
        try:
            monkeypatch.setattr(importlib.import_module(name), "generate_content_with_fallback", fn)
        except ImportError:
            pass


def run_audit(**kw):
    return ra.audit_master_resume(CAND, PREFS, llm=lambda p: llm_answer(**kw), use_cache=False)


def test_claims_are_verified_against_the_real_profile():
    a = run_audit()
    status = {}
    for name in a["skills_listed"]:
        status[name] = "listed"
    for h in a["hidden_skills"]:
        status[h["skill"]] = "evidenced"
    for g in a["gaps"]:
        status[g] = "absent"
    assert status == {"LangGraph": "listed", "Python": "evidenced", "LoRA": "evidenced", "Quantum Approximate Optimisation Algorithm": "absent", "PyTorch": "absent"}
    assert a["other_evidenced_skills"] == ["vLLM"]          # Kubernetes unsupported; Redis already listed


def test_score_arithmetic_and_shape():
    a = run_audit()
    assert a["engine"] == "ai" and a["expected_total"] == 5 and a["skills_count"] == 1
    assert a["skills_coverage"] == round(100 * (1 + 0.6 + 0.6) / 5)                       # 44
    assert a["total_bullets"] == 4 and a["quantified_bullets"] == 2 and a["quantified_percentage"] == 50
    assert a["ats_score"] == round(0.40 * 44 + 0.35 * 90 + 0.25 * 60)                      # years >= 2
    assert {"skills_count", "total_bullets", "quantified_percentage", "candidate_years", "suggestions"} <= set(a)


def test_tips_name_the_unlisted_skills_and_not_the_gaps():
    tips = " ".join(run_audit()["suggestions"])
    assert "Python" in tips and "LoRA" in tips
    assert "Add Python to the skills line." not in tips          # the model's duplicate is dropped
    assert "Quantum Approximate Optimisation Algorithm" not in tips


def test_skills_to_add_never_includes_gaps_or_listed_skills():
    a = run_audit()
    assert ra.skills_to_add(a, CAND) == ["Python", "LoRA", "vLLM"]


def test_bad_llm_output_raises_fit_unavailable():
    for bad in (lambda p: "nope", lambda p: llm_answer(expected_skills=[])):
        with pytest.raises(fs.FitUnavailable):
            ra.audit_master_resume(CAND, PREFS, llm=bad, use_cache=False)


def test_audit_is_cached():
    calls = []

    def llm(p):
        calls.append(1)
        return llm_answer()
    ra.audit_master_resume(CAND, PREFS, llm=llm)
    ra.audit_master_resume(CAND, PREFS, llm=llm)
    assert len(calls) == 1


# ─── the command ──────────────────────────────────────────────────────────────
def test_run_audit_falls_back_to_keyword_engine_with_a_note(monkeypatch):
    from job_finder.commands import ats

    def boom(*a, **k):
        raise fs.FitUnavailable("429 quota")
    monkeypatch.setattr(ra, "audit_master_resume", boom)
    out = ats._run_audit(CAND, PREFS, keyword=False)
    assert out["engine"] == "keyword" and "429 quota" in out["note"] and "ats_score" in out


def test_keyword_flag_never_calls_the_ai(monkeypatch):
    from job_finder.commands import ats

    def boom(*a, **k):
        raise AssertionError("AI audit must not run with --keyword")
    monkeypatch.setattr(ra, "audit_master_resume", boom)
    assert ats._run_audit(CAND, PREFS, keyword=True)["engine"] == "keyword"


def test_add_skills_backs_up_and_appends(tmp_path, monkeypatch):
    from backend.job_finder_mcp.tools import profile_tools
    from job_finder.commands import ats
    path = tmp_path / "candidate_profile.json"
    profile = {"candidate": json.loads(json.dumps(CAND))}
    path.write_text(json.dumps(profile))
    monkeypatch.setattr(profile_tools, "_checked_save_path", lambda: str(path))
    monkeypatch.setattr(profile_tools, "save_profile_data", lambda d: path.write_text(json.dumps(d)))
    audit = run_audit()
    ats._add_skills(profile, audit, assume_yes=True)
    saved = json.loads(path.read_text())["candidate"]["core_skills"]
    assert saved == ["LangGraph", "Redis", "Mem0", "Python", "LoRA", "vLLM"]
    backups = [p for p in os.listdir(tmp_path) if ".bak-" in p]
    assert len(backups) == 1 and json.loads((tmp_path / backups[0]).read_text())["candidate"]["core_skills"] == ["LangGraph", "Redis", "Mem0"]


def test_add_skills_refuses_without_confirmation_in_non_interactive_shell(tmp_path, monkeypatch):
    from backend.job_finder_mcp.tools import profile_tools
    from job_finder.commands import ats
    path = tmp_path / "p.json"
    path.write_text("{}")
    monkeypatch.setattr(profile_tools, "_checked_save_path", lambda: str(path))
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False, raising=False)
    with pytest.raises(SystemExit):
        ats._add_skills({"candidate": json.loads(json.dumps(CAND))}, run_audit(), assume_yes=False)
    assert path.read_text() == "{}"


def test_default_llm_uses_the_audit_schema_not_the_job_fit_schema(monkeypatch):
    """Regression: the audit once reused the job-fit LLM helper and got a job-fit answer back."""
    seen = {}

    def fake_generate(prompt, schema=None, *a, **k):
        seen["fields"] = sorted(schema.model_fields)
        return llm_answer()
    _patch_gemini(monkeypatch, fake_generate)
    a = ra.audit_master_resume(CAND, PREFS, use_cache=False)
    assert seen["fields"] == ["expected_skills", "other_evidenced_skills", "suggestions", "target_field"]
    assert a["engine"] == "ai"


def test_job_fit_default_llm_still_uses_the_job_fit_schema(monkeypatch):
    seen = {}
    _patch_gemini(monkeypatch, lambda prompt, schema=None, *a, **k: seen.setdefault("fields", sorted(schema.model_fields)) and "{}")
    fs._default_llm("x")
    assert "requirements" in seen["fields"] and "role_fit" in seen["fields"]


def test_a_skill_the_model_calls_absent_is_upgraded_when_the_profile_shows_it():
    """Regression: the model said 'RAG: absent' for a candidate who 'Built a Graph-RAG retrieval system'."""
    cand = json.loads(json.dumps(CAND))
    cand["work_experience"][0]["highlights"].append("Built a Graph-RAG retrieval system over vendor contracts")
    answer = llm_answer(expected_skills=[
        {"skill": "Retrieval-Augmented Generation (RAG)", "status": "absent", "evidence": ""},
        {"skill": "Kubernetes", "status": "absent", "evidence": ""},
        {"skill": "PyTorch", "status": "absent", "evidence": ""},
        {"skill": "Large Language Models", "status": "evidenced", "evidence": "Fine-tuned models with LoRA and served them on vLLM"}])
    a = ra.audit_master_resume(cand, PREFS, llm=lambda p: answer, use_cache=False)
    hidden = {h["skill"]: h["evidence"] for h in a["hidden_skills"]}
    assert "Retrieval-Augmented Generation (RAG)" in hidden and "Graph-RAG" in hidden["Retrieval-Augmented Generation (RAG)"]
    assert "Large Language Models" in hidden                   # semantic claim accepted: its cited evidence is real
    assert a["gaps"] == ["Kubernetes", "PyTorch"]              # genuine gaps stay gaps


def test_matching_is_whole_word_not_substring():
    assert not ra._mentions("storage fragment pragmatic", "RAG")
    assert ra._mentions("built a graph-rag system", "RAG")
    assert ra._mentions("python, c++ and go", "C++")
    assert not ra._mentions("python only", "Kubernetes")


def test_cache_stores_the_raw_answer_and_reverifies_on_read(monkeypatch):
    ra.audit_master_resume(CAND, PREFS, llm=lambda p: llm_answer())
    cached = fs._cache_get(next(k for k in [_only_key()]))
    assert cached["expected_skills"][1] == {"skill": "Python", "status": "listed", "evidence": ""}   # the model's raw (wrong) claim
    # a second call serves from cache but still applies today's verification
    a = ra.audit_master_resume(CAND, PREFS, llm=lambda p: (_ for _ in ()).throw(AssertionError("no LLM call expected")))
    assert "Python" in [h["skill"] for h in a["hidden_skills"]]


def _only_key():
    import sqlite3
    with sqlite3.connect(fs._cache_path()) as db:
        return db.execute("select key from fit where key like 'audit|%'").fetchone()[0]


def test_model_skills_line_tips_are_dropped_as_duplicates_of_ours():
    a = run_audit(suggestions=["Add Python to the Skills line.", "Include vLLM in your skills section.",
                               "Reword 'Wrote docs' to say what the docs enabled."])
    assert [t for t in a["suggestions"] if "Reword" in t] and not [t for t in a["suggestions"] if "Skills line." in t]
    assert sum("Python" in t for t in a["suggestions"]) == 1          # only our own generated tip


def test_skills_to_add_skips_long_entries():
    audit = {"hidden_skills": [{"skill": "Python", "evidence": ""}],
             "other_evidenced_skills": ["GGUF", "Quantum Approximate Optimisation Algorithm"]}
    assert ra.skills_to_add(audit, {"core_skills": ["Redis"]}) == ["Python", "GGUF"]
