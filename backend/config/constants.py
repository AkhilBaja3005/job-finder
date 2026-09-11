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
