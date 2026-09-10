"""
test_browser_use_prototype.py — Unit and integration tests for browser-use Gemini agent.
"""

import pytest
import os
from services.browser_use_agent import build_application_task_prompt, get_browser_use_llm

def test_build_application_task_prompt():
    sample_resume = {
        "name": "Jane Developer",
        "email": "jane@example.com",
        "phone": "+44 7123 456789",
        "location": "London, UK",
        "linkedin": "https://linkedin.com/in/janedev",
        "github": "https://github.com/janedev",
        "summary": "Senior AI Infrastructure Engineer with expertise in PyTorch and vLLM."
    }
    job_url = "https://job-boards.greenhouse.io/sample/jobs/12345"
    prompt = build_application_task_prompt(job_url, sample_resume)
    
    assert job_url in prompt
    assert "Jane Developer" in prompt
    assert "jane@example.com" in prompt
    assert "+44 7123 456789" in prompt
    assert "SAFETY GUARDRAIL" in prompt
    assert "DO NOT click final 'Submit Application'" in prompt

def test_get_browser_use_llm_structure():
    # Verify client instantiation with fallback
    fake_key = "AIzaSyFakeKeyForTest123456789"
    llm = get_browser_use_llm(model_name="gemini-3.5-flash-lite", custom_api_key=fake_key)
    assert llm is not None
    assert llm.model == "gemini-3.5-flash-lite"
