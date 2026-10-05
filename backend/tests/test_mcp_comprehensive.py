"""
test_mcp_comprehensive.py — Pytest wrapper for full MCP server and Skills suite.
Executes all 21 MCP tool protocol assertions and 8 Agent Skill frontmatter checks.
"""

import pytest
import asyncio
from mcp.comprehensive_test import test_all_mcp_tools as _run_all_mcp_tools, test_all_skills as _run_all_skills

pytestmark = pytest.mark.slow


from unittest.mock import patch, AsyncMock

@pytest.mark.slow
@pytest.mark.asyncio
async def test_mcp_tools_and_skills_suite():
    """Runs end-to-end integration test suite for all MCP tools and Agent Skills."""
    mock_latex = r"""\documentclass{resume}
\begin{document}
\begin{rSection}{Technical Skills}
\textbf{Languages:} Python, C++
\end{rSection}
\end{document}"""
    mock_outreach = type("MockOutreach", (), {
        "linkedin_message": "Hi Alex,\n\nI noticed the opening at Stripe and wanted to reach out. As a Senior AI Engineer with Python experience, I'd love to connect.\n\nBest,\nTest User",
        "email_body": "Hi Alex,\n\nI noticed the opening at Stripe...",
        "why_applying": "Why",
        "why_fit": "Fit",
        "questions": ["Q1"],
        "email_subject": "Subject",
        "model_dump": lambda self: {}
    })()

    with patch("services.gemini_client.generate_content_with_fallback", return_value="Generated mock content with required keywords and metrics."):
        with patch("backend.services.gemini_client.generate_content_with_fallback", return_value="Generated mock content with required keywords and metrics."):
            with patch("mcp.tools.interview_tools.generate_content_with_fallback", return_value="Generated mock content with required keywords and metrics."):
                with patch("mcp.tools.resume_tools.tailor_latex_code", return_value=mock_latex):
                    with patch("services.gemini_client.generate_latex_with_strong_model", return_value=mock_latex):
                        with patch("backend.services.gemini_client.generate_latex_with_strong_model", return_value=mock_latex):
                            with patch("services.gemini_client.call_gemini_grounded", return_value={"text": "Mock grounded response", "citations": []}):
                                with patch("mcp.tools.networking_tools.extract_recruiter", new_callable=AsyncMock, return_value={"recruiter_name": "Alex Recruiter", "recruiter_profile_url": "https://linkedin.com/in/alex", "company_name": "Stripe", "platform": "linkedin"}):
                                    with patch("mcp.tools.networking_tools.generate_outreach_message", return_value=mock_outreach):
                                        await _run_all_mcp_tools()
                                        _run_all_skills()
