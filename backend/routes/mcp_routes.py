"""
FastAPI HTTP / SSE MCP Transport Router.
Exposes Model Context Protocol endpoints over HTTP and SSE for web agents.
"""

import json
import asyncio
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse, JSONResponse
from mcp.server import process_mcp_request, ALL_TOOLS

router = APIRouter(prefix="/mcp", tags=["Model Context Protocol"])


@router.get("/tools")
async def list_tools_endpoint():
    """Direct HTTP endpoint for agent harnesses to inspect registered tools."""
    return {"tools": ALL_TOOLS}


@router.post("/messages")
async def handle_mcp_message(request: Request):
    """Standard JSON-RPC 2.0 message handler for MCP over HTTP."""
    try:
        body = await request.json()
        response = await process_mcp_request(body)
        if response is not None:
            return JSONResponse(content=response)
        return JSONResponse(content={"status": "ok"})
    except Exception as e:
        return JSONResponse(
            status_code=400,
            content={"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(e)}}
        )


@router.get("/sse")
async def mcp_sse_endpoint():
    """SSE streaming endpoint for remote MCP clients."""
    async def event_generator():
        # Yield initial endpoint registration notification
        endpoint_event = {
            "type": "endpoint",
            "uri": "/mcp/messages"
        }
        yield f"event: endpoint\ndata: /mcp/messages\n\n"
        while True:
            await asyncio.sleep(15)
            yield f": ping\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive"
        }
    )
