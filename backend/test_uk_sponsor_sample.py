"""
Sample Test Script for UK Visa Sponsor Verification
Demonstrates and tests:
1. Exact & fuzzy company name normalization
2. Verification against Home Office Register (~143,000 sponsors)
3. Fallback advice card generation for companies not found (e.g. Insight / non-sponsors)
4. Integration behavior for Job Finder Website API, CLI, and Chrome Extension
"""

import sys
import os
import json

# Ensure backend root is on sys.path
backend_dir = os.path.dirname(os.path.abspath(__file__))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from services.uk_sponsor_service import (
    normalize_company_name,
    check_uk_sponsor,
    get_sponsor_stats,
    sync_uk_sponsors
)

def run_sample_tests():
    print("=" * 70)
    print("   UK VISA SPONSOR CHECKER - SAMPLE TEST SUITE")
    print("=" * 70)

    # 1. Check current database / cache stats
    stats = get_sponsor_stats()
    print(f"\n📊 [1] Database Stats:")
    print(f"   Total Licensed UK Sponsors: {stats.get('total_sponsors'):,}")
    print(f"   Last Register Sync Date    : {stats.get('last_sync')}")

    if stats.get('total_sponsors', 0) == 0:
        print("\n⏳ Database empty, running initial sync from GOV.UK...")
        sync_res = sync_uk_sponsors(force=True)
        print(f"   Sync result: {sync_res}")

    # 2. Test Cases across different corporate naming formats
    test_companies = [
        # Prominent verified sponsors
        "Google",
        "Google UK Limited",
        "Meta",
        "Amazon",
        "Microsoft Limited",
        "Palantir Technologies UK",
        "DeepMind Technologies Limited",
        "AaruvikA Limited",
        
        # The specific user-tested case: "Insight"
        "Insight",
        "Insight International (UK) Limited",
        "Insight Global Limited",

        # Non-sponsors / Unregistered companies
        "Insight Non-Sponsor Entity XYZ",
        "Random Startup London 123",
        "Fake Company Not Sponsoring Ltd"
    ]

    print("\n🔍 [2] Running Verification on Sample Companies:")
    print("-" * 70)

    for company in test_companies:
        norm = normalize_company_name(company)
        res = check_uk_sponsor(company)
        is_sp = res.get("is_sponsor")
        badge = res.get("badge")
        matched = res.get("matched_name")

        if is_sp:
            details = res.get("details", {})
            city = details.get("city") or "UK"
            route = details.get("route") or "Skilled Worker"
            print(f"🟢 [SPONSOR] {company}")
            print(f"   Normalized   : '{norm}'")
            print(f"   Matched Entity: '{matched}' ({city}) | Route: {route}")
            print(f"   Badge Shown  : {badge}\n")
        else:
            notice = res.get("notice", {})
            print(f"🔴 [NOT FOUND] {company}")
            print(f"   Normalized   : '{norm}'")
            print(f"   Badge Shown  : {badge}")
            print(f"   Notice Title : {notice.get('title')}")
            print(f"   Notice Body  : {notice.get('description')}")
            print(f"   Advice       : {notice.get('advice')}\n")

    print("=" * 70)
    print("   SAMPLE TEST COMPLETE")
    print("=" * 70)

if __name__ == "__main__":
    run_sample_tests()
