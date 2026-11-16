"""`job-finder scan` command."""

import argparse
import json
import logging
import os
import re
import sys

from job_finder import ui

logger = logging.getLogger(__name__)


def run(args: argparse.Namespace):
    if args.auto_apply:
        os.environ["JOB_FINDER_DISABLE_GUARDRAILS"] = "1"
    import asyncio
    from applications_tracker.scheduled_job_scanner import run_pipeline

    # Check if harvest requested or if registry is older than 24 hours / empty
    try:
        try:
            from backend.services.company_slug_registry import get_active_slugs, validate_all_unverified_slugs, should_run_daily_harvest
            from backend.services.company_slug_harvester import harvest_all_company_slugs
        except ImportError:
            from services.company_slug_registry import get_active_slugs, validate_all_unverified_slugs, should_run_daily_harvest
            from services.company_slug_harvester import harvest_all_company_slugs

        needs_refresh = getattr(args, "harvest", False) or should_run_daily_harvest(max_age_hours=24.0)

        if needs_refresh:
            print("[ATS Harvester] Running scheduled daily refresh of verified ATS company boards...")
            asyncio.run(harvest_all_company_slugs(sources=["seeds"]))
            asyncio.run(validate_all_unverified_slugs(limit=50))
            active = get_active_slugs()
            total_active = sum(len(slugs) for slugs in active.values())
            print(f"  Active ATS boards ready: {total_active} companies across Ashby, Greenhouse, Lever\n")
    except Exception as he:
        logger.debug(f"Harvester init note: {he}")

    asyncio.run(run_pipeline(
        target_url=args.url,
        timeout=args.timeout,
        tailor_timeout=args.tailor_timeout,
        max_steps=args.max_steps,
        max_apps=args.limit if args.limit > 0 else None,
        min_ats=args.min_ats,
        role=args.role,
        location_override=args.location,
        timeframe_override=args.timeframe,
        model_override=args.model,
        headless=True if args.headless else None,
        auto_submit_override=True if args.auto_apply else None,
        top_applicant_only=True if args.top_applicant else None,
        sponsor_only=True if args.sponsor_only else None,
        skip_portals=args.skip_portals
    ))
