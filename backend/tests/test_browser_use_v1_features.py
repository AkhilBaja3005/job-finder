"""
Unit test suite for browser-use 1.0+ and GPT Luna integration in job-finder.
Validates:
1. Local Browser Explicit Guard (CDP URL attachment and local Chromium).
2. Sensitive credentials masking via sensitive_data and type_secret support.
3. Luna decision engine selection when OPENAI_API_KEY is present vs Gemini fallback.
4. Fast DOM vs Vision reasoning tier configuration in browser-use 1.0.
"""

import os
import pytest
from unittest.mock import patch, MagicMock


def test_browser_use_v1_local_browser_guard():
    """Ensures get_or_create_browser_session explicitly binds to local CDP with keep_alive=True."""
    from backend.services.browser_use_agent import get_or_create_browser_session

    with patch("backend.services.browser_use_agent.ensure_persistent_browser", return_value="http://127.0.0.1:9222"), \
         patch("backend.services.browser_use_agent.cleanup_stale_chrome_tabs", return_value=None), \
         patch("backend.services.browser_use_agent.Browser") as mock_browser_cls:

        mock_instance = MagicMock()
        mock_browser_cls.return_value = mock_instance

        browser = get_or_create_browser_session(headless=True)
        mock_browser_cls.assert_called_once_with(
            cdp_url="http://127.0.0.1:9222",
            headless=True,
            keep_alive=True,
        )
        assert browser == mock_instance


def test_browser_use_v1_sensitive_data_shielding():
    """Ensures candidate credentials and phone numbers are bundled into sensitive_data for type_secret."""
    from backend.services.browser_use_agent import run_browser_use_autofill

    captured_fast_kwargs = {}
    captured_vision_kwargs = {}

    class DummyAgent:
        def __init__(self, **kwargs):
            if kwargs.get("use_vision") is False:
                captured_fast_kwargs.update(kwargs)
            else:
                captured_vision_kwargs.update(kwargs)

        async def run(self, max_steps=50):
            mock_hist = MagicMock()
            mock_hist.is_done.return_value = True
            mock_hist.final_result.return_value = "SUBMISSION_CONFIRMED: Application submitted."
            mock_hist.history = [1, 2]
            return mock_hist

    mock_llm = MagicMock()
    mock_llm.model = "gemini-3.5-flash-lite"

    resume_payload = {
        "name": "Alex Candidate",
        "email": "alex@example.com",
        "phone": "+1-555-019-2834",
        "password": "SuperSecretPassword99!",
    }

    with patch("backend.services.browser_use_agent.preflight_check_job_url", return_value=("https://boards.greenhouse.io/test/jobs/1", True, None)), \
         patch("backend.services.browser_use_agent.get_browser_use_llm", return_value=mock_llm), \
         patch("backend.services.browser_use_agent.get_or_create_browser_session", return_value=MagicMock()), \
         patch("backend.services.browser_use_agent.MultiFallbackAgent", DummyAgent), \
         patch("backend.services.browser_use_agent.Agent", DummyAgent):

        import asyncio
        res = asyncio.run(run_browser_use_autofill(
            job_url="https://boards.greenhouse.io/test/jobs/1",
            resume_data=resume_payload,
            auto_submit=True,
        ))

        assert res["status"] == "success"
        sensitive_data = captured_fast_kwargs.get("sensitive_data")
        assert sensitive_data is not None
        assert sensitive_data["candidate_password"] == "SuperSecretPassword99!"
        assert sensitive_data["candidate_phone"] == "+1-555-019-2834"


def test_browser_use_llm_luna_priority_with_openai_key():
    """Validates that get_browser_use_llm selects GPT-6 Luna when OPENAI_API_KEY is available."""
    from backend.services.browser_use_agent import get_browser_use_llm

    with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test-key-luna-12345"}, clear=False), \
         patch("backend.services.browser_use_agent.ChatOpenAI") as mock_chat_openai:

        mock_chat_openai.return_value = MagicMock(model="gpt-6-luna")
        llm = get_browser_use_llm()

        mock_chat_openai.assert_called_once_with(
            model="gpt-6-luna",
            api_key="sk-test-key-luna-12345",
            temperature=None,
            frequency_penalty=None,
            reasoning_effort="low",
        )
        assert llm.model == "gpt-6-luna"


def test_browser_use_llm_gemini_fallback_without_openai_key():
    """Validates that get_browser_use_llm falls back to Gemini Flash-Lite when OPENAI_API_KEY is unset."""
    from backend.services.browser_use_agent import get_browser_use_llm

    env_without_openai = dict(os.environ)
    env_without_openai.pop("OPENAI_API_KEY", None)

    with patch.dict(os.environ, env_without_openai, clear=True), \
         patch("services.gemini_client.get_next_gemini_api_key", return_value="gemini-test-key"), \
         patch("backend.services.browser_use_agent.ChatGoogle") as mock_chat_google, \
         patch("backend.services.browser_use_agent.get_best_flash_lite_model", return_value="gemini-3.5-flash-lite"):

        mock_chat_google.return_value = MagicMock(model="gemini-3.5-flash-lite")
        llm = get_browser_use_llm()

        mock_chat_google.assert_called_once_with(
            model="gemini-3.5-flash-lite",
            api_key="gemini-test-key",
        )
        assert llm.model == "gemini-3.5-flash-lite"
