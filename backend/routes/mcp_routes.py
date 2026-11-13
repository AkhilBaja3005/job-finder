"""
FastAPI HTTP / SSE MCP Transport Router.
Exposes Model Context Protocol endpoints over HTTP and SSE for web agents (Claude.ai Custom Connectors, etc.).
"""

import json
import asyncio
from fastapi import APIRouter, Request, Response
from fastapi.responses import StreamingResponse, JSONResponse
from mcp.server import process_mcp_request, ALL_TOOLS

router = APIRouter(prefix="/mcp", tags=["Model Context Protocol"])


@router.get("/tools")
async def list_tools_endpoint():
    """Direct HTTP endpoint for agent harnesses to inspect registered tools."""
    return {"tools": ALL_TOOLS}


@router.post("")
@router.post("/")
@router.post("/messages")
async def handle_mcp_message(request: Request):
    """
    Standard JSON-RPC 2.0 message handler for MCP over HTTP.
    Supports Streamable HTTP transport (used by Claude.ai Custom Connectors).
    """
    try:
        body = await request.json()
        response = await process_mcp_request(body)
        if response is not None:
            return JSONResponse(
                content=response,
                headers={"Content-Type": "application/json"}
            )
        return Response(status_code=204)
    except Exception as e:
        return JSONResponse(
            status_code=400,
            content={"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(e)}}
        )


@router.get("")
@router.get("/")
@router.get("/sse")
async def mcp_sse_endpoint(request: Request):
    """
    SSE streaming endpoint for remote MCP clients.
    Serves full absolute URL for message posting in compliance with MCP SSE spec.
    """
    # Build fully-qualified URL for messages endpoint
    base_url = str(request.base_url).rstrip("/")
    # Check if forwarded headers exist (e.g. Hugging Face Spaces proxy)
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    forwarded_host = request.headers.get("x-forwarded-host", "")
    if forwarded_proto and forwarded_host:
        messages_endpoint = f"{forwarded_proto}://{forwarded_host}/mcp/messages"
    elif "hf.space" in base_url or request.headers.get("host", "").endswith(".hf.space"):
        host = request.headers.get("host", "abaja-job-finder.hf.space")
        messages_endpoint = f"https://{host}/mcp/messages"
    else:
        messages_endpoint = f"{base_url}/mcp/messages"

    async def event_generator():
        # Yield initial endpoint registration notification with absolute URI
        yield f"event: endpoint\ndata: {messages_endpoint}\n\n"
        while True:
            await asyncio.sleep(15)
            yield f": ping\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

