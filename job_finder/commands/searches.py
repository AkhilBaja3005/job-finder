"""
`job-finder searches`: every search has its own Excel. List them, switch between them, move jobs from one to another.

    job-finder searches                                list all searches (the current one is marked *)
    job-finder searches use cyber                      make this the search that approve / prepare / review / apply work on
    job-finder searches move --from main --to cyber-security-graduate --ids 46,47,50-52
                                                       move NEW (not yet approved) jobs between searches' Excel files
    job-finder searches path cyber                     print the Excel's path
"""

import argparse
import os
import re
import sys
from datetime import datetime

from job_finder import ui


def _ids(text):
    out = []
    for part in re.split(r"[,\s]+", (text or "").strip()):
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out += list(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return out


def run(args: argparse.Namespace):
    from backend.services import searches
    from backend.services.excel_tracker import ExcelTracker

    action = args.action or "list"
    current = searches.current_name() or (searches.MAIN if searches._paths(searches.MAIN).exists else None)

    if action == "list":
        found = searches.list_searches()
        if not found:
            ui.info("No searches yet. Run e.g.  job-finder scan cyber security graduate roles")
            return
        rows = []
        for s in found:
            c = searches.counts(s)
            m = s.meta or {}
            what = (", ".join(m.get("topics", []))[:42] or m.get("role") or ("(original workbook)" if s.is_main else "-"))
            when = str(m.get("last_scan", ""))[:16].replace("T", " ") or "-"
            rows.append([("* " if s.name == current else "  ") + s.name[:46], what, m.get("level") or "-",
                         str(c["jobs"]), str(c["approved"]), str(c["applied"]), when])
        ui.print_table("Searches (* = current)", ["Search", "Topics", "Level", "Jobs", "Approved", "Applied", "Last scan"], rows, status_col=None)
        print("\nOpen one: ./jf open --search NAME     Work on one: ./jf searches use NAME     Update one: ./jf scan --search NAME")
        return

    if action == "path":
        s = searches.get(args.name) if args.name else searches.resolve_current()
        print(s.scanned)
        print(s.approved)
        return

    if action == "use":
        if not args.name:
            ui.error("Say which search: job-finder searches use NAME")
            sys.exit(2)
        try:
            s = searches.get(args.name)
        except KeyError as e:
            ui.error(str(e))
            sys.exit(1)
        searches.set_current(s.name)
        ui.info(f"Current search: {s.name}\n  {s.scanned}")
        return

    if action == "move":
        if not (args.source and args.to and args.ids):
            ui.error("Usage: job-finder searches move --from SEARCH --to SEARCH --ids 3,5,8-10")
            sys.exit(2)
        try:
            src = searches.get(args.source)
        except KeyError as e:
            ui.error(str(e))
            sys.exit(1)
        dst, created = (searches.get(args.to), False) if _exists(searches, args.to) else searches.get_or_create(
            args.to, created_by="move", topics=[], level=None)
        ids = set(_ids(args.ids))
        s_tracker, d_tracker = ExcelTracker(src.scanned), ExcelTracker(dst.scanned)
        movable, refused = [], []
        for r in s_tracker.rows():
            if r.get("ID") not in ids:
                continue
            if str(r.get("Status")) in ("New", "Shortlisted", "Skipped", "Closed") and str(r.get("Applied") or "No") != "Yes":
                movable.append(r)
            else:
                refused.append((r.get("ID"), f"status {r.get('Status')}: only jobs that are not approved/applied can move"))
        missing = ids - {r.get("ID") for r in s_tracker.rows()}
        for i in sorted(missing):
            refused.append((i, "no such ID in the source search"))
        records = []
        for r in movable:
            rec = {k: v for k, v in r.items() if not k.startswith("_") and v not in (None, "")}
            for k in ("ID", "Approve", "Docs OK", "Pack Folder", "Cover Letter"):
                rec.pop(k, None)
            records.append(rec)
        added, dup = d_tracker.add_jobs(records) if records else ([], 0)
        removed = s_tracker.remove_rows([r.get("ID") for r in movable])
        if created:
            searches.save_meta(dst, moved_from=src.name)
        searches.save_meta(dst, last_scan=datetime.now().isoformat(timespec="seconds")) if not dst.is_main else None
        ui.info(f"Moved {len(added)} job(s) from '{src.name}' to '{dst.name}'" + (f" ({dup} already there)" if dup else "") +
                f". Removed {removed} from the source.")
        for i, why in refused:
            ui.warn(f"#{i}: {why}")
        print(f"New Excel: {dst.scanned}")
        return

    ui.error(f"Unknown action '{action}'.")
    sys.exit(2)


def _exists(searches, ref: str) -> bool:
    try:
        searches.get(ref)
        return True
    except KeyError:
        return False
