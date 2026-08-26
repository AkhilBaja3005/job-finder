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
import json
from dataclasses import dataclass, field
from typing import List, Tuple, Dict, Set, Optional, Any

# ─────────────────────────────────────────────────────────────────────────────
# 1. ENHANCED TAXONOMY & GLOBAL LOCALIZATION DICTIONARIES
# ─────────────────────────────────────────────────────────────────────────────
SKILL_ALIASES: Dict[str, List[str]] = {
    "machine learning":    ["machine learning", "ml", "sklearn", "scikit-learn"],
    "deep learning":       ["deep learning", "dl", "neural network", "neural net", "cnn", "rnn"],
    "llm":                 ["llm", "large language model", "gpt", "gemini", "claude", "chatgpt"],
    "nlp":                 ["nlp", "natural language processing", "text mining"],
    "computer vision":     ["computer vision", "image recognition", "object detection"],
    "generative ai":       ["generative ai", "gen ai", "genai", "diffusion model"],
    "rag":                 ["rag", "retrieval augmented generation", "retrieval-augmented"],
    "agentic ai":          ["agentic ai", "ai agents", "agentic workflows", "multi-agent"],
    "vector databases":    ["vector database", "vector databases", "vector db", "pinecone", "weaviate", "qdrant", "chromadb", "faiss", "milvus"],
    "semantic search":     ["semantic search", "embedding", "embeddings", "vector search"],
    "openai":              ["openai", "chatgpt", "gpt-4", "gpt-4o", "gpt-3.5"],
    "claude":              ["claude", "anthropic"],
    "fine-tuning":         ["fine-tuning", "finetuning", "lora", "qlora", "peft"],
    "pytorch":             ["pytorch", "torch"],
    "tensorflow":          ["tensorflow", "tf", "keras"],
    "langchain":           ["langchain", "lang chain"],
    "prompt engineering": ["prompt engineering", "prompt design"],
    "huggingface":          ["hugging face", "huggingface", "transformers library", "transformers"],
    "mlops":               ["mlops", "mlflow", "kubeflow", "sagemaker"],
    "python":              ["python", "py"],
    "javascript":          ["javascript", "js", "node", "nodejs", "node.js"],
    "typescript":          ["typescript", "ts"],
    "java":                ["java", "jvm"],
    "c++":                 ["c++", "cpp"],
    "csharp":              ["c#", "csharp", ".net", "dotnet", "asp.net"],
    "go":                  ["go", "golang"],
    "rust":                ["rust", "rustlang"],
    "php":                 ["php"],
    "ruby":                ["ruby", "rails", "ruby on rails"],
    "swift":               ["swift", "swiftui"],
    "kotlin":              ["kotlin"],
    "sql":                 ["sql", "mysql", "postgresql", "postgres", "sqlite"],
    "redis":               ["redis"],
    "kafka":               ["kafka", "apache kafka"],
    "databricks":          ["databricks"],
    "snowflake":           ["snowflake"],
    "elasticsearch":       ["elasticsearch", "opensearch"],
    "aws":                 ["aws", "amazon web services", "ec2", "s3", "lambda"],
    "gcp":                 ["gcp", "google cloud", "bigquery", "vertex ai"],
    "azure":               ["azure", "microsoft azure", "azure devops", "aks"],
    "docker":              ["docker", "containerization"],
    "kubernetes":          ["kubernetes", "k8s", "eks"],
    "terraform":           ["terraform", "iac"],
    "ansible":             ["ansible"],
    "helm":                ["helm"],
    "ci/cd":               ["ci/cd", "github actions", "jenkins", "gitlab ci", "cicd"],
    "observability":       ["grafana", "prometheus", "datadog"],
    "react":               ["react", "reactjs", "react.js"],
    "nextjs":              ["next.js", "nextjs"],
    "vue":                 ["vue", "vuejs", "vue.js"],
    "angular":             ["angular", "angularjs"],
    "django":              ["django"],
    "flask":               ["flask"],
    "fastapi":             ["fastapi"],
    "spring":              ["spring boot", "springboot", "spring framework"],
    "graphql":             ["graphql"],
    "mobile":              ["react native", "flutter", "ios", "android"],
    "cybersecurity":       ["cybersecurity", "penetration testing", "soc2", "iso 27001", "iam", "oauth"],
    "vector database":     ["vector database", "vector db", "pinecone", "weaviate", "chromadb", "qdrant", "milvus"],

    # ── Product management ──────────────────────────────────────────────
    "product management":  ["product management", "product manager", "product owner"],
    "roadmapping":          ["roadmapping", "product roadmap", "product strategy"],
    "user research":        ["user research", "usability testing", "customer interviews"],
    "rapid prototyping":    ["rapid prototyping", "prototyping", "prototype", "prototypes", "proof of concept", "poc development", "prototype development"],
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
    "wireframing":          ["wireframing", "wireframes", "wireframe"],
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
    # Preserve # (for C#) and dots in .net/framework names
    text = re.sub(r'[•·▪▸–—\-\_/]', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()

# Global structural reverse lookups
_SKILL_LOOKUP: Dict[str, str] = {alias.lower(): canonical for canonical, aliases in SKILL_ALIASES.items() for alias in aliases}

def _build_skill_pattern(alias: str) -> re.Pattern:
    cleaned_alias = _clean_text(alias)
    # If alias ends with non-word character like '#', use word boundary before and non-word or space after
    if cleaned_alias.endswith('#'):
        return re.compile(r'\b' + re.escape(cleaned_alias) + r'(?:\b|\s|[.,;!?]|$)')
    elif cleaned_alias.startswith('.'):
        return re.compile(r'(?:^|\s)' + re.escape(cleaned_alias) + r'\b')
    return re.compile(r'\b' + re.escape(cleaned_alias) + r'\b')

_COMPILED_SKILL_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (_build_skill_pattern(alias), canonical)
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

# Precompiled alias patterns per canonical skill (using _clean_text(alias)) for fast importance weighting
_COMPILED_SKILL_ALIAS_PATTERNS: Dict[str, List[re.Pattern]] = {
    canonical: [re.compile(r'\b' + re.escape(_clean_text(alias)) + r'\b', re.IGNORECASE) for alias in aliases]
    for canonical, aliases in SKILL_ALIASES.items()
}

@dataclass
class ScoringConfig:
    """Configurable scoring weights, thresholds, and penalty scaling factors."""
    skill_mandatory_weight: float = 85.0    # Portion of skills_score from required skills
    skill_preferred_weight: float = 15.0    # Portion of skills_score from preferred skills
    overall_skills_weight: float = 0.40     # Overall score weight for skills
    overall_exp_weight: float = 0.35        # Overall score weight for experience
    overall_fit_weight: float = 0.25        # Overall score weight for role fit
    tier_penalty_per_level: float = 0.15    # Penalty per missing seniority tier level
    tenure_volatility_modifier: float = 0.88# Default tenure modifier for avg tenure < 9 months
    tenure_volatility_modifier_range: float = 0.12 # Max scaling penalty range for severe job hopping (< 0.75 yrs avg)
    master_ats_floor: int = 55              # Standalone master resume score min floor
    master_ats_cap: int = 95                # Standalone master resume score max cap
    display_match_threshold: float = 0.15   # Display threshold for matched vs missing skills list

DEFAULT_SCORING_CONFIG = ScoringConfig()

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
    score_breakdown: Dict[str, Any]

def _flatten_resume_skills(raw_skills: Any) -> str:
    """Safely flattens dictionary or list skills into a single string for taxonomy extraction."""
    if isinstance(raw_skills, dict):
        all_skills = []
        for v in raw_skills.values():
            if isinstance(v, list):
                all_skills.extend([str(item) for item in v])
            elif isinstance(v, str):
                all_skills.append(v)
        return " ".join(all_skills)
    elif isinstance(raw_skills, list):
        return " ".join([str(s) for s in raw_skills])
    return str(raw_skills or "")

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
            # "golang" in text directly grants "go" token match without requiring context guard words
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
VISA_BLOCK_PHRASES = [
    "no visa sponsorship", "must have right to work", "not able to sponsor",
    "without sponsorship", "us citizens only", "must be authorized to work",
    "no sponsorship available"
]
LOCATION_TRIGGER_PHRASES = [
    "must be based in", "onsite in", "must reside in",
    "candidates must be located in"
]

def evaluate_knockouts(resume_data: dict, jd_text: str) -> Tuple[bool, Optional[str]]:
    """Evaluates critical alignment filters (Location restrictions / Visa Sponsorship requirements)."""
    jd_lower = jd_text.lower()
    
    # Extract structural candidate data points
    location_str = _clean_text(resume_data.get("location", ""))
    requires_sponsorship = resume_data.get("requires_sponsorship", False)
    
    # Rule A: Detect explicit geographic on-site requirements
    if any(p in jd_lower for p in LOCATION_TRIGGER_PHRASES):
        # Simple string-match locator verification
        city_match = re.search(r'(?:based in|onsite in|located in|reside in)\s+([a-z\s]{3,20})', jd_lower)
        if city_match:
            target_city = city_match.group(1).strip()
            if target_city not in location_str and len(location_str) > 0:
                return False, f"Geographic mismatch. Target location required: {target_city.title()}."

    # Rule B: Explicit Visa sponsorship disqualification
    if any(p in jd_lower for p in VISA_BLOCK_PHRASES):
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
    
    # 1. Fallback: Numeric MM/YYYY or M/YYYY (e.g. "01/2023", "5/2021")
    m_slash = re.search(r'\b(0?[1-9]|1[0-2])/(19\d{2}|20\d{2})\b', s)
    if m_slash:
        return datetime.date(int(m_slash.group(2)), int(m_slash.group(1)), 1).toordinal()

    # 2. Fallback: Numeric YYYY-MM (e.g. "2023-01")
    m_dash = re.search(r'\b(19\d{2}|20\d{2})-(0?[1-9]|1[0-2])\b', s)
    if m_dash:
        return datetime.date(int(m_dash.group(1)), int(m_dash.group(2)), 1).toordinal()

    # 3. Fallback: Quarter YYYY-Qn or Qn YYYY (e.g. "Q1 2023", "2023-Q3")
    m_q1 = re.search(r'\bq([1-4])\s*(19\d{2}|20\d{2})\b', s)
    if m_q1:
        q_month = (int(m_q1.group(1)) - 1) * 3 + 1
        return datetime.date(int(m_q1.group(2)), q_month, 1).toordinal()
    m_q2 = re.search(r'\b(19\d{2}|20\d{2})\s*[-/]?\s*q([1-4])\b', s)
    if m_q2:
        q_month = (int(m_q2.group(2)) - 1) * 3 + 1
        return datetime.date(int(m_q2.group(1)), q_month, 1).toordinal()

    # 4. Standard "Mon YYYY" or bare year
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

def calculate_flattened_experience(resume_data: dict) -> Tuple[float, float, List[Tuple[int, int, float]], List[str]]:
    """
    Merges overlapping professional experience, tracking total years,
    average structural tenure parameters, recency coefficients, and date parsing failures.
    """
    intervals = []
    job_durations = []
    parse_failures = []

    for idx, exp in enumerate(resume_data.get("experience", [])):
        if not isinstance(exp, dict):
            continue
        role_label = exp.get("role") or f"Position #{idx+1}"
        company_label = exp.get("company") or "Unknown Company"
        job_context = f"'{role_label} at {company_label}'"

        start_str = exp.get("start_date", "")
        end_str = exp.get("end_date", "")
        if not end_str:
            end_str = "Present"

        start = _parse_date_to_ordinal(start_str)
        if not start_str:
            parse_failures.append(f"Missing start_date for job {job_context} (timeline range omitted from calculation)")
        elif start is None:
            parse_failures.append(f"Could not parse start_date: '{start_str}' in job {job_context}")

        end = _parse_date_to_ordinal(end_str)
        if end_str and end is None:
            parse_failures.append(f"Could not parse end_date: '{end_str}' in job {job_context}")

        if start and end and end >= start:
            if start == end:
                end = start + 365
            intervals.append((start, end))
            job_durations.append((end - start) / 365.25)
            
    if not intervals:
        return 0.0, 0.0, [], parse_failures
        
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
        weight = 1.0 if years_ago <= 1.0 else max(0.4, 1.0 - ((years_ago - 1.0) / 4.0) * 0.6)
        weighted_segments.append((start, end, weight))
        
    return calendar_years, avg_tenure, weighted_segments, parse_failures

# ─────────────────────────────────────────────────────────────────────────────
# 6. EDUCATION CREDITS, SENIORITY TIERS & TENURE VOLATILITY ADJUSTERS
# ─────────────────────────────────────────────────────────────────────────────
def get_highest_education_tier(resume_data: dict, only_completed: bool = True) -> str:
    """
    Returns the candidate's highest degree tier. By default, only counts
    degrees whose end_date has already passed — an in-progress degree with
    a future end_date shouldn't grant the same virtual experience-years
    credit as a completed one.
    """
    edu_list = resume_data.get("education", [])
    now_ordinal = datetime.datetime.now().toordinal()
    tier_rank = {"bachelors": 0, "masters": 1, "phd": 2}
    tier = "bachelors"

    for edu in edu_list:
        if not isinstance(edu, dict):
            continue
        degree_text = edu.get("degree", "").lower()
        end_date_str = edu.get("end_date") or edu.get("graduation_date", "")
        end_ordinal = _parse_date_to_ordinal(end_date_str)

        if only_completed and end_ordinal is not None and end_ordinal > now_ordinal:
            continue  # ongoing/future degree — skip for completed credit

        candidate_tier = "bachelors"
        if "phd" in degree_text or "ph.d" in degree_text or "doctorate" in degree_text:
            candidate_tier = "phd"
        elif "master" in degree_text or "msc" in degree_text or "mba" in degree_text:
            candidate_tier = "masters"

        if tier_rank[candidate_tier] > tier_rank[tier]:
            tier = candidate_tier

    return tier

def extract_jd_expectations(jd_text: str) -> Tuple[int, str, str]:
    """Parses JD text for explicit years, required degrees, and targeted seniority tiers."""
    cleaned = _clean_text(jd_text)
    
    # 1. Parse required experience years (tolerant of apostrophes, adjectives, and range lower bounds like 3-5)
    years_required = 0
    p_years = re.search(r"(\d+)(?:\s*[-–—\s]\s*(\d+))?\+?\s*(?:to\s*\d+)?\s*years?\s*'?\s*(?:of\s+)?(?:[a-z]+\s+){0,2}experience", cleaned)
    if p_years:
        years_required = int(p_years.group(1))
    else:
        # Fallback for bare "N+ years in..." or "N+ years"
        p_bare = re.search(r"(\d+)\+\s*years?\b", cleaned)
        if p_bare:
            years_required = int(p_bare.group(1))
    
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

def _compute_skill_importance_weights(jd_text: str, skills: List[str]) -> Dict[str, float]:
    """
    Computes normalized importance weights (summing to 1.0) for a list of skills
    based on JD mention frequency and placement in the intro/title lines.
    Guarded for high-risk tokens to prevent non-technical word collisions.
    """
    if not skills:
        return {}
    
    cleaned_jd = _clean_text(jd_text)
    lines = [line.strip() for line in jd_text.split('\n') if line.strip()]
    header_text = _clean_text(" ".join(lines[:2])) if lines else ""

    raw_scores: Dict[str, float] = {}
    for skill in skills:
        patterns = []
        if skill in HIGH_RISK_TOKENS or skill in _HIGH_RISK_CANONICAL.values():
            # Find the matching token key
            matching_token = None
            for tok, canon in _HIGH_RISK_CANONICAL.items():
                if canon == skill or tok == skill:
                    matching_token = tok
                    break
            if matching_token:
                # Use context pattern for guarded high-risk token
                ctx_pat = HIGH_RISK_TOKEN_CONTEXT.get(matching_token)
                base_pat = re.compile(r'\b' + re.escape(_clean_text(matching_token)) + r'\b', re.IGNORECASE)
                patterns = [(base_pat, ctx_pat)]
        
        if not patterns:
            pattern_list = _COMPILED_SKILL_ALIAS_PATTERNS.get(skill)
            if not pattern_list:
                aliases = SKILL_ALIASES.get(skill, [skill])
                pattern_list = [_build_skill_pattern(alias) for alias in aliases]
            patterns = [(p, None) for p in pattern_list]

        count = 0
        header_bonus = 0
        for pat, ctx_pat in patterns:
            if ctx_pat:
                if ctx_pat.search(cleaned_jd):
                    count += len(pat.findall(cleaned_jd))
                    if ctx_pat.search(header_text) and pat.search(header_text):
                        header_bonus = 1
            else:
                count += len(pat.findall(cleaned_jd))
                if pat.search(header_text):
                    header_bonus = 1

        raw_scores[skill] = max(1.0, float(count)) + header_bonus

    total_raw = sum(raw_scores.values())
    if total_raw == 0:
        return {s: 1.0 / len(skills) for s in skills}
    
    return {s: raw_scores[s] / total_raw for s in skills}

# ─────────────────────────────────────────────────────────────────────────────
# 7. CONTEXTUAL DENSITY SKILLS EVALUATOR
# ─────────────────────────────────────────────────────────────────────────────
def compute_skills_score(
    resume_data: dict, required_skills: List[str], preferred_skills: List[str],
    weighted_segments: List[Tuple[int, int, float]],
    jd_text: str = "",
    config: ScoringConfig = DEFAULT_SCORING_CONFIG
) -> SkillMatchResult:
    """Evaluates keyword matches using location weighting and a stuffing-prevention cap."""
    skills_sec_canon = _extract_taxonomy_skills(_flatten_resume_skills(resume_data.get("skills", [])))

    job_profiles: List[Tuple[Set[str], float]] = []
    for exp in resume_data.get("experience", []):
        if not isinstance(exp, dict):
            continue
        start = _parse_date_to_ordinal(exp.get("start_date", ""))
        end_str = exp.get("end_date", "") or "Present"
        end = _parse_date_to_ordinal(end_str)
        
        weight = 0.5
        if start and end:
            for s_ord, e_ord, w_val in weighted_segments:
                if max(start, s_ord) < min(end, e_ord):
                    weight = w_val
                    break
        
        job_text = _clean_text(exp.get("role", "") + " " + " ".join(exp.get("description", [])))
        job_profiles.append((_extract_taxonomy_skills(job_text), weight))

    def evaluate_skill_strength(skill: str) -> float:
        strength = 0.5 if skill in skills_sec_canon else 0.0
        for j_skills, weight in job_profiles:
            if skill in j_skills:
                strength += (0.5 * weight)
        return min(1.0, strength)

    DISPLAY_MATCH_THRESHOLD = config.display_match_threshold

    if not required_skills:
        if preferred_skills:
            matched_pref, missing_pref, total_pref_strength = [], [], 0.0
            for s in preferred_skills:
                str_val = evaluate_skill_strength(s)
                total_pref_strength += str_val
                if str_val >= DISPLAY_MATCH_THRESHOLD:
                    matched_pref.append(s)
                else:
                    missing_pref.append(s)
            match_ratio = total_pref_strength / len(preferred_skills)
            dynamic_score = min(85, max(50, round(50 + (match_ratio * 35))))
            return SkillMatchResult(dynamic_score, [], matched_pref, [], missing_pref, f"No mandatory requirements extracted; score computed dynamically from preferred skill matches ({len(matched_pref)}/{len(preferred_skills)}).")
        return SkillMatchResult(60, [], [], [], [], "No mandatory technical keywords recognized in this JD — skills score is a neutral default, not a real match assessment.")

    # Decoupled Threshold Architecture:
    # 1. Continuous strength (str_val) contributes to total_req_strength/total_pref_strength
    #    for ALL required/preferred skills to eliminate hard-cliff scoring penalties for older experience.
    # 2. A separate display threshold (>= config.display_match_threshold) is used purely to determine
    #    matched_required vs missing_required lists for UI reporting and audit breakdowns.
    DISPLAY_MATCH_THRESHOLD = config.display_match_threshold

    # Compute skill importance weights if jd_text is provided
    importance_weights = _compute_skill_importance_weights(jd_text, required_skills) if jd_text else {s: 1.0 / len(required_skills) for s in required_skills}

    matched_req, missing_req, weighted_req_strength = [], [], 0.0
    for s in required_skills:
        str_val = evaluate_skill_strength(s)
        w = importance_weights.get(s, 1.0 / len(required_skills))
        weighted_req_strength += (str_val * w)
        if str_val >= DISPLAY_MATCH_THRESHOLD:
            matched_req.append(s)
        else:
            missing_req.append(s)

    matched_pref, missing_pref, total_pref_strength = [], [], 0.0
    for s in preferred_skills:
        str_val = evaluate_skill_strength(s)
        total_pref_strength += str_val
        if str_val >= DISPLAY_MATCH_THRESHOLD:
            matched_pref.append(s)
        else:
            missing_pref.append(s)

    req_score = weighted_req_strength * config.skill_mandatory_weight
    pref_score = (total_pref_strength / len(preferred_skills)) * config.skill_preferred_weight if preferred_skills else config.skill_preferred_weight
    final_skills_score = min(100, max(0, round(req_score + pref_score)))
    
    detail = f"Required Match Strength: {len(matched_req)}/{len(required_skills)} (Weighted importance). Section weights: Mandatory: {round(req_score)}/{round(config.skill_mandatory_weight)}"
    if preferred_skills: detail += f" + Preferred: {round(pref_score)}/{round(config.skill_preferred_weight)}."

    return SkillMatchResult(final_skills_score, matched_req, matched_pref, missing_req, missing_pref, detail)

# ─────────────────────────────────────────────────────────────────────────────
# 8. MAIN ENTRY PIPELINE
# ─────────────────────────────────────────────────────────────────────────────
def compute_ats_score(resume_data: dict, jd_text: str, config: ScoringConfig = DEFAULT_SCORING_CONFIG) -> ATSScoreResult:
    """Executes the optimized multi-stage deterministic ATS ingestion pipeline."""
    # Stage 1: Screen binary knockouts
    eligible, reason = evaluate_knockouts(resume_data, jd_text)
    if not eligible:
        return ATSScoreResult(False, reason, 0, 0, [], [], 0.0, 0, {"status": f"Rejected by Knockout Filter Layer: {reason}"})
        
    # Stage 2: Extract requirements and map out timelines
    required_years, required_edu, required_tier = extract_jd_expectations(jd_text)
    calendar_years, avg_tenure, weighted_segments, parse_failures = calculate_flattened_experience(resume_data)
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
        tier_modifier -= config.tier_penalty_per_level * (req_tier_idx - cand_tier_idx)

    # Stage 6: Apply Volatility Metrics (Tenure stability scaling factor)
    tenure_modifier = 1.0
    if 0.0 < avg_tenure < 0.75:  # Avg tenure lower than 9 months
        severity = (0.75 - avg_tenure) / 0.75
        tenure_modifier = 1.0 - (config.tenure_volatility_modifier_range * severity)
        
    final_experience_score = min(100, max(0, round(base_exp_score * tier_modifier * tenure_modifier)))

    # Stage 7: Evaluate Contextual Taxonomy Matrix
    skill_res = compute_skills_score(resume_data, required_skills, preferred_skills, weighted_segments, jd_text=jd_text, config=config)
    importance_weights = _compute_skill_importance_weights(jd_text, required_skills) if jd_text else {}
    
    all_matched = sorted(list(set(skill_res.matched_required + skill_res.matched_preferred)))
    score_breakdown = {
        "skills_breakdown": skill_res.match_detail,
        "experience_breakdown": (
            f"Chronological Timeline base: {calendar_years}y (Adjusted with Education Credit: +{education_credit_applied}y). "
            f"Seniority Target: {required_tier.title()} vs Candidate Profile: {candidate_tier.title()}. "
            f"Average Job Tenure: {round(avg_tenure, 1)}y. Final Dimension Score: {final_experience_score}/100."
        ),
        "required_skills_found": ", ".join(skill_res.matched_required) or "None",
        "missing_critical_skills": ", ".join(skill_res.missing_required) or "None",
        "skill_weights": importance_weights
    }
    if parse_failures:
        score_breakdown["date_parse_warnings"] = " | ".join(parse_failures)
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

def compute_overall_score(skills: int, experience: int, role_fit: int, config: ScoringConfig = DEFAULT_SCORING_CONFIG) -> int:
    """Calculates final combined ATS score matching recruiter weights."""
    return round(config.overall_skills_weight * skills + config.overall_exp_weight * experience + config.overall_fit_weight * role_fit)


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
    resume_skills = _extract_taxonomy_skills(_flatten_resume_skills(resume_data.get("skills", [])))
    overlap_ratio = (len(jd_skills & resume_skills) / len(jd_skills)) if jd_skills else 0.5

    base = 90 - (tier_gap * 15)
    domain_adjustment = round((overlap_ratio - 0.5) * 30)
    return max(0, min(100, base + domain_adjustment))


def evaluate_master_resume(resume_data: dict, config: ScoringConfig = DEFAULT_SCORING_CONFIG) -> dict:
    """
    Evaluates master resume health standalone upon upload before tailoring against a specific job.
    Checks Playbook compliance, quantification density, skill taxonomy coverage, and timeline integrity.
    """
    suggestions = []
    
    # 1. Experience Timeline & Metrics Check
    cand_years, avg_tenure, weighted_segments, _ = calculate_flattened_experience(resume_data)
    
    exp_list = resume_data.get("experience", [])
    total_bullets = 0
    quantified_bullets = 0
    
    for exp in exp_list:
        bullets = exp.get("description", [])
        total_bullets += len(bullets)
        for b in bullets:
            if re.search(r'\b\d+(?:\.\d+)?%|\b\$\d+|\b£\d+|\bINR\s*\d+|\b\d+\+|\b\d+x\b', b, re.IGNORECASE):
                quantified_bullets += 1
                
    quant_ratio = (quantified_bullets / total_bullets) if total_bullets > 0 else 0
    quant_score = min(100, int(quant_ratio * 120))
    
    if quant_ratio < 0.5:
        suggestions.append("📊 Quantify more achievements: Only " + str(round(quant_ratio*100)) + "% of bullet points contain measurable metrics (e.g. %, £/$, latency cut, user count). Aim for 60%+.")
        
    # 2. Skill Taxonomy Audit
    found_skills = _extract_taxonomy_skills(_flatten_resume_skills(resume_data.get("skills", [])))
    
    tech_score = min(100, max(40, len(found_skills) * 8))
    if len(found_skills) < 8:
        suggestions.append("💡 Expand Technical Skills: Found " + str(len(found_skills)) + " core ATS taxonomy keywords. Consider adding specific frameworks (e.g. PySpark, Docker, Azure OpenAI, XGBoost).")

    # 3. Summary & Positioning Check
    summary = resume_data.get("summary", "")
    summary_words = len(summary.split())
    if not summary:
        suggestions.append("📝 Add a Professional Summary: Standout positioning (AI/ML Engineer, 3+ years experience, key differentiators) increases initial recruiter scan conversion.")
    elif summary_words < 15 or summary_words > 70:
        suggestions.append("🎯 Optimize Summary Length: Summary is " + str(summary_words) + " words. Master Playbook recommends 2–3 visual lines (~25–50 words).")

    if re.search(r'strong foundation in|passionate about|seeking an entry', summary, re.IGNORECASE):
        suggestions.append("⚠️ Avoid weak positioning: Replace phrases like 'strong foundation in' with experienced phrasing e.g. 'AI/ML Engineer with 3+ years experience...'.")

    # 4. Overall Baseline ATS Score Calculation
    base_ats_score = round(config.overall_skills_weight * tech_score + config.overall_exp_weight * (90 if cand_years >= 2 else 70) + config.overall_fit_weight * quant_score)
    base_ats_score = max(config.master_ats_floor, min(config.master_ats_cap, base_ats_score))

    # 5. Gemini AI Executive Qualitative Audit (Domain-Agnostic & Adaptive)
    ai_suggestions = []
    try:
        from services.gemini_client import generate_content_with_fallback
        prompt = (
            "You are an Executive Recruiter and ATS Specialist auditing a candidate's master resume profile.\n"
            "Dynamically infer the candidate's target field/domain (e.g., Software/AI, Data Science, Product Management, Finance, Marketing, Engineering, Healthcare, etc.) from their experience and skills.\n\n"
            f"Candidate Master Resume JSON:\n{json.dumps(resume_data, indent=2)}\n\n"
            "Task:\n"
            "Identify 1-2 sharp, highly actionable, role-appropriate suggestions to enhance this profile's ATS strength, domain clarity, or executive impact.\n"
            "Do NOT repeat basic metric checks (e.g. counting % signs). Focus on domain-specific impact wording, key technical/tool specificity, or positioning clarity.\n"
            "Return ONLY a valid JSON array of 1-2 string suggestions."
        )
        res_text = generate_content_with_fallback(
            prompt=prompt,
            system_instruction="You are an expert ATS & Executive Resume Auditor. Output ONLY a valid JSON array of 1-2 string suggestions."
        )
        if res_text:
            cleaned = res_text.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
                cleaned = re.sub(r'\s*```$', '', cleaned)
            parsed = json.loads(cleaned)
            if isinstance(parsed, list):
                ai_suggestions = [x for x in parsed if isinstance(x, str)]
    except Exception as e:
        # Silently degrade qualitative Gemini audit fallback to baseline rules
        pass

    combined_sugs = suggestions + ai_suggestions
    return {
        "ats_score": base_ats_score,
        "skills_count": len(found_skills),
        "total_bullets": total_bullets,
        "quantified_bullets": quantified_bullets,
        "quantified_percentage": round(quant_ratio * 100),
        "candidate_years": round(cand_years, 1),
        "suggestions": combined_sugs[:2]
    }