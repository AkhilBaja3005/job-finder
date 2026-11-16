"""`job-finder mcp` command."""

import argparse
import json
import logging
import os
import re
import sys

from job_finder import ui

logger = logging.getLogger(__name__)


def run(args: argparse.Namespace):
    from backend.job_finder_mcp.server import main as mcp_main
    mcp_main()
