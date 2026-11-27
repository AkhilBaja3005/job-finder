"""
`job-finder review`: look at the application packs and give (or withdraw) the go-ahead.

    job-finder review                 list packs and whether you have signed them off
    job-finder review --open 3        open the pack folder in Finder / your file manager
    job-finder review --ok 3,7        you have read the CV / cover letter: allow `apply` to use them (Docs OK = Yes)
    job-finder review --revoke 3      take the sign-off back

`apply` only submits jobs whose pack is signed off, and it uploads that pack's cv.pdf and pastes that pack's cover letter.
"""

import argparse
import os
import re
import subprocess
import sys

from job_finder import ui


def _ids(text):
    return [int(x) for x in re.split(r"[,\s]+", text.strip()) if x] if text else None


def run(args: argparse.Namespace):
    from backend.services.excel_tracker import ExcelTracker, approved_path

    scanned = ExcelTracker()
    approved = ExcelTracker(approved_path(scanned.path))
    rows = [r for r in approved.rows() if r.get("Pack Folder") and str(r.get("Status")) in ("Approved", "Needs Review")
            and str(r.get("Applied") or "No") != "Yes"]
    by_id = {r.get("ID"): r for r in rows}

    if args.open is not None:
        r = by_id.get(args.open)
        if not r:
            ui.error(f"No pack for ID {args.open}. Run `job-finder review` to see the packs.")
            sys.exit(1)
        folder = str(r["Pack Folder"])
        print(folder)
        if sys.platform == "darwin":
            subprocess.run(["open", folder], check=False)
        elif sys.platform.startswith("linux"):
            subprocess.run(["xdg-open", folder], check=False)
        elif sys.platform.startswith("win"):
            os.startfile(folder)  # type: ignore[attr-defined]
        return

    for flag, value in (("--ok", _ids(args.ok)), ("--revoke", _ids(args.revoke))):
        if not value:
            continue
        marking = flag == "--ok"
        done, refused = [], []
        for i in value:
            r = by_id.get(i)
            if not r:
                refused.append((i, "no pack for that ID"))
            elif marking and not os.path.isfile(os.path.join(str(r["Pack Folder"]), "cv.pdf")):
                refused.append((i, "cv.pdf is missing: run `job-finder prepare --ids %s --render-only`" % i))
            else:
                done.append(i)
        if done:
            approved.update_many([({"row_id": i}, {"Docs OK": "Yes" if marking else "No"}, None) for i in done])
            ui.info(f"Docs OK = {'Yes' if marking else 'No'} for: {', '.join(map(str, done))}")
        for i, why in refused:
            ui.warn(f"#{i}: {why}")
        return

    if not rows:
        ui.info("No application packs yet. Approve jobs with `job-finder approve` (it builds the packs), or run `job-finder prepare`.")
        return
    table = [[str(r["ID"]), str(r.get("Company"))[:22], str(r.get("Job Role"))[:34], str(r.get("Cover Letter") or "-"),
              "YES" if str(r.get("Docs OK")) == "Yes" else "not yet", os.path.basename(str(r["Pack Folder"]))] for r in rows]
    ui.print_table("Application packs", ["ID", "Company", "Role", "Cover letter", "Signed off", "Folder"], table, status_col=None)
    waiting = [str(r["ID"]) for r in rows if str(r.get("Docs OK")) != "Yes"]
    print(f"\nPacks live in: {os.path.dirname(str(rows[0]['Pack Folder']))}")
    if waiting:
        print(f"Awaiting your review: {', '.join(waiting)}   ->  ./jf review --open {waiting[0]}   then   ./jf review --ok {waiting[0]}")
