"""`job-finder tracker` command."""

import argparse
import json
import logging
import os
import re
import sys

from job_finder import ui

logger = logging.getLogger(__name__)


def run(args: argparse.Namespace):
    from job_finder.tracker_view import render_tracker
    if getattr(args, "approved", False):
        from backend.services.excel_tracker import ExcelTracker, approved_path
        apps = ExcelTracker(approved_path(ExcelTracker().path)).legacy_entries()
        apps.sort(key=lambda a: a.get("timestamp", 0), reverse=True)
    else:
        from backend.services.application_tracker import list_applications
        apps = list_applications()
    sys.exit(render_tracker(apps, status=args.status, limit=args.limit, as_json=args.json))
