"""
`job-finder approve`: move jobs you want to apply for from scanned_jobs.xlsx into approved_jobs.xlsx.

    job-finder approve                    copy every row you marked  Approve = Yes  (or Status = Approved) in Excel
    job-finder approve --ids 3,7,12       approve specific rows (IDs are the ID column)
    job-finder approve --min-ats 85       approve every open row scoring at least 85%
    job-finder approve --revoke --ids 7   take rows back out of the queue (not if already applied)
    job-finder approve --list             show what is waiting in the approved queue

`job-finder apply` only ever works from approved_jobs.xlsx.
"""

import argparse
import os
import re
import sys

from job_finder import ui


def _ids(text):
    return [int(x) for x in re.split(r"[,\s]+", text.strip()) if x] if text else None


def _row(r):
    ats = r.get("ATS %")
    return [str(r.get("ID") or "-"), f"{ats}%" if ats is not None else "-", str(r.get("Company") or "")[:26],
            str(r.get("Job Role") or "")[:46], str(r.get("Closing Date").date()) if hasattr(r.get("Closing Date"), "date") else "-"]


def run(args: argparse.Namespace):
    from backend.services.approval import approve_jobs, withdraw_jobs
    from backend.services.excel_tracker import ExcelTracker, approved_path

    scanned = ExcelTracker()
    approved = ExcelTracker(approved_path(scanned.path))
    ids = _ids(args.ids)
    cols = ["ID", "ATS", "Company", "Role", "Closes"]

    if args.list:
        queue = [r for r in approved.rows() if str(r.get("Status")) == "Approved" and str(r.get("Applied")) != "Yes"]
        done = sum(1 for r in approved.rows() if str(r.get("Applied")) == "Yes")
        ui.key_values("Approved queue", {"Waiting to apply": len(queue), "Already applied": done, "File": approved.path})
        if queue:
            ui.print_table("Waiting to apply", cols, [_row(r) for r in queue], status_col=None)
        else:
            ui.info("Nothing waiting. Mark rows Approve = Yes in the scanned file, then run `job-finder approve`.")
        return

    if args.revoke:
        if not ids:
            ui.error("--revoke needs --ids, e.g. `job-finder approve --revoke --ids 7`.")
            sys.exit(2)
        res = withdraw_jobs(scanned, approved, ids)
        if res["withdrawn"]:
            ui.info(f"Withdrawn from the queue: {', '.join(map(str, res['withdrawn']))} (back to New in the scanned file).")
        if res["refused"]:
            ui.warn(f"Already applied, can't withdraw: {', '.join(map(str, res['refused']))}.")
        if not res["withdrawn"] and not res["refused"]:
            ui.info("None of those IDs are in the approved queue.")
        return

    res = approve_jobs(scanned, approved, ids=ids, min_ats=args.min_ats)
    if res["approved"]:
        ui.print_table(f"Approved {len(res['approved'])} job(s) -> {approved.path}", cols, [_row(r) for r in res["approved"]], status_col=None)
    if res["already"]:
        ui.info(f"Already in the queue: {', '.join(map(str, res['already']))}.")
    if res["skipped"]:
        ui.print_table("Not approved", ["ID", "Company", "Role", "Why"],
                       [[str(s["id"]), str(s["company"])[:24], str(s["role"])[:40], s["reason"]] for s in res["skipped"]], status_col=None)
    if not (res["approved"] or res["already"] or res["skipped"]):
        ui.info("Nothing to approve. Open the scanned file, set  Approve = Yes  on the rows you want, save, and run this again")
        ui.info(f"   {scanned.path}")
        ui.info("(or use --ids 3,7 / --min-ats 85)")
        return
    if res["approved"] and not getattr(args, "no_prepare", False):
        try:
            from backend.job_finder_mcp.tools.profile_tools import load_profile_data
            from job_finder.commands.prepare import prepare_jobs
            prof = load_profile_data() or {}
            fresh_ids = {r.get("ID") for r in res["approved"]}
            rows = [r for r in approved.rows() if r.get("ID") in fresh_ids]
            print(f"\nBuilding application packs for {len(rows)} job(s): tailored CV, cover letter if the posting asks for one...")
            built = prepare_jobs(rows, scanned, approved, prof.get("candidate", {}),
                                 level=(prof.get("search_preferences") or {}).get("level"),
                                 cover_letter=getattr(args, "cover_letter", "auto"))
            ui.print_table("Application packs (review these before applying)", ["ID", "Company", "CV", "Cover letter", "Status"],
                           [[str(r.get("ID")), str(r.get("Company"))[:22], "tailored" if p.cv_tailored else "as-is", p.cover_letter, p.status]
                            for r, p in built], status_col=None)
            for r, p in built:
                for w in p.warnings:
                    ui.warn(f"#{r.get('ID')}: {w}")
            if built:
                print(f"Folders are in: {os.path.dirname(built[0][1].folder)}\nNext:  ./jf review --open {built[0][0].get('ID')}   then   ./jf review --ok {built[0][0].get('ID')}")
        except Exception as e:   # approving must never fail because documents could not be built
            ui.warn(f"Could not build the application packs ({type(e).__name__}: {e}). Run `job-finder prepare` to retry.")
    queue_n = sum(1 for r in approved.rows() if str(r.get("Status")) == "Approved" and str(r.get("Applied")) != "Yes")
    print(f"\n{queue_n} job(s) waiting in the approved queue. After reviewing their packs:  job-finder apply --dry-run   |   job-finder apply --submit")
