"""`job-finder server` command."""

import argparse
import json
import logging
import os
import re
import sys

from job_finder import ui

logger = logging.getLogger(__name__)


def run(args: argparse.Namespace):
    os.environ["PORT"] = str(args.port)
    os.environ["HOST"] = args.host
    from backend.main import start_server
    start_server()
