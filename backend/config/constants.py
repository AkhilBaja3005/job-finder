"""
constants.py — Centralized configuration for Job Finder application version and AI model tiers.
Updating models or versions here propagates throughout the backend automatically.
"""

import os
import re
import time
from typing import List, Dict, Optional, Tuple, Any

# ── Application Version ──────────────────────────────────────────────────────────
# Single source of truth for application & extension version
APP_VERSION = "3.1.0"
APP_NAME = "AI Job Finder Agent"

# ── Workspace & User Data Root Resolution ─────────────────────────────────────────
def resolve_workspace_root() -> str:
    """
    Determines the workspace root for candidate data, tracker history, and outputs.
    Guarantees user data is NEVER saved inside .venv, site-packages, or python library folders.
    Order of precedence:
      1. Explicit JOB_FINDER_ROOT environment variable (if set and not empty).
      2. Hugging Face /data persistent mount (if present and writable).
      3. Current working directory (os.getcwd()), IF the package is executing from inside
         site-packages, dist-packages, or a virtual environment (.venv/venv).
      4. Repository root (if running from source checkout).
    """
    explicit = os.getenv("JOB_FINDER_ROOT")
    if explicit and explicit.strip():
        return os.path.abspath(explicit.strip())

    # Hugging Face Spaces persistent volume
    if os.path.exists("/data") and os.access("/data", os.W_OK):
        return "/data"

    # Inspect location of this file
    this_file = os.path.abspath(__file__)
    parts = this_file.split(os.sep)
    is_installed_pkg = any(p in parts for p in ("site-packages", "dist-packages", ".venv", "venv"))

    if is_installed_pkg:
        # Running as installed package: save user data to current working directory
        return os.path.abspath(os.getcwd())

    # Running from source checkout: backend/config/constants.py -> backend -> repo root
    repo_candidate = os.path.dirname(os.path.dirname(os.path.dirname(this_file)))
    return repo_candidate

def get_applications_tracker_dir() -> str:
    """Returns directory path for applications tracking ledger and tailored resumes."""
    ws = resolve_workspace_root()
    d = os.path.join(ws, "applications_tracker")
    return d

def get_tailored_resumes_dir() -> str:
    """Returns directory path for generated tailored resumes (.pdf and .tex)."""
    t_dir = get_applications_tracker_dir()
    d = os.path.join(t_dir, "tailored_resumes")
    return d

def get_tracker_csv_path() -> str:
    """Returns path to the job applications CSV spreadsheet."""
    t_dir = get_applications_tracker_dir()
    return os.path.join(t_dir, "job_applications_tracker.csv")

def get_output_dir() -> str:
    """Returns output directory for resume outputs and per-user session history."""
    ws = resolve_workspace_root()
    d = os.path.join(ws, "output")
    return d


# ── Fallback Model Catalog (Guaranteed Flash Models, Strictly No Pro) ────────────
# Used if offline or prior to API discovery
DEFAULT_FAST_LITE_MODELS: List[str] = [
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash-lite",
    "gemini-3.5-flash",
]

DEFAULT_STRONG_MODELS: List[str] = [
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.0-flash",
    "gemini-3.5-flash-lite",
]

DEFAULT_GROUNDED_SEARCH_MODELS: List[str] = [
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
]

# Allow overriding via environment variable
PREFERRED_GEMINI_MODEL = os.getenv("GEMINI_PREFERRED_MODEL", "gemini-3.5-flash-lite")

# RPM Limits mapped dynamically. Default for unknown flash models is 10 RPM.
MODEL_RPM_LIMITS: Dict[str, int] = {
    "gemini-3.5-flash-lite": 15,
    "gemini-3.1-flash-lite": 15,
    "gemini-2.5-flash-lite": 10,
    "gemini-3.8-flash": 10,
    "gemini-3.7-flash": 10,
    "gemini-3.6-flash": 10,
    "gemini-3.5-flash": 10,
    "gemini-3.0-flash": 10,
}

# ── Dynamic Model Discovery Engine ───────────────────────────────────────────────
_DISCOVERED_CACHE: Dict[str, Any] = {
    "timestamp": 0.0,
    "lite_models": list(DEFAULT_FAST_LITE_MODELS),
    "strong_models": list(DEFAULT_STRONG_MODELS),
}
_DISCOVERY_TTL_SECONDS = 3600  # Refresh model list once per hour


def _extract_gemini_version(name: str) -> float:
    """Extracts numeric version from model name like 'gemini-3.8-flash' -> 3.8"""
    m = re.search(r"gemini-(\d+(?:\.\d+)?)", name)
    return float(m.group(1)) if m else 0.0


def discover_gemini_models(api_key: Optional[str] = None) -> Tuple[List[str], List[str]]:
    """
    Dynamically queries the Google Gemini API to discover active models.
    Categorizes them by use case (Fast-Lite vs Flagship Flash), sorted newest-first.
    
    CRITICAL POLICY:
    - NEVER selects 'pro' models (avoids latency spikes and restrictive rate limits).
    - Filters out single-purpose preview endpoints (audio, tts, robotics, transcribe).
    - Caches results for 1 hour to ensure zero runtime latency overhead.
    """
    global _DISCOVERED_CACHE
    now = time.time()
    if now - _DISCOVERED_CACHE["timestamp"] < _DISCOVERY_TTL_SECONDS and _DISCOVERED_CACHE["lite_models"]:
        return _DISCOVERED_CACHE["lite_models"], _DISCOVERED_CACHE["strong_models"]

    effective_key = api_key or os.getenv("GEMINI_API_KEY")
    if not effective_key:
        return DEFAULT_FAST_LITE_MODELS, DEFAULT_STRONG_MODELS

    try:
        from google import genai
        client = genai.Client(api_key=effective_key)
        raw_models = [str(m.name).replace("models/", "") for m in client.models.list() if m and getattr(m, "name", None)]

        # Non-conversational / auxiliary markers to exclude
        exclude_tags = ("pro", "image", "tts", "preview", "live", "audio", "robotics", "transcribe", "embedding")

        # 1. Lite Tier: Specifically flash-lite models, sorted newest first
        lite_candidates = [
            m for m in raw_models
            if "flash-lite" in m and not any(tag in m for tag in ("pro", "image", "tts", "audio", "transcribe", "embedding"))
        ]
        lite_candidates.sort(key=_extract_gemini_version, reverse=True)

        # 2. Strong Flash Tier: Flagship Flash models (Strictly NO PRO), sorted newest first
        strong_candidates = [
            m for m in raw_models
            if "flash" in m and not any(tag in m for tag in ("pro", "image", "tts", "audio", "robotics", "transcribe", "embedding"))
        ]
        strong_candidates.sort(key=_extract_gemini_version, reverse=True)

        # Ensure fallbacks if API returned empty
        final_lite = lite_candidates if lite_candidates else DEFAULT_FAST_LITE_MODELS
        final_strong = strong_candidates if strong_candidates else DEFAULT_STRONG_MODELS

        _DISCOVERED_CACHE["timestamp"] = now
        _DISCOVERED_CACHE["lite_models"] = final_lite
        _DISCOVERED_CACHE["strong_models"] = final_strong

        # Update dynamic RPM limits for any newly discovered models
        for m in final_lite:
            if m not in MODEL_RPM_LIMITS:
                MODEL_RPM_LIMITS[m] = 15
        for m in final_strong:
            if m not in MODEL_RPM_LIMITS:
                MODEL_RPM_LIMITS[m] = 10

        return final_lite, final_strong
    except Exception as e:
        # Graceful fallback to static defaults
        return DEFAULT_FAST_LITE_MODELS, DEFAULT_STRONG_MODELS


def get_best_flash_lite_model(api_key: Optional[str] = None) -> str:
    """Returns the newest available Gemini Flash-Lite model (e.g. gemini-3.5-flash-lite)."""
    lite, _ = discover_gemini_models(api_key)
    return lite[0] if lite else "gemini-3.5-flash-lite"


def get_best_flash_model(api_key: Optional[str] = None) -> str:
    """Returns the newest available flagship Gemini Flash model (e.g. gemini-3.8-flash), strictly excluding Pro."""
    _, strong = discover_gemini_models(api_key)
    return strong[0] if strong else "gemini-3.8-flash"
