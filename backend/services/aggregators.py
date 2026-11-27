"""
aggregators.py - official job-aggregator APIs (they need a free API key, so they are optional).

  Adzuna  https://developer.adzuna.com/   (free: ADZUNA_APP_ID + ADZUNA_APP_KEY in .env)  -> UK jobs from many boards
  Reed    https://www.reed.co.uk/developers (free: REED_API_KEY in .env)                   -> used by the existing scanner

These are the sanctioned way to read many job boards at once; scraping Glassdoor, Monster, CV-Library, Milkround or
Gradcracker is blocked by their bot protection and terms of service, so they are deliberately not included.
"""

import asyncio
import os
import re
from typing import Any, Dict, List, Optional

import httpx

ADZUNA_URL = "https://api.adzuna.com/v1/api/jobs/gb/search/{page}"
_DAYS = {"24h": 1, "48h": 2, "1w": 7, "1m": 30}


def adzuna_configured() -> bool:
    return bool(os.getenv("ADZUNA_APP_ID") and os.getenv("ADZUNA_APP_KEY"))


def _city(location: str) -> str:
    return (location or "London").split(",")[0].strip() or "London"


def _parse_adzuna(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for r in (payload or {}).get("results", []) or []:
        url, title = r.get("redirect_url"), r.get("title")
        if not url or not title:
            continue
        out.append({
            "title": re.sub(r"</?strong>", "", str(title)).strip(),
            "company": ((r.get("company") or {}).get("display_name") or "Company"),
            "location": ((r.get("location") or {}).get("display_name") or ""),
            "url": url, "platform": "Adzuna", "source": "Adzuna", "posted_date": r.get("created") or "",
            "description": "", "estimated": True,          # Adzuna only returns a snippet: the scan fetches the full posting
            "ats_score": 50,
        })
    return out


async def search_adzuna(queries: List[str], location: str, timeframe: str = "1m", per_query: int = 50,
                        client: Optional[httpx.AsyncClient] = None) -> List[Dict[str, Any]]:
    """One search per query. Returns [] (silently) when no key is configured or the API fails."""
    if not adzuna_configured():
        return []
    own = client is None
    client = client or httpx.AsyncClient(timeout=20.0)
    app_id, app_key = os.getenv("ADZUNA_APP_ID"), os.getenv("ADZUNA_APP_KEY")
    days = _DAYS.get(timeframe)

    async def one(q: str):
        params = {"app_id": app_id, "app_key": app_key, "what": q, "where": _city(location),
                  "results_per_page": per_query, "sort_by": "date", "content-type": "application/json"}
        if days:
            params["max_days_old"] = days
        try:
            r = await client.get(ADZUNA_URL.format(page=1), params=params)
            return _parse_adzuna(r.json()) if r.status_code == 200 else []
        except Exception:
            return []
    try:
        batches = await asyncio.gather(*[one(q) for q in queries])
    finally:
        if own:
            await client.aclose()
    seen, out = set(), []
    for batch in batches:
        for j in batch:
            if j["url"] not in seen:
                seen.add(j["url"])
                out.append(j)
    return out
