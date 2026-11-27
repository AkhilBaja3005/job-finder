"""
`job-finder topic ...`: show what a topic means to `scan` (the whole field), without searching anything.

    job-finder topic cyber security internships
    job-finder topic --topic "applied AI" --level intern
    job-finder topic cyber security --refresh      ask the LLM again (e.g. the first answer missed a sub-area)

The field is cached in data/topic_terms.json. Edit that file by hand to add or remove terms under
"include" (titles to keep), "exclude" (look-alikes to drop) and "search" (extra job-board queries).
"""

import argparse
import json
import sys

from job_finder import ui


def run(args: argparse.Namespace):
    from backend.job_finder_mcp.tools.profile_tools import load_profile_data
    from backend.services import role_spec as rs

    prefs = (load_profile_data() or {}).get("search_preferences", {})
    request = " ".join(args.request or []).strip() or None
    try:
        spec = rs.resolve_spec(topic=args.topic, level=args.level, request=request, prefs=prefs, refresh=args.refresh)
    except ValueError as e:
        ui.error(str(e))
        sys.exit(2)
    if spec is None or not spec.topics:
        ui.error("No topic given and none saved in your profile. Try:  job-finder topic cyber security internships")
        sys.exit(2)

    ui.key_values("What `scan` will do", {
        "Topics": ", ".join(spec.topics),
        "Level": spec.level,
        "Searches (job boards)": " | ".join(spec.queries),
        "Cache file (editable)": rs._cache_path(),
    })
    print(f"\nKeeps a job when its TITLE contains any of ({len(spec.topic_terms)}):")
    print("  " + ", ".join(spec.topic_terms))
    if spec.topic_all_of:
        print("  ...or all of: " + " + ".join("[" + ", ".join(g) + "]" for g in spec.topic_all_of))
    print("\nDrops look-alikes containing:")
    print("  " + (", ".join(spec.topic_exclude) or "(none)"))
    print("\nA job must also carry a level word: " + (", ".join(rs.LEVELS[spec.level]["terms"][:8]) or "(any level)"))
    print("\nNot right? Edit the cache file, or run again with --refresh.")
