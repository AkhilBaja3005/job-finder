"""
test_grounding.py — Unit tests for Gemini Google Search Grounding and Recruiter Discovery.
"""

import pytest
from unittest.mock import patch, MagicMock
from services.gemini_client import call_gemini_grounded
from services.recruiter_finder import find_recruiter_for_job, _recruiter_cache, _make_cache_key
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_make_cache_key():
    key1 = _make_cache_key("Stripe, Inc.", "Staff ML Engineer", "London, UK")
    key2 = _make_cache_key("stripe", "staff ml engineer", "london uk")
    assert key1 == key2


@patch("services.gemini_client.get_gemini_client")
def test_call_gemini_grounded_success(mock_get_client):
    # Setup mock candidate with grounding metadata
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client

    mock_response = MagicMock()
    mock_response.text = "Here are the hiring managers at Stripe."
    
    # Mock grounding metadata
    mock_meta = MagicMock()
    mock_meta.web_search_queries = ["Stripe technical recruiter LinkedIn"]
    
    mock_chunk = MagicMock()
    mock_chunk.web.title = "Jane Doe - Technical Recruiter - Stripe | LinkedIn"
    mock_chunk.web.uri = "https://www.linkedin.com/in/janedoe"
    mock_chunk.web.domain = "linkedin.com"
    mock_meta.grounding_chunks = [mock_chunk]

    mock_candidate = MagicMock()
    mock_candidate.grounding_metadata = mock_meta
    mock_response.candidates = [mock_candidate]

    mock_client.models.generate_content.return_value = mock_response

    result = call_gemini_grounded(
        prompt="Find recruiters at Stripe",
        custom_api_key="AIzaSyDummyKeyForTesting12345"
    )

    assert result["grounded"] is True
    assert len(result["citations"]) == 1
    assert result["citations"][0]["url"] == "https://www.linkedin.com/in/janedoe"
    assert result["queries"] == ["Stripe technical recruiter LinkedIn"]
    assert "Stripe" in result["text"]


@patch("services.recruiter_finder.call_gemini_grounded")
def test_find_recruiter_for_job_and_caching(mock_grounded):
    mock_grounded.return_value = {
        "text": """
        {
          "company": "DeepMind",
          "role": "Research Scientist",
          "recruiters": [
            {
              "name": "Alex Smith",
              "title": "Senior Talent Partner",
              "profile_url": "https://www.linkedin.com/in/alexsmith",
              "relevance": "Leads AI research hiring"
            }
          ],
          "summary": "Found 1 primary recruiter at DeepMind."
        }
        """,
        "citations": [{"title": "Alex Smith LinkedIn", "url": "https://www.linkedin.com/in/alexsmith", "domain": "linkedin.com"}],
        "queries": ["DeepMind research recruiter"],
        "grounded": True
    }

    # Clear cache for this test key
    key = _make_cache_key("DeepMind", "Research Scientist", "London")
    _recruiter_cache.pop(key, None)

    res = find_recruiter_for_job("DeepMind", "Research Scientist", "London")
    assert res["status"] == "success"
    assert len(res["recruiters"]) == 1
    assert res["recruiters"][0]["name"] == "Alex Smith"
    assert res["grounded"] is True

    # Second call should be retrieved from cache without calling call_gemini_grounded again
    call_count_before = mock_grounded.call_count
    cached_res = find_recruiter_for_job("DeepMind", "Research Scientist", "London")
    assert cached_res["recruiters"][0]["name"] == "Alex Smith"
    assert mock_grounded.call_count == call_count_before


def test_find_recruiter_empty_company():
    res = find_recruiter_for_job("", "Engineer")
    assert res["status"] == "error"
    assert "required" in res["message"].lower()


@patch("services.recruiter_finder.find_recruiter_for_job")
def test_find_recruiter_api_endpoint(mock_finder):
    mock_finder.return_value = {
        "status": "success",
        "company": "Anthropic",
        "role": "Prompt Engineer",
        "recruiters": [{"name": "Sara Connor", "title": "Technical Recruiter"}],
        "citations": []
    }

    resp = client.post("/jobs/find_recruiter", json={"company": "Anthropic", "role": "Prompt Engineer"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["recruiters"][0]["name"] == "Sara Connor"


@patch("services.job_searcher.genai.Client")
def test_search_direct_ats_jobs_json(mock_client_cls):
    from services.job_searcher import search_direct_ats_jobs
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client

    mock_resp = MagicMock()
    mock_resp.text = """```json
    [
      {
        "title": "Senior AI Systems Engineer",
        "company": "DeepMind",
        "location": "London, UK",
        "url": "https://boards.greenhouse.io/deepmind/jobs/12345",
        "posted_time": "1 day ago"
      },
      {
        "title": "Machine Learning Engineer",
        "company": "Ashby Corp",
        "location": "Remote",
        "url": "https://jobs.ashbyhq.com/ashbycorp/67890",
        "posted_time": "2 days ago"
      }
    ]
    ```"""
    mock_client.models.generate_content.return_value = mock_resp

    jobs = search_direct_ats_jobs(role="AI Engineer", location="London", timeframe="48h", api_key="test-key")
    assert len(jobs) == 2
    assert jobs[0].platform == "Greenhouse"
    assert jobs[0].title == "Senior AI Systems Engineer"
    assert jobs[0].company == "DeepMind"
    assert jobs[1].platform == "Ashby"
    assert jobs[1].title == "Machine Learning Engineer"


@patch("services.job_searcher.genai.Client")
def test_search_direct_ats_jobs_markdown_fallback(mock_client_cls):
    from services.job_searcher import search_direct_ats_jobs
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client

    mock_resp = MagicMock()
    mock_resp.text = """Here are the listings found:
* **Title:** Workday Tech Lead
* **Company:** Kainos
* **Location:** London
* **URL:** https://kainos.myworkdayjobs.com/en-US/careers/job/123
* **Posted:** Today

* **Title:** Full Stack Engineer
* **Company:** Stripe
* **Location:** Remote
* **URL:** https://jobs.lever.co/stripe/456
* **Posted:** 3 hours ago
"""
    mock_client.models.generate_content.return_value = mock_resp

    jobs = search_direct_ats_jobs(role="Software Engineer", location="London", timeframe="24h", api_key="test-key")
    assert len(jobs) == 2
    assert jobs[0].platform == "Workday"
    assert jobs[0].company == "Kainos"
    assert jobs[1].platform == "Lever"
    assert jobs[1].company == "Stripe"

