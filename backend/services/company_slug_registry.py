"""
company_slug_registry.py — Persistent SQLite storage & async live endpoint validator
for Ashby, Greenhouse, and Lever company board slugs.
"""

import os
import sqlite3
import asyncio
import logging
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse
import httpx

from backend.config.constants import resolve_workspace_root

logger = logging.getLogger(__name__)

# Reserved system keywords to ignore across ATS platforms
RESERVED_WORDS = {
    "api", "assets", "embed", "login", "auth", "static", "terms", 
    "privacy", "job-board", "search", "autocomplete", "v0", "v1",
    "job", "jobs", "careers", "about", "contact", "support", "help",
    "admin", "dashboard", "widget", "iframe", "pricing", "blog"
}

# Live validation endpoint templates & concurrency limits per ATS
VALIDATION_ENDPOINTS = {
    "ashby": {
        "url_template": "https://api.ashbyhq.com/posting-api/job-board/{slug}",
        "max_concurrency": 15,
        "rate_limit_delay": 0.05,
    },
    "greenhouse": {
        "url_template": "https://api.greenhouse.io/v1/boards/{slug}/jobs",
        "max_concurrency": 25,
        "rate_limit_delay": 0.03,
    },
    "lever": {
        "url_template": "https://api.lever.co/v0/postings/{slug}?mode=json",
        "max_concurrency": 10,
        "rate_limit_delay": 0.08,
    }
}


def get_db_path() -> str:
    ws = resolve_workspace_root()
    db_dir = os.path.join(ws, "applications_tracker")
    os.makedirs(db_dir, exist_ok=True)
    return os.path.join(db_dir, "company_slugs.db")


def init_db(db_path: Optional[str] = None) -> None:
    path = db_path or get_db_path()
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS company_slugs (
            ats TEXT NOT NULL,
            slug TEXT NOT NULL,
            is_active INTEGER DEFAULT 0,
            job_count INTEGER DEFAULT 0,
            last_checked TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (ats, slug)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_slugs_active ON company_slugs(ats, is_active)")
    conn.commit()
    conn.close()


def save_slugs_to_db(slug_map: Dict[str, List[str]], db_path: Optional[str] = None) -> int:
    """Saves candidate slugs into the SQLite registry as unchecked (is_active=0)."""
    path = db_path or get_db_path()
    init_db(path)
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    
    total_added = 0
    for ats, slugs in slug_map.items():
        ats_lower = ats.lower()
        for slug in slugs:
            s_clean = slug.strip().lower()
            if not s_clean or s_clean in RESERVED_WORDS:
                continue
            cur.execute("""
                INSERT OR IGNORE INTO company_slugs (ats, slug, is_active, job_count)
                VALUES (?, ?, 0, 0)
            """, (ats_lower, s_clean))
            if cur.rowcount > 0:
                total_added += 1
                
    conn.commit()
    conn.close()
    return total_added


def update_slug_status(ats: str, slug: str, is_active: bool, job_count: int = 0, db_path: Optional[str] = None) -> None:
    path = db_path or get_db_path()
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO company_slugs (ats, slug, is_active, job_count, last_checked)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(ats, slug) DO UPDATE SET
            is_active = excluded.is_active,
            job_count = excluded.job_count,
            last_checked = CURRENT_TIMESTAMP
    """, (ats.lower(), slug.lower(), 1 if is_active else 0, job_count))
    conn.commit()
    conn.close()


def get_active_slugs(ats: Optional[str] = None, db_path: Optional[str] = None) -> Dict[str, List[str]]:
    path = db_path or get_db_path()
    init_db(path)
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    
    if ats:
        cur.execute("SELECT ats, slug FROM company_slugs WHERE is_active = 1 AND ats = ?", (ats.lower(),))
    else:
        cur.execute("SELECT ats, slug FROM company_slugs WHERE is_active = 1")
        
    results: Dict[str, List[str]] = {"ashby": [], "greenhouse": [], "lever": []}
    for r_ats, r_slug in cur.fetchall():
        if r_ats in results:
            results[r_ats].append(r_slug)
        else:
            results[r_ats] = [r_slug]
            
    conn.close()
    return results


async def validate_slug_endpoint(client: httpx.AsyncClient, ats: str, slug: str, semaphore: asyncio.Semaphore) -> Tuple[str, str, bool, int]:
    config = VALIDATION_ENDPOINTS.get(ats.lower())
    if not config:
        return (ats, slug, False, 0)
        
    url = config["url_template"].format(slug=slug)
    delay = config["rate_limit_delay"]
    
    async with semaphore:
        await asyncio.sleep(delay)
        try:
            res = await client.get(url, timeout=10.0, follow_redirects=True)
            if res.status_code == 200:
                data = res.json()
                job_count = 0
                if ats == "ashby":
                    jobs = data.get("jobs", [])
                    job_count = len(jobs) if isinstance(jobs, list) else 0
                elif ats == "greenhouse":
                    jobs = data.get("jobs", [])
                    job_count = len(jobs) if isinstance(jobs, list) else 0
                elif ats == "lever":
                    job_count = len(data) if isinstance(data, list) else 0
                    
                return (ats, slug, True, job_count)
        except Exception as e:
            logger.debug(f"Validation failed for {ats}/{slug}: {e}")
            
    return (ats, slug, False, 0)


async def validate_all_unverified_slugs(ats_filter: Optional[str] = None, limit: Optional[int] = None, db_path: Optional[str] = None) -> Dict[str, int]:
    path = db_path or get_db_path()
    init_db(path)
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    
    if ats_filter:
        cur.execute("SELECT ats, slug FROM company_slugs WHERE is_active = 0 AND ats = ?", (ats_filter.lower(),))
    else:
        cur.execute("SELECT ats, slug FROM company_slugs WHERE is_active = 0")
        
    rows = cur.fetchall()
    conn.close()
    
    if limit and limit > 0:
        rows = rows[:limit]
        
    if not rows:
        return {"verified": 0, "active": 0}
        
    print(f"🔍 Validating {len(rows)} unverified slugs against live ATS endpoints...")
    
    semaphores = {
        ats: asyncio.Semaphore(cfg["max_concurrency"])
        for ats, cfg in VALIDATION_ENDPOINTS.items()
    }
    
    active_count = 0
    headers = {"User-Agent": "JobFinderSlugValidator/1.0"}
    
    async with httpx.AsyncClient(headers=headers, timeout=12.0) as client:
        tasks = []
        for r_ats, r_slug in rows:
            sem = semaphores.get(r_ats, asyncio.Semaphore(10))
            tasks.append(validate_slug_endpoint(client, r_ats, r_slug, sem))
            
        results = await asyncio.gather(*tasks)
        
        for r_ats, r_slug, is_active, job_count in results:
            update_slug_status(r_ats, r_slug, is_active, job_count, db_path=path)
            if is_active:
                active_count += 1
                
    print(f"✅ Live validation completed: {active_count}/{len(rows)} slugs confirmed active!")
    return {"verified": len(rows), "active": active_count}
