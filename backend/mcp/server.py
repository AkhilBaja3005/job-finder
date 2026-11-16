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

_RAW_TOOLS = (
    DISCOVERY_TOOLS_SPEC
    + ATS_TOOLS_SPEC
    + RESUME_TOOLS_SPEC
    + NETWORKING_TOOLS_SPEC
    + INTERVIEW_TOOLS_SPEC
    + TRACKING_TOOLS_SPEC
    + PROFILE_TOOLS_SPEC
    + AUTOFILL_TOOLS_SPEC
)

SUBMIT_TOOLS = {"apply_to_job_browser", "pipeline_auto_apply"}
WRITE_TOOLS = {
    "track_application", "save_candidate_profile", "sync_candidate_profile_from_resume",
    "tailor_resume_latex", "export_overleaf_bundle", "parse_and_convert_to_latex",
    "compile_latex_metrics",
} | SUBMIT_TOOLS

SUPPORTED_PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")


def _with_annotations(tool: Dict[str, Any]) -> Dict[str, Any]:
    spec = dict(tool)
    name = spec["name"]
    spec["annotations"] = {
        "readOnlyHint": name not in WRITE_TOOLS,
        "destructiveHint": name in SUBMIT_TOOLS,
        "openWorldHint": True,
    }
    if name in SUBMIT_TOOLS:
        schema = json.loads(json.dumps(spec.get("inputSchema", {})))
        schema.setdefault("properties", {})["confirm_submit"] = {
            "type": "boolean",
            "description": "Must be true together with auto_submit to actually submit. Otherwise the run stops at the review step.",
            "default": False,
        }
        spec["inputSchema"] = schema
    return spec


ALL_TOOLS = [_with_annotations(t) for t in _RAW_TOOLS]
_TOOL_SCHEMAS = {t["name"]: t.get("inputSchema", {}) for t in ALL_TOOLS}


def _server_version() -> str:
    try:
        from importlib.metadata import version
        return version("job-finder-ai")
    except Exception:
        return "unknown"


def _log(msg: str) -> None:
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()

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


async def process_mcp_request(request: Dict[str, Any], user_token: Optional[str] = None) -> Optional[Dict[str, Any]]:
    req_id = request.get("id")
    method = request.get("method")
    params = request.get("params", {})

    if method == "initialize":
        requested = params.get("protocolVersion")
        negotiated = requested if requested in SUPPORTED_PROTOCOLS else SUPPORTED_PROTOCOLS[0]
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": negotiated,
                "capabilities": {
                    "tools": {"listChanged": False}
                },
                "serverInfo": {
                    "name": "job-finder-career-engine",
                    "version": _server_version()
                }
            }
        }

    elif method in ("notifications/initialized", "initialized"):
        # Notifications do not have an 'id' and MUST NOT receive a response in JSON-RPC 2.0
        return None

    elif method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

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
        arguments = dict(params.get("arguments", {}))

        # Automatically inject authenticated user_token into tool arguments if not already specified
        if user_token and not arguments.get("token"):
            arguments["token"] = user_token

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

        missing = [k for k in _TOOL_SCHEMAS.get(tool_name, {}).get("required", []) if arguments.get(k) in (None, "")]
        if missing:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32602, "message": f"Missing required argument(s) for '{tool_name}': {', '.join(missing)}"}
            }

        notice = None
        if tool_name in SUBMIT_TOOLS and arguments.get("auto_submit") and not arguments.get("confirm_submit"):
            arguments["auto_submit"] = False
            notice = "auto_submit ignored: pass confirm_submit=true to submit. Run stopped at the review step."
        arguments.pop("confirm_submit", None)

        try:
            result = await handler(arguments)
            if notice and isinstance(result, dict):
                result["notice"] = notice
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
            _log(f"Tool '{tool_name}' failed:\n{traceback.format_exc()}")
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "isError": True,
                    "content": [
                        {
                            "type": "text",
                            "text": f"Error executing tool '{tool_name}': {e}"
                        }
                    ]
                }
            }

    # If it is a notification (no 'id'), do not send any response back
    if req_id is None:
        return None

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
    if sys.stdin.isatty():
        sys.stderr.write(
            "Job Finder MCP Server is running over STDIO (JSON-RPC 2.0).\n"
            "Waiting for JSON-RPC messages from Cursor, Claude Code, Gemini CLI, or Antigravity.\n"
            "Press Ctrl+C to stop.\n"
        )
        sys.stderr.flush()

    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader(limit=16 * 1024 * 1024)
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)

    write_lock = asyncio.Lock()
    tasks: set = set()

    async def send(payload: Dict[str, Any]) -> None:
        async with write_lock:
            sys.stdout.write(json.dumps(payload) + "\n")
            sys.stdout.flush()

    async def handle(req: Dict[str, Any]) -> None:
        try:
            resp = await process_mcp_request(req)
        except Exception as err:
            _log(f"Internal error:\n{traceback.format_exc()}")
            if req.get("id") is None:
                return
            resp = {"jsonrpc": "2.0", "id": req.get("id"),
                    "error": {"code": -32603, "message": f"Internal error: {err}"}}
        if resp is not None:
            await send(resp)

    while True:
        line = await reader.readline()
        if not line:
            break

        line_str = line.decode("utf-8").strip()
        if not line_str:
            continue

        try:
            req = json.loads(line_str)
        except json.JSONDecodeError as err:
            await send({"jsonrpc": "2.0", "id": None,
                        "error": {"code": -32700, "message": f"Parse error: {err}"}})
            continue

        if not isinstance(req, dict):
            await send({"jsonrpc": "2.0", "id": None,
                        "error": {"code": -32600, "message": "Invalid Request"}})
            continue

        task = asyncio.create_task(handle(req))
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


def main():
    """CLI entrypoint for MCP server."""
    asyncio.run(run_stdio_server())


if __name__ == "__main__":
    main()
