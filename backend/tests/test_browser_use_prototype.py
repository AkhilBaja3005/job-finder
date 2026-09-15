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
    try:
        from browser_use import Agent
    except (ImportError, Exception) as e:
        pytest.skip(f"browser_use Agent optional dependency not available: {e}")
    from unittest.mock import MagicMock

    mock_llm = MagicMock()
    mock_llm.model = "gemini-3.5-flash-lite"

    # Fast DOM pass: max_history_items must be > 5 (we use 8)
    agent_fast = Agent(
        task="Test autofill",
        llm=mock_llm,
        use_vision=False,
        use_judge=False,
        use_thinking=False,
        max_history_items=8,
        max_actions_per_step=15,
        flash_mode=True,
        enable_planning=False,
        max_failures=2,
        retry_delay=1,
    )
    assert agent_fast.settings.max_history_items == 8
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


def test_discover_gemini_models_excludes_pro():
    """Validates dynamic model discovery strictly excludes all 'pro' models and picks the latest flash models."""
    from config.constants import discover_gemini_models, get_best_flash_lite_model, get_best_flash_model
    from unittest.mock import patch, MagicMock

    mock_client = MagicMock()
    mock_m1 = MagicMock()
    mock_m1.name = "models/gemini-2.5-pro"
    mock_m2 = MagicMock()
    mock_m2.name = "models/gemini-3.5-pro"
    mock_m3 = MagicMock()
    mock_m3.name = "models/gemini-3.8-flash"
    mock_m4 = MagicMock()
    mock_m4.name = "models/gemini-3.5-flash-lite"
    mock_m5 = MagicMock()
    mock_m5.name = "models/gemini-3.1-flash-lite"
    mock_client.models.list.return_value = [mock_m1, mock_m2, mock_m3, mock_m4, mock_m5]

    with patch("google.genai.Client", return_value=mock_client):
        # Force cache refresh with mock
        import config.constants as const
        const._DISCOVERED_CACHE["timestamp"] = 0.0

        lite, strong = discover_gemini_models(api_key="AIzaSyMockKeyForDiscovery")
        
        # Verify NO pro models exist in either tier
        assert not any("pro" in m for m in lite)
        assert not any("pro" in m for m in strong)

        # Verify newest sorted first
        assert lite[0] == "gemini-3.5-flash-lite"
        assert strong[0] == "gemini-3.8-flash"
        assert get_best_flash_lite_model(api_key="AIzaSyMockKeyForDiscovery") == "gemini-3.5-flash-lite"
        assert get_best_flash_model(api_key="AIzaSyMockKeyForDiscovery") == "gemini-3.8-flash"


def test_format_posted_date_time():
    """Validates date; time parsing for relative strings, RFC-822, and standard formats."""
    import sys
    proj_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    tracker_p = os.path.join(proj_root, "applications_tracker")
    if tracker_p not in sys.path:
        sys.path.insert(0, tracker_p)
    from scheduled_job_scanner import format_posted_date_time
    import re

    # Standard regex for YYYY-MM-DD; HH:MM
    dt_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}; \d{2}:\d{2}$")

    # Relative cases
    assert dt_pattern.match(format_posted_date_time("Recent"))
    assert dt_pattern.match(format_posted_date_time("2 hours ago"))
    assert dt_pattern.match(format_posted_date_time("1 day ago"))
    assert dt_pattern.match(format_posted_date_time("30 minutes ago"))
    assert dt_pattern.match(format_posted_date_time("yesterday"))

    # RFC-822
    assert format_posted_date_time("Thu, 10 Sep 2026 14:30:00 GMT") == "2026-09-10; 14:30"

    # Standard ISO
    assert format_posted_date_time("2026-09-11 08:30:00") == "2026-09-11; 08:30"
    assert format_posted_date_time("2026-09-11") == "2026-09-11; 00:00"


def test_adhoc_auto_filler_job_ids_parsing():
    """Validates normalization of raw job IDs and messy inputs into clean LinkedIn URLs."""
    import re
    raw_args = ["4455334729", "4465614142,4464616151", "https://www.linkedin.com/jobs/view/4442843430/"]
    raw_ids = []
    for item in raw_args:
        for sub_id in item.replace(",", " ").split():
            clean_id = sub_id.strip()
            id_match = re.search(r"(\d{8,})", clean_id)
            if id_match:
                raw_ids.append(id_match.group(1))
            elif clean_id.isdigit():
                raw_ids.append(clean_id)

    unique_ids = list(dict.fromkeys(raw_ids))
    assert unique_ids == ["4455334729", "4465614142", "4464616151", "4442843430"]
    urls = [f"https://www.linkedin.com/jobs/view/{jid}/" for jid in unique_ids]
    assert all("linkedin.com/jobs/view/" in u for u in urls)


def test_is_top_applicant_badge():
    """Validates regex matching for various LinkedIn top applicant and competitive badge variations."""
    import sys
    proj_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    tracker_p = os.path.join(proj_root, "applications_tracker")
    if tracker_p not in sys.path:
        sys.path.insert(0, tracker_p)
    from linkedin_top_applicant_scanner import is_top_applicant_badge

    assert is_top_applicant_badge("You’d be a top applicant for this job based on your profile")
    assert is_top_applicant_badge("You'd be a top applicant")
    assert is_top_applicant_badge("In the top 10% of 142 applicants")
    assert is_top_applicant_badge("In the top 25% of applicants")
    assert is_top_applicant_badge("We can help you stand out for this role with Premium")
    assert is_top_applicant_badge("Competitive applicant match")
    assert not is_top_applicant_badge("Regular software engineering job in London")
    assert not is_top_applicant_badge("")


@pytest.mark.asyncio
async def test_top_applicant_bypasses_jd_scoring_and_tailoring():
    """
    Verifies that when a job has is_top_applicant=True, scheduled_job_scanner:
    1. Does NOT call compute_ats_score
    2. Does NOT call scrape_job_description
    3. Does NOT call build_and_compile_tailored_pdf
    4. Directly dispatches application with master_resume_pdf and sets status to 'Top Applicant - Direct Apply'
    """
    from unittest.mock import AsyncMock, patch
    from applications_tracker.scheduled_job_scanner import run_pipeline

    mock_profile = {
        "candidate": {
            "name": "Alex Developer",
            "email": "alex@example.com",
            "phone": "+44 7123 456789",
            "location": "London, UK",
            "core_skills": ["Python", "PyTorch"],
            "work_experience": []
        },
        "search_preferences": {
            "target_roles": ["AI Engineer"],
            "target_locations": ["London, UK"],
            "min_ats_score": 65
        }
    }

    mock_job = {
        "title": "Staff AI Engineer",
        "company": "DeepMind Partner",
        "url": "https://www.linkedin.com/jobs/view/999888777/",
        "is_top_applicant": True,
        "badge_text": "You'd be a top applicant",
        "source": "LinkedIn (Top Applicant)",
        "description": "Short placeholder description"
    }

    dispatched_apps = []

    async def mock_apply_to_job(**kwargs):
        dispatched_apps.append(kwargs)
        return {"status": "success", "final_result": "SUBMITTED"}

    with patch("applications_tracker.scheduled_job_scanner.load_profile_data", return_value=mock_profile), \
         patch("applications_tracker.scheduled_job_scanner.find_master_resume_with_mac_tags", return_value="/dummy/master_resume.pdf"), \
         patch("applications_tracker.scheduled_job_scanner.get_existing_tracked_urls", return_value=set()), \
         patch("applications_tracker.scheduled_job_scanner.handle_search_jobs", new_callable=AsyncMock) as mock_search, \
         patch("services.agent_reach_service.fetch_reddit_hiring_threads", return_value={"community_jobs": []}), \
         patch("applications_tracker.scheduled_job_scanner.scrape_job_description", new_callable=AsyncMock) as mock_scrape, \
         patch("applications_tracker.scheduled_job_scanner.compute_ats_score") as mock_ats, \
         patch("applications_tracker.scheduled_job_scanner.build_and_compile_tailored_pdf") as mock_tailor, \
         patch("applications_tracker.scheduled_job_scanner.apply_to_job", side_effect=mock_apply_to_job), \
         patch("applications_tracker.scheduled_job_scanner.record_to_supabase_or_csv", new_callable=AsyncMock) as mock_record, \
         patch("applications_tracker.scheduled_job_scanner.update_application_status", new_callable=AsyncMock):

        mock_search.return_value = {"jobs": [mock_job], "est_jobs": []}

        await run_pipeline(auto_submit_override=True)

        # 1. Verification: JD scraper, ATS scorer, and LaTeX compiler were NEVER called
        mock_scrape.assert_not_called()
        mock_ats.assert_not_called()
        mock_tailor.assert_not_called()

        # 2. Verification: Application was dispatched directly with master resume
        assert len(dispatched_apps) == 1
        app = dispatched_apps[0]
        assert app["url"] == mock_job["url"]
        assert app["title"] == "Staff AI Engineer"
        assert app["resume_path"] == "/dummy/master_resume.pdf"

        # 3. Verification: Record payload was saved with Top Applicant status and 95 score
        mock_record.assert_called_once()
        recorded = mock_record.call_args[0][0]
        assert recorded["status"] == "Top Applicant - Direct Apply"
        assert recorded["overall_ats"] == 95
        assert recorded["pdf_path"] == "/dummy/master_resume.pdf"


def test_cli_top_applicant_flag_parsing():
    """Validates that CLI parsers in both job-finder scan and scanner_cli recognize --top-applicant."""
    from unittest.mock import AsyncMock, patch
    from job_finder import cli

    test_args = ["scan", "--top-applicant", "--headless"]
    with patch("sys.argv", ["job-finder"] + test_args), \
         patch("applications_tracker.scheduled_job_scanner.run_pipeline", new_callable=AsyncMock) as mock_pipeline:
        try:
            cli.main()
        except SystemExit:
            pass
        mock_pipeline.assert_called_once()
        call_kwargs = mock_pipeline.call_args[1]
        assert call_kwargs.get("top_applicant_only") is True
        assert call_kwargs.get("headless") is True


