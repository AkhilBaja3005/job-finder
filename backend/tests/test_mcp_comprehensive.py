"""
test_mcp_comprehensive.py — Pytest wrapper for full MCP server and Skills suite.
Executes all 21 MCP tool protocol assertions and 8 Agent Skill frontmatter checks.
"""

import pytest
import asyncio
from mcp.comprehensive_test import test_all_mcp_tools as _run_all_mcp_tools, test_all_skills as _run_all_skills

pytestmark = pytest.mark.slow


@pytest.mark.asyncio
async def test_mcp_tools_and_skills_suite():
    """Runs end-to-end integration test suite for all MCP tools and Agent Skills."""
    await _run_all_mcp_tools()
    _run_all_skills()
