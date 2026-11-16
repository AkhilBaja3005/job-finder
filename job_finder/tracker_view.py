"""`job-finder tracker`: summary and table views of tracked applications."""

from collections import Counter
from typing import Any, Dict, List, Optional

from job_finder import ui


def _score(app: Dict[str, Any]) -> Optional[int]:
    raw = app.get("score")
    digits = "".join(ch for ch in str(raw if raw is not None else "") if ch.isdigit())
    return int(digits) if digits else None


def summarize(apps: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_status = Counter((str(a.get("status") or "unknown")).strip() or "unknown" for a in apps)
    scores = [s for s in (_score(a) for a in apps) if s is not None]
    return {
        "total": len(apps),
        "by_status": dict(by_status.most_common()),
        "avg_ats": round(sum(scores) / len(scores), 1) if scores else None,
    }


def filter_apps(apps: List[Dict[str, Any]], status: Optional[str]) -> List[Dict[str, Any]]:
    """Case-insensitive substring match; None or 'all' keeps everything."""
    if not status or status.lower() == "all":
        return apps
    needle = status.lower()
    return [a for a in apps if needle in str(a.get("status") or "").lower()]


def _row(a: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "company": a.get("company") or "Unknown",
        "title": a.get("job_title") or a.get("title") or "Position",
        "ats": _score(a),
        "status": a.get("status") or "saved",
        "date": str(a.get("updated_at") or a.get("created_at") or "")[:10],
        "url": a.get("job_url") or a.get("url") or "",
    }


def render_tracker(apps: List[Dict[str, Any]], status: Optional[str] = "all", limit: int = 20, as_json: bool = False) -> int:
    summary = summarize(apps)
    # Newest first; entries without a date keep their original order at the end
    dated = sorted((a for a in apps if a.get("updated_at") or a.get("created_at")),
                   key=lambda a: str(a.get("updated_at") or a.get("created_at")), reverse=True)
    undated = [a for a in apps if not (a.get("updated_at") or a.get("created_at"))]
    selected = filter_apps(dated + undated, status)
    shown = selected[:limit] if limit and limit > 0 else selected

    if as_json:
        ui.print_json({"summary": summary, "matched": len(selected), "applications": [_row(a) for a in shown]})
        return 0

    if not apps:
        ui.info("No tracked job applications found. Run `job-finder scan` to find some.")
        return 0

    avg = summary["avg_ats"]
    ui.key_values("Application tracker", {"Total": summary["total"], "Average ATS": f"{avg}%" if avg is not None else "n/a"})
    ui.print_table("By status", ["Status", "Count"], [[k, v] for k, v in summary["by_status"].items()], status_col=0)

    if not shown:
        ui.info(f"No applications match status '{status}'.")
        return 0

    rows = []
    for a in shown:
        r = _row(a)
        rows.append([str(r["company"])[:28], str(r["title"])[:48], f"{r['ats']}%" if r["ats"] is not None else "n/a", r["status"], r["date"]])
    title = f"Applications ({len(shown)} of {len(selected)})" + (f" matching '{status}'" if status and status.lower() != "all" else "")
    ui.print_table(title, ["Company", "Role", "ATS", "Status", "Updated"], rows, status_col=3)
    return 0
