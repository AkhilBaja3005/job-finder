"""
`job-finder boards`: the company-board index (open London/UK roles from thousands of Greenhouse / Lever / Ashby boards).

    job-finder boards refresh                 build or refresh the index (first run: several minutes; later: only stale boards)
    job-finder boards refresh --limit 500     try it on the first 500 boards
    job-finder boards refresh --ats greenhouse,lever --force
    job-finder boards status                  what the index holds and how old it is
"""

import argparse
import asyncio
import sys

from job_finder import ui


def run(args: argparse.Namespace):
    from backend.job_finder_mcp.tools.profile_tools import load_profile_data
    from backend.services import board_index as bi

    if args.action == "status":
        st = bi.status()
        if not st["exists"]:
            ui.info("No index yet. Build it with:  job-finder boards refresh")
            return
        ui.key_values("Company-board index", {"File": st["path"], "Open local jobs": st["local_jobs"],
                                              "Age (hours since last visit)": st["age_hours"]})
        ui.print_table("By ATS", ["ATS", "Boards visited", "Reachable", "Local jobs"],
                       [[a, str(v["boards"]), str(v["ok"]), str(v["jobs"])] for a, v in sorted(st["by_ats"].items())], status_col=None)
        return

    prefs = (load_profile_data() or {}).get("search_preferences", {})
    locs = prefs.get("target_locations") or ["London, UK"]
    location = args.location or locs[0]
    ats = [a.strip().lower() for a in args.ats.split(",")] if args.ats else None
    stats = asyncio.run(bi.refresh(ats_list=ats, limit=args.limit, force=args.force, location=location,
                                   concurrency=args.concurrency))
    ui.key_values("Index refreshed", {"Boards visited": stats["visited"], "Reachable": stats["ok"], "Not found": stats["dead"],
                                      "Errors": stats["error"], f"Jobs on those boards": stats["jobs_total"],
                                      f"{location.split(',')[0]} / UK jobs kept": stats["jobs_local"], "Seconds": stats["seconds"]})
    st = bi.status()
    print(f"\nIndex now holds {st['local_jobs']} open {location.split(',')[0]} jobs. `job-finder scan` searches it automatically.")
