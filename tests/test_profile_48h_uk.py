import asyncio
import os
import sys
import json
from collections import defaultdict

sys.path.insert(0, os.path.abspath("backend"))

from services.portal_scanner import PortalScanner
from services.job_searcher import search_jobserve_jobs
from mcp.tools.profile_tools import load_profile_data

async def check_48h_uk_profile_jobs():
    print("=" * 70)
    print("🔍 CHECKING 48H UK POSTINGS FOR YOUR PROFILE: ASHBY, LEVER, JOBSERVE")
    print("=" * 70)

    prof = load_profile_data() or {}
    target_roles = prof.get("search_preferences", {}).get("target_roles", [
        "AI Engineer", "Machine Learning Engineer", "Generative AI Engineer", "AI Systems Engineer", "Data Engineer"
    ])
    
    keywords = ["AI", "Machine Learning", "ML", "GenAI", "LLM", "Data Engineer", "Software Engineer", "Systems"]
    print(f"🎯 Target Profile Roles: {', '.join(target_roles)}")
    print(f"⏳ Timeframe: 48h | 📍 Location: UK\n")

    scanner = PortalScanner()
    
    # 1. Ashby Scan (48h, UK)
    print("📡 Scanning Ashby boards (48h window, Location: UK)...")
    ashby_jobs = await scanner.scan_all_portals(
        target_keywords=keywords,
        timeframe="48h",
        location="UK",
        target_portals=["ashby"]
    )
    print(f"  ✓ Ashby 48h UK tech jobs: {len(ashby_jobs)}")

    # 2. Lever Scan (48h, UK)
    print("\n📡 Scanning Lever boards (48h window, Location: UK)...")
    lever_jobs = await scanner.scan_all_portals(
        target_keywords=keywords,
        timeframe="48h",
        location="UK",
        target_portals=["lever"]
    )
    print(f"  ✓ Lever 48h UK tech jobs: {len(lever_jobs)}")

    # 3. Jobserve Scan (48h, UK)
    print("\n📡 Scanning Jobserve (48h window, Location: UK)...")
    js_jobs_total = []
    for role in target_roles[:3]:
        js_res = await search_jobserve_jobs(
            keyword=role,
            location="UK",
            timeframe="48h"
        )
        js_jobs_total.extend(js_res)
    
    # Deduplicate Jobserve
    seen_urls = set()
    unique_js = []
    for j in js_jobs_total:
        if j.url not in seen_urls:
            seen_urls.add(j.url)
            unique_js.append(j)
    print(f"  ✓ Jobserve 48h UK tech jobs: {len(unique_js)}")

    print("\n" + "=" * 70)
    print("📊 48H UK TOTALS ACCORDING TO YOUR PROFILE")
    print("=" * 70)
    print(f"  • Ashby HQ   : {len(ashby_jobs):>4} jobs posted in last 48h")
    print(f"  • Lever      : {len(lever_jobs):>4} jobs posted in last 48h")
    print(f"  • Jobserve   : {len(unique_js):>4} jobs posted in last 48h")
    print(f"  • TOTAL      : {len(ashby_jobs) + len(lever_jobs) + len(unique_js):>4} jobs")
    print("=" * 70)

    # Print sample jobs
    if ashby_jobs:
        print("\n📋 Ashby Jobs (48h, UK):")
        for j in ashby_jobs[:5]:
            print(f"  • [{j.get('company')}] {j.get('title')} ({j.get('location')}) - Age: {j.get('age')}")
            print(f"    🔗 {j.get('url')}")

    if lever_jobs:
        print("\n📋 Lever Jobs (48h, UK):")
        for j in lever_jobs[:5]:
            print(f"  • [{j.get('company')}] {j.get('title')} ({j.get('location')}) - Age: {j.get('age')}")
            print(f"    🔗 {j.get('url')}")

    if unique_js:
        print("\n📋 Jobserve Jobs (48h, UK):")
        for j in unique_js[:5]:
            print(f"  • [{j.company}] {j.title} ({j.location}) - Age: {j.post_date_raw}")
            print(f"    🔗 {j.url}")

if __name__ == "__main__":
    asyncio.run(check_48h_uk_profile_jobs())
