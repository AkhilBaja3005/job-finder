"""`job-finder open [scanned|approved]`: open the Excel workbook in your default spreadsheet app."""

import argparse
import os
import subprocess
import sys

from job_finder import ui


def run(args: argparse.Namespace):
    from backend.services.excel_tracker import ExcelTracker, approved_path

    scanned = ExcelTracker()
    path = scanned.path if args.which == "scanned" else approved_path(scanned.path)
    if not os.path.exists(path):
        hint = "run `job-finder scan` first" if args.which == "scanned" else "run `job-finder approve` first"
        ui.error(f"{path} does not exist yet: {hint}.")
        sys.exit(1)
    print(path)
    opener = "open" if sys.platform == "darwin" else ("xdg-open" if sys.platform.startswith("linux") else None)
    if opener:
        subprocess.run([opener, path], check=False)
    elif sys.platform.startswith("win"):
        os.startfile(path)  # type: ignore[attr-defined]
