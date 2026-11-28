"""Phase 1: Source of truth, structured master schema, bullet metadata, alias map, and evidence snippets."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

try:
    from . import cv_tailor, fit_scorer
    from .resume_audit import _mentions
except ImportError:  # pragma: no cover
    import cv_tailor
    import fit_scorer
    from resume_audit import _mentions


# Explicit, auditable alias & synonym map (1.5). Used for evidence only, never to add words the source lacks.
ALIAS_MAP: Dict[str, Tuple[str, ...]] = {
    "large language models": ("llm", "llms", "large language model"),
    "large language model": ("llm", "llms", "large language models"),
    "llm": ("large language model", "large language models"),
    "llms": ("large language model", "large language models"),
    "machine learning": ("ml",),
    "ml": ("machine learning",),
    "generative ai": ("genai", "gen ai"),
    "genai": ("generative ai",),
    "retrieval-augmented generation": ("rag", "retrieval augmented generation"),
    "rag": ("retrieval-augmented generation", "retrieval augmented generation"),
    "kubernetes": ("k8s",),
    "k8s": ("kubernetes",),
    "natural language processing": ("nlp",),
    "nlp": ("natural language processing",),
    "computer vision": ("cv",),
    "ci/cd": ("continuous integration", "continuous delivery", "github actions"),
    "agentic workflows": ("multi-agent", "langgraph agent", "langgraph agents", "agentic"),
    "multi-agent systems": ("multi-agent", "langgraph agents", "agentic workflows"),
}

_METRIC_RE = re.compile(r"\d[\d,.]*%|\d[\d,.]*\+|INR\s*\d[\d,.]*\w*|£\d[\d,.]*\w*|\$\d[\d,.]*\w*")


def _extract_resume_text(resume_path: str) -> str:
    p = Path(resume_path)
    if not p.is_file():
        return ""
    ext = p.suffix.lower()
    if ext in (".tex", ".txt", ".md"):
        return p.read_text(encoding="utf-8", errors="replace")
    if ext == ".pdf":
        try:
            import pypdf  # type: ignore
            reader = pypdf.PdfReader(str(p))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception:
            return p.read_bytes().decode("utf-8", errors="ignore")
    if ext == ".docx":
        try:
            import docx  # type: ignore
            doc = docx.Document(str(p))
            return "\n".join(par.text for par in doc.paragraphs)
        except Exception:
            return ""
    return p.read_text(encoding="utf-8", errors="replace")


_SKILL_HEADER = re.compile(r"(?im)^\s*(?:technical\s+)?skills(?:\s*(?:&|and)\s*[a-z ]+)?\s*$")
_NEXT_SECTION = re.compile(r"^[A-Z][A-Z &/]{3,}$")
_GROUP_LINE = re.compile(r"^([A-Z][A-Za-z0-9/&,+ \-]{1,44}?):\s*(.*)$")


def _split_items(text: str) -> List[str]:
    out, depth, cur = [], 0, ""
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return [i.strip().rstrip(".").strip() for i in out if i.strip().rstrip(".").strip()]


def skill_groups_from_resume_text(text: str) -> Dict[str, List[str]]:
    """The labelled skill lines of a resume ("Languages: Python, C++ ..."), in order. Every label and item is copied from the
    resume text; nothing here is generated. Wrapped lines are joined to the group they belong to."""
    lines = (text or "").splitlines()
    start = next((i for i, l in enumerate(lines) if _SKILL_HEADER.match(l)), None)
    if start is None:
        return {}
    groups: Dict[str, str] = {}
    current = None
    for line in lines[start + 1:]:
        stripped = line.strip()
        if not stripped:
            continue
        if _NEXT_SECTION.match(stripped) and ":" not in stripped:
            break
        m = _GROUP_LINE.match(stripped)
        if m and not stripped.lower().startswith(("http", "opensource")):
            current = m.group(1).strip()
            groups[current] = m.group(2)
        elif current:
            groups[current] += " " + stripped
    flat = re.sub(r"\s+", " ", text)
    result: Dict[str, List[str]] = {}
    for label, body in groups.items():
        items = [i for i in _split_items(re.sub(r"\s+", " ", body)) if i in flat]     # drop anything not literally in the resume
        if items:
            result[label] = list(dict.fromkeys(items))
    return result


def resume_text(resume_path: Optional[str] = None) -> str:
    """The text of the candidate's resume file (MASTER_RESUME_PATH unless a path is given); empty when there is none."""
    path = resume_path or os.environ.get("MASTER_RESUME_PATH", "")
    return _extract_resume_text(path) if path else ""


_LABELS = {"OpenSource", "LinkedIn", "GitHub"}
_YEAR = re.compile(r"^(?:19|20)\d\d$")


def resume_gaps(resume_text: str, master: Dict[str, Any]) -> Dict[str, List[str]]:
    """Facts that appear in the candidate's resume file but not in the CV data the app builds from: numbers (proof points, grades)
    and tool or product names. Dates, years, phone numbers and web addresses are ignored. Empty lists mean nothing is lost."""
    text = re.sub(r"https?://\S+|\S+@\S+|\+?\d[\d ]{8,}\d|\b[\w.-]+\.(?:com|io|org|net|dev|ai|co\.uk)\b\S*", " ", resume_text or "")
    name_parts = {w.lower() for w in re.findall(r"[A-Za-z]{3,}", str(master.get("name") or ""))}
    # all-capital lines are the name and the section headings, not facts
    text = "\n".join(l for l in text.splitlines() if not (len(re.findall(r"[A-Za-z]", l)) >= 4 and l.upper() == l and not re.search(r"\d", l)))
    have = cv_tailor.cv_text(master) + "\n" + "\n".join(f"{c['skill']} {c['evidence']}" for c in master.get("confirmed_experience", []))
    have_low = have.lower()
    numbers = []
    for n in re.findall(r"\d[\d,.]*[+%]?", text):
        core = n.strip(".,")
        if len(core.strip("+%,.")) < 2 or _YEAR.match(core.strip("+%")) or core in have:
            continue
        numbers.append(core)
    names = []
    for tok in re.findall(r"\b(?:[A-Z]{2,}[A-Za-z0-9]*|[A-Za-z]+[A-Z][A-Za-z0-9]+|[A-Za-z]+\d[A-Za-z0-9.\-]*|[A-Za-z0-9]+(?:\+\+|#))", text):
        glued = bool(re.match(r"^[a-z][A-Za-z]*[A-Z]", tok) or re.match(r"^[A-Za-z][a-z]+\d", tok))   # "theBIU", "by60": PDF text runs words together
        if glued or tok in _LABELS or tok.lower() in have_low or tok.lower() in name_parts or tok in names:
            continue
        names.append(tok)
    return {"numbers": list(dict.fromkeys(numbers))[:15], "names": names[:15]}


def resume_skill_groups(resume_path: Optional[str] = None) -> Dict[str, List[str]]:
    path = resume_path or os.environ.get("MASTER_RESUME_PATH", "")
    return skill_groups_from_resume_text(_extract_resume_text(path)) if path else {}


def diff_resume_and_profile(resume_path: str, profile: Dict[str, Any]) -> Dict[str, Any]:
    """1.1: Diff the candidate's real resume file against candidate_profile.json."""
    raw = _extract_resume_text(resume_path)
    prof_text = cv_tailor.cv_text(cv_tailor.master_cv_from_profile(profile)).lower()
    missing: List[str] = []
    # Check notable entities: CPI/GPA, Placement/Coordinator roles, and project/section lines
    for line in raw.splitlines():
        clean = re.sub(r"\\[a-zA-Z]+\{|\}|\\", " ", line).strip()
        if not clean or len(clean) < 4:
            continue
        if re.search(r"\b(?:cpi|gpa)\b", clean, re.I) and "cpi" not in prof_text and "gpa" not in prof_text:
            missing.append(clean)
        elif re.search(r"\bplacement\b", clean, re.I) and "placement" not in prof_text:
            missing.append(clean)
        elif ":" in clean and not re.match(r"^(?:section|email|phone)", clean, re.I):
            head = clean.split(":", 1)[0].strip()
            if len(head) >= 3 and head.lower() not in prof_text:
                missing.append(head)
    return {"resume_path": resume_path, "missing_from_profile": list(dict.fromkeys(missing))}


def check_profile_drift(resume_path: Optional[str], profile_path: Optional[str], pack_dir: Optional[str] = None) -> List[str]:
    """1.2: Warn when the resume file is newer than the profile, or the pack is older than the profile."""
    warnings: List[str] = []
    r_mtime = os.path.getmtime(resume_path) if resume_path and os.path.isfile(resume_path) else None
    p_mtime = os.path.getmtime(profile_path) if profile_path and os.path.isfile(profile_path) else None
    if r_mtime and p_mtime and r_mtime > p_mtime:
        warnings.append("Resume file is newer than candidate_profile.json; consider rebuilding your profile.")
    if pack_dir and p_mtime:
        m_path = os.path.join(pack_dir, "manifest.json")
        if os.path.isfile(m_path) and os.path.getmtime(m_path) < p_mtime:
            warnings.append("Application pack is older than candidate_profile.json; consider regenerating.")
    return warnings


def compute_bullet_metadata(bullet_text: str, role_idx: int, bullet_idx: int, skills_list: List[str]) -> Dict[str, Any]:
    """1.4: Compute deterministic metadata for a single bullet."""
    low = bullet_text.lower()
    metrics = _METRIC_RE.findall(bullet_text)
    skills_used = [s for s in skills_list if s and _mentions(low, s)]
    if metrics:
        outcome_type = "quantified"
    elif re.search(r"\b(?:built|designed|engineered|developed|created|launched)\b", low):
        outcome_type = "delivery"
    else:
        outcome_type = "support"
    seniority = "senior" if re.search(r"\b(?:architected|led|spearheaded|owned|directed)\b", low) else "ic"
    digest = hashlib.sha256(f"{role_idx}:{bullet_idx}:{bullet_text}".encode("utf-8")).hexdigest()[:12]
    return {
        "id": f"exp:{role_idx}:{bullet_idx}",
        "hash": digest,
        "skills_used": skills_used,
        "outcome_type": outcome_type,
        "has_metric": bool(metrics),
        "metrics": metrics,
        "recency_rank": role_idx,
        "seniority_signal": seniority,
    }


def confirmed_experience(candidate: Dict[str, Any]) -> List[Dict[str, str]]:
    """Skills the candidate confirmed themselves, each with their own sentence about where they used it. This is the ONLY way a
    skill the resume does not show can reach the CV: the candidate states it, in their own words, with an explicit action."""
    out = []
    for item in candidate.get("confirmed_experience") or []:
        if isinstance(item, dict) and str(item.get("skill") or "").strip() and len(str(item.get("evidence") or "").strip()) >= 20:
            out.append({"skill": str(item["skill"]).strip(), "evidence": str(item["evidence"]).strip(),
                        "group": str(item.get("group") or "").strip()})
    return out


def confirmed_evidence_text(master: Dict[str, Any]) -> str:
    """The candidate's own sentences, for checking claims against; never printed on the CV."""
    return "\n".join(f"{c['skill']}: {c['evidence']}" for c in master.get("confirmed_experience") or [])


def _resume_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _master_cache_file(file_hash: str) -> Path:
    return Path(os.path.dirname(fit_scorer._cache_path())) / f"master_resume_{file_hash[:16]}.json"


def _verify_extracted_against_resume(parsed: Dict[str, Any], raw_text: str) -> Dict[str, Any]:
    """Keep only extracted strings that appear verbatim (whitespace-normalized) in raw_text."""
    norm_raw = re.sub(r"\s+", " ", raw_text or "").strip().lower()

    def _keep(val: Any) -> str:
        s = str(val or "").strip()
        if not s:
            return ""
        return s if re.sub(r"\s+", " ", s).lower() in norm_raw else ""

    summary = _keep(parsed.get("summary"))
    work_experience: List[Dict[str, Any]] = []
    for r in parsed.get("work_experience") or []:
        if not isinstance(r, dict):
            continue
        company = _keep(r.get("company"))
        if not company:
            continue
        role = _keep(r.get("role"))
        start_date = _keep(r.get("start_date"))
        end_raw = str(r.get("end_date") or "").strip()
        end_date = "Present" if end_raw.lower() == "present" and "present" in norm_raw else _keep(end_raw)
        location = _keep(r.get("location"))
        techs = [_keep(t) for t in (r.get("technologies") or []) if _keep(t)]
        bullets = [_keep(b) for b in (r.get("highlights") or r.get("description") or []) if _keep(b)]
        if bullets or role:
            work_experience.append({
                "company": company,
                "role": role,
                "start_date": start_date,
                "end_date": end_date,
                "location": location,
                "technologies": techs,
                "highlights": bullets,
            })

    projects: List[Dict[str, Any]] = []
    for p in parsed.get("projects") or []:
        if not isinstance(p, dict):
            continue
        title = _keep(p.get("title"))
        if not title:
            continue
        techs = [_keep(t) for t in (p.get("technologies") or []) if _keep(t)]
        url = _keep(p.get("url"))
        raw_desc = p.get("description")
        desc_list = raw_desc if isinstance(raw_desc, list) else ([raw_desc] if raw_desc else [])
        desc = [_keep(d) for d in desc_list if _keep(d)]
        projects.append({"title": title, "technologies": techs, "url": url, "description": desc})

    education: List[Dict[str, Any]] = []
    for e in parsed.get("education") or []:
        if not isinstance(e, dict):
            continue
        inst = _keep(e.get("institution"))
        if not inst:
            continue
        education.append({
            "institution": inst,
            "degree": _keep(e.get("degree")),
            "start_date": _keep(e.get("start_date")),
            "graduation_date": _keep(e.get("graduation_date")),
            "location": _keep(e.get("location")),
            "grade": _keep(e.get("grade")),
            "highlights": [_keep(h) for h in (e.get("highlights") or []) if _keep(h)],
        })

    return {
        "summary": summary,
        "work_experience": work_experience,
        "projects": projects,
        "education": education,
    }


def _extract_schema():
    from pydantic import BaseModel

    class RoleItem(BaseModel):
        company: str
        role: str
        start_date: str = ""
        end_date: str = ""
        location: str = ""
        technologies: List[str] = []
        highlights: List[str] = []

    class ProjectItem(BaseModel):
        title: str
        technologies: List[str] = []
        url: str = ""
        description: List[str] = []

    class EduItem(BaseModel):
        institution: str
        degree: str = ""
        start_date: str = ""
        graduation_date: str = ""
        location: str = ""
        grade: str = ""
        highlights: List[str] = []

    class ResumeMaster(BaseModel):
        summary: str = ""
        work_experience: List[RoleItem] = []
        projects: List[ProjectItem] = []
        education: List[EduItem] = []

    return ResumeMaster


def extract_master_from_resume(
    resume_path: Optional[str] = None,
    llm: Optional[Callable[[str], str]] = None,
) -> Dict[str, Any]:
    """Split MASTER_RESUME_PATH text into roles, bullets, projects, education; verify every string is in the resume; cache by hash."""
    raw = resume_text(resume_path)
    if not raw.strip():
        return {}
    h = _resume_hash(raw)
    cache_path = _master_cache_file(h)
    if llm is None and cache_path.is_file():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(cached, dict) and cached.get("resume_hash") == h:
                return cached
        except (OSError, ValueError):
            pass

    prompt = (
        "Split the resume text below into JSON (summary, work_experience, projects, education).\n"
        "CRITICAL: Copy every string VERBATIM from the resume text. Do not paraphrase, fix grammar, or invent anything.\n\n"
        f"RESUME TEXT:\n{raw[:14000]}"
    )
    if llm is None:
        from . import cv_model_runner
        raw_out = cv_model_runner.call_tailor_model(prompt, _extract_schema())
    else:
        raw_out = llm(prompt)
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", str(raw_out or "").strip())
    parsed = json.loads(cleaned)
    if not isinstance(parsed, dict):
        raise ValueError("extracted resume master is not a JSON object")
    verified = _verify_extracted_against_resume(parsed, raw)
    verified["skill_groups"] = skill_groups_from_resume_text(raw)
    verified["resume_hash"] = h
    if llm is None:
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(verified, indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
    return verified


def diff_extracted_master_and_profile(extracted: Dict[str, Any], candidate: Dict[str, Any]) -> Dict[str, Any]:
    """Summarize differences between the resume-extracted master and candidate_profile.json."""
    ext_roles = extracted.get("work_experience") or []
    prof_roles = candidate.get("work_experience") or candidate.get("experience") or []
    ext_bullets = sum(len(r.get("highlights") or []) for r in ext_roles)
    prof_bullets = sum(len(fit_scorer._bullets(r)) for r in prof_roles if isinstance(r, dict))
    ext_projs = extracted.get("projects") or []
    prof_projs = candidate.get("projects") or []
    ext_edu = extracted.get("education") or []
    prof_edu = candidate.get("education") or []

    prof_companies = {str(r.get("company") or "").strip().lower() for r in prof_roles if isinstance(r, dict)}
    new_companies = [r["company"] for r in ext_roles if r.get("company", "").strip().lower() not in prof_companies]
    prof_proj_titles = {str(p.get("title") or p.get("name") or "").strip().lower() for p in prof_projs if isinstance(p, dict)}
    new_projects = [p["title"] for p in ext_projs if p.get("title", "").strip().lower() not in prof_proj_titles]

    has_changes = bool(
        new_companies
        or new_projects
        or len(ext_roles) != len(prof_roles)
        or ext_bullets != prof_bullets
        or len(ext_edu) != len(prof_edu)
    )
    return {
        "roles_resume": len(ext_roles),
        "roles_profile": len(prof_roles),
        "bullets_resume": ext_bullets,
        "bullets_profile": prof_bullets,
        "projects_resume": len(ext_projs),
        "projects_profile": len(prof_projs),
        "education_resume": len(ext_edu),
        "education_profile": len(prof_edu),
        "new_companies": new_companies,
        "new_projects": new_projects,
        "has_changes": has_changes,
    }


def build_structured_master(candidate: Dict[str, Any], resume_path: Optional[str] = None) -> Dict[str, Any]:
    """1.3: Build full structured master CV schema with optional sections and bullet metadata.
    The skill groups come from the real resume file when there is one (MASTER_RESUME_PATH): it is the source of truth for
    what the candidate lists, and the profile may hold only part of it."""
    effective = dict(candidate or {})
    if isinstance(effective.get("master_from_resume"), dict):
        mfr = effective["master_from_resume"]
        for k in ("work_experience", "projects", "education"):
            if mfr.get(k):
                effective[k] = mfr[k]
        if mfr.get("summary"):
            effective["experience_summary"] = mfr["summary"]
    master = cv_tailor.master_cv_from_profile(effective)
    from_resume = resume_skill_groups(resume_path)
    if len(from_resume) >= 2:
        master["skill_groups"] = from_resume
        merged = [s for items in from_resume.values() for s in items]
        master["skills"] = list(dict.fromkeys(merged + list(master.get("skills") or [])))
    confirmed = confirmed_experience(candidate)
    if confirmed:
        known = {x.lower() for x in master.get("skills") or []}
        for item in confirmed:
            if item["skill"].lower() not in known:
                master["skills"] = list(master.get("skills") or []) + [item["skill"]]
                known.add(item["skill"].lower())
            groups = master.get("skill_groups")
            if groups is not None and groups:
                group = item.get("group") or "Additional skills"
                if item["skill"].lower() not in {x.lower() for g in groups.values() for x in g}:
                    groups.setdefault(group, []).append(item["skill"])
        master["confirmed_experience"] = confirmed
    skills = master.get("skills") or []
    for i, exp in enumerate(master.get("experience") or []):
        exp["id"] = f"exp:{i}"
        exp["location"] = str((candidate.get("work_experience") or [{}])[i].get("location") or "") if i < len(candidate.get("work_experience") or []) else ""
        exp["current"] = str(exp.get("end_date") or "").strip().lower() in ("present", "current", "")
        exp["bullet_meta"] = [
            compute_bullet_metadata(b, i, j, skills) for j, b in enumerate(exp.get("description") or [])
        ]
    for i, edu in enumerate(master.get("education") or []):
        src_edu = (candidate.get("education") or [])[i] if i < len(candidate.get("education") or []) else {}
        edu["grade"] = str(src_edu.get("grade") or src_edu.get("cpi") or src_edu.get("gpa") or "")
        edu["coursework"] = list(src_edu.get("coursework") or [])
    for key in ("certifications", "awards", "publications", "languages", "volunteering"):
        val = candidate.get(key) or []
        master[key] = [str(x) for x in val] if isinstance(val, list) else []
    master["clearance"] = str(candidate.get("clearance") or "")
    master["work_authorization"] = str(candidate.get("work_authorization") or "")
    return master


def _all_spans(master: Dict[str, Any]) -> List[Tuple[str, str]]:
    spans: List[Tuple[str, str]] = []
    if master.get("summary"):
        spans.append(("summary", str(master["summary"])))
    for i, e in enumerate(master.get("experience") or []):
        if e.get("technologies"):
            spans.append((f"exp:{i}:tech", str(e["technologies"])))
        for j, b in enumerate(e.get("description") or []):
            spans.append((f"exp:{i}:{j}", str(b)))
    for i, p in enumerate(master.get("projects") or []):
        spans.append((f"proj:{i}:title", str(p.get("title") or "")))
        for j, d in enumerate(p.get("description") or []):
            spans.append((f"proj:{i}:{j}", str(d)))
    if master.get("skills"):
        spans.append(("skills", ", ".join(str(s) for s in master["skills"])))
    return spans


def has_evidence(keyword: str, master: Dict[str, Any]) -> Dict[str, Any]:
    """1.5 & 1.6: Match keyword against master spans using explicit ALIAS_MAP and return exact source snippet."""
    term = str(keyword or "").strip()
    if not term:
        return {"term": term, "evidenced": False, "snippet": "no evidence", "alias_used": None}
    candidates = [term.lower(), *ALIAS_MAP.get(term.lower(), ())]
    for span_id, text in _all_spans(master):
        low = text.lower()
        for cand in candidates:
            if _mentions(low, cand):
                return {
                    "term": term,
                    "evidenced": True,
                    "span_id": span_id,
                    "snippet": text,
                    "alias_used": None if cand == term.lower() else cand,
                }
    return {"term": term, "evidenced": False, "span_id": None, "snippet": "no evidence", "alias_used": None}


def apply_approved_extras(profile: Dict[str, Any], extras: Dict[str, Any], jd_terms: Optional[List[str]] = None) -> Dict[str, Any]:
    """1.7: Merge only user-approved extra facts into a copy of the profile; never write JD terms."""
    out = copy.deepcopy(profile)
    for key in ("certifications", "awards", "publications", "languages", "volunteering", "projects", "core_skills"):
        if key in extras and isinstance(extras[key], list):
            existing = list(out.get(key) or [])
            for item in extras[key]:
                if item not in existing:
                    existing.append(item)
            out[key] = existing
    return out
