"""
ats_scorer.py — Production-Grade Deterministic ATS Scoring Engine.

Computes skills_score and experience_score purely from text signals.
Features: 
- Overlap-aware timeline flattening
- Time-decay skill recency weights
- Contextual density tracking (anti-keyword stuffing)
- Strict case/context bounded single-word tokenization
- Advanced degree experience credits
- Seniority title tier matching & tenure volatility scaling
- Hard knockout parameters (Visa / Location)
"""

import re
import datetime
from dataclasses import dataclass, field
from typing import List, Tuple, Dict, Set, Optional

# ─────────────────────────────────────────────────────────────────────────────
# 1. ENHANCED TAXONOMY & GLOBAL LOCALIZATION DICTIONARIES
# ─────────────────────────────────────────────────────────────────────────────
SKILL_ALIASES: Dict[str, List[str]] = {
    "machine learning":    ["machine learning", "ml", "sklearn", "scikit-learn"],
    "deep learning":       ["deep learning", "dl", "neural network", "neural net", "cnn", "rnn"],
    "llm":                 ["llm", "large language model", "gpt", "gemini", "claude", "chatgpt"],
    "nlp":                 ["nlp", "natural language processing", "text mining"],
    "computer vision":     ["computer vision", "image recognition", "object detection"], # "cv" dropped: near-universally means "curriculum vitae" in resume/JD text, not this skill
    "generative ai":       ["generative ai", "gen ai", "genai", "diffusion model"],
    "rag":                 ["rag", "retrieval augmented generation", "retrieval-augmented"],
    "fine-tuning":         ["fine-tuning", "finetuning", "lora", "qlora", "peft"],
    "pytorch":             ["pytorch", "torch"],
    "tensorflow":          ["tensorflow", "tf", "keras"],
    "langchain":           ["langchain", "lang chain"],
    "python":              ["python", "py"],
    "javascript":          ["javascript", "js", "node", "nodejs", "node.js"],
    "typescript":          ["typescript", "ts"],
    "java":                ["java", "jvm"],
    "c++":                 ["c++", "cpp"],
    "go":                  ["go", "golang"], # Handled specially via context boundary to avoid "google/godaddy" false positives
    "rust":                ["rust", "rustlang"],
    "sql":                 ["sql", "mysql", "postgresql", "postgres", "sqlite"],
    "aws":                 ["aws", "amazon web services", "ec2", "s3", "lambda"],
    "gcp":                 ["gcp", "google cloud", "bigquery", "vertex ai"],
    "docker":              ["docker", "containerization"],
    "kubernetes":          ["kubernetes", "k8s", "eks"],
    "terraform":           ["terraform", "iac"],
    "ci/cd":               ["ci/cd", "github actions", "jenkins", "gitlab ci", "cicd"],
    "react":               ["react", "reactjs", "react.js"],
    "fastapi":             ["fastapi"],
    "vector database":     ["vector database", "vector db", "pinecone", "weaviate", "chromadb"],

    # ── Product management ──────────────────────────────────────────────
    "product management":  ["product management", "product manager", "product owner"],
    "roadmapping":          ["roadmapping", "product roadmap", "product strategy"],
    "user research":        ["user research", "usability testing", "customer interviews"],
    "a/b testing":          ["a/b testing", "ab testing", "split testing", "experimentation"],
    "jira":                 ["jira", "confluence"],
    "product analytics":    ["product analytics", "amplitude", "mixpanel", "pendo"],
    "agile":                ["agile", "scrum", "kanban", "sprint planning"],

    # ── Design ───────────────────────────────────────────────────────────
    "ux design":            ["ux design", "user experience design", "ux/ui", "ui/ux"],
    "ui design":            ["ui design", "user interface design", "visual design"],
    "figma":                ["figma"],
    "sketch":               ["sketch"],
    "adobe creative suite": ["adobe creative suite", "photoshop", "illustrator", "indesign", "adobe xd"],
    "wireframing":          ["wireframing", "wireframes", "prototyping", "prototype"],
    "design systems":       ["design system", "design systems", "component library"],

    # ── Marketing ────────────────────────────────────────────────────────
    "seo":                  ["seo", "search engine optimization"],
    "sem":                  ["sem", "search engine marketing", "google ads", "ppc"],
    "content marketing":    ["content marketing", "content strategy", "copywriting"],
    "email marketing":      ["email marketing", "mailchimp", "hubspot", "marketo"],
    "social media marketing": ["social media marketing", "social media management"],
    "marketing analytics":  ["marketing analytics", "google analytics", "ga4"],
    "brand management":     ["brand management", "brand strategy"],
    "growth marketing":     ["growth marketing", "growth hacking", "demand generation"],

    # ── Sales & business development ────────────────────────────────────
    "salesforce":           ["salesforce", "sfdc"],
    "crm":                  ["crm", "customer relationship management"],
    "account management":   ["account management", "account executive", "key account management"],
    "business development": ["business development", "biz dev", "bizdev"],
    "lead generation":      ["lead generation", "lead gen", "prospecting"],
    "negotiation":          ["negotiation", "contract negotiation"],
    "cold outreach":        ["cold outreach", "cold calling", "cold emailing"],

    # ── Finance & accounting ────────────────────────────────────────────
    "financial modeling":   ["financial modeling", "financial modelling", "financial models", "financial analysis"],
    "financial reporting":  ["financial reporting", "gaap", "ifrs"],
    "budgeting":            ["budgeting", "forecasting", "budget management"],
    "excel":                ["microsoft excel", "spreadsheet modeling"], # bare "excel" is guarded via HIGH_RISK_TOKEN_CONTEXT
    "quickbooks":           ["quickbooks", "netsuite"], # bare "sap" is guarded via HIGH_RISK_TOKEN_CONTEXT
    "valuation":            ["valuation", "dcf", "discounted cash flow"],
    "audit":                ["audit", "auditing", "internal controls"],

    # ── HR & people operations ───────────────────────────────────────────
    "recruiting":           ["recruiting", "talent acquisition", "sourcing"],
    "hris":                 ["hris", "workday", "bamboohr", "adp"],
    "onboarding":           ["onboarding", "employee onboarding"],
    "performance management": ["performance management", "performance reviews"],

    # ── Operations & project management ──────────────────────────────────
    "project management":   ["project management", "pmp", "prince2"],
    "supply chain":         ["supply chain", "logistics", "inventory management"],
    "process improvement":  ["process improvement", "six sigma", "kaizen"], # bare "lean" is guarded via HIGH_RISK_TOKEN_CONTEXT
    "vendor management":    ["vendor management", "procurement"],
}

# High-risk single-word collisions that require context protection rules —
# each of these is a common English word/verb (or, for "sap"/"excel", an
# ambiguous acronym-adjacent term) with a much more frequent non-skill meaning
# ("sales pipeline", "excel in your career", "stay lean", "sap morale"). Each
# maps to a regex of nearby words that must also appear for the match to
# count; a bare high-risk token with none of its guard words nearby is
# assumed to be the common-English usage, not the skill.
HIGH_RISK_TOKEN_CONTEXT: Dict[str, re.Pattern] = {
    "go":       re.compile(r'\b(golang|programming|language|developer|engineer|backend|code|writing)\b'),
    "pipeline": re.compile(r'\b(data|etl|elt|ml|ci|cd|build|deploy\w*|orchestrat\w*|airflow|luigi)\b'),
    "airflow":  re.compile(r'\b(apache|dag|workflow|orchestrat\w*|etl|elt|data)\b'),
    "spark":    re.compile(r'\b(apache|hadoop|databricks|pyspark|big\s?data|cluster|rdd|dataframe)\b'),
    "excel":    re.compile(r'\b(microsoft|spreadsheet|pivot\w*|vlookup|macro\w*|workbook|formula\w*|ms)\b'),
    "lean":     re.compile(r'\b(six\s?sigma|manufactur\w*|methodolog\w*|process|kaizen|agile|kanban|waste)\b'),
    "sap":      re.compile(r'\b(erp|netsuite|s4\s?hana|hana|module\w*|fico|abap|successfactors)\b'),
}
HIGH_RISK_TOKENS = set(HIGH_RISK_TOKEN_CONTEXT.keys())

# Cross-language Seniority & Title Classifications map
TITLE_TIERS: Dict[str, List[str]] = {
    "executive": ["director", "vp", "vice president", "cto", "cio", "cpo", "head of", "leiter", "directeur"],
    "lead":      ["principal", "staff", "lead", "architect", "lead engineer", "haupt", "principal engineer"],
    "senior":    ["senior", "sr", "snr", "senior engineer", "senior developer", "senior software engineer", "softwareentwickler senior"],
    "mid":       ["mid", "software engineer", "developer", "engineer", "softwareentwickler", "ingenieur logiciel"],
    "junior":    ["junior", "jr", "associate", "intern", "trainee", "entry level", "softwareentwickler junior"]
}

# ─────────────────────────────────────────────────────────────────────────────
# 3. TEXT SANITIZATION & BOUNDED SCANNING UTILITIES
# ─────────────────────────────────────────────────────────────────────────────
# Defined here (ahead of the compiled pattern tables below, which is normally
# "section 2" territory) because those tables call _clean_text() at module
# load time to normalize aliases the same way scanned text is normalized.
def _normalize_alphanumeric(text: str) -> str:
    """Strips all structural formatting, spaces, and punctuation for safety lookups."""
    if not text: return ""
    return re.sub(r'[^a-z0-9]', '', text.lower())

def _clean_text(text: str) -> str:
    """Standardizes spaces and structural boundary components."""
    if not text: return ""
    text = text.lower()
    text = re.sub(r'[•·▪▸–—\-\_/]', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()

# Global structural reverse lookups
_SKILL_LOOKUP: Dict[str, str] = {alias.lower(): canonical for canonical, aliases in SKILL_ALIASES.items() for alias in aliases}

# Precompiled skill-matching patterns, built once at module load rather than
# re.escape()'d and re-searched fresh on every _extract_taxonomy_skills() call
# — this function runs per job in discovery (up to DISCOVERY_JD_FETCH_CAP
# times) plus per experience entry in compute_skills_score, so avoiding
# redundant pattern construction on a hot path matters.
#
# Patterns are built from the _clean_text()-normalized alias, not the raw
# alias string. _extract_taxonomy_skills always searches _clean_text()'d
# input, which replaces separators (-, _, /, bullets, dashes) with spaces —
# so a raw alias containing one of those characters (e.g. "ci/cd",
# "fine-tuning") could never match, since the separator in the pattern would
# never appear in the text being searched. Normalizing the alias the same way
# keeps the two sides consistent.
_COMPILED_SKILL_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r'\b' + re.escape(_clean_text(alias)) + r'\b'), canonical)
    for alias, canonical in _SKILL_LOOKUP.items()
    if alias not in HIGH_RISK_TOKENS
]
_COMPILED_HIGH_RISK_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r'\b' + re.escape(_clean_text(token)) + r'\b'), token)
    for token in HIGH_RISK_TOKENS
]
# Canonical display name for each high-risk token — these aren't in
# SKILL_ALIASES (they're matched via the guarded path below, not the plain
# alias table), so _SKILL_LOOKUP has no entry for them.
_HIGH_RISK_CANONICAL: Dict[str, str] = {
    "go": "go", "pipeline": "data pipelines", "airflow": "airflow",
    "spark": "apache spark", "excel": "excel", "lean": "process improvement", "sap": "sap",
}

# Precompiled (tier, pattern) pairs for TITLE_TIERS, in _TIER_ORDER priority
# (executive > lead > senior > junior > mid). extract_jd_expectations and
# get_candidate_seniority_tier both break on first match, so a title matching
# keywords from multiple tiers (e.g. "Senior Software Engineer" matches both
# "senior" and "engineer") now resolves to the highest-priority tier. This is
# an intentional fix, not just a perf change: the original per-tier-dict loop
# only `break`'d the inner keyword loop, so the outer loop kept iterating and
# whichever tier's keyword matched LAST in dict insertion order silently won
# (e.g. "Senior Software Engineer" was misclassified as "mid" via "engineer").
_TIER_ORDER = ["executive", "lead", "senior", "junior", "mid"]
_COMPILED_TITLE_TIER_PATTERNS: List[Tuple[str, re.Pattern]] = [
    (tier, re.compile(r'\b' + re.escape(kw) + r'\b'))
    for tier in _TIER_ORDER
    for kw in TITLE_TIERS[tier]
]

# ─────────────────────────────────────────────────────────────────────────────
# 2. DATA CONTAINERS
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class SkillMatchResult:
    score: int
    matched_required: List[str]
    matched_preferred: List[str]
    missing_required: List[str]
    missing_preferred: List[str]
    match_detail: str

@dataclass
class ExperienceMatchResult:
    score: int
    candidate_years: float
    required_years: int
    detail: str

@dataclass
class ATSScoreResult:
    eligible: bool
    knockout_reason: Optional[str]
    skills_score: int
    experience_score: int
    matched_skills: List[str]
    missing_skills: List[str]
    candidate_years: float
    required_years: int
    score_breakdown: Dict[str, str]

def _extract_taxonomy_skills(text: str) -> Set[str]:
    """
    Extracts canonical skills safely using alphanumeric matching and strict
    boundary checks for vulnerable short single words.
    """
    cleaned = _clean_text(text)
    found_skills = set()

    # 1. Evaluate general dictionary items using standard word boundaries
    for pattern, canonical in _COMPILED_SKILL_PATTERNS:
        if pattern.search(cleaned):
            found_skills.add(canonical)

    # 2. Protected validation for high-risk tokens: each requires one of its
    # guard words (HIGH_RISK_TOKEN_CONTEXT) to also appear nearby, or it's
    # treated as ordinary English usage rather than the skill (e.g. "sales
    # pipeline" vs. "data pipeline", "excel in your career" vs. "MS Excel").
    for pattern, token in _COMPILED_HIGH_RISK_PATTERNS:
        if pattern.search(cleaned):
            context_pattern = HIGH_RISK_TOKEN_CONTEXT[token]
            # "golang" is unambiguous on its own — no context word needed.
            if (token == "go" and "golang" in cleaned) or context_pattern.search(cleaned):
                found_skills.add(_HIGH_RISK_CANONICAL[token])

    return found_skills

def extract_jd_skills(jd_text: str) -> Tuple[List[str], List[str]]:
    """
    Splits the Job Description into structural text chunks (Required vs Preferred)
    and extracts cross-referenced canonical skill tokens using the closed taxonomy.
    """
    required_signals = re.compile(
        r'(required|must\s*have|mandatory|essential|minimum qualifications?|basic qualifications?|requirements)', 
        re.IGNORECASE
    )
    preferred_signals = re.compile(
        r'(preferred|nice\s*to\s*have|bonus|plus|desired|ideally|good to have|beneficial)', 
        re.IGNORECASE
    )
    
    lines = jd_text.split('\n')
    req_chunks: List[str] = []
    pref_chunks: List[str] = []
    current_bucket = req_chunks  # Default fallback context is required
    
    for line in lines:
        if preferred_signals.search(line):
            current_bucket = pref_chunks
        elif required_signals.search(line):
            current_bucket = req_chunks
        current_bucket.append(line)
        
    # Extract distinct taxonomy token intersections from each section text block
    req_set = _extract_taxonomy_skills("\n".join(req_chunks))
    pref_set = _extract_taxonomy_skills("\n".join(pref_chunks))
    
    # Enforce clear logical boundaries: clean preferred choices of items already marked required
    pref_set = pref_set - req_set
    
    return sorted(list(req_set)), sorted(list(pref_set))

# ─────────────────────────────────────────────────────────────────────────────
# 4. BINARY HARD-KNOCKOUT LAYER
# ─────────────────────────────────────────────────────────────────────────────
def evaluate_knockouts(resume_data: dict, jd_text: str) -> Tuple[bool, Optional[str]]:
    """Evaluates critical alignment filters (Location restrictions / Visa Sponsorship requirements)."""
    jd_lower = jd_text.lower()
    
    # Extract structural candidate data points
    location_str = _clean_text(resume_data.get("location", ""))
    requires_sponsorship = resume_data.get("requires_sponsorship", False)
    
    # Rule A: Detect explicit geographic on-site requirements
    if "must be based in" in jd_lower or "onsite in" in jd_lower:
        # Simple string-match locator verification
        city_match = re.search(r'(?:based in|onsite in)\s+([a-z\s]{3,20})', jd_lower)
        if city_match:
            target_city = city_match.group(1).strip()
            if target_city not in location_str and len(location_str) > 0:
                return False, f"Geographic mismatch. Target location required: {target_city.title()}."

    # Rule B: Explicit Visa sponsorship disqualification
    if "no visa sponsorship" in jd_lower or "must have right to work" in jd_lower:
        if requires_sponsorship:
            return False, "Candidate requires visa sponsorship which is unavailable for this role."
            
    return True, None

# ─────────────────────────────────────────────────────────────────────────────
# 5. ADVANCED CHRONOLOGICAL TIMELINE ENGINE (OVERLAPS & RECENCY)
# ─────────────────────────────────────────────────────────────────────────────
def _parse_date_to_ordinal(date_str: str) -> Optional[int]:
    if not date_str: return None
    s = date_str.strip().lower()
    now = datetime.datetime.now()
    if s in ('present', 'current', 'now', 'ongoing', 'till date') or 'present' in s:
        return now.toordinal()
    year_match = re.search(r'\b(19\d{2}|20\d{2})\b', s)
    if not year_match: return None
    year = int(year_match.group(1))
    months = {'jan':1,'feb':2,'mar':3,'apr':4,'may':5,'jun':6,'jul':7,'aug':8,'sep':9,'oct':10,'nov':11,'dec':12}
    month = 1
    for abbr, num in months.items():
        if abbr in s:
            month = num
            break
    return datetime.date(year, month, 1).toordinal()

def calculate_flattened_experience(resume_data: dict) -> Tuple[float, float, List[Tuple[int, int, float]]]:
    """
    Merges overlapping professional experience, tracking total years,
    average structural tenure parameters, and recency coefficients.
    """
    intervals = []
    job_durations = []

    for exp in resume_data.get("experience", []):
        if not isinstance(exp, dict):
            continue
        start = _parse_date_to_ordinal(exp.get("start_date", ""))
        end = _parse_date_to_ordinal(exp.get("end_date", "") or "Present")
        if start and end and end > start:
            intervals.append((start, end))
            job_durations.append((end - start) / 365.25)
            
    if not intervals:
        return 0.0, 0.0, []
        
    intervals.sort(key=lambda x: x[0])
    merged: List[Tuple[int, int]] = []
    for current in intervals:
        if not merged:
            merged.append(current)
        else:
            prev_start, prev_end = merged[-1]
            if current[0] <= prev_end:
                merged[-1] = (prev_start, max(prev_end, current[1]))
            else:
                merged.append(current)
                
    total_days = sum((end - start) for start, end in merged)
    calendar_years = round(total_days / 365.25, 1)
    avg_tenure = sum(job_durations) / len(job_durations) if job_durations else 0.0
    
    now_ordinal = datetime.datetime.now().toordinal()
    weighted_segments = []
    for start, end in merged:
        years_ago = (now_ordinal - end) / 365.25
        # Recency Multiplier: 100% value for recent work; decays to a 40% floor over 5 years
        weight = 1.0 if years_ago <= 1.0 else max(0.4, 1.0 - ((years_ago - 1.0) / 4.0) * 0.6)
        weighted_segments.append((start, end, weight))
        
    return calendar_years, avg_tenure, weighted_segments

# ─────────────────────────────────────────────────────────────────────────────
# 6. EDUCATION CREDITS, SENIORITY TIERS & TENURE VOLATILITY ADJUSTERS
# ─────────────────────────────────────────────────────────────────────────────
def get_highest_education_tier(resume_data: dict) -> str:
    edu_list = resume_data.get("education", [])
    edu_text = ""
    for edu in edu_list:
        if isinstance(edu, dict):
            edu_text += " " + edu.get("degree", "").lower()
    if "phd" in edu_text or "ph.d" in edu_text or "doctorate" in edu_text: return "phd"
    if "master" in edu_text or "ms" in edu_text or "msc" in edu_text or "mba" in edu_text: return "masters"
    return "bachelors"

def extract_jd_expectations(jd_text: str) -> Tuple[int, str, str]:
    """Parses JD text for explicit years, required degrees, and targeted seniority tiers."""
    cleaned = _clean_text(jd_text)
    
    # 1. Parse required experience years
    years_required = 0
    p_years = re.search(r'(\d+)\+?\s*(?:to\s*\d+)?\s*years?\s+(?:of\s+)?(?:relevant|work)?\s*experience', cleaned)
    if p_years: years_required = int(p_years.group(1))
    
    # 2. Parse education tier request
    edu_tier = "bachelors"
    if "phd" in cleaned or "ph.d" in cleaned: edu_tier = "phd"
    elif "master" in cleaned: edu_tier = "masters"
    
    # 3. Parse required seniority tier
    role_tier = "mid"
    for tier, pattern in _COMPILED_TITLE_TIER_PATTERNS:
        if pattern.search(cleaned):
            role_tier = tier
            break

    return years_required, edu_tier, role_tier

def get_candidate_seniority_tier(resume_data: dict) -> str:
    """Classifies the candidate's professional tier using their most recent job titles."""
    exp = resume_data.get("experience", [])
    if not exp: return "junior"

    recent_roles = ""
    for i in range(min(len(exp), 2)):
        exp_item = exp[i]
        if isinstance(exp_item, dict):
            recent_roles += " " + exp_item.get("role", "").lower()

    for tier, pattern in _COMPILED_TITLE_TIER_PATTERNS:
        if pattern.search(recent_roles):
            return tier
    return "mid"

# ─────────────────────────────────────────────────────────────────────────────
# 7. CONTEXTUAL DENSITY SKILLS EVALUATOR
# ─────────────────────────────────────────────────────────────────────────────
def compute_skills_score(
    resume_data: dict, required_skills: List[str], preferred_skills: List[str],
    weighted_segments: List[Tuple[int, int, float]]
) -> SkillMatchResult:
    """Evaluates keyword matches using location weighting and a stuffing-prevention cap."""
    if not required_skills:
        # No taxonomy skills were extractable from the JD text at all (common
        # for JDs in non-tech-heavy industries whose tools aren't in
        # SKILL_ALIASES, e.g. legal/finance-specific software). This is NOT
        # the same as "candidate matches every requirement" — returning 100
        # here previously produced a false-perfect skills_score with 0/0
        # matched skills, inflating overall_score. Use a neutral score
        # instead so an unscoreable JD doesn't look like a perfect match.
        return SkillMatchResult(60, [], [], [], [], "No mandatory technical keywords recognized in this JD — skills score is a neutral default, not a real match assessment.")

    skills_sec_canon = _extract_taxonomy_skills(" ".join(resume_data.get("skills", [])))

    job_profiles: List[Tuple[Set[str], float]] = []
    for exp in resume_data.get("experience", []):
        if not isinstance(exp, dict):
            continue
        start = _parse_date_to_ordinal(exp.get("start_date", ""))
        end = _parse_date_to_ordinal(exp.get("end_date", "") or "Present")
        weight = 0.5
        if start and end:
            for s_ord, e_ord, w_val in weighted_segments:
                if start >= s_ord and end <= e_ord:
                    weight = w_val
                    break
        job_text = _clean_text(exp.get("role", "") + " " + " ".join(exp.get("description", [])))
        job_profiles.append((_extract_taxonomy_skills(job_text), weight))

    def evaluate_skill_strength(skill: str) -> float:
        strength = 0.5 if skill in skills_sec_canon else 0.0
        for j_skills, weight in job_profiles:
            if skill in j_skills:
                strength += (1.0 * weight)
        return min(1.0, strength) # Hard anti-keyword stuffing cap limit

    matched_req, missing_req, total_req_strength = [], [], 0.0
    for s in required_skills:
        str_val = evaluate_skill_strength(s)
        if str_val >= 0.35:
            matched_req.append(s)
            total_req_strength += str_val
        else:
            missing_req.append(s)

    matched_pref, total_pref_strength = [], 0.0
    for s in preferred_skills:
        str_val = evaluate_skill_strength(s)
        if str_val >= 0.35:
            matched_pref.append(s)
            total_pref_strength += str_val

    req_score = (total_req_strength / len(required_skills)) * 85
    pref_score = (total_pref_strength / len(preferred_skills)) * 15 if preferred_skills else 15
    final_skills_score = min(100, max(0, round(req_score + pref_score)))
    
    detail = f"Required Match Strength: {len(matched_req)}/{len(required_skills)}. Section weights: Mandatory: {round(req_score)}/85"
    if preferred_skills: detail += f" + Preferred: {round(pref_score)}/15."

    return SkillMatchResult(final_skills_score, matched_req, matched_pref, missing_req, [], detail)

# ─────────────────────────────────────────────────────────────────────────────
# 8. MAIN ENTRY PIPELINE
# ─────────────────────────────────────────────────────────────────────────────
def compute_ats_score(resume_data: dict, jd_text: str) -> ATSScoreResult:
    """Executes the optimized multi-stage deterministic ATS ingestion pipeline."""
    # Stage 1: Screen binary knockouts
    eligible, reason = evaluate_knockouts(resume_data, jd_text)
    if not eligible:
        return ATSScoreResult(False, reason, 0, 0, [], [], 0.0, 0, {"status": f"Rejected by Knockout Filter Layer: {reason}"})
        
    # Stage 2: Extract requirements and map out timelines
    required_years, required_edu, required_tier = extract_jd_expectations(jd_text)
    calendar_years, avg_tenure, weighted_segments = calculate_flattened_experience(resume_data)
    required_skills, preferred_skills = extract_jd_skills(jd_text)
    
    # Stage 3: Inject Advanced Degree Virtual Credits
    candidate_edu = get_highest_education_tier(resume_data)
    adjusted_years = calendar_years
    education_credit_applied = 0.0
    if candidate_edu == "phd" and required_edu != "phd":
        education_credit_applied = 3.0
    elif candidate_edu == "masters" and required_edu == "bachelors":
        education_credit_applied = 1.5
    adjusted_years += education_credit_applied

    # Stage 4: Experience & Tier matching evaluations
    if required_years == 0:
        base_exp_score = 80
    else:
        ratio = adjusted_years / required_years
        base_exp_score = min(100, 90 + round((adjusted_years - required_years) * 2)) if ratio >= 1.0 else max(35, round(ratio * 90))

    # Stage 5: Apply Seniority Title-Tier Adjustments
    candidate_tier = get_candidate_seniority_tier(resume_data)
    tier_hierarchy = {"junior": 1, "mid": 2, "senior": 3, "lead": 4, "executive": 5}
    req_tier_idx = tier_hierarchy.get(required_tier, 2)
    cand_tier_idx = tier_hierarchy.get(candidate_tier, 2)
    
    tier_modifier = 1.0
    if cand_tier_idx < req_tier_idx:
        # Penalize undersized seniority context (e.g., Senior role target vs Junior candidate title history)
        tier_modifier -= 0.15 * (req_tier_idx - cand_tier_idx)

    # Stage 6: Apply Volatility Metrics (Tenure stability scaling factor)
    tenure_modifier = 1.0
    if avg_tenure > 0.0 and avg_tenure < 0.75:  # Avg tenure lower than 9 months
        tenure_modifier = 0.88  # Apply operational stability scaling penalty
        
    final_experience_score = min(100, max(0, round(base_exp_score * tier_modifier * tenure_modifier)))

    # Stage 7: Evaluate Contextual Taxonomy Matrix
    skill_res = compute_skills_score(resume_data, required_skills, preferred_skills, weighted_segments)
    
    all_matched = sorted(list(set(skill_res.matched_required + skill_res.matched_preferred)))
    score_breakdown = {
        "skills_breakdown": skill_res.match_detail,
        "experience_breakdown": (
            f"Chronological Timeline base: {calendar_years}y (Adjusted with Education Credit: +{education_credit_applied}y). "
            f"Seniority Target: {required_tier.title()} vs Candidate Profile: {candidate_tier.title()}. "
            f"Average Job Tenure: {round(avg_tenure, 1)}y. Final Dimension Score: {final_experience_score}/100."
        ),
        "required_skills_found": ", ".join(skill_res.matched_required) or "None",
        "missing_critical_skills": ", ".join(skill_res.missing_required) or "None"
    }

    return ATSScoreResult(
        eligible=True,
        knockout_reason=None,
        skills_score=skill_res.score,
        experience_score=final_experience_score,
        matched_skills=all_matched,
        missing_skills=skill_res.missing_required,
        candidate_years=calendar_years,
        required_years=required_years,
        score_breakdown=score_breakdown
    )

def compute_overall_score(skills: int, experience: int, role_fit: int) -> int:
    """Calculates final combined ATS score matching recruiter weights."""
    return round(0.40 * skills + 0.35 * experience + 0.25 * role_fit)


def estimate_role_fit_score(resume_data: dict, jd_text: str) -> int:
    """
    Deterministic stand-in for the LLM-based role_fit_score used in analyze_job_fit.

    Used at job-discovery time to score many jobs cheaply without an LLM call per
    job. Combines seniority-tier alignment (same logic as compute_ats_score's
    tier_modifier) with a domain-overlap ratio (JD taxonomy skills vs. candidate's
    strongest skill section), so discovery's overall_score is computed with the
    same weighting formula and comparable magnitude to the real ATS score,
    without requiring a live JD fetch + LLM round-trip for every listing.
    """
    _, _, required_tier = extract_jd_expectations(jd_text)
    candidate_tier = get_candidate_seniority_tier(resume_data)
    tier_hierarchy = {"junior": 1, "mid": 2, "senior": 3, "lead": 4, "executive": 5}
    req_idx = tier_hierarchy.get(required_tier, 2)
    cand_idx = tier_hierarchy.get(candidate_tier, 2)
    tier_gap = abs(cand_idx - req_idx)

    required_skills, preferred_skills = extract_jd_skills(jd_text)
    jd_skills = set(required_skills) | set(preferred_skills)
    resume_skills = _extract_taxonomy_skills(" ".join(resume_data.get("skills", [])))
    overlap_ratio = (len(jd_skills & resume_skills) / len(jd_skills)) if jd_skills else 0.5

    base = 90 - (tier_gap * 15)
    domain_adjustment = round((overlap_ratio - 0.5) * 30)
    return max(0, min(100, base + domain_adjustment))