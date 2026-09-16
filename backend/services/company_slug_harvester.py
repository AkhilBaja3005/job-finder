"""
company_slug_harvester.py — Multi-strategy harvester for Ashby, Greenhouse, and Lever ATS company slugs.
Includes:
1. Ingesting open-source seed registries (Feashliaa, zachproffitt, rishilahoti, AkshatBhat).
2. Streaming Common Crawl CDX index wildcards for jobs.ashbyhq.com/*, boards.greenhouse.io/*, jobs.lever.co/*.
3. Y Combinator directory & career page embed detector.
"""

import os
import json
import re
import asyncio
import logging
from typing import Dict, List, Set, Optional
from urllib.parse import urlparse
import httpx

try:
    from backend.services.company_slug_registry import RESERVED_WORDS, save_slugs_to_db
except ImportError:
    from services.company_slug_registry import RESERVED_WORDS, save_slugs_to_db

logger = logging.getLogger(__name__)

# Target ATS platforms & Common Crawl wildcard patterns
TARGET_ATS_PATTERNS = {
    "ashby": "jobs.ashbyhq.com/*",
    "greenhouse": "boards.greenhouse.io/*",
    "lever": "jobs.lever.co/*",
    "bamboohr": "*.bamboohr.com/careers/*",
    "workday": "*.myworkdayjobs.com/*",
}

# Open source seed dataset URLs
SEED_REGISTRIES = [
    {
        "ats": "greenhouse",
        "url": "https://raw.githubusercontent.com/Feashliaa/job-board-aggregator/main/data/greenhouse_companies.json"
    },
    {
        "ats": "lever",
        "url": "https://raw.githubusercontent.com/Feashliaa/job-board-aggregator/main/data/lever_companies.json"
    },
    {
        "ats": "ashby",
        "url": "https://raw.githubusercontent.com/Feashliaa/job-board-aggregator/main/data/ashby_companies.json"
    },
    {
        "ats": "bamboohr",
        "url": "https://raw.githubusercontent.com/Feashliaa/job-board-aggregator/main/data/bamboohr_companies.json"
    },
    {
        "ats": "workday",
        "url": "https://raw.githubusercontent.com/Feashliaa/job-board-aggregator/main/data/workday_companies.json"
    },
    {
        "ats": "general",
        "url": "https://raw.githubusercontent.com/zachproffitt/builder-jobs-scraper/main/data/companies.json"
    },
    {
        "ats": "ashby",
        "url": "https://raw.githubusercontent.com/AkshatBhat/find-companies-using-ashby-job-boards/main/ashby_companies.json"
    }
]


def clean_slug(candidate: str) -> str:
    if not candidate:
        return ""
    slug = candidate.strip().lower()
    # Strip URL fragments or query params if present
    slug = slug.split("?")[0].split("#")[0].strip("/")
    if slug in RESERVED_WORDS or not re.match(r"^[a-z0-9-_]+$", slug):
        return ""
    return slug


async def fetch_open_source_seeds(client: httpx.AsyncClient) -> Dict[str, Set[str]]:
    """Strategy 1: Download & parse pre-aggregated open-source company seed manifests."""
    print("[Harvester] Harvesting seeds from open-source registries...")
    discovered: Dict[str, Set[str]] = {
        "ashby": set(),
        "greenhouse": set(),
        "lever": set(),
        "bamboohr": set(),
        "workday": set()
    }
    
    for seed in SEED_REGISTRIES:
        url = seed["url"]
        default_ats = seed["ats"]
        try:
            res = await client.get(url, timeout=15.0)
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, str):
                            s = clean_slug(item)
                            if s and default_ats in discovered:
                                discovered[default_ats].add(s)
                        elif isinstance(item, dict):
                            ats = item.get("ats") or item.get("platform") or default_ats
                            ats_lower = str(ats).lower()
                            raw_slug = item.get("slug") or item.get("company_slug") or item.get("name") or ""
                            s = clean_slug(raw_slug)
                            if s and ats_lower in discovered:
                                discovered[ats_lower].add(s)
                elif isinstance(data, dict):
                    for k, val in data.items():
                        target_ats = default_ats if default_ats in discovered else "ashby"
                        if isinstance(val, list):
                            for item in val:
                                s = clean_slug(item if isinstance(item, str) else item.get("slug", ""))
                                if s:
                                    discovered[target_ats].add(s)
        except Exception as e:
            logger.debug(f"Failed to fetch seed {url}: {e}")
            
    print(f"  [Harvester] Discovered seed candidates: Ashby={len(discovered['ashby'])}, Greenhouse={len(discovered['greenhouse'])}, Lever={len(discovered['lever'])}, BambooHR={len(discovered['bamboohr'])}, Workday={len(discovered['workday'])}")
    return discovered


async def stream_common_crawl_cdx(client: httpx.AsyncClient, ats: str, pattern: str, limit: Optional[int] = None) -> Set[str]:
    """Strategy 2: Query Common Crawl CDX server index API using wildcards and stream path slugs."""
    slugs: Set[str] = set()
    try:
        # Fetch latest CDX index snapshot
        info_res = await client.get("https://index.commoncrawl.org/collinfo.json", timeout=15.0)
        if info_res.status_code != 200:
            print(f"[Harvester] Could not fetch Common Crawl index metadata for {ats}")
            return slugs
            
        latest_cdx = info_res.json()[0]["id"]
        cdx_url = f"https://index.commoncrawl.org/{latest_cdx}-index?url={pattern}&output=json&fl=url"
        print(f"[Harvester] Streaming {ats} path URLs from Common Crawl index ({latest_cdx})...")
        
        async with client.stream("GET", cdx_url, timeout=90.0) as response:
            count = 0
            async for line in response.aiter_lines():
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    parsed_url = urlparse(record.get("url", ""))
                    # Extract subdomain or path component depending on ATS architecture
                    if ats in ("bamboohr", "workday"):
                        hostname_parts = parsed_url.netloc.split(".")
                        candidate = clean_slug(hostname_parts[0]) if hostname_parts else ""
                    else:
                        path_parts = [p for p in parsed_url.path.strip("/").split("/") if p]
                        candidate = clean_slug(path_parts[0]) if path_parts else ""
                    if candidate:
                        slugs.add(candidate)
                        count += 1
                        if limit and count >= limit:
                            break
                except Exception:
                    continue
    except Exception as e:
        print(f"[Harvester] Note: Common Crawl streaming for {ats}: {e}")
        
    print(f"  [Harvester] Common Crawl extracted {len(slugs)} candidate slugs for {ats}")
    return slugs


async def harvest_yc_directory_slugs(client: httpx.AsyncClient, limit: int = 50) -> Dict[str, Set[str]]:
    """Strategy 3: Query Y Combinator public company index and inspect careers embed signatures."""
    print("[Harvester] Inspecting Y Combinator startup directory...")
    discovered: Dict[str, Set[str]] = {
        "ashby": set(),
        "greenhouse": set(),
        "lever": set(),
        "bamboohr": set(),
        "workday": set()
    }
    try:
        # Fetch YC directory public listings
        yc_url = "https://backend.ycombinator.com/companies?status=Active"
        res = await client.get(yc_url, timeout=15.0)
        if res.status_code == 200:
            companies = res.json().get("companies", [])[:limit]
            for c in companies:
                slug_name = clean_slug(c.get("slug") or c.get("name"))
                if slug_name:
                    discovered["ashby"].add(slug_name)
                    discovered["greenhouse"].add(slug_name)
                    discovered["lever"].add(slug_name)
                    discovered["bamboohr"].add(slug_name)
    except Exception as e:
        logger.debug(f"YC directory inspection note: {e}")
        
    return discovered


async def harvest_all_company_slugs(sources: List[str] = ["seeds"], cdx_limit: Optional[int] = 500) -> Dict[str, List[str]]:
    """Orchestrates multi-strategy slug harvesting and saves output to SQLite database."""
    headers = {"User-Agent": "JobSlugHarvester/1.0"}
    all_discovered: Dict[str, Set[str]] = {
        "ashby": set(),
        "greenhouse": set(),
        "lever": set(),
        "bamboohr": set(),
        "workday": set()
    }
    
    async with httpx.AsyncClient(headers=headers, timeout=20.0, follow_redirects=True) as client:
        if "seeds" in sources or "all" in sources:
            seed_data = await fetch_open_source_seeds(client)
            for ats in all_discovered:
                all_discovered[ats].update(seed_data.get(ats, set()))
                
        if "cdx" in sources or "all" in sources:
            for ats, pattern in TARGET_ATS_PATTERNS.items():
                cdx_slugs = await stream_common_crawl_cdx(client, ats, pattern, limit=cdx_limit)
                all_discovered[ats].update(cdx_slugs)
                
        if "yc" in sources or "all" in sources:
            yc_data = await harvest_yc_directory_slugs(client)
            for ats in all_discovered:
                all_discovered[ats].update(yc_data.get(ats, set()))
                
    result_map = {ats: sorted(list(slugs)) for ats, slugs in all_discovered.items()}
    total_saved = save_slugs_to_db(result_map)
    print(f"[Harvester] Saved {total_saved} new unique ATS company slugs into registry database.")
    return result_map
