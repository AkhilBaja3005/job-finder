"""
constants.py — Centralized configuration for Job Finder application version and AI model tiers.
Updating models or versions here propagates throughout the backend automatically.
"""

import os
from typing import List

# ── Application Version ──────────────────────────────────────────────────────────
# Single source of truth for application & extension version
APP_VERSION = "3.1.0"
APP_NAME = "AI Job Finder Agent"

# ── Gemini Model Hierarchy & Catalog ─────────────────────────────────────────────
# When new Gemini versions release, prepend/configure them here.
# Models are ordered by priority: Fast-lite models first for sub-second execution & high RPM,
# followed by strong reasoning models for complex LaTeX and deep role analysis.

DEFAULT_FAST_LITE_MODELS: List[str] = [
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash-lite",
    "gemini-3.5-flash",
    "gemini-2.5-flash",
]

DEFAULT_STRONG_MODELS: List[str] = [
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.0-flash",
    "gemini-2.5-flash",
    "gemini-3.5-flash-lite",
]

DEFAULT_GROUNDED_SEARCH_MODELS: List[str] = [
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
]

# Allow overriding via environment variable (e.g. GEMINI_PREFERRED_MODEL=gemini-3.5-flash-lite)
PREFERRED_GEMINI_MODEL = os.getenv("GEMINI_PREFERRED_MODEL", "gemini-3.5-flash-lite")

# RPM Limits mapped dynamically. Default for unknown flash models is 10 RPM.
MODEL_RPM_LIMITS = {
    "gemini-3.5-flash-lite": 15,
    "gemini-3.1-flash-lite": 15,
    "gemini-2.5-flash-lite": 10,
    "gemini-3.8-flash": 5,
    "gemini-3.7-flash": 5,
    "gemini-3.6-flash": 5,
    "gemini-3.5-flash": 5,
    "gemini-3.0-flash": 5,
    "gemini-2.5-flash": 5,
}
