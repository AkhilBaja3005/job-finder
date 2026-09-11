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


def test_browser_use_agent_parameters_valid():
    """
    Validates browser-use Agent parameter constraints.
    browser-use enforces: assert max_history_items is None or max_history_items > 5
    Ensures our agent configurations adhere strictly to this constraint.
    """
    from browser_use import Agent
    from unittest.mock import MagicMock

    mock_llm = MagicMock()
    mock_llm.model = "gemini-3.5-flash-lite"

    # Fast DOM pass: max_history_items must be > 5 (we use 6)
    agent_fast = Agent(
        task="Test autofill",
        llm=mock_llm,
        use_vision=False,
        use_judge=False,
        use_thinking=False,
        max_history_items=6,
        max_actions_per_step=15,
        flash_mode=True,
        enable_planning=False,
        max_failures=2,
        retry_delay=1,
    )
    assert agent_fast.settings.max_history_items == 6
    assert agent_fast.settings.max_history_items > 5

    # Vision pass: max_history_items must be > 5 (we use 8)
    agent_vision = Agent(
        task="Test autofill vision",
        llm=mock_llm,
        use_vision=True,
        use_judge=False,
        use_thinking=True,
        max_history_items=8,
        max_actions_per_step=10,
        flash_mode=False,
        enable_planning=True,
        max_failures=2,
        retry_delay=1,
    )
    assert agent_vision.settings.max_history_items == 8
    assert agent_vision.settings.max_history_items > 5

    # Verify that <= 5 raises AssertionError as documented by browser-use
    with pytest.raises(AssertionError, match="max_history_items must be None or greater than 5"):
        Agent(task="Test fail", llm=mock_llm, max_history_items=5)


def test_preflight_check_job_url_closed_or_expired():
    from unittest.mock import patch, MagicMock
    import urllib.error
    from email.message import Message
    from services.browser_use_agent import preflight_check_job_url

    # Test HTTP 404
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="https://example.com/job/1", code=404, msg="Not Found", hdrs=Message(), fp=None
        )
        url, is_active, reason = preflight_check_job_url("https://example.com/job/1")
        assert is_active is False
        assert reason is not None and "404" in reason

    # Test closed marker in content
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_response = MagicMock()
        mock_response.geturl.return_value = "https://example.com/job/closed"
        mock_response.read.return_value = b"<html><body>This job has expired and is no longer accepting applications</body></html>"
        mock_urlopen.return_value.__enter__.return_value = mock_response

        url, is_active, reason = preflight_check_job_url("https://example.com/job/closed")
        assert is_active is False
        assert reason is not None and "expired" in reason.lower()

