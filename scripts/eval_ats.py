"""Print the ATS golden-set results. Usage: python scripts/eval_ats.py [path/to/golden.json]"""

import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "backend"))

from services.ats_scorer import compute_ats_score, compute_overall_score, estimate_role_fit_score  # noqa: E402


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "backend", "tests", "fixtures", "ats_golden.json")
    with open(path, encoding="utf-8") as fh:
        golden = json.load(fh)
    bad = 0
    print(f"{'case':<48}{'score':>6}  band      result")
    for case in golden["cases"]:
        res = compute_ats_score(golden["resume"], case["jd"])
        score = 0 if not res.eligible else compute_overall_score(res.skills_score, res.experience_score, estimate_role_fit_score(golden["resume"], case["jd"]))
        ok = case["min"] <= score <= case["max"]
        bad += 0 if ok else 1
        print(f"{case['name']:<48}{score:>6}  {case['min']}-{case['max']:<5}  {'ok' if ok else 'OUT OF BAND'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
