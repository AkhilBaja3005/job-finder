"""
test_agent_reach.py — Comprehensive Unit & Integration Tests for Agent-Reach Capability Layer
"""

import pytest
from services.agent_reach_service import (
    fetch_reddit_company_insights,
    fetch_reddit_hiring_threads,
    extract_youtube_transcript,
    scrape_with_jina,
    generate_enhanced_company_brief,
    agent_reach_doctor
)


def test_agent_reach_doctor_returns_valid_structure():
    doc = agent_reach_doctor()
    assert "status" in doc
    assert doc["status"] in ["healthy", "degraded"]
    assert "diagnostics" in doc
    assert isinstance(doc["diagnostics"], dict)
    assert "python_env" in doc["diagnostics"]
    assert "recommendations" in doc
    assert isinstance(doc["recommendations"], list)


def test_fetch_reddit_company_insights_empty_company():
    res = fetch_reddit_company_insights("")
    assert res["status"] == "error"
    assert res["message"] == "Company name required"
    assert res["posts"] == []


def test_fetch_reddit_company_insights_mock():
    res = fetch_reddit_company_insights("Google", "Software Engineer")
    assert "status" in res
    assert res["company"] == "Google"
    assert isinstance(res.get("posts"), list)


def test_fetch_reddit_hiring_threads():
    res = fetch_reddit_hiring_threads("Python", "Remote")
    assert "status" in res
    assert isinstance(res.get("community_jobs"), list)


def test_extract_youtube_transcript_invalid_id():
    res = extract_youtube_transcript("invalid_video_id_123")
    assert "status" in res
    assert res["video_id"] == "invalid_video_id_123"


def test_scrape_with_jina_formatting():
    res = scrape_with_jina("example.com")
    assert "status" in res
    assert res["url"] == "https://example.com"
