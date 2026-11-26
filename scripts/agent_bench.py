#!/usr/bin/env python3
"""Runs the browser agent against the fake job board and reports, per site type, whether it filled and submitted the form.

    python scripts/agent_bench.py                 # all three: greenhouse, lever, ashby
    python scripts/agent_bench.py --only ashby    # one site type
    python scripts/agent_bench.py --profile ~/some/candidate_profile.json

Needs an AI key in your .env and Google Chrome, like a normal run. The forms are served from this computer and the
agent submits to this computer only, so nothing is sent to a real employer. Use it after every change to the agent's
prompt, the upload handling or the model defaults, and compare the table with the last run."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend"), str(ROOT / "tests" / "bench")]

SAMPLE = {"name": "Ada Lovelace", "email": "ada@example.com", "phone": "+44 7700 900123", "location": "London, UK",
          "linkedin": "https://www.linkedin.com/in/ada-example", "github": "https://github.com/ada-example",
          "work_authorization": "Authorized to work in the UK without restriction", "requires_sponsorship": False,
          "current_company": "Analytical Engines Ltd"}
RESUME_STUB = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def load_candidate(path: str | None) -> dict:
    """The `candidate` section of a profile file, or the built-in sample when there is none."""
    file = Path(path) if path else Path(os.environ.get("JOB_FINDER_ROOT", ".")) / "candidate_profile.json"
    try:
        return json.loads(file.read_text(encoding="utf-8")).get("candidate") or SAMPLE
    except (OSError, ValueError):
        return SAMPLE


async def run_one(ats: str, board, candidate: dict, resume: str, max_steps: int) -> dict:
    from services import browser_use_agent as agent
    agent.preflight_check_job_url = lambda url: (url, True, None)  # the board is on localhost, which the real check refuses
    before = len(board.submissions)
    started = time.time()
    result = await agent.run_browser_use_autofill(
        job_url=f"{board.base}/{ats}/job", resume_data=candidate, resume_pdf_path=resume, headless=False, auto_submit=True,
        max_steps=max_steps, new_tab=True,
    )
    got = board.submissions[before:]
    return {"ats": ats, "status": result.get("status"), "steps": result.get("steps_taken"), "seconds": round(time.time() - started),
            "submitted": bool(got), "fields": got[0][1] if got else {}, "usage": result.get("usage") or {}}


def main() -> int:
    from board import FORMS, Board
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", choices=sorted(FORMS))
    parser.add_argument("--profile", help="a candidate_profile.json (default: the one in JOB_FINDER_ROOT, else a sample)")
    parser.add_argument("--max-steps", type=int, default=30)
    args = parser.parse_args()
    candidate = load_candidate(args.profile)
    with tempfile.TemporaryDirectory() as tmp, Board() as board:
        resume = str(Path(tmp) / "resume.pdf")
        Path(resume).write_bytes(RESUME_STUB)
        rows = [asyncio.run(run_one(ats, board, candidate, resume, args.max_steps)) for ats in ([args.only] if args.only else sorted(FORMS))]
    print(f"\n{'site':<12}{'agent said':<14}{'form received':<15}{'steps':<7}{'seconds':<9}missing required fields")
    ok = True
    for r in rows:
        missing = [f for f in FORMS[r["ats"]]["required"] if not str(r["fields"].get(f, "")).strip()] if r["submitted"] else FORMS[r["ats"]]["required"]
        ok &= r["submitted"]
        print(f"{r['ats']:<12}{str(r['status']):<14}{'yes' if r['submitted'] else 'NO':<15}{str(r['steps']):<7}{r['seconds']:<9}{', '.join(missing) or '-'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
