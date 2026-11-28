"""Phase 3: Deterministic CV content selector.

Scores every bullet, project, and skill against weighted JD requirements
(using cv_master.ALIAS_MAP), enforces per-role floors, fills the page budget
into [92%, 100%] without overflowing, orders sections by archetype/level,
and preserves timeline dates, gaps, and exact names/links.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from backend.services.cv_master import ALIAS_MAP


_LINES_PER_PAGE = 40


def _expand_aliases(term: str) -> List[str]:
    low = term.lower().strip()
    variants = {low}
    for key, syns in ALIAS_MAP.items():
        all_forms = {key.lower()} | {s.lower() for s in syns}
        if low in all_forms:
            variants |= all_forms
    return sorted(variants)


def score_item(text: str, jd_analysis: Dict[str, Any]) -> float:
    """Deterministically score a bullet or project description against JD requirements."""
    low = (text or "").lower()
    if not low:
        return 0.0
    reqs = jd_analysis.get("requirements", {})
    must_have = reqs.get("must_have", [])
    strong = reqs.get("strong", [])
    nice = reqs.get("nice_to_have", [])

    score = 0.0
    for term, weight in ((t, 3.0) for t in must_have):
        if any(re.search(rf"(?<![a-z0-9]){re.escape(v)}(?![a-z0-9])", low) for v in _expand_aliases(term)):
            score += weight
    for term, weight in ((t, 1.8) for t in strong):
        if any(re.search(rf"(?<![a-z0-9]){re.escape(v)}(?![a-z0-9])", low) for v in _expand_aliases(term)):
            score += weight
    for term, weight in ((t, 0.8) for t in nice):
        if any(re.search(rf"(?<![a-z0-9]){re.escape(v)}(?![a-z0-9])", low) for v in _expand_aliases(term)):
            score += weight

    if re.search(r"\b\d+(?:\.\d+)?%|\b\d+[kKmMbB+]\b|\$\d+|INR\s*\d+", text):
        score += 1.0
    return round(score, 3)


def compute_page_budget(
    candidate_years: float = 0.0,
    archetype: str = "general",
    override: Optional[int] = None,
) -> int:
    """1 page up to ~8 years, 2 pages above or for academic/research roles."""
    if override in (1, 2):
        return int(override)
    if archetype in ("research", "academic") or candidate_years >= 8.0:
        return 2
    return 1


def choose_section_order(
    archetype: str = "general",
    level: str = "mid",
    candidate_years: float = 3.0,
) -> List[str]:
    """Order sections by role archetype and candidate seniority."""
    if level in ("junior", "intern", "graduate") or candidate_years < 1.0:
        return ["summary", "education", "projects", "skills", "experience"]
    if archetype in ("docs_devrel", "research"):
        return ["summary", "skills", "projects", "experience", "education"]
    if archetype in ("applied_ml", "platform"):
        return ["summary", "skills", "experience", "projects", "education"]
    return ["summary", "experience", "projects", "skills", "education"]


def filter_education(
    education: List[Dict[str, Any]],
    *,
    has_degree: Optional[bool] = None,
    min_grade_threshold: float = 0.0,
) -> List[Dict[str, Any]]:
    """Filter education per 3.6: omit high school when degree exists, keep exact dates."""
    if not education:
        return []
    if has_degree is None:
        has_degree = any(
            not any(hs in (e.get("degree", "").lower()) for hs in ("high school", "secondary"))
            for e in education
        )
    out: List[Dict[str, Any]] = []
    for edu in education:
        deg_low = (edu.get("degree") or "").lower()
        if has_degree and ("high school" in deg_low or "secondary" in deg_low):
            continue
        item = dict(edu)
        if min_grade_threshold > 0 and item.get("grade"):
            m = re.search(r"(\d+(?:\.\d+)?)", str(item["grade"]))
            if m and float(m.group(1)) < min_grade_threshold:
                item.pop("grade", None)
        out.append(item)
    return out


def organize_skills(
    skills: Any,
    jd_analysis: Dict[str, Any],
    source_text: str = "",
    max_skills: int = 24,
) -> Dict[str, List[str]]:
    """Group skills by category, order relevant groups first, deduplicate near-synonyms."""
    if isinstance(skills, list):
        skills_dict: Dict[str, List[str]] = {"Skills": list(skills)}
    elif isinstance(skills, dict):
        skills_dict = {str(k): list(v) for k, v in skills.items()}
    else:
        return {}

    src_low = source_text.lower()
    seen_canonical: set[str] = set()
    scored_groups: List[Tuple[float, str, List[str]]] = []

    def _canon(s: str) -> str:
        low = s.lower().strip()
        for k, syns in ALIAS_MAP.items():
            if low == k.lower() or low in {x.lower() for x in syns}:
                return k.lower()
        return low

    total_kept = 0
    for group_name, items in skills_dict.items():
        group_score = score_item(" ".join(items), jd_analysis)
        kept: List[str] = []
        for s in items:
            if total_kept >= max_skills:
                break
            if src_low and s.lower() not in src_low:
                continue
            c = _canon(s)
            if c in seen_canonical:
                continue
            seen_canonical.add(c)
            kept.append(s)
            total_kept += 1
        if kept:
            scored_groups.append((group_score, group_name, kept))

    scored_groups.sort(key=lambda x: -x[0])
    return {name: items for _, name, items in scored_groups}


def _estimate_lines(selection: Dict[str, Any]) -> int:
    lines = 4  # header + summary
    for role in selection.get("roles", []):
        lines += 2
        for b in role.get("bullets", []):
            txt = b.get("text", "") if isinstance(b, dict) else str(b)
            lines += max(1, (len(txt) + 79) // 80)
    for proj in selection.get("projects", []):
        desc = proj.get("description", "")
        lines += 1 + max(1, (len(desc) + 79) // 80)
    lines += max(1, len(selection.get("skills", {})))
    for edu in selection.get("education", []):
        lines += 2
        if edu.get("placement_role"):
            lines += 1
        if edu.get("coursework"):
            lines += 1
    for extra_key in ("awards", "certifications", "publications", "languages", "gaps"):
        items = selection.get(extra_key) or []
        if items:
            lines += 1 + len(items)
    return lines


def estimate_fill_ratio(selection: Dict[str, Any], page_budget: int = 1) -> float:
    """Estimate normalized page fill in [0.0, 1.0+]."""
    cap = _LINES_PER_PAGE * max(1, page_budget)
    return round(min(1.0, _estimate_lines(selection) / cap), 3)


def select_cv_content(
    master: Dict[str, Any],
    jd_analysis: Dict[str, Any],
    *,
    page_budget: Optional[int] = None,
    candidate_years: float = 3.0,
) -> Dict[str, Any]:
    """Select and rank CV content respecting floors and filling the page budget."""
    arch = jd_analysis.get("archetype", {}).get("archetype", "general")
    level = jd_analysis.get("seniority", {}).get("level", "mid")
    budget = compute_page_budget(candidate_years=candidate_years, archetype=arch, override=page_budget)
    cap_lines = _LINES_PER_PAGE * budget

    raw_roles = master.get("roles", [])
    selected_roles: List[Dict[str, Any]] = []
    extra_bullet_pool: List[Tuple[float, int, Dict[str, Any]]] = []

    for r_idx, role in enumerate(raw_roles):
        bullets = list(role.get("bullets", []))
        scored = [
            (score_item(b.get("text", "") if isinstance(b, dict) else str(b), jd_analysis), b_idx, b)
            for b_idx, b in enumerate(bullets)
        ]
        # Keep strongest quantified result first, then highest relevance score
        scored_sorted = sorted(
            scored,
            key=lambda x: (-(1 if (isinstance(x[2], dict) and x[2].get("has_metric")) else 0), -x[0], x[1]),
        )
        floor = min(len(bullets), 3 if r_idx == 0 else 1)
        chosen = [item[2] for item in scored_sorted[:floor]]
        chosen_ids = {id(item) for item in chosen}
        for s_val, _, b_obj in scored_sorted[floor:]:
            if id(b_obj) not in chosen_ids:
                extra_bullet_pool.append((s_val, r_idx, b_obj))

        role_copy = dict(role)
        role_copy["bullets"] = chosen
        selected_roles.append(role_copy)

    raw_projects = master.get("projects", [])
    def _proj_rank(p: Dict[str, Any]) -> Tuple[float, int]:
        base = score_item(f"{p.get('name', '')} {p.get('description', '')}", jd_analysis)
        if base > 0 and (p.get("open_source") or p.get("published")):
            base += 3.5
        return (-base, -(1 if p.get("open_source") else 0))

    scored_projects = sorted(raw_projects, key=_proj_rank)
    selected_projects = [dict(p) for p in scored_projects[:4]]
    if len(selected_projects) < min(2, len(raw_projects)):
        selected_projects = [dict(p) for p in scored_projects[:2]]

    education = filter_education(master.get("education", []))
    skills = organize_skills(master.get("skills", {}), jd_analysis)

    selection: Dict[str, Any] = {
        "name": master.get("name", ""),
        "summary": master.get("summary", ""),
        "section_order": choose_section_order(archetype=arch, level=level, candidate_years=candidate_years),
        "roles": selected_roles,
        "projects": selected_projects,
        "skills": skills,
        "education": education,
        "gaps": list(master.get("gaps", [])),
        "page_budget": budget,
        "extras_used": [],
    }

    # Fill remaining space up to target [92%, 100%] without overflowing cap_lines
    extra_bullet_pool.sort(key=lambda x: -x[0])
    for _, r_idx, b_obj in extra_bullet_pool:
        if _estimate_lines(selection) >= int(cap_lines * 0.94):
            break
        selected_roles[r_idx]["bullets"].append(b_obj)
        selection["extras_used"].append(f"bullet:{r_idx}")

    for extra_key in ("awards", "certifications", "publications", "languages"):
        items = master.get(extra_key) or []
        if not items:
            continue
        if _estimate_lines(selection) >= int(cap_lines * 0.96):
            break
        selection[extra_key] = list(items)
        selection["extras_used"].append(extra_key)

    return selection
