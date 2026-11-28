"""Phase 9: Golden-set evaluation, baseline comparison, pack metrics & local outcome feedback."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from backend.services.cv_model_runner import offline_tailor
from backend.services.cv_selector import estimate_fill_ratio
from backend.services.cv_verifier import check_facts


GOLDEN_JDS: List[Dict[str, str]] = [
    {"id": f"gd_{i:02d}", "title": title, "company": comp, "jd": jd}
    for i, (title, comp, jd) in enumerate(
        [
            ("Applied ML Engineer - Developer Publications", "Apple", "Required: Python, Large Language Models, RAG, agentic workflows, documentation."),
            ("Applied AI Engineer", "Anthropic", "Required: Python, LLMs, evaluation, tool calling, LangGraph."),
            ("Backend SWE (FastAPI)", "Stripe", "Required: Python, FastAPI, PostgreSQL, Docker, CI/CD."),
            ("ML Platform Engineer", "Databricks", "Required: Kubernetes, Docker, PyTorch, Python, serving."),
            ("Research Engineer", "DeepMind", "Required: PyTorch, NLP, transformers, publications, Python."),
            ("Data Scientist", "Monzo", "Required: SQL, Python, experimentation, scikit-learn."),
            ("RAG Systems Engineer", "Cohere", "Required: RAG, embeddings, vector databases, Python."),
            ("GenAI Developer", "Mistral", "Required: LLMs, LangGraph, FastAPI, Python."),
            ("DevRel AI Engineer", "Hugging Face", "Required: developer relations, documentation, Python, transformers."),
            ("Senior ML Engineer", "Scale AI", "Required: 5+ years Python, PyTorch, LLMs, evaluation."),
            ("Junior AI Engineer", "Synthesia", "Required: Python, PyTorch, deep learning."),
            ("Full Stack AI Engineer", "Vercel", "Required: TypeScript, React, Python, LLMs."),
            ("Cloud Infrastructure Engineer", "Cloudflare", "Required: Docker, Kubernetes, CI/CD, Terraform."),
            ("NLP Engineer", "Grammarly", "Required: NLP, transformers, Python, PyTorch."),
            ("AI Agent Engineer", "LangChain", "Required: LangGraph, agentic workflows, Python, FastAPI."),
            ("Computer Vision Engineer", "Wayve", "Required: Computer Vision, OpenCV, PyTorch, Python."),
            ("Data Platform Engineer", "Snowflake", "Required: SQL, PostgreSQL, Python, Spark."),
            ("MLOps Engineer", "Weights & Biases", "Required: Kubernetes, Docker, Python, CI/CD."),
            ("Product AI Engineer", "Linear", "Required: Python, LLMs, FastAPI, TypeScript."),
            ("Engineering Manager - AI", "Notion", "Required: Engineering Manager, LLMs, Python, RAG."),
        ],
        start=1,
    )
]


def run_golden_eval(master: Dict[str, Any], golden_jds: Sequence[Dict[str, str]] = GOLDEN_JDS) -> Dict[str, Any]:
    """Run offline/deterministic tailoring across the 20-JD golden set and measure fill + hallucinations."""
    source_blob = json.dumps(master, ensure_ascii=False)
    cases: List[Dict[str, Any]] = []
    hallucinations = 0
    total_fill = 0.0

    for item in golden_jds:
        out = offline_tailor(master, item["jd"], title=item["title"], company=item["company"])
        fill = estimate_fill_ratio(out, page_budget=out.get("page_budget", 1))
        total_fill += fill
        texts = [out.get("summary", "")]
        for r in out.get("roles", []):
            for b in r.get("bullets", []):
                texts.append(b.get("text", "") if isinstance(b, dict) else str(b))
        issues = [iss for t in texts for iss in check_facts(t, source_blob)]
        hallucinations += len(issues)
        cases.append({"id": item["id"], "fill_ratio": fill, "hallucinations": len(issues)})

    n = max(1, len(cases))
    return {
        "total": len(cases),
        "hallucination_count": hallucinations,
        "avg_fill_ratio": round(total_fill / n, 3),
        "cases": cases,
    }


def compare_against_baseline(
    tool_scores: Sequence[float],
    baseline_scores: Sequence[float],
    *,
    ledger_failures: int = 0,
) -> Dict[str, Any]:
    """Compare average tool score against chat-model baseline with zero ledger failures."""
    t_avg = sum(tool_scores) / max(1, len(tool_scores))
    b_avg = sum(baseline_scores) / max(1, len(baseline_scores))
    delta = round(t_avg - b_avg, 2)
    return {
        "tool_avg": round(t_avg, 2),
        "baseline_avg": round(b_avg, 2),
        "delta_avg": delta,
        "ledger_failures": ledger_failures,
        "beats_or_matches_baseline": ledger_failures == 0 and t_avg >= b_avg,
    }


def record_pack_metrics(
    manifest_path: Path,
    *,
    duration_ms: int,
    tokens_in: int,
    tokens_out: int,
    model: str,
    repairs: int = 0,
    fallbacks: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Store runtime/token/repair/fallback metrics in manifest.json."""
    existing: Dict[str, Any] = {}
    if manifest_path.is_file():
        try:
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}
    existing["metrics"] = {
        "duration_ms": duration_ms,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "model": model,
        "repairs": repairs,
        "fallbacks": list(fallbacks or []),
    }
    manifest_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    return existing["metrics"]


def record_local_outcome(
    log_path: Path,
    *,
    pack_id: str,
    outcome: str,
    choices: Sequence[str],
) -> None:
    """Append local-only outcome feedback (reply/interview/rejected) without network calls."""
    rows: List[Dict[str, Any]] = []
    if log_path.is_file():
        try:
            rows = json.loads(log_path.read_text(encoding="utf-8"))
        except Exception:
            rows = []
    rows.append({"pack_id": pack_id, "outcome": outcome, "choices": list(choices)})
    log_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")


def compute_outcome_correlations(log_path: Path) -> Dict[str, Dict[str, int]]:
    """Aggregate local outcomes by tailoring choice."""
    stats: Dict[str, Dict[str, int]] = defaultdict(lambda: {"total": 0, "interviews": 0})
    if not log_path.is_file():
        return {}
    rows = json.loads(log_path.read_text(encoding="utf-8"))
    for row in rows:
        is_interview = str(row.get("outcome", "")).lower() in ("interview", "offer", "reply")
        for c in row.get("choices", []):
            stats[c]["total"] += 1
            if is_interview:
                stats[c]["interviews"] += 1
    return dict(stats)


def verify_prompt_version_gate(*, hallucination_failures: int, golden_passed: bool) -> bool:
    """Prompt changes require zero hallucination failures and passing golden set."""
    return hallucination_failures == 0 and bool(golden_passed)
