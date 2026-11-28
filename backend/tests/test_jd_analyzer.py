"""Acceptance tests for Phase 2: JD Analyzer (tasks 2.1 - 2.9)."""
from __future__ import annotations

import pytest

from backend.services.jd_analyzer import (
    analyze_jd,
    check_jd_quality,
    classify_archetype,
    detect_knockouts,
    detect_language,
    detect_spelling_variant,
    extract_company_context,
    extract_weighted_requirements,
    parse_jd_sections,
    assess_seniority,
)


def test_at_2_1_sections_exclude_benefits_and_legal_from_keywords():
    jd = """
    About the Role
    We are building an AI platform for developer tools.

    Responsibilities
    - Design Python and PyTorch pipelines for LLM evaluation.

    Minimum Qualifications
    - 3+ years with Python, FastAPI, and RAG systems.

    Preferred Qualifications
    - Experience with LangGraph and Kubernetes.

    Benefits & Perks
    - Comprehensive health insurance, 401k matching, unlimited PTO, gym membership,
      free lunch, commuter stipend, parental leave, wellness reimbursement.

    Equal Opportunity Employer
    Apple is an equal opportunity employer committed to diversity and inclusion.
    We do not discriminate on the basis of race, religion, color, or disability.
    """
    sections = parse_jd_sections(jd)
    assert "Python" in sections["responsibilities"]
    assert "FastAPI" in sections["required"]
    assert "401k" in sections["benefits"]
    assert "equal opportunity" in sections["legal"].lower()

    reqs = extract_weighted_requirements(jd, title="Applied ML Engineer")
    all_terms = " ".join(reqs["must_have"] + reqs["strong"] + reqs["nice_to_have"]).lower()
    assert "401k" not in all_terms
    assert "gym" not in all_terms
    assert "pto" not in all_terms
    assert "discriminate" not in all_terms
    assert any("python" in t.lower() for t in reqs["must_have"])


def test_at_2_2_weighted_requirements_ranking_10_jds():
    # Hand-labelled fixtures: items in title + required + repeated rank above preferred-only items
    fixtures = [
        ("Applied ML Engineer - Python", "Required: Python, PyTorch, Python.\nPreferred: Go.", "python", "go"),
        ("Backend Engineer (FastAPI)", "Must have: FastAPI, PostgreSQL.\nNice to have: Rust.", "fastapi", "rust"),
        ("LLM Platform Engineer", "Required: 4+ years LLM serving, vLLM.\nPreferred: Terraform.", "llm", "terraform"),
        ("Data Scientist", "Required: SQL, scikit-learn, SQL.\nPreferred: Spark.", "sql", "spark"),
        ("RAG Systems Engineer", "Required: RAG, vector databases, embeddings.\nBonus: GraphQL.", "rag", "graphql"),
        ("MLOps Engineer", "Required: Kubernetes, Docker, CI/CD.\nPreferred: Ansible.", "kubernetes", "ansible"),
        ("GenAI Developer", "Required: LangGraph, LangChain.\nNice to have: Ruby.", "langgraph", "ruby"),
        ("NLP Engineer", "Required: NLP, transformers, PyTorch.\nPreferred: Scala.", "nlp", "scala"),
        ("AI Agent Engineer", "Required: agentic workflows, tool calling.\nPreferred: Elixir.", "agentic workflows", "elixir"),
        ("Computer Vision Engineer", "Required: OpenCV, PyTorch.\nNice to have: Unity.", "opencv", "unity"),
    ]
    for title, jd, top_term, low_term in fixtures:
        reqs = extract_weighted_requirements(jd, title=title)
        must_lower = [t.lower() for t in reqs["must_have"]]
        nice_lower = [t.lower() for t in reqs["nice_to_have"]]
        assert any(top_term in t for t in must_lower), f"Expected {top_term} in must_have for {title}: {reqs}"
        assert any(low_term in t for t in nice_lower) or not any(
            low_term in t for t in must_lower
        ), f"Expected {low_term} below must_have for {title}: {reqs}"


def test_at_2_3_archetype_apple_developer_publications():
    jd = """
    Apple's Developer Publications team builds interactive documentation, code samples,
    and ML-powered developer tooling for Xcode and Apple frameworks.
    Responsibilities: build LLM evaluation pipelines and documentation tooling.
    """
    arch = classify_archetype(
        "Applied Machine Learning Engineer - Developer Publications",
        jd,
    )
    assert arch["archetype"] == "docs_devrel"
    assert "projects" in arch["section_order"]

    ml_arch = classify_archetype("Senior Applied ML Engineer", "Build PyTorch training and inference pipelines.")
    assert ml_arch["archetype"] == "applied_ml"


def test_at_2_4_seniority_and_years_gap_note():
    jd = "Senior ML Engineer. Required: 5+ years of production machine learning experience."
    res = assess_seniority(jd, title="Senior ML Engineer", candidate_years=3.0)
    assert res["required_years"] == 5
    assert res["candidate_years"] == 3.0
    assert res["status"] == "under_qualified"
    assert "5+" in res["gap_note"] and "3" in res["gap_note"]

    res_ok = assess_seniority("ML Engineer. 2+ years Python.", title="ML Engineer", candidate_years=3.5)
    assert res_ok["status"] == "match"


def test_at_2_5_knockouts_detected_for_all_classes():
    jd = """
    Requirements:
    - Must be authorized to work in the UK without visa sponsorship.
    - Role is hybrid in London, United Kingdom (3 days on-site).
    - Active SC security clearance required; background security check mandatory.
    - Master's degree in Computer Science required.
    - Fluent German and English required.
    - Must be able to travel up to 25% internationally.
    """
    ko = detect_knockouts(jd)
    classes = {item["category"] for item in ko}
    assert {
        "work_authorization",
        "location",
        "clearance",
        "degree",
        "language",
        "security_check",
        "travel",
    }.issubset(classes)


def test_at_2_6_company_context_extracted_separately():
    jd = """
    About Acme Robotics: Our mission is to make warehouse automation effortless.
    Team: You will join the Autonomy Platform group working on perception.
    Requirements: Python, ROS2, PyTorch.
    """
    ctx = extract_company_context(jd, company="Acme Robotics")
    assert ctx["company"] == "Acme Robotics"
    assert "warehouse automation" in ctx["mission"].lower() or "autonomy" in ctx["product_area"].lower()


@pytest.mark.parametrize(
    "case_name,jd_text,expected_status",
    [
        ("empty", "", "empty"),
        ("too_short", "Python engineer needed.", "too_short"),
        ("login_wall", "Sign in to LinkedIn to view this job posting. Join now to see who you know.", "login_wall"),
        ("closed", "This job is no longer accepting applications. The position has been filled.", "closed"),
        (
            "boilerplate_only",
            "Equal Opportunity Employer. All qualified applicants will receive consideration for employment "
            "without regard to race, color, religion, sex, sexual orientation, gender identity, national origin, "
            "disability, or veteran status. Benefits include 401k, dental, vision, and PTO.",
            "boilerplate_only",
        ),
        (
            "duplicated",
            ("We need a Python engineer with FastAPI and SQL experience to build backend APIs. " * 6),
            "duplicated",
        ),
        (
            "non_english",
            "Wir suchen einen erfahrenen Softwareentwickler für Machine Learning Systeme in Berlin. "
            "Anforderungen: Python, PyTorch, Erfahrung mit großen Sprachmodellen und Cloud-Infrastruktur.",
            "non_english",
        ),
        (
            "html_junk",
            "<div><script>alert(1)</script><p>We are hiring a Python ML Engineer with 3+ years of experience "
            "in PyTorch, FastAPI, RAG, and distributed systems for our core AI platform team.</p></div>",
            "html_cleaned",
        ),
        (
            "oversized",
            "\n".join(f"- Build scalable microservice component #{i} using Python and FastAPI" for i in range(42)),
            "oversized",
        ),
    ],
)
def test_at_2_7_jd_quality_cases(case_name, jd_text, expected_status):
    res = check_jd_quality(jd_text)
    assert res["status"] == expected_status, f"{case_name}: got {res}"
    assert res["note"]


def test_at_2_8_non_english_jd_keeps_cv_language_en():
    german_jd = (
        "Wir suchen einen Applied Machine Learning Engineer für unser Team in München. "
        "Anforderungen: Python, PyTorch, Large Language Models, RAG, Docker, Kubernetes."
    )
    assert detect_language(german_jd) == "de"
    analysis = analyze_jd(german_jd, title="Applied ML Engineer", target_cv_language=None)
    assert analysis["jd_language"] == "de"
    assert analysis["cv_language"] == "en"

    analysis_de = analyze_jd(german_jd, title="Applied ML Engineer", target_cv_language="de")
    assert analysis_de["cv_language"] == "de"


def test_at_2_9_spelling_variant_follows_location_and_master():
    uk_jd = "London, UK. We optimise inference pipelines and analyse model behaviour."
    assert detect_spelling_variant(uk_jd, location="London, UK") == "en-GB"

    us_jd = "San Francisco, CA. We optimize inference pipelines and analyze model behavior."
    assert detect_spelling_variant(us_jd, location="Cupertino, CA") == "en-US"
