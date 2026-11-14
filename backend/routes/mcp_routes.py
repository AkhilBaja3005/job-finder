"""
FastAPI HTTP / SSE MCP Transport Router.
Exposes Model Context Protocol endpoints over HTTP and SSE for web agents (Claude.ai Custom Connectors, etc.).
"""

import json
import asyncio
from typing import Optional
from fastapi import APIRouter, Request, Response
from fastapi.responses import StreamingResponse, JSONResponse
from mcp.server import process_mcp_request, ALL_TOOLS

router = APIRouter(prefix="/mcp", tags=["Model Context Protocol"])


def _extract_auth_token(request: Request) -> Optional[str]:
    """
    Extracts user session token or sync code from:
    1. Authorization header ('Bearer <token>')
    2. X-User-Token header
    3. Query parameter (?token=<token> or ?sync_code=<code>)
    """
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if auth and auth.strip():
        parts = auth.strip().split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1].strip()
        elif len(parts) == 1:
            return parts[0].strip()

    x_token = request.headers.get("x-user-token") or request.headers.get("X-User-Token")
    if x_token and x_token.strip():
        return x_token.strip()

    q_token = request.query_params.get("token") or request.query_params.get("sync_code")
    if q_token and q_token.strip():
        return q_token.strip()

    return None


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
        user_token = _extract_auth_token(request)
        body = await request.json()
        response = await process_mcp_request(body, user_token=user_token)
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
    # Ensure HTTPS for public web connectors (Claude.ai rejects plain http)
    base_url = str(request.base_url).rstrip("/")
    if base_url.startswith("http://"):
        base_url = "https://" + base_url[len("http://"):]
    forwarded_host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""

    user_token = _extract_auth_token(request)
    token_suffix = f"?token={user_token}" if user_token else ""

    if forwarded_host:
        messages_endpoint = f"https://{forwarded_host}/mcp/messages{token_suffix}"
    else:
        messages_endpoint = f"{base_url}/mcp/messages{token_suffix}"

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

