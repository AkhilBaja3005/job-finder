"""`job-finder sponsor` command."""

import argparse
import json
import logging
import os
import re
import sys

from job_finder import ui

logger = logging.getLogger(__name__)


def run(args: argparse.Namespace):
    from services.uk_sponsor_service import (
        check_uk_sponsor,
        get_sponsor_stats,
        sync_uk_sponsors
    )

    if args.sync:
        print("\n⏳ Downloading latest Home Office Register of Licensed Sponsors CSV from GOV.UK...")
        res = sync_uk_sponsors(force=True)
        if res.get("status") == "success":
            print(f"Successfully synced {res.get('total_sponsors'):,} UK sponsors!")
            print(f"   Updated: {res.get('last_updated')}\n")
        else:
            print(f"Sync note: {res.get('message', 'Completed')}\n")

    if args.stats or (not args.company and not args.sync):
        stats = get_sponsor_stats()
        print("\n🇬🇧 ========================================================")
        print("      UK VISA SPONSOR REGISTER (HOME OFFICE)")
        print("========================================================\n")
        print(f"  Total Licensed UK Sponsors : {stats.get('total_sponsors', 0):,}")
        print(f"  Last Sync Date (UTC)       : {stats.get('last_sync', 'Never')}")
        print("\nUsage:")
        print("  job-finder sponsor \"Google\"       Check specific company sponsor status")
        print("  job-finder sponsor --sync         Force refresh from GOV.UK\n")

    if args.company:
        comp_name = args.company.strip()
        print(f"\nVerifying UK visa sponsorship for: '{comp_name}'...")
        res = check_uk_sponsor(comp_name)
        is_sponsor = res.get("is_sponsor")
        print("\n--------------------------------------------------------")
        if is_sponsor:
            matched = res.get("matched_name") or comp_name
            dt = res.get("details") or {}
            print(f"{res.get('badge', 'UK Visa Sponsor')}")
            print(f"   Registered Entity : {matched}")
            if dt.get("city"):
                print(f"   Location          : {dt.get('city')}")
            if dt.get("route"):
                print(f"   Visa Route        : {dt.get('route')}")
            print("--------------------------------------------------------\n")
        else:
            notice = res.get("notice") or {}
            print(f"{res.get('badge', 'Not on sponsor')}")
            print(f"\n {notice.get('title', 'Company Could Not Be Found in Sponsor Database')}")
            print(f"   {notice.get('description', f'{comp_name} is not currently registered as a visa sponsor with the UK government.')}\n")
            print(f"Guidance:")
            print(f"   {notice.get('advice', 'Consider reaching out directly to ask about their sponsorship policy or future plans.')}")
            print("--------------------------------------------------------\n")
