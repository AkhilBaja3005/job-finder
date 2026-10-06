import asyncio
import os
import sys
import json
from collections import defaultdict

# Ensure backend path is in sys.path
sys.path.insert(0, os.path.abspath("backend"))

from services.portal_scanner import PortalScanner
from services.job_searcher import search_jobserve_jobs

async def validate_ats_yield():
    print("=" * 70)
    print("🔍 VALIDATING LIVE JOB YIELD GROUPED BY ATS PLATFORM")
    print("=" * 70)

    scanner = PortalScanner()
    keywords = ["Engineer", "Developer", "AI", "Software", "Machine Learning", "Data"]
    
    # 1. Test scanning individual ATS platforms
    platforms_to_test = ["ashby", "greenhouse", "lever", "bamboohr"]
    counts_by_platform = defaultdict(int)
    sample_jobs_by_platform = defaultdict(list)

    for plat in platforms_to_test:
        print(f"\n📡 Scanning live active boards for [{plat.upper()}] (Location: UK)...")
        try:
            jobs = await asyncio.wait_for(
                scanner.scan_all_portals(
                    target_keywords=keywords,
                    timeframe="all",
                    location="UK",
                    target_portals=[plat]
                ),
                timeout=45.0
            )
            counts_by_platform[plat] = len(jobs)
            sample_jobs_by_platform[plat] = jobs[:3]
            print(f"  ✓ {plat.upper()}: {len(jobs)} active matching UK jobs found!")
        except Exception as e:
            print(f"  ❌ {plat.upper()} error: {e}")

    # 2. Test Jobserve
    print("\n📡 Testing Jobserve Live Engine...")
    try:
        js_jobs = await search_jobserve_jobs(
            keyword="Software Engineer",
            location="London",
            timeframe="48h"
        )
        counts_by_platform["jobserve"] = len(js_jobs)
        sample_jobs_by_platform["jobserve"] = js_jobs[:3]
        print(f"  ✓ JOBSERVE: {len(js_jobs)} active matching jobs found!")
    except Exception as e:
        print(f"  ❌ JOBSERVE error: {e}")

    print("\n" + "=" * 70)
    print("📊 FINAL SUMMARY: ACTIVE JOBS GROUPED BY PLATFORM")
    print("=" * 70)
    total_jobs = 0
    for plat, count in counts_by_platform.items():
        total_jobs += count
        print(f"  • {plat.upper():<12}: {count:>5} jobs")
    print(f"  • {'TOTAL':<12}: {total_jobs:>5} jobs")
    print("=" * 70)

    print("\n📋 SAMPLES BY PLATFORM:")
    for plat, samples in sample_jobs_by_platform.items():
        print(f"\n--- {plat.upper()} ---")
        for j in samples:
            title = j.get("title") if isinstance(j, dict) else j.title
            comp = j.get("company") if isinstance(j, dict) else j.company
            loc = j.get("location") if isinstance(j, dict) else j.location
            url = j.get("url") if isinstance(j, dict) else j.url
            print(f"  • [{comp}] {title} | {loc} -> {url[:60]}...")

if __name__ == "__main__":
    asyncio.run(validate_ats_yield())
