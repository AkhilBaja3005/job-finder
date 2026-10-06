import asyncio
import os
import sys
import json
from collections import defaultdict

sys.path.insert(0, os.path.abspath("backend"))

from services.portal_scanner import PortalScanner
from mcp.tools.profile_tools import load_profile_data

async def check_48h_uk_bamboo_workday():
    print("=" * 70)
    print("🔍 CHECKING 48H UK POSTINGS FOR YOUR PROFILE: BAMBOOHR & WORKDAY")
    print("=" * 70)

    keywords = ["AI", "Machine Learning", "ML", "GenAI", "LLM", "Data Engineer", "Software Engineer", "Systems", "Developer"]
    print("⏳ Timeframe: 48h | 📍 Location: UK\n")

    scanner = PortalScanner()
    
    # 1. BambooHR Scan (48h, UK)
    print("📡 Scanning BambooHR boards (48h window, Location: UK)...")
    bamboo_jobs = await scanner.scan_all_portals(
        target_keywords=keywords,
        timeframe="48h",
        location="UK",
        target_portals=["bamboohr"]
    )
    print(f"  ✓ BambooHR 48h UK tech jobs: {len(bamboo_jobs)}")

    # 2. Workday Scan (48h, UK)
    print("\n📡 Scanning Workday boards (48h window, Location: UK)...")
    workday_jobs = await scanner.scan_all_portals(
        target_keywords=keywords,
        timeframe="48h",
        location="UK",
        target_portals=["workday"]
    )
    print(f"  ✓ Workday 48h UK tech jobs: {len(workday_jobs)}")

    print("\n" + "=" * 70)
    print("📊 48H UK TOTALS: BAMBOOHR & WORKDAY")
    print("=" * 70)
    print(f"  • BambooHR   : {len(bamboo_jobs):>4} jobs posted in last 48h")
    print(f"  • Workday    : {len(workday_jobs):>4} jobs posted in last 48h")
    print(f"  • TOTAL      : {len(bamboo_jobs) + len(workday_jobs):>4} jobs")
    print("=" * 70)

    if bamboo_jobs:
        print("\n📋 BambooHR Jobs (48h, UK):")
        for j in bamboo_jobs[:5]:
            print(f"  • [{j.get('company')}] {j.get('title')} ({j.get('location')}) - Age: {j.get('age')}")
            print(f"    🔗 {j.get('url')}")

    if workday_jobs:
        print("\n📋 Workday Jobs (48h, UK):")
        for j in workday_jobs[:5]:
            print(f"  • [{j.get('company')}] {j.get('title')} ({j.get('location')}) - Age: {j.get('age')}")
            print(f"    🔗 {j.get('url')}")

if __name__ == "__main__":
    asyncio.run(check_48h_uk_bamboo_workday())
