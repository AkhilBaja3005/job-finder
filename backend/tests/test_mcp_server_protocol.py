"""Protocol-level tests for the MCP server dispatcher."""

import asyncio
import pytest

from job_finder_mcp.server import process_mcp_request, ALL_TOOLS


def run(req):
    return asyncio.run(process_mcp_request(req))


def test_ping_returns_empty_result():
    assert run({"jsonrpc": "2.0", "id": 1, "method": "ping"})["result"] == {}


def test_initialize_negotiates_protocol_and_reports_version():
    res = run({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
    assert res["result"]["protocolVersion"] == "2025-06-18"
    assert res["result"]["serverInfo"]["version"] != "1.0.0"
    res = run({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "1999-01-01"}})
    assert res["result"]["protocolVersion"] in ("2025-06-18", "2025-03-26", "2024-11-05")


def test_missing_required_argument_is_invalid_params():
    res = run({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "apply_to_job_browser", "arguments": {}}})
    assert res["error"]["code"] == -32602


def test_unknown_tool_is_method_not_found():
    res = run({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "nope", "arguments": {}}})
    assert res["error"]["code"] == -32601


def test_tool_annotations_present():
    by_name = {t["name"]: t for t in ALL_TOOLS}
    assert by_name["search_jobs"]["annotations"]["readOnlyHint"] is True
    assert by_name["apply_to_job_browser"]["annotations"]["destructiveHint"] is True
    assert "confirm_submit" in by_name["apply_to_job_browser"]["inputSchema"]["properties"]


def test_auto_submit_requires_confirmation(monkeypatch):
    import job_finder_mcp.server as server
    seen = {}

    async def fake(arguments):
        seen.update(arguments)
        return {"ok": True}

    monkeypatch.setitem(server.HANDLERS, "apply_to_job_browser", fake)
    res = run({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
               "params": {"name": "apply_to_job_browser", "arguments": {"job_url": "https://x", "auto_submit": True}}})
    assert seen["auto_submit"] is False
    assert "confirm_submit" in res["result"]["content"][0]["text"]

    seen.clear()
    run({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "apply_to_job_browser", "arguments": {"job_url": "https://x", "auto_submit": True, "confirm_submit": True}}})
    assert seen["auto_submit"] is True


def test_tool_errors_do_not_leak_tracebacks(monkeypatch):
    import job_finder_mcp.server as server

    async def boom(arguments):
        raise RuntimeError("kaboom")

    monkeypatch.setitem(server.HANDLERS, "get_candidate_profile", boom)
    res = run({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "get_candidate_profile", "arguments": {}}})
    text = res["result"]["content"][0]["text"]
    assert "kaboom" in text and "Traceback" not in text
