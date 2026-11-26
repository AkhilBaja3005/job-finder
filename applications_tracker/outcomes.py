"""
A plain-text record of what happened with every application the agent tried.

One JSON line per attempt in applications_tracker/run_outcomes.jsonl: when, which job, how it ended, which model drove
the browser, how many steps it took, why it stopped, and where the final screenshot is. `summarize` turns that into a
success rate per site, so a site that keeps failing is easy to spot.
"""
from __future__ import annotations

import json
import os
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

SITE_FAMILIES = (
    ("linkedin.com", "LinkedIn"), ("greenhouse.io", "Greenhouse"), ("lever.co", "Lever"), ("ashbyhq.com", "Ashby"),
    ("myworkdayjobs.com", "Workday"), ("workday", "Workday"), ("icims.com", "iCIMS"), ("smartrecruiters.com", "SmartRecruiters"),
    ("workable.com", "Workable"), ("oraclecloud.com", "Oracle"), ("taleo.net", "Taleo"), ("bamboohr.com", "BambooHR"),
)
SUBMITTED, REVIEW, FAILED = "submitted", "needs_review", "failed"


def ledger_path(workspace: Optional[str] = None) -> Path:
    root = Path(workspace or os.environ.get("JOB_FINDER_ROOT") or os.getcwd())
    return root / "applications_tracker" / "run_outcomes.jsonl"


def site_of(url: str) -> str:
    host = (urlparse(url or "").hostname or "").lower()
    for needle, name in SITE_FAMILIES:
        if needle in host:
            return name
    return host.removeprefix("www.") or "unknown"


def classify(status: str) -> str:
    """The agent's status as one of three outcomes."""
    status = (status or "").lower()
    if status == "success":
        return SUBMITTED
    if status in ("needs_review", "preview_ready"):
        return REVIEW
    return FAILED


def append_outcome(record: Dict[str, Any], workspace: Optional[str] = None) -> None:
    """Adds one attempt to the ledger. Never raises: keeping the record must not stop a run."""
    try:
        path = ledger_path(workspace)
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "site": site_of(record.get("url", "")), **record}
        entry["outcome"] = classify(record.get("status", ""))
        entry["final_result"] = str(entry.get("final_result", ""))[:400]
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def read_outcomes(workspace: Optional[str] = None) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    try:
        for line in ledger_path(workspace).read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    except OSError:
        pass
    return rows


def summarize(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Per site: attempts, how many were submitted, needed review, or failed, and the most common reason for a miss."""
    sites: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"attempts": 0, SUBMITTED: 0, REVIEW: 0, FAILED: 0, "reasons": defaultdict(int)})
    for row in rows:
        s = sites[row.get("site") or "unknown"]
        s["attempts"] += 1
        s[row.get("outcome") or FAILED] += 1
        if row.get("outcome") != SUBMITTED and row.get("final_result"):
            s["reasons"][row["final_result"][:90]] += 1
    out = []
    for name, s in sites.items():
        top = max(s["reasons"].items(), key=lambda kv: kv[1])[0] if s["reasons"] else ""
        out.append({"site": name, "attempts": s["attempts"], "submitted": s[SUBMITTED], "needs_review": s[REVIEW], "failed": s[FAILED],
                    "rate": round(100 * s[SUBMITTED] / s["attempts"]), "top_reason": top})
    return sorted(out, key=lambda r: (-r["attempts"], r["site"]))
