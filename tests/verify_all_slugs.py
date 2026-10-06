#!/usr/bin/env python3
"""
verify_all_slugs.py — High-Throughput Parallel ATS Slug Validation Engine.

Validates all unverified company board candidate slugs across:
- Ashby (api.ashbyhq.com)
- Greenhouse (boards-api.greenhouse.io)
- Lever (api.lever.co)
- BambooHR (careers list)
- Workday (Candidate Experience CXS)

Features:
- High-concurrency async connection pools (httpx)
- Bulk SQLite WAL transactions for instant updates
- Real-time progress updates with pass/fail counts
"""

import os
import sys
import asyncio
import sqlite3
import httpx
from datetime import datetime, timezone
from typing import Dict, List, Tuple

sys.path.insert(0, os.path.abspath("backend"))

from services.company_slug_registry import get_db_path, init_db, VALIDATION_ENDPOINTS

CONCURRENCY_CONFIG = {
    "ashby": {"concurrency": 35, "delay": 0.02, "url": "https://api.ashbyhq.com/posting-api/job-board/{slug}"},
    "greenhouse": {"concurrency": 45, "delay": 0.01, "url": "https://api.greenhouse.io/v1/boards/{slug}/jobs"},
    "lever": {"concurrency": 25, "delay": 0.03, "url": "https://api.lever.co/v0/postings/{slug}?mode=json"},
    "bamboohr": {"concurrency": 30, "delay": 0.02, "url": "https://{slug}.bamboohr.com/careers/list"},
    "workday": {"concurrency": 25, "delay": 0.03, "url": "https://{tenant}.{instance}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"},
}


async def validate_slug(client: httpx.AsyncClient, ats: str, slug: str, sem: asyncio.Semaphore) -> Tuple[str, str, bool, int]:
    cfg = CONCURRENCY_CONFIG.get(ats)
    if not cfg:
        return (ats, slug, False, 0)

    async with sem:
        if cfg["delay"] > 0:
            await asyncio.sleep(cfg["delay"])
        try:
            if ats == "workday":
                parts = slug.split("|")
                tenant = parts[0]
                instance = parts[1] if len(parts) > 1 else "wd1"
                site = parts[2] if len(parts) > 2 else "External"
                url = cfg["url"].format(tenant=tenant, instance=instance, site=site)
                headers = {"Content-Type": "application/json", "Accept": "application/json"}
                res = await client.post(url, json={"limit": 5, "offset": 0, "searchText": ""}, headers=headers, timeout=6.0)
            else:
                url = cfg["url"].format(slug=slug)
                res = await client.get(url, timeout=6.0, follow_redirects=True)

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
                elif ats == "bamboohr":
                    jobs = data.get("result", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
                    job_count = len(jobs)
                elif ats == "workday":
                    jobs = data.get("jobPostings", []) if isinstance(data, dict) else []
                    job_count = data.get("total", len(jobs)) if isinstance(data, dict) else len(jobs)

                return (ats, slug, True, job_count)
        except Exception:
            pass

    return (ats, slug, False, 0)


async def validate_platform_slugs(ats: str, slugs: List[str], db_path: str):
    cfg = CONCURRENCY_CONFIG.get(ats, {"concurrency": 20, "delay": 0.05})
    sem = asyncio.Semaphore(cfg["concurrency"])
    
    total = len(slugs)
    print(f"\n🚀 Validating {total} candidate slugs for [{ats.upper()}] (Concurrency={cfg['concurrency']})...")

    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) JobFinderValidator/2.0"}
    limits = httpx.Limits(max_keepalive_connections=50, max_connections=cfg["concurrency"] + 10)
    
    active_found = 0
    processed = 0
    batch_updates = []

    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")

    async with httpx.AsyncClient(headers=headers, limits=limits, timeout=8.0) as client:
        chunk_size = 300
        for i in range(0, total, chunk_size):
            chunk = slugs[i:i + chunk_size]
            tasks = [validate_slug(client, ats, s, sem) for s in chunk]
            results = await asyncio.gather(*tasks)

            now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            updates = []
            for r_ats, r_slug, is_act, j_cnt in results:
                updates.append((1 if is_act else 0, j_cnt, now_str, r_ats, r_slug))
                if is_act:
                    active_found += 1

            conn.executemany("""
                UPDATE company_slugs
                SET is_active = ?, job_count = ?, last_checked = ?
                WHERE ats = ? AND slug = ?
            """, updates)
            conn.commit()

            processed += len(chunk)
            print(f"  [{ats.upper()}] Progress: {processed}/{total} checked ({active_found} active confirmed so far)")

    conn.close()
    print(f"✓ [{ats.upper()}] Completed! Total Active Confirmed: {active_found}/{total}")


async def main():
    db_path = get_db_path()
    init_db(db_path)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("SELECT ats, slug FROM company_slugs WHERE is_active = 0 AND last_checked IS NULL ORDER BY ats")
    all_unverified = cur.fetchall()
    conn.close()

    grouped: Dict[str, List[str]] = {}
    for ats, slug in all_unverified:
        grouped.setdefault(ats, []).append(slug)

    print("=" * 65)
    print(" 🔍 STARTING MASS ATS SLUG VALIDATION")
    print("=" * 65)
    for ats, slugs in grouped.items():
        print(f"  • {ats.capitalize():<12}: {len(slugs):>6} unverified candidates")
    print("=" * 65)

    # Validate high-priority platforms in order
    platforms_order = ["ashby", "lever", "greenhouse", "bamboohr", "workday"]
    for plat in platforms_order:
        if plat in grouped and grouped[plat]:
            await validate_platform_slugs(plat, grouped[plat], db_path)

    # Print final tally
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT ats, is_active, COUNT(*) FROM company_slugs GROUP BY ats, is_active")
    stats = cur.fetchall()
    cur.execute("SELECT COUNT(*) FROM company_slugs WHERE is_active = 1")
    total_active = cur.fetchone()[0]
    conn.close()

    print("\n" + "=" * 65)
    print(" 🏁 FINAL VERIFIED SLUG REGISTRY STATS")
    print("=" * 65)
    for ats, is_act, count in stats:
        status_label = "ACTIVE (Verified)" if is_act == 1 else "Inactive / Stale"
        print(f"  • {ats.capitalize():<12} | {status_label:<18} | {count:>6} boards")
    print(f"\n  🎯 TOTAL ACTIVE VERIFIED BOARDS: {total_active}+")
    print("=" * 65)


if __name__ == "__main__":
    asyncio.run(main())
