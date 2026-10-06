import asyncio
import os
import sys
import json
from collections import defaultdict

sys.path.insert(0, os.path.abspath("backend"))

from services.portal_scanner import PortalScanner
from services.job_searcher import search_jobserve_jobs
from mcp.tools.profile_tools import load_profile_data

async def check_all_platforms_48h_uk():
    print("=" * 70)
    print("🌐 UNIFIED 48H UK SCAN: ASHBY, GREENHOUSE, LEVER, BAMBOOHR, WORKDAY, JOBSERVE")
    print("=" * 70)

    prof = load_profile_data() or {}
    target_roles = prof.get("search_preferences", {}).get("target_roles", [
        "AI Engineer", "Machine Learning Engineer", "Generative AI Engineer", "AI Systems Engineer", "Data Engineer"
    ])
    keywords = ["AI", "Machine Learning", "ML", "GenAI", "LLM", "Data Engineer", "Software Engineer", "Systems", "Developer"]

    print(f"🎯 Target Profile Roles: {', '.join(target_roles)}")
    print("⏳ Timeframe: 48h | 📍 Location: UK\n")

    scanner = PortalScanner()
    counts = defaultdict(int)
    samples = defaultdict(list)

    # 1. Direct ATS Platforms
    ats_platforms = ["ashby", "greenhouse", "lever", "bamboohr", "workday"]
    for plat in ats_platforms:
        print(f"📡 Scanning [{plat.upper()}] (48h window, Location: UK)...")
        try:
            jobs = await scanner.scan_all_portals(
                target_keywords=keywords,
                timeframe="48h",
                location="UK",
                target_portals=[plat]
            )
            counts[plat] = len(jobs)
            samples[plat] = jobs[:3]
            print(f"  ✓ {plat.upper():<12}: {len(jobs)} active matching jobs")
        except Exception as e:
            print(f"  ❌ {plat.upper()} error: {e}")

    # 2. Jobserve
    print("\n📡 Scanning [JOBSERVE] (48h window, Location: UK)...")
    try:
        js_total = []
        for role in target_roles[:3]:
            js_res = await search_jobserve_jobs(
                keyword=role,
                location="UK",
                timeframe="48h"
            )
            js_total.extend(js_res)
        
        seen_urls = set()
        unique_js = []
        for j in js_total:
            if j.url not in seen_urls:
                seen_urls.add(j.url)
                unique_js.append(j)
        counts["jobserve"] = len(unique_js)
        samples["jobserve"] = unique_js[:3]
        print(f"  ✓ JOBSERVE    : {len(unique_js)} active matching jobs")
    except Exception as e:
        print(f"  ❌ JOBSERVE error: {e}")

    # Final Combined Output
    print("\n" + "=" * 70)
    print("📊 48H UK POSTINGS SUMMARY (ALL 6 PLATFORMS)")
    print("=" * 70)
    total_48h = 0
    for plat in ["ashby", "greenhouse", "lever", "bamboohr", "workday", "jobserve"]:
        cnt = counts[plat]
        total_48h += cnt
        print(f"  • {plat.upper():<14}: {cnt:>5} jobs posted in last 48h")
    print("=" * 70)
    print(f"  • {'TOTAL 48H UK':<14}: {total_48h:>5} Verified Matching Postings")
    print("=" * 70)

    print("\n📋 LIVE SAMPLES ACROSS PLATFORMS:")
    for plat in ["ashby", "greenhouse", "lever", "bamboohr", "workday", "jobserve"]:
        if samples[plat]:
            print(f"\n--- {plat.upper()} ---")
            for j in samples[plat]:
                title = j.get("title") if isinstance(j, dict) else j.title
                comp = j.get("company") if isinstance(j, dict) else j.company
                loc = j.get("location") if isinstance(j, dict) else j.location
                url = j.get("url") if isinstance(j, dict) else j.url
                age = j.get("age") if isinstance(j, dict) else j.post_date_raw
                print(f"  • [{comp}] {title} ({loc}) - {age}")
                print(f"    🔗 {url}")

if __name__ == "__main__":
    asyncio.run(check_all_platforms_48h_uk())
