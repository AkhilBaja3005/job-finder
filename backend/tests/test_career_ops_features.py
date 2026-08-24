"""
test_career_ops_features.py — Unit & Integration tests for Career-Ops features

Tests:
1. Alignment Report with Red Flags schema and model serialization
2. Portal Scanner (Greenhouse, Ashby, Lever) parsing and batch scoring
3. HTML Resume Renderer structure and styling
"""

import pytest
import asyncio
from services.llm_agent import MatchScoreDetails, _SemanticScoreResult
from services.portal_scanner import PortalScanner
from services.html_resume_renderer import render_html_resume


def test_alignment_report_with_red_flags():
    """Verify MatchScoreDetails contains 4-pillars and red_flags."""
    report = {
        "seniority": "Target Senior vs 3.1y Profile",
        "tech_stack": "8/10 Required Skills Matched",
        "domain": "Direct GenAI Match",
        "verdict": "Strong Fit",
        "red_flags": "Requires on-site in Berlin"
    }
    match = MatchScoreDetails(
        overall_score=85,
        skills_score=90,
        experience_score=80,
        role_fit_score=85,
        matched_skills=["python", "docker"],
        missing_skills=["rust"],
        tailoring_suggestions=["Highlight systems background"],
        score_breakdown={},
        keyword_stats={"required_matched": "8/10", "candidate_years": "3.1", "required_years": "3"},
        alignment_report=report
    )
    assert match.alignment_report["seniority"] == "Target Senior vs 3.1y Profile"
    assert match.alignment_report["red_flags"] == "Requires on-site in Berlin"
    assert match.alignment_report["verdict"] == "Strong Fit"


def test_portal_scanner_configuration_and_scoring():
    """Verify PortalScanner loads portals.yml and scores candidate listings."""
    scanner = PortalScanner()
    assert "portals" in scanner.config
    assert "greenhouse" in scanner.config["portals"]

    dummy_jobs = [
        {
            "id": "test_1",
            "title": "Senior AI / Machine Learning Engineer",
            "company": "Anthropic",
            "url": "https://boards.greenhouse.io/anthropic/jobs/123",
            "location": "London / Remote",
            "description": "Requirements: 3+ years experience in Python, PyTorch, LLMs, GenAI, and Docker.",
            "portal": "greenhouse"
        },
        {
            "id": "test_2",
            "title": "Accountant",
            "company": "OtherCorp",
            "url": "https://boards.greenhouse.io/other/jobs/456",
            "location": "London",
            "description": "Requirements: 5+ years in accounting and bookkeeping.",
            "portal": "greenhouse"
        }
    ]

    candidate_resume = {
        "name": "Akhil Baja",
        "skills": ["Python", "PyTorch", "LLMs", "Generative AI", "Docker"],
        "experience": [{"company": "Qualcomm", "role": "Software Engineer", "start_date": "2024", "end_date": "2026", "description": ["Built LLM pipelines"]}]
    }

    scored = scanner.score_portal_jobs_for_candidate(dummy_jobs, candidate_resume, min_score=60)
    assert len(scored) == 1
    assert scored[0]["company"] == "Anthropic"
    assert scored[0]["ats_score"] >= 60

    # Verify timeframe filter logic
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    recent_ts = int((now - timedelta(hours=12)).timestamp() * 1000)
    old_ts = int((now - timedelta(days=10)).timestamp() * 1000)

    assert scanner._is_within_timeframe(recent_ts, "24h") is True
    assert scanner._is_within_timeframe(old_ts, "24h") is False
    assert scanner._is_within_timeframe(old_ts, "14d") is True


def test_html_resume_renderer():
    """Verify HTML resume renderer generates well-formed HTML with all core sections."""
    sample_resume = {
        "name": "Akhil Baja",
        "email": "akhil@example.com",
        "phone": "+44 7000000000",
        "links": ["https://linkedin.com/in/akhilbaja", "https://github.com/AkhilBaja3005"],
        "summary": "AI Engineer specializing in GenAI and Machine Learning.",
        "skills": {"Languages": ["Python", "SQL", "C++"], "AI/ML": ["PyTorch", "LLMs", "RAG"]},
        "experience": [{
            "company": "Qualcomm",
            "role": "Software Engineer",
            "start_date": "Dec 2024",
            "end_date": "Aug 2026",
            "description": ["Engineered cross-language LLM pipelines cutting latency by 60%."]
        }],
        "education": [{
            "institution": "Imperial College London",
            "degree": "MSc",
            "field_of_study": "Artificial Intelligence",
            "start_date": "2026",
            "graduation_date": "2027"
        }]
    }

    html = render_html_resume(sample_resume)
    assert "<!DOCTYPE html>" in html
    assert "AKHIL BAJA" in html
    assert "Qualcomm" in html
    assert "Imperial College London" in html
    assert "Professional Summary" in html
    assert "Technical Skills" in html
