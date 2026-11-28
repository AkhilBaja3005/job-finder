"""Phase 5: Layout, ATS round-trip verification, region rules & safe rendering."""
from __future__ import annotations

import copy
import html
import json
import re
import shutil
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from backend.services.cv_writer import escape_for_html


STANDARD_HEADINGS: Dict[str, str] = {
    "summary": "Summary",
    "experience": "Experience",
    "education": "Education",
    "skills": "Skills",
    "projects": "Projects",
}


def region_page_rules(region: str = "US") -> Dict[str, Any]:
    """Return page size and privacy rules by region."""
    reg = (region or "US").strip().upper()
    if reg in ("UK", "GB", "UNITED KINGDOM"):
        return {"region": "UK", "page_size": "A4", "allow_photo": False, "allow_age": False}
    if reg in ("EU", "DE", "FR", "NL", "ES", "IT"):
        return {"region": reg, "page_size": "A4", "allow_photo": True, "allow_age": False}
    return {"region": "US", "page_size": "Letter", "allow_photo": False, "allow_age": False}


def _estimate_used_ratio(cv: Dict[str, Any], font_pt: float, page_budget: int) -> float:
    # Approximate line capacity scales inversely with font size
    lines = 5
    for r in cv.get("roles", []):
        lines += 2
        for b in r.get("bullets", []):
            txt = b.get("text", "") if isinstance(b, dict) else str(b)
            lines += max(1, (len(txt) + 74) // 75)
    for p in cv.get("projects", []):
        lines += 2
    lines += max(1, len(cv.get("skills", {})))
    lines += 2 * len(cv.get("education", []))
    base_cap = 40.0 * (10.0 / max(font_pt, 6.0)) * max(1, page_budget)
    return lines / base_cap


def fit_layout_with_floor(
    cv: Dict[str, Any],
    *,
    page_budget: int = 1,
    font_floor_pt: float = 9.0,
    font_ceiling_pt: float = 11.5,
    max_iterations: int = 10,
) -> Dict[str, Any]:
    """Adjust font (never below floor) and drop lowest-scoring bullets to fit page_budget."""
    working = copy.deepcopy(cv)
    font_pt = 10.0
    dropped = 0
    iterations = 0

    for _ in range(max_iterations):
        iterations += 1
        ratio = _estimate_used_ratio(working, font_pt, page_budget)
        if ratio > 1.0:
            if font_pt > font_floor_pt:
                font_pt = max(font_floor_pt, round(font_pt - 0.5, 2))
                continue
            # At font floor: drop lowest-scoring bullet from any role with > 1 bullet
            best_target = None
            for r_idx, role in enumerate(working.get("roles", [])):
                bullets = role.get("bullets", [])
                if len(bullets) <= 1:
                    continue
                for b_idx, b in enumerate(bullets):
                    sc = float(b.get("score", 0.0)) if isinstance(b, dict) else 0.0
                    if best_target is None or sc < best_target[0]:
                        best_target = (sc, r_idx, b_idx)
            if best_target is None:
                break
            _, r_idx, b_idx = best_target
            working["roles"][r_idx]["bullets"].pop(b_idx)
            dropped += 1
        elif ratio < 0.92 and font_pt < font_ceiling_pt:
            font_pt = min(font_ceiling_pt, round(font_pt + 0.5, 2))
        else:
            break

    final_ratio = round(min(1.0, _estimate_used_ratio(working, font_pt, page_budget)), 3)
    return {
        "cv": working,
        "font_pt": font_pt,
        "pages": page_budget,
        "fill_ratio": final_ratio,
        "dropped_bullets": dropped,
        "iterations": iterations,
    }


def render_ats_html(cv: Dict[str, Any], *, region: str = "US", font_pt: float = 10.0) -> str:
    """Render single-column, ATS-safe, tagged HTML with standard headings."""
    rules = region_page_rules(region)
    name = escape_for_html(cv.get("name", ""))
    contact_parts = [cv.get("email", ""), cv.get("phone", ""), cv.get("linkedin", "")]
    contact_line = " | ".join(escape_for_html(p) for p in contact_parts if p)

    roles_html: List[str] = []
    for r in cv.get("roles", []):
        bullets_li = "".join(
            f"<li>{escape_for_html(b.get('text', '') if isinstance(b, dict) else str(b))}</li>"
            for b in r.get("bullets", [])
        )
        roles_html.append(
            f"<article><h3>{escape_for_html(r.get('title', ''))} — {escape_for_html(r.get('company', ''))}</h3>"
            f"<div class='meta'>{escape_for_html(r.get('dates', ''))}</div><ul>{bullets_li}</ul></article>"
        )

    proj_html = "".join(
        f"<li><strong>{escape_for_html(p.get('name', ''))}</strong>: "
        f"{escape_for_html(p.get('description', ''))} "
        f"<span class='url'>{escape_for_html(p.get('url', ''))}</span></li>"
        for p in cv.get("projects", [])
    )

    skills_obj = cv.get("skills", {})
    if isinstance(skills_obj, dict):
        skills_html = "".join(
            f"<p><strong>{escape_for_html(cat)}:</strong> {escape_for_html(', '.join(vals))}</p>"
            for cat, vals in skills_obj.items()
        )
    else:
        skills_html = f"<p>{escape_for_html(', '.join(str(x) for x in skills_obj))}</p>"

    edu_html = "".join(
        f"<p><strong>{escape_for_html(e.get('degree', ''))}</strong>, "
        f"{escape_for_html(e.get('institution', ''))} ({escape_for_html(e.get('dates', ''))})</p>"
        for e in cv.get("education", [])
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{name}</title>
<style>
  @page {{ size: {rules['page_size']}; margin: 0.5in; }}
  body {{ font-family: Arial, Helvetica, sans-serif; font-size: {font_pt}pt; line-height: 1.35; color: #111; }}
  h1, h2, h3 {{ margin: 0 0 4px 0; }}
  ul {{ list-style-type: disc; padding-left: 18px; margin: 4px 0 8px 0; }}
  .url {{ overflow-wrap: anywhere; word-break: break-word; hyphens: none; }}
</style>
</head>
<body>
  <header><h1>{name}</h1><p>{contact_line}</p></header>
  <section><h2>{STANDARD_HEADINGS['summary']}</h2><p>{escape_for_html(cv.get('summary', ''))}</p></section>
  <section><h2>{STANDARD_HEADINGS['experience']}</h2>{''.join(roles_html)}</section>
  <section><h2>{STANDARD_HEADINGS['projects']}</h2><ul>{proj_html}</ul></section>
  <section><h2>{STANDARD_HEADINGS['skills']}</h2>{skills_html}</section>
  <section><h2>{STANDARD_HEADINGS['education']}</h2>{edu_html}</section>
</body>
</html>"""


def run_ats_parse_check(html_doc: str, *, expected_name: str, expected_email: str) -> Dict[str, Any]:
    """Verify reading order, standard headings, contact extraction, and no tables/images."""
    has_table = "<table" in html_doc.lower()
    has_img = "<img" in html_doc.lower()
    plain = html.unescape(re.sub(r"<[^>]+>", " ", html_doc))
    plain = re.sub(r"\s+", " ", plain).strip()
    missing_headings = [h for h in STANDARD_HEADINGS.values() if h not in plain]
    name_ok = expected_name in plain
    email_ok = expected_email in plain
    order_ok = plain.find(expected_name) < plain.find(STANDARD_HEADINGS["summary"]) < plain.find(STANDARD_HEADINGS["experience"])
    ok = (not has_table) and (not has_img) and not missing_headings and name_ok and email_ok and order_ok
    return {
        "ok": ok,
        "missing_headings": missing_headings,
        "name_ok": name_ok,
        "email_ok": email_ok,
        "order_ok": order_ok,
        "has_table": has_table,
        "has_img": has_img,
    }


def build_pdf_metadata(*, name: str, role: str, language: str = "en") -> Dict[str, str]:
    """Build clean PDF metadata with zero tool/model traces."""
    return {
        "Title": f"{name} - {role}".strip(" -"),
        "Author": name,
        "Language": language,
    }


def build_safe_cv_filename(name: str, company: str, role: str) -> str:
    """Create a filesystem-safe Name_Company_Role.pdf filename."""
    def _clean(s: str) -> str:
        tokens = re.findall(r"[A-Za-z0-9]+", s or "")
        return "_".join(tokens)

    parts = [p for p in (_clean(name), _clean(company), _clean(role)) if p]
    return ("_".join(parts) or "resume") + ".pdf"


def save_cv_json_respecting_edits(cv_path: Path, new_data: Dict[str, Any], *, redo: bool = False) -> bool:
    """Never overwrite user-edited cv.json unless redo=True."""
    if cv_path.exists() and not redo:
        try:
            existing = json.loads(cv_path.read_text(encoding="utf-8"))
            if existing.get("edited_by_user"):
                return False
        except Exception:
            pass
    cv_path.write_text(json.dumps(new_data, indent=2, ensure_ascii=False), encoding="utf-8")
    return True


def render_with_fallback(
    html_doc: str,
    out_pdf: Path,
    *,
    primary_renderer: Optional[Callable[[str, Path], bytes]] = None,
    simple_renderer: Optional[Callable[[str, Path], bytes]] = None,
    master_pdf_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Try primary -> simple -> master PDF fallback on missing renderer/timeout/empty PDF."""
    errors: List[str] = []
    for label, fn in (("primary", primary_renderer), ("simple", simple_renderer)):
        if fn is None:
            continue
        try:
            data = fn(html_doc, out_pdf)
            if data:
                out_pdf.write_bytes(data)
                return {"ok": True, "fallback_used": None if label == "primary" else label, "errors": errors}
            errors.append(f"{label}:empty_pdf")
        except Exception as exc:
            errors.append(f"{label}:{exc}")

    if master_pdf_path and master_pdf_path.exists():
        shutil.copyfile(master_pdf_path, out_pdf)
        return {"ok": True, "fallback_used": "master_pdf", "errors": errors}

    return {"ok": False, "fallback_used": "none", "errors": errors}
