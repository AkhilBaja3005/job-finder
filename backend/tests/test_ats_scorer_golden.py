"""Golden-set regression tests for the deterministic ATS scorer.

The golden cases pin expected score bands so scoring changes are deliberate. Add cases to
fixtures/ats_golden.json (resume + JD + expected min/max overall score) as you gather real examples.
"""

import json
import os

import pytest

from services.ats_scorer import (
    ScoringConfig, _extract_taxonomy_skills, compute_ats_score, compute_overall_score,
    estimate_role_fit_score, extract_jd_expectations, get_candidate_seniority_tier,
)

with open(os.path.join(os.path.dirname(__file__), "fixtures", "ats_golden.json"), encoding="utf-8") as fh:
    GOLDEN = json.load(fh)


def overall(resume, jd):
    res = compute_ats_score(resume, jd)
    if not res.eligible:
        return 0
    return compute_overall_score(res.skills_score, res.experience_score, estimate_role_fit_score(resume, jd))


@pytest.mark.parametrize("case", GOLDEN["cases"], ids=[c["name"] for c in GOLDEN["cases"]])
def test_golden_case_in_expected_band(case):
    score = overall(GOLDEN["resume"], case["jd"])
    assert case["min"] <= score <= case["max"], f"{case['name']}: {score} not in [{case['min']}, {case['max']}]"


def test_scores_rank_matches_correctly():
    scores = {c["name"]: overall(GOLDEN["resume"], c["jd"]) for c in GOLDEN["cases"]}
    assert scores["strong_ml_match"] > scores["partial_match"] > scores["unrelated_sales_role"]


def test_header_decides_required_tier_not_body():
    jd = "Machine Learning Engineer\nYou report to the Director of Engineering and mentor senior staff.\n3 years of experience"
    assert extract_jd_expectations(jd)[2] == "mid"
    assert extract_jd_expectations("Senior Machine Learning Engineer\n5 years of experience")[2] == "senior"
    assert extract_jd_expectations("Director of Engineering\nLead the org")[2] == "executive"


def test_work_experience_key_is_honored():
    resume = {"work_experience": [{"role": "Senior Engineer", "company": "X", "start_date": "Jan 2020", "end_date": "Present",
                                   "description": ["Built Python services"]}], "skills": ["python"]}
    assert get_candidate_seniority_tier(resume) == "senior"
    res = compute_ats_score(resume, "Engineer\nRequirements: Python\n2 years of experience")
    assert res.candidate_years > 0


def test_ambiguous_aliases_no_longer_match():
    assert "huggingface" not in _extract_taxonomy_skills("We maintain electrical power transformers and substations")
    assert "javascript" not in _extract_taxonomy_skills("each node of the graph is visited")
    assert "recruiting" not in _extract_taxonomy_skills("sourcing components from suppliers")
    assert "python" not in _extract_taxonomy_skills("a py file")
    assert "huggingface" in _extract_taxonomy_skills("fine-tuned models with Hugging Face")


def test_no_double_counted_vector_database():
    skills = _extract_taxonomy_skills("experience with a vector database such as pinecone")
    assert "vector databases" in skills and "vector database" not in skills


def test_overqualified_candidate_penalized_mildly():
    resume = {"skills": ["python"], "experience": [{"role": "Director of Engineering", "company": "X",
              "start_date": "Jan 2010", "end_date": "Present", "description": ["Python"]}]}
    jd = "Junior Python Developer\nRequirements: Python\n1 years of experience"
    penalised = compute_ats_score(resume, jd).experience_score
    none = compute_ats_score(resume, jd, ScoringConfig(overqualified_penalty_per_level=0.0)).experience_score
    assert none - penalised > 0 and none - penalised <= 25
