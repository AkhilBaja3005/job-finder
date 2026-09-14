"""
test_prefilled_fields_preservation.py
Unit test suite verifying that pre-filled form fields are overwritten with authoritative
candidate profile data (to replace outdated autofill info), while prefilled fields without
profile overrides are preserved.
"""

import os
import sys
import pytest
import asyncio
from unittest.mock import patch, AsyncMock, MagicMock
from backend.services.browser_use_agent import build_application_task_prompt
from backend.services.autofill_agent import fill_visible_fields


def test_task_prompt_contains_outdated_overwrite_rules():
    """Verifies that the LLM agent prompt enforces overwriting outdated pre-filled fields with candidate profile data."""
    sample_resume = {
        "name": "Jane Developer",
        "email": "jane@example.com",
        "phone": "+44 7123 456789",
        "location": "London, UK"
    }
    prompt = build_application_task_prompt("https://example.com/job/1", sample_resume)

    # Verify critical rules for replacing outdated prefilled data
    assert "OVERWRITE OUTDATED PRE-FILLED FIELDS WITH CANDIDATE PROFILE DATA" in prompt
    assert "CLEAR the existing text in that field and replace it with our profile value" in prompt
    assert "PRE-FILLED FIELDS & OUTDATED DATA OVERWRITE RULE" in prompt
    assert "clear and re-enter our profile value to guarantee the application uses current data" in prompt
    assert "leave it as-is without clearing it" in prompt


def test_autofill_replaces_prefilled_field_when_profile_has_value():
    """Verifies that fill_visible_fields clears and replaces a pre-filled field if candidate profile has data."""
    async def run_test():
        mock_page = AsyncMock()
        mock_input = AsyncMock()

        mock_input.is_visible.return_value = True
        mock_input.get_attribute.side_effect = lambda attr: {
            "data-autofilled": None,
            "type": "text",
            "id": "firstname",
            "name": "firstname"
        }.get(attr, "")
        mock_input.evaluate_handle.return_value = None
        mock_page.evaluate.return_value = ""

        # Simulate JS evaluate: element already has an outdated prefilled value
        async def evaluate_side_effect(script, *args):
            if "selectedOptions" in script or "value.trim()" in script:
                return True  # is_prefilled is True
            return ""
        mock_input.evaluate.side_effect = evaluate_side_effect

        mock_page.query_selector_all.return_value = [mock_input]
        mock_page.query_selector.return_value = None

        session_filled = set()
        resume_data = {"name": "Jane Doe", "email": "jane@example.com"}

        await fill_visible_fields(
            page=mock_page,
            resume_data=resume_data,
            resume_pdf_path="/path/to/resume.pdf",
            session_filled_questions=session_filled
        )

        # Pre-filled field SHOULD be replaced with the current candidate profile name
        mock_input.fill.assert_called_once_with("Jane")
        # It should have marked data-autofilled
        calls = [str(c) for c in mock_input.evaluate.call_args_list]
        assert any("setAttribute('data-autofilled', 'true')" in c for c in calls)
        assert "firstname" in session_filled

    asyncio.run(run_test())


def test_autofill_preserves_prefilled_field_when_no_profile_override():
    """Verifies that fill_visible_fields leaves a prefilled field untouched when there's no candidate profile value."""
    async def run_test():
        mock_page = AsyncMock()
        mock_input = AsyncMock()

        mock_input.is_visible.return_value = True
        # Custom/unknown question not in candidate profile
        mock_input.get_attribute.side_effect = lambda attr: {
            "data-autofilled": None,
            "type": "text",
            "id": "how_did_you_hear",
            "name": "how_did_you_hear"
        }.get(attr, "")
        mock_input.evaluate_handle.return_value = None
        mock_page.evaluate.return_value = ""

        # Simulate JS evaluate: element is prefilled
        async def evaluate_side_effect(script, *args):
            if "selectedOptions" in script or "value.trim()" in script:
                return True  # is_prefilled is True
            return ""
        mock_input.evaluate.side_effect = evaluate_side_effect

        mock_page.query_selector_all.return_value = [mock_input]
        mock_page.query_selector.return_value = None

        session_filled = set()
        resume_data = {"name": "Jane Doe", "email": "jane@example.com"}

        await fill_visible_fields(
            page=mock_page,
            resume_data=resume_data,
            resume_pdf_path="/path/to/resume.pdf",
            session_filled_questions=session_filled
        )

        # Because we don't have a value for this unknown field, do NOT call fill (preserve it)
        mock_input.fill.assert_not_called()
        assert "how_did_you_hear" in session_filled

    asyncio.run(run_test())


def test_autofill_populates_empty_input():
    """Verifies that fill_visible_fields populates an empty input field."""
    async def run_test():
        mock_page = AsyncMock()
        mock_input = AsyncMock()

        mock_input.is_visible.return_value = True
        mock_input.get_attribute.side_effect = lambda attr: {
            "data-autofilled": None,
            "type": "text",
            "id": "firstname",
            "name": "firstname"
        }.get(attr, "")
        mock_input.evaluate_handle.return_value = None
        mock_page.evaluate.return_value = ""

        # Simulate JS evaluate: input is empty
        async def evaluate_side_effect(script, *args):
            if "selectedOptions" in script or "value.trim()" in script:
                return False  # is_prefilled is False
            return ""
        mock_input.evaluate.side_effect = evaluate_side_effect

        mock_page.query_selector_all.return_value = [mock_input]
        mock_page.query_selector.return_value = None

        session_filled = set()
        resume_data = {"name": "Jane Doe", "email": "jane@example.com"}

        await fill_visible_fields(
            page=mock_page,
            resume_data=resume_data,
            resume_pdf_path="/path/to/resume.pdf",
            session_filled_questions=session_filled
        )

        # Empty input SHOULD be filled with the candidate's first name
        mock_input.fill.assert_called_once_with("Jane")
        assert "firstname" in session_filled

    asyncio.run(run_test())


def test_task_prompt_contains_workday_prompt_button_rules():
    """Verifies that the LLM agent prompt contains explicit handling for Workday prompt buttons and Enter key."""
    sample_resume = {
        "name": "Jane Developer",
        "email": "jane@example.com",
        "phone": "+44 7123 456789",
        "location": "London, UK"
    }
    prompt = build_application_task_prompt("https://example.com/job/1", sample_resume)

    assert "WORKDAY PROMPT BUTTONS (TRIPLE-BAR / 3 DOTS / HAMBURGER MENU) HANDLING" in prompt
    assert "WORKDAY PROMPT BUTTON RULE" in prompt
    assert "Press 'Enter' immediately to trigger the menu search/filter" in prompt
    assert "How did you hear about this job?" in prompt
    assert "LinkedIn Corporate Jobs" in prompt


def test_autofill_presses_enter_on_prompt_combobox_field():
    """Verifies that fill_visible_fields types and presses Enter on prompt/combobox fields."""
    async def run_test():
        mock_page = AsyncMock()
        mock_input = AsyncMock()

        mock_input.is_visible.return_value = True
        mock_input.get_attribute.side_effect = lambda attr: {
            "data-autofilled": None,
            "type": "text",
            "id": "source_channel",
            "name": "source_channel"
        }.get(attr, "")
        mock_input.evaluate_handle.return_value = None
        mock_page.evaluate.return_value = ""

        # JS evaluate: input is empty initially, and is a combobox/prompt field
        async def evaluate_side_effect(script, *args):
            if "selectedOptions" in script or "value.trim()" in script:
                return False  # not prefilled
            if "is_prompt_or_combobox" in script or "aria-haspopup" in script or "combobox" in script:
                return True
            return ""
        mock_input.evaluate.side_effect = evaluate_side_effect

        mock_page.query_selector_all.return_value = [mock_input]
        mock_page.query_selector.return_value = None

        session_filled = set()
        resume_data = {"name": "Jane Doe", "email": "jane@example.com"}

        with patch("backend.services.autofill_agent.get_answer_from_llm", return_value="LinkedIn"):
            await fill_visible_fields(
                page=mock_page,
                resume_data=resume_data,
                resume_pdf_path="/path/to/resume.pdf",
                session_filled_questions=session_filled
            )

        # It should fill the text AND press Enter on the prompt button input
        mock_input.fill.assert_called_once_with("LinkedIn")
        mock_input.press.assert_called_once_with("Enter")
        assert "source_channel" in session_filled

    asyncio.run(run_test())

