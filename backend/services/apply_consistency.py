"""Phase 8: Cover letter ledger verification, cross-document consistency, and apply hash log."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.services.cv_verifier import (
    check_facts,
    check_no_conversions,
    check_strength_escalation,
)


def verify_cover_letter_against_ledger(
    cover_letter: str,
    *,
    source_text: str,
    jd_text: str = "",
    company_note: str = "",
) -> Dict[str, Any]:
    """Verify cover letter claims against candidate source (+ JD/note for company context)."""
    combined_source = f"{source_text}\n{jd_text}\n{company_note}\nDear Hello Sincerely Regards".strip()
    issues: List[str] = []
    issues.extend(check_facts(cover_letter, combined_source))
    issues.extend(check_no_conversions(cover_letter, combined_source, combined_source))
    issues.extend(check_strength_escalation(cover_letter, source_text, combined_source))
    return {"ok": len(issues) == 0, "issues": issues}


def cross_check_application_consistency(
    *,
    cv_data: Dict[str, Any],
    cover_letter: str = "",
    form_answers: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, str]]:
    """Flag mismatches across CV, cover letter, and form answers (titles, dates, numbers)."""
    mismatches: List[Dict[str, str]] = []
    answers = form_answers or {}
    roles = cv_data.get("roles", [])
    cv_titles = [r.get("title", "").strip() for r in roles if r.get("title")]
    cv_text = cv_data.get("text", "") + " " + " ".join(
        f"{r.get('title', '')} {r.get('company', '')} {r.get('dates', '')}" for r in roles
    )

    form_title = str(answers.get("current_title") or "").strip()
    if form_title and cv_titles and form_title.lower() not in [t.lower() for t in cv_titles]:
        mismatches.append({"category": "title_mismatch", "detail": f"Form title '{form_title}' != CV titles {cv_titles}"})

    # Check numbers/percentages in cover letter vs CV text
    cv_nums = set(re.findall(r"\b\d+(?:\.\d+)?%", cv_text))
    cl_nums = set(re.findall(r"\b\d+(?:\.\d+)?%", cover_letter or ""))
    extra_cl_nums = cl_nums - cv_nums
    if extra_cl_nums:
        mismatches.append({"category": "number_mismatch", "detail": f"Cover letter % {sorted(extra_cl_nums)} not in CV {sorted(cv_nums)}"})

    # Check seniority/title escalation in cover letter
    for senior_word in ("principal", "staff", "director", "vp", "head of"):
        if senior_word in (cover_letter or "").lower() and senior_word not in cv_text.lower():
            mismatches.append({"category": "title_mismatch", "detail": f"Cover letter uses '{senior_word}' absent from CV"})

    # Check start_date year in form answers
    start_date = str(answers.get("start_date") or "").strip()
    if start_date and roles:
        cv_dates = " ".join(str(r.get("dates", "")) for r in roles)
        if start_date not in cv_dates:
            mismatches.append({"category": "date_mismatch", "detail": f"Form start_date '{start_date}' not in CV dates '{cv_dates}'"})

    return mismatches


def record_apply_file_hashes(
    *,
    log_path: Path,
    job_id: str,
    files: Dict[str, Path],
) -> Dict[str, Any]:
    """Compute SHA-256 hashes of reviewed files and append to the apply log."""
    hashes: Dict[str, str] = {}
    for label, fpath in files.items():
        if fpath.is_file():
            hashes[label] = hashlib.sha256(fpath.read_bytes()).hexdigest()
        else:
            hashes[label] = ""

    entry = {
        "job_id": str(job_id),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "hashes": hashes,
    }
    existing: List[Dict[str, Any]] = []
    if log_path.is_file():
        try:
            existing = json.loads(log_path.read_text(encoding="utf-8"))
        except Exception:
            existing = []
    existing.append(entry)
    log_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    return entry


def answer_sensitive_field(field_name: str, profile: Dict[str, Any]) -> Tuple[str, Optional[str]]:
    """Return sensitive field only from profile; never estimate if missing."""
    val = str(profile.get(field_name) or "").strip()
    if not val:
        return "", f"Missing '{field_name}' in profile; left blank without estimating."
    return val, None
