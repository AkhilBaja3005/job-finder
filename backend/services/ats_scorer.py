"""
ats_scorer.py — Deterministic ATS scoring engine.

Computes skills_score and experience_score purely from text signals,
with no LLM involvement. The LLM handles only semantic role_fit scoring.

Final formula:
    overall_score = round(0.40 × skills_score + 0.35 × experience_score + 0.25 × role_fit_score)
"""

import re
import math
from difflib import SequenceMatcher
from typing import List, Tuple, Dict
from dataclasses import dataclass, field


# ─────────────────────────────────────────────────────────────────────────────
# Synonym / alias table for fuzzy skill matching
# Maps canonical name → list of acceptable surface forms
# ─────────────────────────────────────────────────────────────────────────────
SKILL_ALIASES: Dict[str, List[str]] = {
    # AI / ML
    "machine learning":    ["machine learning", "ml", "sklearn", "scikit-learn"],
    "deep learning":       ["deep learning", "dl", "neural network", "neural net"],
    "llm":                 ["llm", "large language model", "gpt", "gemini", "claude", "chatgpt", "foundation model"],
    "nlp":                 ["nlp", "natural language processing", "text mining", "text analysis"],
    "computer vision":     ["computer vision", "cv", "image recognition", "object detection", "cnn"],
    "reinforcement learning": ["reinforcement learning", "rl", "rlhf"],
    "generative ai":       ["generative ai", "gen ai", "genai", "diffusion model", "stable diffusion"],
    "prompt engineering":  ["prompt engineering", "prompt design", "prompting"],
    "rag":                 ["rag", "retrieval augmented generation", "retrieval-augmented"],
    "fine-tuning":         ["fine-tuning", "finetuning", "lora", "qlora", "peft"],
    # Frameworks
    "pytorch":             ["pytorch", "torch"],
    "tensorflow":          ["tensorflow", "tf", "keras"],
    "langchain":           ["langchain", "lang chain"],
    "langgraph":           ["langgraph", "lang graph"],
    "autogen":             ["autogen", "auto gen", "microsoft autogen"],
    "hugging face":        ["hugging face", "huggingface", "transformers"],
    # Languages
    "python":              ["python", "py"],
    "javascript":          ["javascript", "js", "node", "nodejs", "node.js"],
    "typescript":          ["typescript", "ts"],
    "java":                ["java", "jvm"],
    "c++":                 ["c++", "cpp", "c plus plus"],
    "go":                  ["go", "golang"],
    "rust":                ["rust", "rustlang"],
    "sql":                 ["sql", "mysql", "postgresql", "postgres", "sqlite", "t-sql", "plsql"],
    # Cloud / DevOps
    "aws":                 ["aws", "amazon web services", "ec2", "s3", "lambda", "sagemaker"],
    "gcp":                 ["gcp", "google cloud", "bigquery", "vertex ai", "cloud run"],
    "azure":               ["azure", "microsoft azure", "azure ml"],
    "docker":              ["docker", "dockerfile", "containerization"],
    "kubernetes":          ["kubernetes", "k8s", "helm", "eks", "gke", "aks"],
    "terraform":           ["terraform", "iac", "infrastructure as code"],
    "ci/cd":               ["ci/cd", "github actions", "jenkins", "gitlab ci", "circleci", "devops pipeline"],
    # Data
    "spark":               ["spark", "apache spark", "pyspark"],
    "kafka":               ["kafka", "apache kafka"],
    "airflow":             ["airflow", "apache airflow"],
    "dbt":                 ["dbt", "data build tool"],
    "pandas":              ["pandas", "dataframe"],
    # Web
    "react":               ["react", "reactjs", "react.js"],
    "fastapi":             ["fastapi", "fast api"],
    "django":              ["django"],
    "flask":               ["flask"],
    "rest api":            ["rest api", "restful", "rest", "api design"],
    "graphql":             ["graphql"],
    # Vector / Search
    "vector database":     ["vector database", "vector db", "vectordb", "pinecone", "weaviate", "chromadb", "faiss", "milvus"],
    "elasticsearch":       ["elasticsearch", "elastic search", "opensearch"],
}

# Flatten aliases into a lookup: surface_form → canonical_name
_ALIAS_LOOKUP: Dict[str, str] = {}
for canonical, aliases in SKILL_ALIASES.items():
    for alias in aliases:
        _ALIAS_LOOKUP[alias.lower()] = canonical


# ─────────────────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SkillMatchResult:
    score: int                          # 0–100
    matched_required: List[str]         # required skills found
    matched_preferred: List[str]        # preferred skills found (bonus)
    missing_required: List[str]         # required skills not found
    missing_preferred: List[str]        # preferred skills not found
    match_detail: str                   # human-readable breakdown

@dataclass
class ExperienceMatchResult:
    score: int                          # 0–100
    candidate_years: float
    required_years: int
    year_score: int                     # 0–100 component
    detail: str

@dataclass
class ATSScoreResult:
    skills_score: int
    experience_score: int
    matched_skills: List[str]           # union of required + preferred matched
    missing_skills: List[str]           # required skills not found
    matched_required_count: int
    total_required_count: int
    candidate_years: float
    required_years: int
    score_breakdown: Dict[str, str]     # human-readable breakdown per dimension


# ─────────────────────────────────────────────────────────────────────────────
# Text normalisation helpers
# ─────────────────────────────────────────────────────────────────────────────

def _normalise(text: str) -> str:
    """Lowercase, collapse whitespace, remove punctuation noise."""
    text = text.lower()
    text = re.sub(r'[•·▪▸–—]', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def _canonicalise(term: str) -> str:
    """Map a raw term to its canonical form via alias table, else return lowercased."""
    low = _normalise(term)
    return _ALIAS_LOOKUP.get(low, low)

def _fuzzy_similar(a: str, b: str, threshold: float = 0.82) -> bool:
    """True if two strings are similar enough to be considered the same skill."""
    return SequenceMatcher(None, a, b).ratio() >= threshold

def _token_match(candidate_text: str, skill: str) -> bool:
    """
    Check if `skill` appears in `candidate_text`.
    Uses: exact word boundary, alias lookup, and clean normalized text matching.
    """
    canon = _canonicalise(skill)
    norm_text = _normalise(candidate_text)

    # Clean boundary check helper
    def has_word(text: str, word: str) -> bool:
        pattern = r'(?:^|[\s,/\(\)\[\]:;])' + re.escape(word) + r'(?:$|[\s,/\(\)\[\]:;])'
        return bool(re.search(pattern, text))

    # 1. Exact canonical match
    if has_word(norm_text, canon):
        return True

    # 2. Check all known aliases of the canonical form
    aliases = SKILL_ALIASES.get(canon, [skill.lower()])
    for alias in aliases:
        if has_word(norm_text, alias):
            return True

    # 3. Fuzzy fallback (for typos / minor variations)
    for word_group in re.split(r'[\s,/\(\)\[\]:;]+', norm_text):
        if word_group and _fuzzy_similar(canon, word_group):
            return True

    return False


# ─────────────────────────────────────────────────────────────────────────────
# JD parsing: extract required / preferred skills
# ─────────────────────────────────────────────────────────────────────────────

# Patterns that signal "required" context
_REQUIRED_SIGNALS = re.compile(
    r'(required|must.have|mandatory|essential|minimum qualifications?'
    r'|basic qualifications?|you must|we require|key requirements?)',
    re.IGNORECASE
)

# Patterns that signal "preferred / nice-to-have" context
_PREFERRED_SIGNALS = re.compile(
    r'(preferred|nice.to.have|bonus|plus|desired|advantage|ideally'
    r'|good to have|added benefit|would be beneficial)',
    re.IGNORECASE
)

# Common tech-skill extraction pattern (catches "X years of Python", "experience with Kubernetes", etc.)
_SKILL_INLINE = re.compile(
    r'(?:experience(?:\s+with)?|proficiency(?:\s+in)?|knowledge(?:\s+of)?'
    r'|expertise(?:\s+in)?|skilled(?:\s+in)?|familiarity(?:\s+with)?'
    r'|background(?:\s+in)?|strong\s+in|hands.on\s+(?:with|in))\s+'
    r'([A-Za-z0-9\+\#\./\- ]{2,40})',
    re.IGNORECASE
)


def _split_jd_sections(jd_text: str) -> Tuple[str, str]:
    """
    Attempt to split JD into a 'required' section and a 'preferred' section.
    Falls back to treating the whole JD as required if no signals found.
    """
    lines = jd_text.split('\n')
    required_lines, preferred_lines = [], []
    current_bucket = required_lines

    for line in lines:
        if _PREFERRED_SIGNALS.search(line):
            current_bucket = preferred_lines
        elif _REQUIRED_SIGNALS.search(line):
            current_bucket = required_lines
        current_bucket.append(line)

    return '\n'.join(required_lines), '\n'.join(preferred_lines)


def _extract_skill_tokens(text: str) -> List[str]:
    """
    Extract candidate skill tokens from a block of text.
    Strategy:
      1. Bullet/comma-separated lists after skill-signal phrases
      2. Inline "experience with X" patterns
      3. Known alias matches anywhere in text
    """
    norm = _normalise(text)
    found = set()

    # Pass 1: known alias scan (check every alias against the whole text)
    for canonical, aliases in SKILL_ALIASES.items():
        for alias in aliases:
            if re.search(r'\b' + re.escape(alias) + r'\b', norm):
                found.add(canonical)
                break

    # Pass 2: inline "experience with X" pattern — catches things not in alias table
    for m in _SKILL_INLINE.finditer(text):
        raw = m.group(1).strip().rstrip('.,;:)')
        canon = _canonicalise(raw)
        if len(canon) >= 2:
            found.add(canon)

    return list(found)


def extract_jd_skills(jd_text: str) -> Tuple[List[str], List[str]]:
    """
    Returns (required_skills, preferred_skills) extracted from the JD.
    Both lists contain canonical skill names.
    """
    required_text, preferred_text = _split_jd_sections(jd_text)
    required = _extract_skill_tokens(required_text)
    preferred = _extract_skill_tokens(preferred_text)

    # Skills appearing in both → keep them only in required
    preferred = [s for s in preferred if s not in required]

    return required, preferred


# ─────────────────────────────────────────────────────────────────────────────
# Resume skill surface: build a single text blob from all skill signals
# ─────────────────────────────────────────────────────────────────────────────

def _build_resume_skill_surface(resume_data: dict) -> str:
    """
    Merge all text from the resume that contains skill evidence:
    skills list, experience bullets, project bullets, achievements.
    """
    parts = []

    # Skills section (highest signal)
    skills = resume_data.get("skills", [])
    if isinstance(skills, list):
        parts.append(' '.join(skills))

    # Experience bullets
    for exp in resume_data.get("experience", []):
        parts.append(exp.get("role", ""))
        for bullet in exp.get("description", []):
            parts.append(bullet)

    # Project descriptions
    for proj in resume_data.get("projects", []):
        for bullet in proj.get("description", []):
            parts.append(bullet)

    # Achievements
    for ach in resume_data.get("achievements", []):
        parts.append(ach)

    return ' '.join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# Skills scoring
# ─────────────────────────────────────────────────────────────────────────────

def compute_skills_score(
    resume_data: dict,
    required_skills: List[str],
    preferred_skills: List[str],
) -> SkillMatchResult:
    """
    Scores skill match deterministically.

    Weights:
      - Required skills: 80% of skills_score
      - Preferred skills: 20% bonus (capped)

    Formula:
      required_pct  = matched_required / total_required   (if total_required > 0)
      preferred_pct = matched_preferred / total_preferred (if total_preferred > 0)
      skills_score  = round(required_pct * 80 + preferred_pct * 20)
    """
    surface = _build_resume_skill_surface(resume_data)

    matched_req, missing_req = [], []
    for skill in required_skills:
        if _token_match(surface, skill):
            matched_req.append(skill)
        else:
            missing_req.append(skill)

    matched_pref, missing_pref = [], []
    for skill in preferred_skills:
        if _token_match(surface, skill):
            matched_pref.append(skill)
        else:
            missing_pref.append(skill)

    req_pct  = len(matched_req) / len(required_skills)  if required_skills  else 0.5
    pref_pct = len(matched_pref) / len(preferred_skills) if preferred_skills else 1.0

    score = round(req_pct * 80 + pref_pct * 20) if required_skills else 50
    score = min(100, max(0, score))

    detail = (
        f"Required: {len(matched_req)}/{len(required_skills)} matched "
        f"({round(req_pct*100)}%)"
    )
    if preferred_skills:
        detail += f" | Preferred: {len(matched_pref)}/{len(preferred_skills)} matched ({round(pref_pct*100)}%)"

    return SkillMatchResult(
        score=score,
        matched_required=matched_req,
        matched_preferred=matched_pref,
        missing_required=missing_req,
        missing_preferred=missing_pref,
        match_detail=detail,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Experience years scoring
# ─────────────────────────────────────────────────────────────────────────────

_YEARS_REQUIRED_PATTERNS = [
    re.compile(r'(\d+)\+?\s*(?:to\s*\d+)?\s*years?\s+(?:of\s+)?(?:relevant\s+)?(?:work\s+)?experience', re.IGNORECASE),
    re.compile(r'minimum\s+(?:of\s+)?(\d+)\s*\+?\s*years?', re.IGNORECASE),
    re.compile(r'at\s+least\s+(\d+)\s*\+?\s*years?', re.IGNORECASE),
    re.compile(r'(\d+)\s*\+\s*years?', re.IGNORECASE),
]


def extract_years_required(jd_text: str) -> int:
    """Extract minimum required years of experience from JD. Returns 0 if not found."""
    for pattern in _YEARS_REQUIRED_PATTERNS:
        m = pattern.search(jd_text)
        if m:
            return int(m.group(1))
    return 0


def _parse_year(date_str: str) -> Optional[float]:
    """
    Parse a date string to a fractional year.
    Handles: 'Jan 2022', 'January 2022', '2022', 'Present', 'Current'
    """
    import datetime
    if not date_str:
        return None
    s = date_str.strip().lower()
    if s in ('present', 'current', 'now', 'ongoing', 'till date'):
        return datetime.datetime.now().year + datetime.datetime.now().month / 12.0

    # Try 4-digit year
    m = re.search(r'\b(20\d{2}|19\d{2})\b', s)
    if m:
        year = int(m.group(1))
        # Try to extract month
        months = {'jan':1,'feb':2,'mar':3,'apr':4,'may':5,'jun':6,
                  'jul':7,'aug':8,'sep':9,'oct':10,'nov':11,'dec':12}
        for abbr, num in months.items():
            if abbr in s:
                return year + num / 12.0
        return float(year)
    return None


def extract_candidate_years(resume_data: dict) -> float:
    """
    Compute total professional experience in years from the resume's experience list.
    Sums up non-overlapping spans across all jobs.
    """
    total_months = 0.0
    for exp in resume_data.get("experience", []):
        start = _parse_year(exp.get("start_date", ""))
        end   = _parse_year(exp.get("end_date", "") or "Present")
        if start and end and end > start:
            total_months += (end - start) * 12
    return round(total_months / 12.0, 1)


def compute_experience_score(candidate_years: float, required_years: int) -> ExperienceMatchResult:
    """
    Score years-of-experience match.
    Uses a continuous progressive formula to align with real-world human recruiters:
    - Meets/exceeds requirement -> 100%
    - 0 years required -> 75% base (neutral)
    - Under-experience calculated along a progressive curve rather than steep tier drops:
      score = round( (candidate / required) * 100 )
      No matter how low, you get a minimum of 45% if you have some experience.
    """
    if required_years == 0:
        return ExperienceMatchResult(
            score=75,
            candidate_years=candidate_years,
            required_years=0,
            year_score=75,
            detail=f"No explicit year requirement found. Candidate has {candidate_years}y total."
        )

    if candidate_years >= required_years:
        year_score = 100
        verdict = "meets or exceeds"
    else:
        # Continuous linear ratio with a floor of 45% to keep it realistic
        ratio = candidate_years / required_years if required_years > 0 else 1.0
        year_score = max(45, round(ratio * 100))
        verdict = "below"

    detail = (
        f"Candidate: {candidate_years}y, Required: {required_years}y → "
        f"{verdict} requirement ({round((candidate_years / required_years)*100 if required_years > 0 else 100)}%)"
    )
    return ExperienceMatchResult(
        score=year_score,
        candidate_years=candidate_years,
        required_years=required_years,
        year_score=year_score,
        detail=detail,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────────────────

# Import here to avoid circular at module level
from typing import Optional

def compute_ats_score(resume_data: dict, jd_text: str) -> ATSScoreResult:
    """
    Full deterministic ATS scoring pipeline.
    Returns ATSScoreResult with skills_score, experience_score, and supporting data.
    The caller (llm_agent) will add LLM-derived role_fit_score and compute overall.
    """
    # 1. Extract skills from JD
    required_skills, preferred_skills = extract_jd_skills(jd_text)

    # 2. Score skills
    skill_result = compute_skills_score(resume_data, required_skills, preferred_skills)

    # 3. Score experience years
    candidate_years = extract_candidate_years(resume_data)
    required_years  = extract_years_required(jd_text)
    exp_result      = compute_experience_score(candidate_years, required_years)

    # 4. Build matched/missing lists for the frontend (deduplicated, human-readable)
    all_matched  = list(dict.fromkeys(skill_result.matched_required + skill_result.matched_preferred))
    all_missing  = list(dict.fromkeys(skill_result.missing_required))  # only show required misses

    score_breakdown = {
        "skills":     skill_result.match_detail,
        "experience": exp_result.detail,
        "required_skills_found":    ", ".join(skill_result.matched_required) or "none",
        "preferred_skills_found":   ", ".join(skill_result.matched_preferred) or "none",
        "required_skills_missing":  ", ".join(skill_result.missing_required) or "none",
    }

    return ATSScoreResult(
        skills_score=skill_result.score,
        experience_score=exp_result.score,
        matched_skills=all_matched,
        missing_skills=all_missing,
        matched_required_count=len(skill_result.matched_required),
        total_required_count=len(required_skills),
        candidate_years=candidate_years,
        required_years=required_years,
        score_breakdown=score_breakdown,
    )


def compute_overall_score(skills: int, experience: int, role_fit: int) -> int:
    """
    Weighted formula for overall ATS score.
    Weights reflect real recruiter priorities:
      40% skills (most ATS systems are keyword-first)
      35% experience (years + domain proximity)
      25% role fit (semantic match — title, level, industry)
    """
    return round(0.40 * skills + 0.35 * experience + 0.25 * role_fit)
