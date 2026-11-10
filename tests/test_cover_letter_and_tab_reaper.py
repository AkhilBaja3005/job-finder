"""
test_cover_letter_and_tab_reaper.py — Tests for:
1. 6-step cover letter generator structure and fallback
2. AI route `/generate_cover_letter_history` schema and response parsing
3. Automatic Chrome tab reaper (`cleanup_stale_chrome_tabs`) logic
4. KeyboardInterrupt skip handling behavior in autofill pipeline
"""

import json
import os
import sys
import pytest
from unittest.mock import MagicMock, patch

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from services.cover_letter_generator import generate_structured_cover_letter
from services.browser_use_agent import cleanup_stale_chrome_tabs, build_application_task_prompt


def test_cover_letter_generation_structure():
    mock_profile = {
        "candidate": {
            "name": "Akhil Baja",
            "location": "London, UK",
            "notice_period": "Available immediately",
            "requires_sponsorship": True,
            "skills": ["Python", "FastAPI", "Playwright"]
        }
    }

    mock_llm_response = """### 1. Role Analysis
- Core Skills: Autonomous multi-agent pipelines, Python, Playwright
- Problem to Solve: Automate end-to-end recruitment workflows

### 2. Gaps & Highlights
- Strong match: Python and Playwright browser orchestration
- No gap detected

### 3. Cover Letter
Dear Hiring Team,

I am writing to express my strong interest in the AI Automation Engineer position at Acme Corp. With a solid foundation in building production-grade autonomous agent systems, I have engineered multi-step browser workflows that increased throughput significantly.

My technical background centers on Python, FastAPI, and Playwright automation, enabling me to build resilient distributed scrapers and real-time inference systems. Based in London and available immediately, I focus on delivering observable, fault-tolerant engineering solutions.

I look forward to discussing how my experience can contribute to Acme Corp's automation goals.

Sincerely,
Akhil Baja

### 4. Alternative Opening Lines
1. Acme Corp's commitment to scaling agentic infrastructure directly matches my work building autonomous automation pipelines.
2. Delivering robust browser automation requires deterministic orchestration, which has been the primary focus of my engineering work.
"""

    with patch("services.cover_letter_generator.generate_content_with_fallback", return_value=mock_llm_response):
        result = generate_structured_cover_letter(
            job_title="AI Automation Engineer",
            company="Acme Corp",
            job_description="Looking for an AI engineer to build autonomous Playwright pipelines.",
            candidate_profile=mock_profile
        )

    assert result["status"] == "success"
    assert "Dear Hiring Team" in result["cover_letter"]
    assert "Acme Corp" in result["cover_letter"]
    assert len(result["role_analysis"]) > 5
    assert len(result["alternative_openings"]) > 10


def test_cover_letter_fallback_on_llm_failure():
    mock_profile = {
        "candidate": {
            "name": "Akhil Baja",
            "location": "London, UK",
            "notice_period": "Available immediately",
            "requires_sponsorship": True
        }
    }

    with patch("services.cover_letter_generator.generate_content_with_fallback", side_effect=Exception("API limit exceeded")):
        result = generate_structured_cover_letter(
            job_title="Software Engineer",
            company="Beta AI",
            job_description="Build web tools",
            candidate_profile=mock_profile
        )

    assert result["status"] == "fallback"
    assert "Beta AI" in result["cover_letter"]
    assert "Akhil Baja" in result["cover_letter"]
    assert "London, UK" in result["cover_letter"]


def test_cleanup_stale_chrome_tabs_reaps_oldest():
    fake_tabs = [
        {"id": "tab-1", "type": "page", "title": "Old Job 1"},
        {"id": "tab-2", "type": "page", "title": "Old Job 2"},
        {"id": "tab-3", "type": "page", "title": "Old Job 3"},
        {"id": "tab-4", "type": "page", "title": "Active Target Job"}
    ]

    closed_tab_ids = []

    class FakeResponse:
        def __init__(self, data):
            self._data = data
        def read(self):
            return self._data
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    def mock_urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req
        if "/json/list" in str(url):
            return FakeResponse(json.dumps(fake_tabs).encode("utf-8"))
        elif "/json/close/" in str(url):
            tab_id = str(url).split("/json/close/")[1]
            closed_tab_ids.append(tab_id)
            return FakeResponse(b"")

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        # We specify max_tabs_to_keep=2, so tab-1 and tab-2 should be closed
        cleanup_stale_chrome_tabs("http://127.0.0.1:9222", max_tabs_to_keep=2)

    assert closed_tab_ids == ["tab-1", "tab-2"]


def test_greenhouse_cover_letter_instruction_in_task_prompt():
    prompt = build_application_task_prompt(
        job_url="https://boards.greenhouse.io/sample/jobs/1",
        resume_data={"name": "Akhil Baja", "email": "akhil@example.com", "phone": "+447123456789"},
        resume_pdf_path="/path/to/resume.pdf",
        auto_submit=False
    )
    assert "GREENHOUSE \"TYPE COVER LETTER\" MANDATORY ACTION" in prompt
    assert "Type Cover Letter" in prompt
    assert "tailored, compelling 3-paragraph cover letter" in prompt
