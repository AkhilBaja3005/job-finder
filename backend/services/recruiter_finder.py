"""
recruiter_finder.py — Discover verified recruiters and hiring managers using Gemini Search Grounding.
"""

import os
import re
import json
import time
from typing import Dict, Any, List, Optional
from services.gemini_client import call_gemini_grounded

# In-memory cache with 7-day TTL to conserve Grounding API calls
_recruiter_cache: Dict[str, Dict[str, Any]] = {}
CACHE_TTL_SECONDS = 7 * 24 * 3600  # 7 days


def _make_cache_key(company: str, role: str, location: str) -> str:
    c = re.sub(r"\b(inc|ltd|llc|corp|corporation)\b", "", company.lower()).strip().rstrip(",")
    c = re.sub(r"[^a-zA-Z0-9]", "", c)
    r = re.sub(r"[^a-zA-Z0-9]", "", role.lower())
    l = re.sub(r"[^a-zA-Z0-9]", "", (location or "").lower())
    return f"{c}:{r}:{l}"


def find_recruiter_for_job(
    company: str,
    role: str,
    location: str = "",
    custom_api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Discovers recruiters, talent acquisition leads, or engineering hiring managers
    for a given company and role using Google Search Grounding.
    """
    if not company or not company.strip():
        return {
            "status": "error",
            "message": "Company name is required.",
            "recruiters": [],
            "citations": []
        }

    company_clean = company.strip()
    role_clean = (role or "Software Engineer").strip()
    loc_clean = (location or "Remote").strip()

    cache_key = _make_cache_key(company_clean, role_clean, loc_clean)
    cached_entry = _recruiter_cache.get(cache_key)
    if cached_entry and (time.time() - cached_entry.get("timestamp", 0) < CACHE_TTL_SECONDS):
        return cached_entry["data"]

    prompt = f"""
Use Google Search to find current talent acquisition recruiters, technical sourcers, or engineering hiring managers at {company_clean} who hire for {role_clean} (location: {loc_clean}).

Search LinkedIn specifically for real people currently in these roles.
Extract 1 to 3 relevant contacts.

Return STRICT JSON matching this exact structure:
{{
  "company": "{company_clean}",
  "role": "{role_clean}",
  "recruiters": [
    {{
      "name": "Full Name",
      "title": "Exact Current Title at {company_clean}",
      "profile_url": "https://www.linkedin.com/in/username",
      "relevance": "Why this person is relevant to {role_clean}"
    }}
  ],
  "summary": "Brief 1-2 sentence overview of hiring contacts found."
}}
"""

    try:
        grounded_resp = call_gemini_grounded(prompt=prompt, custom_api_key=custom_api_key)
        raw_text = grounded_resp.get("text", "")
        citations = grounded_resp.get("citations", [])
        queries = grounded_resp.get("queries", [])

        # Parse JSON from response
        clean_json_str = raw_text.strip()
        if "```json" in clean_json_str:
            clean_json_str = clean_json_str.split("```json", 1)[1].split("```", 1)[0].strip()
        elif "```" in clean_json_str:
            clean_json_str = clean_json_str.split("```", 1)[1].split("```", 1)[0].strip()

        data: Dict[str, Any] = {}
        try:
            data = json.loads(clean_json_str)
        except Exception:
            match = re.search(r"\{.*\}", clean_json_str, re.DOTALL)
            if match:
                data = json.loads(match.group(0))

        recruiters: List[Dict[str, str]] = data.get("recruiters", [])
        summary: str = data.get("summary", f"Found {len(recruiters)} hiring contacts at {company_clean}.")

        result = {
            "status": "success",
            "company": company_clean,
            "role": role_clean,
            "recruiters": recruiters,
            "summary": summary,
            "citations": citations,
            "search_queries": queries,
            "grounded": grounded_resp.get("grounded", False)
        }

        # Cache successful search
        _recruiter_cache[cache_key] = {
            "timestamp": time.time(),
            "data": result
        }

        return result
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to discover recruiters via Grounding: {str(e)}",
            "company": company_clean,
            "role": role_clean,
            "recruiters": [],
            "citations": []
        }
