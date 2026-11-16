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
    from backend.services.application_tracker import list_applications
    from job_finder.tracker_view import render_tracker
    sys.exit(render_tracker(list_applications(), status=args.status, limit=args.limit, as_json=args.json))
