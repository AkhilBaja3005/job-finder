"""
test_prefilled_fields_preservation.py
Unit test suite verifying that pre-filled form fields are preserved and not overwritten.
"""

import os
import sys
import pytest
import asyncio
from unittest.mock import patch, AsyncMock, MagicMock
from backend.services.browser_use_agent import build_application_task_prompt
from backend.services.autofill_agent import fill_visible_fields


def test_task_prompt_contains_prefilled_preservation_rules():
    """Verifies that the LLM agent prompt strictly enforces preserving already auto-filled fields."""
    sample_resume = {
        "name": "Jane Developer",
        "email": "jane@example.com",
        "phone": "+44 7123 456789",
        "location": "London, UK"
    }
    prompt = build_application_task_prompt("https://example.com/job/1", sample_resume)

    # Verify critical rules for preserving prefilled fields
    assert "PRESERVE ALREADY AUTO-FILLED FIELDS" in prompt
    assert "DO NOT clear, re-type, or overwrite it" in prompt
    assert "Leave it untouched and immediately proceed to the next field" in prompt
    assert "PRE-FILLED FIELDS CHECK" in prompt
    assert "leave it as-is. Do not re-type into it" in prompt


def test_autofill_skips_prefilled_input():
    """Verifies that fill_visible_fields skips an input that is already populated."""
    async def run_test():
        mock_page = AsyncMock()
        mock_input = AsyncMock()

        mock_input.is_visible.return_value = True
        mock_input.get_attribute.side_effect = lambda attr: {
            "data-autofilled": None,
            "type": "text",
            "id": "first_name",
            "name": "first_name"
        }.get(attr, "")
        mock_input.evaluate_handle.return_value = None
        mock_page.evaluate.return_value = ""

        # Simulate JS evaluate: element has an existing value 'Pre-filled Jane'
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

        # Input should NOT have fill called because it was already pre-filled
        mock_input.fill.assert_not_called()
        # It should have marked data-autofilled to keep session tidy
        calls = [str(c) for c in mock_input.evaluate.call_args_list]
        assert any("setAttribute('data-autofilled', 'true')" in c for c in calls)
        assert "first_name" in session_filled

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
