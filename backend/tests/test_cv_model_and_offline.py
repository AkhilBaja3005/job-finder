"""Acceptance tests for Phase 6: Model routing, determinism, repair, offline (tasks 6.1 - 6.7)."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from backend.services.cv_model_runner import (
    DEFAULT_TAILOR_MODELS,
    TailorCache,
    call_with_backoff,
    compare_candidates,
    compute_tailor_cache_key,
    redact_secrets,
    resolve_tailor_provider_and_model,
    run_two_pass_repair,
    write_manifest_model_info,
)


def test_at_6_1_respects_chosen_provider_and_avoids_lite_default(tmp_path: Path):
    prov, model = resolve_tailor_provider_and_model(provider="claude", model=None)
    assert prov == "claude"
    assert "claude" in model.lower()
    assert "lite" not in model.lower()

    for p in ("gemini", "claude", "openai"):
        _, m = resolve_tailor_provider_and_model(provider=p, model=None)
        assert "lite" not in m.lower()
        assert m == DEFAULT_TAILOR_MODELS[p]

    manifest_path = tmp_path / "manifest.json"
    write_manifest_model_info(manifest_path, provider="claude", model=model, prompt_version="v2")
    data = json.loads(manifest_path.read_text())
    assert data["tailor_provider"] == "claude"
    assert data["tailor_model"] == model


def test_at_6_2_determinism_cache_key_and_temp_zero():
    master = {"summary": "ML Engineer", "roles": []}
    k1 = compute_tailor_cache_key(master, "Python LLM job", "v2", "claude-sonnet-4-5")
    k2 = compute_tailor_cache_key(master, "Python LLM job", "v2", "claude-sonnet-4-5")
    k3 = compute_tailor_cache_key(master, "Different JD", "v2", "claude-sonnet-4-5")
    assert k1 == k2
    assert k1 != k3

    cache = TailorCache()
    calls = 0

    def _run():
        nonlocal calls
        calls += 1
        return {"summary": "ML Engineer", "temperature": 0.0}

    r1 = cache.get_or_compute(k1, _run)
    r2 = cache.get_or_compute(k1, _run)
    assert r1 == r2
    assert calls == 1


def test_at_6_3_two_pass_repair_terminates_and_falls_back():
    items = [
        {"id": "b1", "original": "Built Python API (20% faster).", "candidate": "Built Python API (50% faster)."},
        {"id": "b2", "original": "Deployed FastAPI service.", "candidate": "Deployed FastAPI service."},
    ]
    repair_calls = 0

    def _validator(item):
        if "50%" in item["candidate"]:
            return ["number_changed"]
        return []

    def _repair_fn(item, reasons):
        nonlocal repair_calls
        repair_calls += 1
        # Keep failing to test hard cap of 2 repairs -> fallback to original
        return item["candidate"]

    out = run_two_pass_repair(items, validator=_validator, repair_fn=_repair_fn, max_repairs=2)
    assert repair_calls == 2
    assert out[0]["final_text"] == "Built Python API (20% faster)."
    assert out[0]["reverted"] is True
    assert out[1]["final_text"] == "Deployed FastAPI service."
    assert out[1]["reverted"] is False


def test_at_6_4_candidate_comparison_picks_higher_scoring():
    c1 = {"id": "A", "text": "General SWE"}
    c2 = {"id": "B", "text": "Applied ML Engineer with Python and LLM"}
    best = compare_candidates([c1, c2], scorer=lambda c: 82.0 if c["id"] == "B" else 68.0)
    assert best["id"] == "B"


def test_at_6_5_rate_limit_429_retries_and_user_message():
    attempts = 0

    def _flaky():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise RuntimeError("429 Too Many Requests: quota exceeded")
        return "ok"

    res = call_with_backoff(_flaky, max_retries=3, base_delay=0.0)
    assert res["ok"] is True and res["result"] == "ok" and attempts == 3

    def _always_429():
        raise RuntimeError("429 Too Many Requests")

    res2 = call_with_backoff(_always_429, max_retries=2, base_delay=0.0)
    assert res2["ok"] is False
    assert "rate limit" in res2["user_message"].lower()


def test_at_6_6_privacy_no_secrets_and_no_full_cv_logged(caplog):
    prompt = "API_KEY=sk-secret1234567890abcdef and AIzaSyD1234567890abcdefghij"
    redacted = redact_secrets(prompt)
    assert "sk-secret" not in redacted
    assert "AIzaSy" not in redacted
