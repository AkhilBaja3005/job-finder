"""
Unified Model Context Protocol (MCP) Server for Job Finder & Career Engine.
Supports JSON-RPC 2.0 over Stdio (Claude Code, Cursor, Gemini CLI) and SSE.
"""

import sys
import os
import json
import asyncio
import traceback
from typing import Dict, Any, List, Optional

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp.tools.discovery_tools import DISCOVERY_TOOLS_SPEC, handle_search_jobs, handle_scrape_job_posting
from mcp.tools.ats_tools import ATS_TOOLS_SPEC, handle_calculate_ats_score, handle_analyze_skill_gap, handle_extract_seniority_salary
from mcp.tools.resume_tools import RESUME_TOOLS_SPEC, handle_tailor_resume_latex, handle_compile_latex_metrics, handle_export_overleaf_bundle, handle_parse_and_convert_to_latex
from mcp.tools.networking_tools import NETWORKING_TOOLS_SPEC, handle_extract_recruiter_profile, handle_generate_outreach_inmail
from mcp.tools.interview_tools import INTERVIEW_TOOLS_SPEC, handle_generate_interview_pack, handle_company_culture_brief
from mcp.tools.tracking_tools import TRACKING_TOOLS_SPEC, handle_track_application, handle_list_applications, handle_check_duplicate_application
from mcp.tools.profile_tools import PROFILE_TOOLS_SPEC, handle_save_candidate_profile, handle_get_candidate_profile, handle_sync_candidate_profile_from_resume
from mcp.tools.autofill_tools import AUTOFILL_TOOLS_SPEC, handle_apply_to_job_browser, handle_pipeline_auto_apply

ALL_TOOLS = (
    DISCOVERY_TOOLS_SPEC
    + ATS_TOOLS_SPEC
    + RESUME_TOOLS_SPEC
    + NETWORKING_TOOLS_SPEC
    + INTERVIEW_TOOLS_SPEC
    + TRACKING_TOOLS_SPEC
    + PROFILE_TOOLS_SPEC
    + AUTOFILL_TOOLS_SPEC
)

HANDLERS = {
    "search_jobs": handle_search_jobs,
    "scrape_job_posting": handle_scrape_job_posting,
    "calculate_ats_score": handle_calculate_ats_score,
    "analyze_skill_gap": handle_analyze_skill_gap,
    "extract_seniority_salary": handle_extract_seniority_salary,
    "tailor_resume_latex": handle_tailor_resume_latex,
    "compile_latex_metrics": handle_compile_latex_metrics,
    "export_overleaf_bundle": handle_export_overleaf_bundle,
    "parse_and_convert_to_latex": handle_parse_and_convert_to_latex,
    "extract_recruiter_profile": handle_extract_recruiter_profile,
    "generate_outreach_inmail": handle_generate_outreach_inmail,
    "generate_interview_pack": handle_generate_interview_pack,
    "company_culture_brief": handle_company_culture_brief,
    "track_application": handle_track_application,
    "list_applications": handle_list_applications,
    "check_duplicate_application": handle_check_duplicate_application,
    "save_candidate_profile": handle_save_candidate_profile,
    "get_candidate_profile": handle_get_candidate_profile,
    "sync_candidate_profile_from_resume": handle_sync_candidate_profile_from_resume,
    "apply_to_job_browser": handle_apply_to_job_browser,
    "pipeline_auto_apply": handle_pipeline_auto_apply,
}


async def process_mcp_request(request: Dict[str, Any]) -> Dict[str, Any]:
    req_id = request.get("id")
    method = request.get("method")
    params = request.get("params", {})

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {"listChanged": False}
                },
                "serverInfo": {
                    "name": "job-finder-career-engine",
                    "version": "1.0.0"
                }
            }
        }

    elif method == "notifications/initialized":
        return {}

    elif method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": ALL_TOOLS
            }
        }

    elif method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        handler = HANDLERS.get(tool_name)

        if not handler:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32601,
                    "message": f"Tool '{tool_name}' not found."
                }
            }

        try:
            result = await handler(arguments)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2)
                        }
                    ]
                }
            }
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "isError": True,
                    "content": [
                        {
                            "type": "text",
                            "text": f"Error executing tool '{tool_name}': {str(e)}\n{traceback.format_exc()}"
                        }
                    ]
                }
            }

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {
            "code": -32601,
            "message": f"Method '{method}' not implemented."
        }
    }


async def run_stdio_server():
    """Runs the MCP server over standard input/output for CLI agents."""
    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)

    while True:
        line = await reader.readline()
        if not line:
            break

        line_str = line.decode("utf-8").strip()
        if not line_str:
            continue

        try:
            req = json.loads(line_str)
            resp = await process_mcp_request(req)
            if resp is not None:
                sys.stdout.write(json.dumps(resp) + "\n")
                sys.stdout.flush()
        except Exception as err:
            err_resp = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {str(err)}"}
            }
            sys.stdout.write(json.dumps(err_resp) + "\n")
            sys.stdout.flush()


def main():
    """CLI entrypoint for MCP server."""
    asyncio.run(run_stdio_server())


if __name__ == "__main__":
    main()
