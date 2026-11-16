"""`job-finder harvest-slugs` command."""

import argparse
import json
import logging
import os
import re
import sys

from job_finder import ui

logger = logging.getLogger(__name__)


def run(args: argparse.Namespace):
    import asyncio
    from backend.services.company_slug_harvester import harvest_all_company_slugs
    from backend.services.company_slug_registry import validate_all_unverified_slugs, get_active_slugs

    sources = [s.strip().lower() for s in args.source.split(",")]
    asyncio.run(harvest_all_company_slugs(sources=sources))

    if args.validate:
        asyncio.run(validate_all_unverified_slugs(ats_filter=args.ats, limit=args.limit))

    active = get_active_slugs(ats=args.ats)
    print("\nActive Company Board Registry Summary:")
    for platform, slugs in active.items():
        print(f"  • {platform.capitalize():<12}: {len(slugs)} active board slugs")
