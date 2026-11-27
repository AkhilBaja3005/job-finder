"""Fixes from a live scan: 429 storms across query streams, false fee-based rejections, 'ML Engineer' titles dropped."""
from unittest.mock import MagicMock, patch

import services.job_searcher as js
from services import role_spec


def test_ats_search_stops_after_every_key_is_429_on_the_first_model(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k1111111")
    js._ats_grounding_quota_exhausted = False
    calls = []
    with patch("services.job_searcher.genai.Client") as client_cls, \
         patch("services.gemini_client.get_gemini_api_keys", return_value=["k1111111", "k2222222", "k3333333"]):
        def fake(*a, **k):
            calls.append(1)
            raise Exception("429 RESOURCE_EXHAUSTED")
        client_cls.return_value = MagicMock(models=MagicMock(generate_content=fake))
        assert js.search_direct_ats_jobs("AI Engineer", "London", "48h") == []
    assert js._ats_grounding_quota_exhausted is True
    assert len(calls) == 3  # one try per key, not keys x models
    js._ats_grounding_quota_exhausted = False


def test_ats_search_bails_out_when_another_stream_flipped_the_breaker(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k1111111")
    js._ats_grounding_quota_exhausted = False
    with patch("services.job_searcher.genai.Client") as client_cls, \
         patch("services.gemini_client.get_gemini_api_keys", return_value=["k1111111", "k2222222"]):
        def fake(*a, **k):
            js._ats_grounding_quota_exhausted = True  # a parallel query finds the quota gone
            raise Exception("429 RESOURCE_EXHAUSTED")
        client_cls.return_value = MagicMock(models=MagicMock(generate_content=fake))
        js.search_direct_ats_jobs("AI Engineer", "London", "48h")
        assert client_cls.call_count == 1  # second key never tried
    js._ats_grounding_quota_exhausted = False


def test_fee_filter_rejects_paid_courses():
    assert js._looks_fee_based("Course fees of £1,995 apply. Job guaranteed on completion.")
    assert js._looks_fee_based("We will refund you 100% if you do not get a job")
    assert js._looks_fee_based("A traineeship. Fees apply to the training course.")


def test_fee_filter_keeps_normal_jobs():
    assert not js._looks_fee_based("Great benefits: we pay for your training course and certifications. Senior Backend Engineer.")
    assert not js._looks_fee_based("Join our graduate traineeship in compliance advisory.")
    assert not js._looks_fee_based("")


def test_ml_titles_match_an_ai_topic(tmp_path, monkeypatch):
    monkeypatch.setattr(role_spec, "_cache_path", lambda: str(tmp_path / "topic_terms.json"))
    fam = role_spec.Family(core=["ai engineer"], include=["ai engineer", "machine learning", "deep learning"], exclude=[], search=[])
    spec = role_spec.resolve_spec(topic="AI Engineer", level="experienced", llm=lambda t: fam)
    assert spec is not None
    assert spec.matches("ML Engineer - Simulation & Robotics")[0]
    assert spec.matches("Software ML Engineer (C++, Python)")[0]
    assert not spec.matches("HTML Developer")[0]
    assert role_spec._abbreviations(["machine learning", "natural language processing", "deep learning"]) == ["ml", "nlp"]
