import os
import json
import glob
import queue
import threading
import asyncio
from typing import Optional, Tuple, Any, Dict, List
from services.auth import get_user_by_token

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
USER_DATA_DIR = os.path.join(BASE_DIR, "user_data")

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(USER_DATA_DIR, exist_ok=True)

# Central thread-safe in-memory session store
_session_store: dict = {}
_store_lock = threading.Lock()

# Central LLM Client log queue
LLMClientLogQueue: queue.Queue = queue.Queue()


def _safe_key(token: Any) -> str:
    """Sanitize a token or guest ID for use as a filesystem directory name."""
    if token is None:
        return "guest"
    raw = str(token).strip()
    if not raw:
        return "guest"
    return "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in raw)


def _get_user_storage_dirs(user_id: str) -> Tuple[str, str]:
    """Return (upload_dir, output_dir) dedicated to a single user_id."""
    key = _safe_key(user_id)
    user_upload_dir = os.path.join(USER_DATA_DIR, key, "uploads")
    user_output_dir = os.path.join(USER_DATA_DIR, key, "output")
    os.makedirs(user_upload_dir, exist_ok=True)
    os.makedirs(user_output_dir, exist_ok=True)
    return user_upload_dir, user_output_dir


def _user_output_paths(token: Optional[str]) -> Tuple[str, str]:
    """Return per-user tex/pdf output paths inside the user's dedicated output subdirectory."""
    key = _safe_key(token)
    _, user_out_dir = _get_user_storage_dirs(key)
    tex_path = os.path.join(user_out_dir, f"tailored_resume_{key}.tex")
    pdf_path = os.path.join(user_out_dir, f"tailored_resume_{key}.pdf")
    return tex_path, pdf_path


def drain_llm_logs() -> list:
    """Non-blocking drain of all currently-queued LLM client log messages."""
    messages = []
    while True:
        try:
            msg = LLMClientLogQueue.get(block=False)
        except queue.Empty:
            break
        except Exception as e:
            print(f"[drain_llm_logs] Unexpected error draining log queue: {e}")
            break
        messages.append(msg)
    return messages


def _format_log_event(msg: str) -> str:
    """Turns one raw LLMClientLogQueue message into an SSE-ready JSON line."""
    try:
        parsed = json.loads(msg)
        if parsed.get("type") == "llm_warn":
            return json.dumps({"type": "llm_warn", "message": parsed.get("message"), "model": parsed.get("model", ""), "wait_s": parsed.get("wait_s", 10)}) + "\n"
        return json.dumps({"type": "log", "message": parsed.get("message")}) + "\n"
    except Exception:
        if "429" in msg or "rate limit" in msg.lower() or "Rate limit" in msg:
            return json.dumps({"type": "llm_warn", "message": msg, "model": "", "wait_s": 10}) + "\n"
        return json.dumps({"type": "log", "message": msg}) + "\n"


async def _stream_task_logs(task: asyncio.Task):
    """Polls drain_llm_logs() every 0.5s and yields formatted SSE lines until task completes."""
    while not task.done():
        for msg in drain_llm_logs():
            yield _format_log_event(msg)
        await asyncio.sleep(0.5)


def _drain_remaining_logs():
    """Formats any log messages left in the queue after a task has completed."""
    return [_format_log_event(msg) for msg in drain_llm_logs()]


def get_session_data(token: Optional[str]) -> dict:
    key = token or "guest"
    with _store_lock:
        data = _session_store.get(key)
        if data and data.get("data") and data["data"].get("education"):
            return data

    # Try fetching from Supabase if token exists
    if token:
        try:
            user = get_user_by_token(token)
            if user:
                user_id = user.get("id")
                from services.auth import supabase_request
                res = supabase_request(f"user_resumes?user_id=eq.{user_id}", "GET")
                if res and len(res) > 0:
                    raw_rdata = res[0].get("resume_data", {})
                    resume_dict = json.loads(raw_rdata) if isinstance(raw_rdata, str) else (raw_rdata or {})
                    path = ""
                    master_latex = res[0].get("master_latex", "")
                    if master_latex:
                        user_up_dir, _ = _get_user_storage_dirs(user_id)
                        path = os.path.join(user_up_dir, f"{user_id}_master.tex")
                        with open(path, "w", encoding="utf-8") as f:
                            f.write(master_latex)
                    with _store_lock:
                        _session_store[token] = {"data": resume_dict, "path": path}
                    return {"data": resume_dict, "path": path}
        except Exception as e:
            print(f"Failed to load resume from Supabase user session: {e}")

    # Search output directory for the latest complete state file
    try:
        state_files = glob.glob(os.path.join(OUTPUT_DIR, "**", "resume_state_*.json"), recursive=True)
        for sf in sorted(state_files, key=os.path.getmtime, reverse=True):
            with open(sf, "r", encoding="utf-8") as f:
                content = json.load(f)
                d = content.get("data", {})
                if d and d.get("education"):
                    set_session_data(key, d, content.get("path", ""))
                    return {"data": d, "path": content.get("path", "")}
    except Exception as ex:
        print(f"[get_session_data] Error searching state files: {ex}")

    # Fallback to guest if user session is empty
    with _store_lock:
        return _session_store.get("guest", {"data": {}, "path": ""})


def set_session_data(token: Optional[str], data: dict, path: str):
    key = token or "guest"
    with _store_lock:
        _session_store[key] = {"data": data, "path": path}

    if token:
        master_latex = ""
        if path and os.path.exists(path) and path.endswith(".tex"):
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    master_latex = f.read()
            except Exception as e:
                print(f"Failed to read master latex: {e}")

        try:
            user = get_user_by_token(token)
            if user and user.get("id") and not str(user.get("id")).startswith("guest_"):
                user_id = user["id"]
                from services.auth import supabase_request
                existing = supabase_request(f"user_resumes?user_id=eq.{user_id}", "GET")
                record = {
                    "user_id": user_id,
                    "resume_data": data,
                    "master_latex": master_latex,
                    "updated_at": "now()"
                }
                if existing and len(existing) > 0:
                    supabase_request(f"user_resumes?user_id=eq.{user_id}", "PATCH", record)
                else:
                    supabase_request("user_resumes", "POST", record)
        except Exception as e:
            print(f"Failed to persist resume to Supabase user session: {e}")
