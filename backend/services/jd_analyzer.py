"""Phase 2: Deterministic job description analyzer.

Parses JD sections, weights requirements, classifies role archetypes,
detects seniority/knockouts/quality issues/language/spelling, and extracts
company context without letting boilerplate or benefits leak into keywords.
"""
from __future__ import annotations

import html
import re
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple


_SECTION_HEADERS: List[Tuple[str, Tuple[str, ...]]] = [
    ("benefits", ("benefits", "perks", "what we offer", "compensation & benefits", "why join")),
    ("legal", ("equal opportunity", "eeo", "diversity", "legal", "accommodation", "privacy notice")),
    ("preferred", ("preferred", "nice to have", "nice-to-have", "bonus", "desired", "plus")),
    ("required", ("required", "minimum qualifications", "requirements", "must have", "must-have", "qualifications")),
    ("responsibilities", ("responsibilities", "what you'll do", "what you will do", "your role", "day to day")),
    ("about_role", ("about the role", "about us", "about the team", "overview", "summary", "role")),
]

_KNOWN_TERMS: Tuple[str, ...] = (
    "Python", "PyTorch", "TensorFlow", "FastAPI", "Django", "Flask", "SQL", "PostgreSQL",
    "Docker", "Kubernetes", "LangGraph", "LangChain", "RAG", "LLM", "Large Language Models",
    "Agentic Workflows", "Multi-Agent", "Tool Calling", "NLP", "Computer Vision", "OpenCV",
    "Transformers", "Hugging Face", "vLLM", "scikit-learn", "Spark", "Terraform", "AWS",
    "GCP", "Azure", "CI/CD", "Git", "TypeScript", "React", "Next.js", "Go", "Rust",
    "Ruby", "Scala", "Elixir", "GraphQL", "Ansible", "Unity", "ROS2", "Vector Databases",
    "Embeddings", "Fine-tuning", "Evaluation", "Xcode", "Swift",
)

_ARCHETYPE_RULES: List[Tuple[str, Tuple[str, ...], List[str]]] = [
    (
        "docs_devrel",
        ("developer publications", "devrel", "developer relations", "documentation", "technical writer", "developer advocacy"),
        ["summary", "skills", "projects", "experience", "education"],
    ),
    (
        "research",
        ("research scientist", "research engineer", "publications", "neurips", "icml", "arxiv"),
        ["summary", "education", "publications", "projects", "experience", "skills"],
    ),
    (
        "platform",
        ("platform", "mlops", "infrastructure", "kubernetes", "serving", "distributed systems"),
        ["summary", "skills", "experience", "projects", "education"],
    ),
    (
        "data_science",
        ("data scientist", "analytics", "experimentation", "a/b testing", "statistical"),
        ["summary", "experience", "skills", "projects", "education"],
    ),
    (
        "management",
        ("engineering manager", "head of", "director", "vp ", "people management"),
        ["summary", "experience", "skills", "education"],
    ),
    (
        "applied_ml",
        ("machine learning", "applied ml", "ai engineer", "llm", "genai", "nlp", "computer vision", "rag"),
        ["summary", "skills", "experience", "projects", "education"],
    ),
    (
        "swe",
        ("software engineer", "backend", "frontend", "full stack", "fullstack"),
        ["summary", "experience", "projects", "skills", "education"],
    ),
]

_NON_EN_MARKERS: Dict[str, Tuple[str, ...]] = {
    "de": ("wir suchen", "anforderungen", "erfahrung mit", "für unser", "kenntnisse", "und", "mit"),
    "fr": ("nous recherchons", "compétences", "expérience", "avec", "pour notre"),
    "es": ("buscamos", "requisitos", "experiencia", "para nuestro", "conocimientos"),
}

_UK_SPELLING = ("optimise", "optimising", "analyse", "analysing", "behaviour", "organisation", "colour", "centre")
_US_SPELLING = ("optimize", "optimizing", "analyze", "analyzing", "behavior", "organization", "color", "center")


def _strip_html(text: str) -> Tuple[str, bool]:
    if "<" not in text or ">" not in text:
        return text, False
    cleaned = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = html.unescape(cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    return cleaned.strip(), cleaned != text


def parse_jd_sections(jd_text: str) -> Dict[str, str]:
    """Split a JD into canonical sections; benefits and legal stay isolated."""
    sections: Dict[str, List[str]] = {
        "about_role": [],
        "responsibilities": [],
        "required": [],
        "preferred": [],
        "benefits": [],
        "legal": [],
    }
    current = "about_role"
    for raw_line in (jd_text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        low = line.lower().rstrip(":")
        matched_section: Optional[str] = None
        if len(low) <= 60:
            for sec_name, markers in _SECTION_HEADERS:
                if any(low == m or low.startswith(m + " ") or low.startswith(m + ":") or m in low for m in markers):
                    # Inline "Required: Python, SQL" should also capture remainder
                    matched_section = sec_name
                    break
        if matched_section:
            current = matched_section
            if ":" in line:
                _, rest = line.split(":", 1)
                if rest.strip():
                    sections[current].append(rest.strip())
            continue
        sections[current].append(line)
    return {k: "\n".join(v).strip() for k, v in sections.items()}


def _find_terms(text: str) -> List[str]:
    found: List[str] = []
    low = text.lower()
    for term in _KNOWN_TERMS:
        pattern = r"(?<![a-z0-9])" + re.escape(term.lower()) + r"(?![a-z0-9])"
        if re.search(pattern, low):
            found.append(term)
    return found


def extract_weighted_requirements(jd_text: str, title: str = "") -> Dict[str, Any]:
    """Rank requirements by section, title match, repetition, and years attached."""
    sections = parse_jd_sections(jd_text)
    relevant_text = "\n".join(
        sections[k] for k in ("about_role", "responsibilities", "required", "preferred") if sections[k]
    )
    if not relevant_text.strip():
        return {"must_have": [], "strong": [], "nice_to_have": [], "scores": {}}

    scores: Dict[str, float] = {}
    title_low = (title or "").lower()
    req_low = sections["required"].lower()
    resp_low = sections["responsibilities"].lower()
    pref_low = sections["preferred"].lower()
    rel_low = relevant_text.lower()

    for term in _find_terms(relevant_text + "\n" + (title or "")):
        t_low = term.lower()
        pat = r"(?<![a-z0-9])" + re.escape(t_low) + r"(?![a-z0-9])"
        score = 0.0
        if re.search(pat, title_low):
            score += 4.0
        if re.search(pat, req_low):
            score += 3.5
        if re.search(pat, resp_low):
            score += 2.0
        if re.search(pat, pref_low) and not re.search(pat, req_low):
            score += 0.8
        count = len(re.findall(pat, rel_low))
        score += min(count, 4) * 0.6
        if re.search(rf"\d+\+?\s*years?.{{0,25}}{re.escape(t_low)}", rel_low):
            score += 1.5
        scores[term] = round(score, 2)

    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0].lower()))
    must_have = [t for t, s in ranked if s >= 4.0]
    strong = [t for t, s in ranked if 2.0 <= s < 4.0]
    nice_to_have = [t for t, s in ranked if s < 2.0]
    return {
        "must_have": must_have,
        "strong": strong,
        "nice_to_have": nice_to_have,
        "scores": dict(ranked),
    }


def classify_archetype(title: str, jd_text: str) -> Dict[str, Any]:
    """Classify the job archetype and return recommended section order."""
    combined = f"{title}\n{jd_text}".lower()
    for archetype, markers, order in _ARCHETYPE_RULES:
        if any(m in combined for m in markers):
            return {
                "archetype": archetype,
                "section_order": list(order),
                "emphasis": list(markers[:3]),
            }
    return {
        "archetype": "general",
        "section_order": ["summary", "experience", "skills", "projects", "education"],
        "emphasis": [],
    }


def assess_seniority(
    jd_text: str,
    title: str = "",
    candidate_years: Optional[float] = None,
) -> Dict[str, Any]:
    """Extract required years/level and compare against candidate's computed years."""
    combined = f"{title}\n{jd_text}"
    years_matches = [int(m) for m in re.findall(r"(\d+)\s*\+?\s*years?", combined, flags=re.IGNORECASE)]
    required_years = max(years_matches) if years_matches else None

    low = (title or "").lower()
    if any(w in low for w in ("principal", "staff", "lead")):
        level = "staff"
    elif "senior" in low or "sr." in low or (required_years and required_years >= 5):
        level = "senior"
    elif "intern" in low or "junior" in low or "graduate" in low:
        level = "junior"
    else:
        level = "mid"

    status = "unknown"
    gap_note = ""
    if candidate_years is not None and required_years is not None:
        if candidate_years + 0.25 < required_years:
            status = "under_qualified"
            gap_note = f"Role asks for {required_years}+ years; candidate dates show {candidate_years:g} years."
        elif candidate_years > required_years + 5:
            status = "over_qualified"
            gap_note = f"Role asks for {required_years}+ years; candidate has {candidate_years:g} years."
        else:
            status = "match"

    return {
        "required_years": required_years,
        "level": level,
        "candidate_years": candidate_years,
        "status": status,
        "gap_note": gap_note,
    }


def detect_knockouts(jd_text: str) -> List[Dict[str, str]]:
    """Detect hard requirements / knockouts without hiding mismatches."""
    patterns: List[Tuple[str, str]] = [
        ("work_authorization", r"(?:authorized|authorised)\s+to\s+work|without\s+(?:visa\s+)?sponsorship|right\s+to\s+work"),
        ("location", r"(?:on-?site|hybrid|relocat|based\s+in|days?\s+in\s+office)"),
        ("clearance", r"security\s+clearance|\b(?:sc|dv|ts/sci|secret)\s+clearance\b"),
        ("security_check", r"background\s+(?:security\s+)?check|vetting"),
        ("degree", r"(?:bachelor|master|phd|doctorate)(?:'s)?\s+degree\s+in\s+[a-z ]+|degree\s+required"),
        ("language", r"fluent\s+(?:in\s+)?[a-z]+|bilingual\s+in"),
        ("travel", r"able\s+to\s+travel|travel\s+up\s+to\s+\d+%"),
    ]
    found: List[Dict[str, str]] = []
    for line in (jd_text or "").splitlines():
        s = line.strip()
        if not s:
            continue
        low = s.lower()
        for category, pat in patterns:
            if re.search(pat, low):
                if not any(item["category"] == category for item in found):
                    found.append({"category": category, "evidence": s})
    return found


def extract_company_context(jd_text: str, company: str = "") -> Dict[str, Any]:
    """Extract mission/product context for tone only (never quoted on CV)."""
    mission = ""
    product_area = ""
    for line in (jd_text or "").splitlines():
        low = line.lower()
        if not mission and ("mission" in low or "we believe" in low or "our goal" in low):
            mission = line.strip()
        if not product_area and ("team" in low or "group" in low or "platform" in low):
            product_area = line.strip()
    return {
        "company": company,
        "mission": mission,
        "product_area": product_area,
    }


def detect_language(jd_text: str) -> str:
    """Lightweight language detector for JD gating."""
    low = f" {(jd_text or '').lower()} "
    best_lang = "en"
    best_hits = 0
    for lang, markers in _NON_EN_MARKERS.items():
        hits = sum(1 for m in markers if f" {m} " in low or m in low)
        if hits > best_hits:
            best_hits = hits
            best_lang = lang
    return best_lang if best_hits >= 3 else "en"


def detect_spelling_variant(jd_text: str, location: str = "", master_text: str = "") -> str:
    """Infer en-GB vs en-US from job text, location, and master CV."""
    combined = f"{jd_text}\n{master_text}".lower()
    uk_hits = sum(1 for w in _UK_SPELLING if re.search(rf"\b{w}\b", combined))
    us_hits = sum(1 for w in _US_SPELLING if re.search(rf"\b{w}\b", combined))
    if uk_hits > us_hits:
        return "en-GB"
    if us_hits > uk_hits:
        return "en-US"
    loc_low = (location or "").lower()
    if any(k in loc_low for k in ("uk", "united kingdom", "london", "manchester", "edinburgh", "cambridge, uk")):
        return "en-GB"
    return "en-US"


def check_jd_quality(jd_text: str) -> Dict[str, Any]:
    """Classify JD quality edge cases and return a defined action/note."""
    raw = (jd_text or "").strip()
    if not raw:
        return {"status": "empty", "usable": False, "cleaned_text": "", "note": "JD is empty; using master CV."}

    cleaned, had_html = _strip_html(raw)
    low = cleaned.lower()

    if any(m in low for m in ("sign in to linkedin", "join now to see", "log in to view", "please sign in to continue")):
        return {"status": "login_wall", "usable": False, "cleaned_text": cleaned, "note": "JD appears to be a login wall; paste full job text."}
    if any(m in low for m in ("no longer accepting applications", "position has been filled", "job is closed", "this role has closed")):
        return {"status": "closed", "usable": False, "cleaned_text": cleaned, "note": "Job posting appears closed."}
    if len(cleaned) < 120:
        return {"status": "too_short", "usable": False, "cleaned_text": cleaned, "note": "JD is under 120 characters; using master CV."}

    sections = parse_jd_sections(cleaned)
    non_boilerplate = " ".join(sections[k] for k in ("about_role", "responsibilities", "required", "preferred")).strip()
    has_boilerplate_markers = any(
        m in low for m in ("equal opportunity employer", "without regard to race", "veteran status", "401k")
    )
    if (len(non_boilerplate) < 40 and (sections["benefits"] or sections["legal"])) or (
        has_boilerplate_markers and not _find_terms(cleaned) and not sections["required"] and not sections["responsibilities"]
    ):
        return {"status": "boilerplate_only", "usable": False, "cleaned_text": cleaned, "note": "JD contains only boilerplate/benefits."}

    sentences = [s.strip().lower() for s in re.split(r"[.\n]+", cleaned) if len(s.strip()) > 20]
    if sentences:
        counts = Counter(sentences)
        if counts.most_common(1)[0][1] >= 3 and len(counts) <= max(2, len(sentences) // 3):
            return {"status": "duplicated", "usable": False, "cleaned_text": cleaned, "note": "JD text is heavily duplicated."}

    lang = detect_language(cleaned)
    if lang != "en":
        return {"status": "non_english", "usable": True, "cleaned_text": cleaned, "note": f"Non-English JD detected ({lang}); keep CV in target language."}

    bullets = [ln for ln in cleaned.splitlines() if ln.strip().startswith(("-", "*", "•"))]
    if len(bullets) >= 35:
        return {"status": "oversized", "usable": True, "cleaned_text": cleaned, "note": f"Oversized JD ({len(bullets)} bullets); focusing on top weighted terms."}

    if had_html:
        return {"status": "html_cleaned", "usable": True, "cleaned_text": cleaned, "note": "Stripped HTML markup from JD."}

    return {"status": "ok", "usable": True, "cleaned_text": cleaned, "note": ""}


def analyze_jd(
    jd_text: str,
    title: str = "",
    company: str = "",
    location: str = "",
    candidate_years: Optional[float] = None,
    target_cv_language: Optional[str] = None,
    master_text: str = "",
) -> Dict[str, Any]:
    """Run full Phase 2 JD analysis."""
    quality = check_jd_quality(jd_text)
    cleaned = quality["cleaned_text"] or jd_text or ""
    sections = parse_jd_sections(cleaned)
    requirements = extract_weighted_requirements(cleaned, title=title)
    archetype = classify_archetype(title, cleaned)
    seniority = assess_seniority(cleaned, title=title, candidate_years=candidate_years)
    knockouts = detect_knockouts(cleaned)
    company_context = extract_company_context(cleaned, company=company)
    jd_language = detect_language(cleaned)
    cv_language = target_cv_language or "en"
    spelling = detect_spelling_variant(cleaned, location=location, master_text=master_text)

    return {
        "quality": quality,
        "sections": sections,
        "requirements": requirements,
        "archetype": archetype,
        "seniority": seniority,
        "knockouts": knockouts,
        "company_context": company_context,
        "jd_language": jd_language,
        "cv_language": cv_language,
        "spelling": spelling,
    }
