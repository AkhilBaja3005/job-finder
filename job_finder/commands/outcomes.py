"""`job-finder outcomes` command: how applications ended, per job site."""

import argparse
import json

from applications_tracker.outcomes import ledger_path, question_counts, read_outcomes, summarize


def run(args: argparse.Namespace):
    rows = read_outcomes()
    if getattr(args, "questions", False):
        ranked = question_counts(rows)
        if getattr(args, "json", False):
            print(json.dumps({"questions": ranked, "attempts": len(rows)}, indent=2))
        elif not ranked:
            print("No questions recorded yet. The agent reports the questions it meets at the end of each application.")
        else:
            print(f"Questions met most often, over {len(rows)} attempts\n")
            for entry in ranked:
                print(f"{entry['count']:>4}  {entry['question']}  ({', '.join(entry['sites']) or 'unknown site'})")
        return
    summary = summarize(rows)
    if getattr(args, "json", False):
        print(json.dumps({"ledger": str(ledger_path()), "sites": summary, "attempts": len(rows)}, indent=2))
        return
    if not rows:
        print(f"No application attempts recorded yet. They are saved to {ledger_path()} as runs happen.")
        return
    print(f"{len(rows)} attempts recorded ({ledger_path()})\n")
    print(f"{'Site':<18}{'Tried':>6}{'Submitted':>11}{'Review':>8}{'Failed':>8}{'Rate':>7}  Most common reason it did not go through")
    for s in summary:
        print(f"{s['site']:<18}{s['attempts']:>6}{s['submitted']:>11}{s['needs_review']:>8}{s['failed']:>8}{str(s['rate']) + '%':>7}  {s['top_reason']}")
    recent = max(0, int(getattr(args, "recent", 0) or 0))
    if recent:
        print(f"\nLast {recent}:")
        for r in rows[-recent:]:
            print(f"- {r.get('time', '')}  {r.get('outcome', ''):<12} {r.get('company', '')}: {r.get('title', '')}")
            if r.get("final_result") and r.get("outcome") != "submitted":
                print(f"    {r['final_result'][:160]}")
            if r.get("screenshot"):
                print(f"    screenshot: {r['screenshot']}")
