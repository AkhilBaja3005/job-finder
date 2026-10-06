#!/usr/bin/env python3
"""
verify_tier1_ats_slugs.py — Exhaustive Validator for Ashby, Greenhouse & Lever Slugs.

Validates ALL 15,000+ candidate slugs across:
- Ashby (2,969 candidate slugs)
- Greenhouse (8,111 candidate slugs)
- Lever (4,209 candidate slugs)
"""

import os
import sys
import asyncio
import sqlite3
import httpx
from datetime import datetime, timezone
from typing import Dict, List, Tuple

sys.path.insert(0, os.path.abspath("backend"))
from services.company_slug_registry import get_db_path

PLATFORMS = {
    "ashby": {
        "url_template": "https://api.ashbyhq.com/posting-api/job-board/{slug}",
        "concurrency": 40,
        "rate_delay": 0.015,
        "max_conn": 60,
    },
    "greenhouse": {
        "url_template": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
        "concurrency": 50,
        "rate_delay": 0.01,
        "max_conn": 75,
    },
    "lever": {
        "url_template": "https://api.lever.co/v0/postings/{slug}?mode=json",
        "concurrency": 35,
        "rate_delay": 0.02,
        "max_conn": 50,
    }
}


async def validate_single(client: httpx.AsyncClient, ats: str, slug: str, url_tmpl: str, sem: asyncio.Semaphore, delay: float) -> Tuple[str, str, bool, int]:
    async with sem:
        if delay > 0:
            await asyncio.sleep(delay)
        url = url_tmpl.format(slug=slug)
        try:
            res = await client.get(url, timeout=7.0, follow_redirects=True)
            if res.status_code == 200:
                data = res.json()
                cnt = 0
                if ats == "ashby":
                    jobs = data.get("jobs", [])
                    cnt = len(jobs) if isinstance(jobs, list) else 0
                elif ats == "greenhouse":
                    jobs = data.get("jobs", [])
                    cnt = len(jobs) if isinstance(jobs, list) else 0
                elif ats == "lever":
                    cnt = len(data) if isinstance(data, list) else 0
                return (ats, slug, True, cnt)
        except Exception:
            pass
    return (ats, slug, False, 0)


async def run_platform(ats: str, slugs: List[str], db_path: str):
    cfg = PLATFORMS[ats]
    total = len(slugs)
    print(f"\n{'=' * 65}")
    print(f"🚀 Exhaustively validating all {total} [{ats.upper()}] slugs (Concurrency={cfg['concurrency']})...")
    print(f"{'=' * 65}")

    sem = asyncio.Semaphore(cfg["concurrency"])
    limits = httpx.Limits(max_keepalive_connections=cfg["max_conn"], max_connections=cfg["max_conn"])
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) JobFinderATSValidator/3.0"}

    active_count = 0
    processed = 0
    chunk_size = 400

    conn = sqlite3.connect(db_path, timeout=60.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")

    async with httpx.AsyncClient(headers=headers, limits=limits, timeout=8.0) as client:
        for i in range(0, total, chunk_size):
            chunk = slugs[i:i + chunk_size]
            tasks = [validate_single(client, ats, s, cfg["url_template"], sem, cfg["rate_delay"]) for s in chunk]
            results = await asyncio.gather(*tasks)

            now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            updates = []
            for r_ats, r_slug, is_act, j_cnt in results:
                updates.append((1 if is_act else 0, j_cnt, now_str, r_ats, r_slug))
                if is_act:
                    active_count += 1

            conn.executemany("""
                UPDATE company_slugs
                SET is_active = ?, job_count = ?, last_checked = ?
                WHERE ats = ? AND slug = ?
            """, updates)
            conn.commit()

            processed += len(chunk)
            pct = int((processed / total) * 100)
            print(f"  [{ats.upper()}] [{pct:>3}%] {processed:>5}/{total} processed — Confirmed Active so far: {active_count}")

    conn.close()
    print(f"✓ [{ats.upper()}] All {total} slugs validated! Total Confirmed Active: {active_count}\n")


async def main():
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    for ats in ["ashby", "lever", "greenhouse"]:
        cur.execute("SELECT slug FROM company_slugs WHERE ats = ? AND is_active = 0", (ats,))
        candidate_slugs = [r[0] for r in cur.fetchall()]
        if candidate_slugs:
            await run_platform(ats, candidate_slugs, db_path)

    # Print final tally
    cur.execute("SELECT ats, is_active, COUNT(*) FROM company_slugs WHERE ats IN ('ashby', 'greenhouse', 'lever') GROUP BY ats, is_active")
    rows = cur.fetchall()
    conn.close()

    print("=" * 65)
    print(" 🏁 FINAL DIRECT ATS VERIFIED SLUG TOTALS")
    print("=" * 65)
    for ats, is_act, count in rows:
        status = "ACTIVE (Verified)" if is_act == 1 else "Inactive / Stale"
        print(f"  • {ats.capitalize():<12} | {status:<18} | {count:>5} boards")
    print("=" * 65)


if __name__ == "__main__":
    asyncio.run(main())
