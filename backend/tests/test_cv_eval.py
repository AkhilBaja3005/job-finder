"""Acceptance tests for Phase 9: Evaluation, metrics, local feedback & property tests (tasks 9.1 - 9.6)."""
from __future__ import annotations

import json
import random
from pathlib import Path

from backend.services.cv_eval import (
    GOLDEN_JDS,
    compare_against_baseline,
    compute_outcome_correlations,
    record_local_outcome,
    record_pack_metrics,
    run_golden_eval,
    verify_prompt_version_gate,
)
from backend.services.cv_model_runner import offline_tailor
from backend.services.cv_verifier import check_facts


def _sample_master() -> dict:
    return {
        "name": "Akhil Bajaj",
        "summary": "Applied AI/ML engineer with 3+ years building Python, LLM, and LangGraph systems.",
        "roles": [
            {
                "title": "Applied AI/ML Engineer",
                "company": "Acme AI",
                "dates": "2023 – Present",
                "bullets": [
                    {"id": "b1", "text": "Built 7 LangGraph agents in Python and FastAPI reducing latency by 40%.", "has_metric": True},
                    {"id": "b2", "text": "Deployed RAG pipelines with Docker, Kubernetes, and PyTorch.", "has_metric": False},
                    {"id": "b3", "text": "Automated CI/CD evaluation suites with SQL and PostgreSQL.", "has_metric": False},
                ],
            }
        ],
        "projects": [
            {"name": "Graphite", "description": "7 LangGraph agents with 4 validation gates.", "url": "https://github.com/a/b", "open_source": True}
        ],
        "skills": {"AI & ML": ["Python", "LLMs", "LangGraph", "RAG", "PyTorch", "FastAPI", "Docker", "Kubernetes", "SQL"]},
        "education": [{"degree": "MSc AI", "institution": "Imperial College London", "dates": "2022 – 2023"}],
    }


def test_at_9_1_golden_set_20_jds_zero_hallucinations():
    assert len(GOLDEN_JDS) == 20
    report = run_golden_eval(_sample_master(), GOLDEN_JDS)
    assert report["total"] == 20
    assert report["hallucination_count"] == 0
    assert report["avg_fill_ratio"] > 0.0
    assert len(report["cases"]) == 20


def test_at_9_2_compare_against_chat_baseline():
    tool_scores = [84.0, 88.0, 81.0]
    baseline_scores = [79.0, 85.0, 80.0]
    cmp = compare_against_baseline(tool_scores, baseline_scores, ledger_failures=0)
    assert cmp["beats_or_matches_baseline"] is True
    assert cmp["delta_avg"] > 0


def test_at_9_3_pack_metrics_in_manifest(tmp_path: Path):
    manifest = tmp_path / "manifest.json"
    record_pack_metrics(
        manifest,
        duration_ms=420,
        tokens_in=1200,
        tokens_out=350,
        model="claude-sonnet-4-5",
        repairs=1,
        fallbacks=[],
    )
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["metrics"]["duration_ms"] == 420
    assert data["metrics"]["tokens_in"] == 1200
    assert data["metrics"]["model"] == "claude-sonnet-4-5"
    assert data["metrics"]["repairs"] == 1


def test_at_9_4_local_outcome_feedback_never_leaves_machine(tmp_path: Path):
    log_path = tmp_path / "outcomes.json"
    record_local_outcome(log_path, pack_id="0016", outcome="interview", choices=["projects_first", "graphite_kept"])
    record_local_outcome(log_path, pack_id="0017", outcome="rejected", choices=["projects_first"])
    corr = compute_outcome_correlations(log_path)
    assert corr["graphite_kept"]["interviews"] == 1
    assert log_path.is_file()


def test_at_9_5_property_tests_random_master_and_jd_zero_invented_facts():
    rng = random.Random(42)
    tools = ["Python", "PyTorch", "FastAPI", "Docker", "Kubernetes", "LangGraph", "RAG", "SQL"]
    companies = ["AlphaCorp", "BetaLabs", "GammaAI"]
    master = _sample_master()
    source_blob = json.dumps(master)

    for _ in range(25):
        picked = rng.sample(tools, k=3)
        comp = rng.choice(companies)
        jd = f"{comp} is hiring. Required: {', '.join(picked)}, Rust, Scala, 10+ years."
        out = offline_tailor(master, jd, title="ML Engineer", company=comp)
        out_texts = [out.get("summary", "")]
        for r in out.get("roles", []):
            for b in r.get("bullets", []):
                out_texts.append(b.get("text", ""))
        for txt in out_texts:
            assert check_facts(txt, source_blob) == []


def test_at_9_6_prompt_version_gate():
    assert verify_prompt_version_gate(hallucination_failures=0, golden_passed=True) is True
    assert verify_prompt_version_gate(hallucination_failures=1, golden_passed=True) is False
