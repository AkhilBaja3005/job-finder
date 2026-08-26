import os
import asyncio
from typing import Optional
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from services.auth import async_get_user_by_token
from services.log_queue import LLMClientLogQueue
from services.session_store import _safe_key, _get_user_storage_dirs

router = APIRouter(tags=["Admin & Monitoring"])


@router.get("/healthz")
@router.get("/health")
def healthz():
    return {"status": "ok", "service": "job-finder-backend"}


@router.post("/clear_cache")
async def clear_cache(request: Request):
    """Resets user-scoped temporary files and caches."""
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "").strip() if auth_header.startswith("Bearer ") else None

    try:
        user = await async_get_user_by_token(token) if token else None
        user_key = _safe_key(user["id"] if user else token) if (user or token) else "guest"
        _, user_output_dir = _get_user_storage_dirs(user_key)

        if os.path.exists(user_output_dir):
            for filename in os.listdir(user_output_dir):
                if filename.startswith("application_history_"):
                    continue
                file_path = os.path.join(user_output_dir, filename)
                try:
                    if os.path.isfile(file_path) or os.path.islink(file_path):
                        os.unlink(file_path)
                except Exception:
                    pass

        return {"status": "success", "message": "Cache successfully cleared."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/admin/logs", response_class=HTMLResponse)
@router.get("/admin/logs/", response_class=HTMLResponse)
async def admin_logs_dashboard(key: Optional[str] = None):
    """Secure admin live log streaming dashboard URL."""
    admin_key = os.getenv("ADMIN_LOG_KEY", "akhil-admin-secret-123")
    if key != admin_key:
        raise HTTPException(status_code=403, detail="Unauthorized Admin Access")

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Live Server Logs - Job Finder Admin</title>
        <style>
            body {{ background-color: #0F172A; color: #38BDF8; font-family: monospace; padding: 20px; font-size: 13px; }}
            h2 {{ color: #F43F5E; font-family: sans-serif; display: flex; align-items: center; justify-content: space-between; }}
            #logs {{ background: #1E293B; border: 1px solid #334155; border-radius: 8px; padding: 15px; height: 75vh; overflow-y: auto; white-space: pre-wrap; line-height: 1.5; }}
            .btn {{ background: #0284C7; color: white; border: none; padding: 8px 16px; border-radius: 6px; cursor: pointer; font-weight: bold; }}
            .btn:hover {{ background: #0369A1; }}
        </style>
    </head>
    <body>
        <h2>
            <span>🚀 Live Server Logs (Real-time Stream)</span>
            <button class="btn" onclick="document.getElementById('logs').innerText=''">Clear Screen</button>
        </h2>
        <div id="logs">Connecting to live server log stream...</div>
        <script>
            const logDiv = document.getElementById('logs');
            const eventSource = new EventSource('/admin/logs/stream?key={admin_key}');
            
            eventSource.onmessage = function(e) {{
                logDiv.innerText += e.data + "\\n";
                logDiv.scrollTop = logDiv.scrollHeight;
            }};
            
            eventSource.onerror = function() {{
                logDiv.innerText += "\\n[Stream Disconnected. Reconnecting...]\\n";
            }};
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


@router.get("/admin/logs/stream")
async def admin_logs_stream(key: Optional[str] = None):
    admin_key = os.getenv("ADMIN_LOG_KEY", "akhil-admin-secret-123")
    if key != admin_key:
        raise HTTPException(status_code=403, detail="Unauthorized Admin Access")

    async def generate_logs():
        yield "data: 🟢 Connected to Live Admin Log Stream\n\n"
        while True:
            msgs = LLMClientLogQueue.get_all()
            if msgs:
                for msg in msgs:
                    formatted = msg.replace("\n", " ")
                    yield f"data: {formatted}\n\n"
            else:
                yield ": ping\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        generate_logs(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.get("/user/logs/stream")
async def user_logs_stream(request: Request):
    """SSE log stream for the authenticated frontend user."""
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "").strip() if auth_header.startswith("Bearer ") else None
    if not token:
        raise HTTPException(status_code=401, detail="Unauthorized")
    user = await async_get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired session token")

    async def generate_user_logs():
        yield "data: 🟢 Connected to Live Log Stream\n\n"
        while True:
            if await request.is_disconnected():
                break
            msgs = LLMClientLogQueue.get_all()
            if msgs:
                for msg in msgs:
                    formatted = msg.replace("\n", " ")
                    yield f"data: {formatted}\n\n"
            else:
                yield ": ping\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(
        generate_user_logs(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )
