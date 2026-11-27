"""`job-finder scan` command: discover jobs and save them to the Excel tracker. Never applies."""

import argparse
import logging
import sys
from datetime import datetime

from job_finder import ui

logger = logging.getLogger(__name__)


def run(args: argparse.Namespace):
    request = " ".join(args.request or []).strip()
    if request.lower().startswith(("http://", "https://")) or args.retired_apply_flag or args.retired_apply_opt:
        ui.error("`scan` only discovers jobs now; it no longer tailors resumes or applies.")
        ui.info("Run `job-finder scan` to fill the Excel tracker, then `job-finder apply` (or `apply <url>`) to apply.")
        sys.exit(2)

    try:
        from backend.services.role_spec import normalize_level
        normalize_level(args.level)  # fail fast, before any searching, on a typo like --level interm
    except ValueError as ve:
        ui.error(str(ve))
        sys.exit(2)

    import asyncio
    from applications_tracker.scheduled_job_scanner import run_scan

    # Refresh the verified ATS company-board registry if requested or stale (>24h)
    try:
        try:
            from backend.services.company_slug_registry import get_active_slugs, validate_all_unverified_slugs, should_run_daily_harvest
            from backend.services.company_slug_harvester import harvest_all_company_slugs
        except ImportError:
            from services.company_slug_registry import get_active_slugs, validate_all_unverified_slugs, should_run_daily_harvest
            from services.company_slug_harvester import harvest_all_company_slugs

        if getattr(args, "harvest", False) or should_run_daily_harvest(max_age_hours=24.0):
            print("[ATS Harvester] Running scheduled daily refresh of verified ATS company boards...")
            asyncio.run(harvest_all_company_slugs(sources=["seeds"]))
            asyncio.run(validate_all_unverified_slugs(limit=50))
            active = get_active_slugs()
            total_active = sum(len(slugs) for slugs in active.values())
            print(f"  Active ATS boards ready: {total_active} companies across Ashby, Greenhouse, Lever\n")
    except Exception as he:
        logger.debug(f"Harvester init note: {he}")

    # ── which Excel does this search belong to? (one per search; repeating a search updates the same one) ──
    from backend.job_finder_mcp.tools.profile_tools import load_profile_data
    from backend.services import role_spec, searches
    prefs = (load_profile_data() or {}).get("search_preferences", {})
    try:
        base = searches.get(args.search) if args.search else None
        meta = (base.meta if base else {}) or {}
        # `--search NAME` repeats a saved search; anything typed now overrides its saved criteria
        topic = args.topic or (None if (request or args.role) else (", ".join(meta.get("topics", [])) or None))
        level = args.level or meta.get("level")
        role = args.role or (meta.get("role") if not (request or args.topic) else None)
        location = args.location or meta.get("location")
        topics, lvl = role_spec.parse_inputs(topic, level, request or None, role, prefs)
        split_all = lvl == "all"
        if split_all and (args.into or args.name):
            raise ValueError("--into / --name choose ONE Excel, so also say which level: --level intern, graduate or experienced "
                             "(without a level the scan files results into three Excels, one per level).")
        if not split_all:
            if args.into:
                target, created = (searches.get(args.into), False) if _exists(searches, args.into) else searches.get_or_create(args.into)
            elif args.name:
                target, created = searches.get_or_create(args.name)
            elif base:
                target, created = base, False
            else:
                name = searches.auto_name(topics, lvl, role)
                target, created = (searches._paths(name), not searches._paths(name).exists) if args.dry_run else \
                    searches.get_or_create(name, topics=topics, level=lvl, role=role)
    except (KeyError, ValueError) as e:
        ui.error(str(e))
        sys.exit(2)

    common = dict(
        location_override=location, timeframe_override=args.timeframe, min_ats=args.min_ats,
        limit=args.limit if args.limit > 0 else None, skip_portals=args.skip_portals,
        sponsor_only=True if args.sponsor_only else None, top_applicant_only=True if args.top_applicant else None,
        headless=True if args.headless else None, enrich=not args.no_enrich, topic=topic, request=request or None,
        loose=args.loose, exact=args.exact, ai_score=not args.no_ai_score, dry_run=args.dry_run,
        use_boards=not args.no_boards, expand=0 if args.no_expand else args.expand, ai_limit=args.ai_limit, ai_all=args.score_all, core_only=args.core_only)
    loc_now = location or (prefs.get("target_locations") or ["London, UK"])[0]
    stamp = datetime.now().isoformat(timespec="seconds")

    if split_all:
        # No level typed: every job found is filed into the Excel for its level (intern / graduate / experienced).
        targets, made = {}, {}
        group = searches.auto_name(topics, "all")
        for b in ("intern", "graduate", "experienced"):
            name = searches.auto_name(topics, b)
            sx = searches._paths(name) if args.dry_run else searches.get_or_create(name, topics=topics, level=b, location=loc_now, group=group)[0]
            targets[b] = sx
        for b, sx in targets.items():
            n = searches.counts(sx)["jobs"] if sx.exists else 0
            ui.info(f"{b:<12} -> '{sx.name}': " + ("new Excel" if not sx.exists else f"updating its Excel ({n} jobs so far)"))
        searches.activate(targets["intern"])
        result = asyncio.run(run_scan(role=role, level=None, targets={b: sx.scanned for b, sx in targets.items()}, **common))
        if not args.dry_run and result:
            for b, sx in targets.items():
                m = searches._load_meta(sx)
                searches.save_meta(sx, topics=topics, level=b, location=loc_now, request=request or m.get("request"), last_scan=stamp,
                                   scans=int(m.get("scans", 0)) + 1, group=group)
            by = result.get("by_bucket") or {}
            best = max(("intern", "graduate", "experienced"), key=lambda b: (by.get(b, 0), b == "intern"))
            searches.set_current(targets[best].name)
            print(f"\nCurrent search is now '{targets[best].name}' ({best}). Switch with  ./jf searches use NAME  "
                  f"or name one per command: ./jf open --search {targets['graduate'].name[:24]}")
        return

    n_existing = searches.counts(target)["jobs"] if target.exists else 0
    ui.info(f"Search '{target.name}': " + ("new Excel will be created" if not target.exists else f"updating its Excel ({n_existing} jobs so far)")
            + f"\n  {target.scanned}")
    searches.activate(target)

    asyncio.run(run_scan(role=role, level=level, **common))
    if not args.dry_run:
        meta_now = searches._load_meta(target)
        searches.save_meta(target, topics=topics or meta_now.get("topics", []), level=lvl, role=role, location=loc_now,
                           request=request or meta_now.get("request"), last_scan=stamp, scans=int(meta_now.get("scans", 0)) + 1)
        searches.set_current(target.name)
        print(f"\nCurrent search is now '{target.name}': approve / prepare / review / apply / open work on it.  (./jf searches lists them all)")


def _exists(searches, ref):
    try:
        searches.get(ref)
        return True
    except KeyError:
        return False
