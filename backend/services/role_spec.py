"""
role_spec.py - turn "what I want to apply for" into search queries + a title relevance filter.

Nothing here is specific to AI. Whatever you type becomes the topic:

    quantum computing internships        -> topic "quantum computing", level intern
    "agentic AI, applied AI" + intern    -> two topics, level intern
    robotics graduate roles              -> topic "robotics", level graduate

Pieces
- parse_request(text)      free text -> (topics, level)
- resolve_spec(...)        CLI flags / free text / profile defaults -> RoleSpec (or None = legacy behaviour)
- RoleSpec.queries         what to type into the job boards
- RoleSpec.matches(job)    does this posting's TITLE fit the topic and the level?

Topic terms are expanded once per topic with an LLM (abbreviations, adjacent role names) and cached in
data/topic_terms.json. If the LLM is unavailable the topic's own words are used, so it still works offline.
"""

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

# ─── levels ───────────────────────────────────────────────────────────────────
LEVELS: Dict[str, Dict[str, List[str]]] = {
    "intern": {
        "queries": ["Intern", "Internship"],
        "terms": ["intern", "interns", "internship", "internships", "placement", "industrial placement",
                  "summer analyst", "co-op", "coop", "working student", "year in industry"],
    },
    "graduate": {
        "queries": ["Graduate"],
        "terms": ["graduate", "graduates", "new grad", "grad scheme", "early careers", "early career",
                  "entry level", "entry-level", "trainee", "junior", "jr"],
    },
    "junior": {
        "queries": ["Junior"],
        "terms": ["junior", "jr", "entry level", "entry-level", "associate", "early career"],
    },
    "senior": {
        "queries": ["Senior"],
        "terms": ["senior", "sr", "staff", "lead", "principal"],
    },
    "any": {"queries": [], "terms": []},
    # "experienced" = neither intern nor graduate (mid, senior, lead ...); "all" = every level, split into three Excels.
    "experienced": {"queries": [], "terms": []},
    "all": {"queries": [], "terms": []},
}
# Words in the user's request that name a level -> canonical level.
_LEVEL_WORDS = {
    "intern": "intern", "interns": "intern", "internship": "intern", "internships": "intern",
    "placement": "intern", "placements": "intern",
    "graduate": "graduate", "graduates": "graduate", "grad": "graduate", "new grad": "graduate",
    "junior": "junior", "entry level": "junior", "entry-level": "junior",
    "senior": "senior", "staff": "senior", "lead": "senior", "principal": "senior",
    "experienced": "experienced", "mid": "experienced", "mid-level": "experienced", "everything": "all",
}
_SENIOR_TITLE = re.compile(r"(?<![a-z0-9])(senior|sr|staff|principal|lead|head of|director|vp|vice president|manager)(?![a-z0-9])", re.I)
_FILLER = {"job", "jobs", "role", "roles", "position", "positions", "opportunity", "opportunities", "vacancy",
           "vacancies", "find", "search", "apply", "for", "me", "to", "in", "a", "an", "the", "some", "any",
           "scan", "look", "looking", "want", "please", "related", "type", "of", "new"}
# Single words too generic to count as "on topic" on their own.
_GENERIC = {"engineer", "engineering", "developer", "software", "research", "researcher", "data", "analyst",
            "scientist", "technology", "tech", "computing", "computer", "science", "manager", "specialist",
            "consultant", "applied", "advanced", "modern", "digital", "systems", "system", "product", "project",
            "and", "or", "the", "of", "for", "in", "with", "a", "an",
            # generic business / admin words that drift into an LLM-built field map and then match every job
            "strategy", "operations", "operation", "control", "controls", "policy", "compliance", "ethics", "fairness", "robustness",
            "planning", "support", "management", "marketing", "sales", "finance", "business", "commercial", "growth", "program",
            "programme", "consulting", "associate", "assistant", "officer", "executive", "administrator", "coordinator", "advisor",
            "adviser", "manager", "director", "lead", "operations associate", "strategy associate", "policy analyst",
            "compliance officer", "regulatory affairs", "game theory", "decision theory", "cognitive science", "bioethics",
            "societal impact", "futures research", "content moderation", "ethics researcher", "human oversight", "agent foundations",
            "dual use", "existential risk", "biorisk", "robotic", "algorithm", "analytics", "evaluation", "assessment", "risk",
            # bare words that match legal / corporate roles ("Privacy Counsel", "Corporate Governance Paralegal")
            "governance", "audit", "trust", "privacy"}
# Professions that are never what a technical search means; skipped when the search itself names them ("legal tech", "privacy law").
_OFF_FIELD = ["lawyer", "lawyers", "counsel", "paralegal", "paralegals", "solicitor", "attorney", "legal", "secretarial",
              "company secretary", "accountant", "accounting", "recruiter", "recruitment", "talent acquisition", "receptionist",
              "bookkeeper", "payroll", "nurse", "teacher"]


def normalize_level(level: Optional[str]) -> Optional[str]:
    """'Internship' -> 'intern'. Raises ValueError for unknown levels. None stays None."""
    if level is None or not str(level).strip():
        return None
    key = str(level).strip().lower()
    if key in LEVELS:
        return key
    if key in _LEVEL_WORDS:
        return _LEVEL_WORDS[key]
    raise ValueError(f"Unknown level '{level}'. Use one of: {', '.join(LEVELS)} (or intern/internship, graduate, junior, senior).")


# ─── free-text parsing ────────────────────────────────────────────────────────
_LEVEL_RE = re.compile(
    r"(?<![A-Za-z0-9])(new grad|entry[- ]level|internships?|interns?|placements?|graduates?|grad|junior|senior|staff|lead|principal)(?![A-Za-z0-9])",
    re.I,
)


def parse_request(text: str) -> Tuple[List[str], Optional[str]]:
    """
    'quantum computing internships' -> (['quantum computing'], 'intern')
    'agentic AI, applied AI and AI engineering interns' -> (['agentic AI', 'applied AI', 'AI engineering'], 'intern')
    """
    text = (text or "").strip()
    if not text:
        return [], None
    m = _LEVEL_RE.search(text)
    level = _LEVEL_WORDS.get(re.sub(r"[- ]+", " ", m.group(1).lower())) if m else None
    rest = _LEVEL_RE.sub(" ", text)
    parts = re.split(r"\s*(?:,|;|\band\b|\bor\b|\+|&)\s*", rest, flags=re.I)
    topics: List[str] = []
    for part in parts:
        words = [w for w in part.split() if w.lower().strip(".:") not in _FILLER]
        phrase = " ".join(words).strip(" .:-")
        if phrase:
            topics.append(phrase)
    return list(dict.fromkeys(topics)), level


# ─── term matching ────────────────────────────────────────────────────────────
# Word families that job titles use interchangeably ("Applied Science Intern" is an "applied scientist" role).
_FAMILIES = {
    **{w: r"scien(?:ce|ces|tist|tists|tific)" for w in ("science", "sciences", "scientist", "scientists", "scientific")},
    **{w: r"research(?:er|ers)?" for w in ("research", "researcher", "researchers")},
    **{w: r"engineer(?:s|ing)?" for w in ("engineer", "engineers", "engineering")},
    **{w: r"develop(?:er|ers|ment|ing)?" for w in ("developer", "developers", "development", "developing")},
    **{w: r"analy(?:st|sts|tics|tic|sis)" for w in ("analyst", "analysts", "analytics", "analytic", "analysis")},
    **{w: r"test(?:ing|er|ers|s)?" for w in ("testing", "tester", "testers", "test")},
    **{w: r"hack(?:ing|er|ers|s)?" for w in ("hacking", "hacker", "hackers")},
    **{w: r"defen[cs]e" for w in ("defense", "defence")},
}


def _word_pattern(word: str) -> str:
    """One word, tolerant of plural/singular and of the usual noun/profession forms (science~scientist, research~researcher)."""
    if word in _FAMILIES:
        return _FAMILIES[word]
    w = re.escape(word)
    if len(word) >= 5 and word.endswith("s") and not word.endswith("ss"):
        return re.escape(word[:-1]) + "s?"
    if len(word) >= 4 and word.endswith(("ic", "er", "or", "ist", "ent")):
        return w + "s?"
    return w


def _compile(terms: Iterable[str]) -> Optional[re.Pattern]:
    terms = sorted({t.strip().lower() for t in terms if t and t.strip()}, key=len, reverse=True)
    if not terms:
        return None
    parts = []
    for t in terms:
        words = re.split(r"[\s\-]+", t)
        parts.append(r"[\s\-]+".join(_word_pattern(w) for w in words if w))
    return re.compile(rf"(?<![a-z0-9])(?:{'|'.join(parts)})(?![a-z0-9])", re.I)


def _distinctive(topic: str) -> List[str]:
    words = [w for w in re.split(r"[^a-z0-9+#.]+", topic.strip().lower()) if w]
    return [w for w in words if w not in _GENERIC and len(w) >= 2]


def _own_terms(topic: str) -> List[str]:
    """
    Terms that identify `topic` by itself: the phrase, its joined spelling ('cyber security' -> 'cybersecurity'),
    and - only when exactly one word carries the meaning ('quantum computing' -> 'quantum') - that word.
    Topics with several meaningful words ('AI cyber security') are NOT split into separate alternatives, which
    would let any 'AI' job or any 'security' job through; they match via `_all_of` instead.
    """
    t = topic.strip().lower()
    terms = [t]
    if " " in t:
        terms.append(re.sub(r"[\s\-]+", "", t))
    dist = _distinctive(topic)
    if len(dist) == 1:
        terms.append(dist[0])
    return list(dict.fromkeys(terms))


def _all_of(topic: str) -> List[str]:
    """Distinctive words that must ALL appear in a title (any order) for a multi-word topic; [] if not applicable."""
    dist = _distinctive(topic)
    return dist if len(dist) >= 2 else []


def _cache_path() -> str:
    try:
        try:
            from config.constants import resolve_workspace_root
        except ImportError:
            from backend.config.constants import resolve_workspace_root
        root = resolve_workspace_root()
    except Exception:
        root = os.getcwd()
    return os.path.join(root, "data", "topic_terms.json")


@dataclass
class Family:
    """What a topic means as a FIELD: title terms to include, look-alikes to exclude, extra phrases to search."""
    include: List[str] = field(default_factory=list)   # everything in the field, including adjacent roles ("Related")
    exclude: List[str] = field(default_factory=list)
    search: List[str] = field(default_factory=list)
    core: List[str] = field(default_factory=list)      # the subset that unmistakably IS the field ("Core")


def _clean_terms(items, limit: int, allow_generic: bool = False) -> List[str]:
    out = []
    for t in items or []:
        t = re.sub(r"\s+", " ", str(t).strip().lower())
        if not t or len(t) > 40:
            continue
        if not allow_generic and t in _GENERIC:
            continue
        if any(w in _LEVEL_WORDS for w in t.split()):
            continue
        out.append(t)
    return list(dict.fromkeys(out))[:limit]


def _normalize_family(obj) -> Family:
    """Accept a plain term list (older format / simple callers) or a dict with include/exclude/search."""
    if isinstance(obj, Family):
        obj = {"include": obj.include, "exclude": obj.exclude, "search": obj.search}
    if isinstance(obj, (list, tuple)):
        obj = {"include": list(obj)}
    obj = obj or {}
    inc = _clean_terms(obj.get("include"), 70)
    exc = _clean_terms(obj.get("exclude"), 15, allow_generic=True)
    exc = [e for e in exc if e not in inc]
    core = _clean_terms(obj.get("core"), 30)
    inc = list(dict.fromkeys(inc + core))                 # core terms are always matched too
    return Family(include=inc, exclude=exc, search=_clean_terms(obj.get("search"), 14), core=core)


def _llm_terms(topic: str) -> dict:
    """Ask the LLM what `topic` means as a whole field. Returns {} on any failure."""
    from pydantic import BaseModel

    class TopicFamily(BaseModel):
        core: List[str]
        include: List[str]
        exclude: List[str]
        search: List[str]

    try:
        try:
            from services.gemini_client import generate_content_with_fallback
        except ImportError:
            from backend.services.gemini_client import generate_content_with_fallback
        prompt = (
            f"A job seeker wants roles in the FIELD: '{topic}'. Treat it as a whole field, not a literal phrase: "
            "they want every kind of job in it.\n\n"
            "Return JSON with:\n"
            "- core: 10-20 lowercase terms that UNMISTAKABLY mean this exact field or niche (the narrow specialism, not the wider "
            "industry). Example for 'ai security engineer': ai security, llm security, ml security, ai red team, adversarial machine "
            "learning, model security, ai safety engineer. Generic terms like 'ai engineer' or 'machine learning engineer' are NOT core.\n"
            "- include: 40-60 lowercase words or short phrases that appear in JOB TITLES anywhere in this field. Be "
            "EXHAUSTIVE: think of every team and specialisation in a large organisation in this field, including the "
            "less obvious ones (e.g. for security: digital forensics, privacy, risk and compliance, fraud), plus adjacent "
            "role names (researcher, scientist, analyst, engineer variants) and standard abbreviations. "
            "Example for 'cyber security': software/application security, cloud security, "
            "network security, system security, AI/ML/LLM security, penetration testing, red team, threat intelligence, "
            "incident response, malware, cryptography, devsecops, infosec, appsec, GRC... Example for 'applied AI': "
            "machine learning, ml engineer, ml researcher, ai researcher, research scientist, applied scientist, deep "
            "learning, nlp, computer vision, llm, generative ai, mlops, data scientist... A single distinctive word is "
            "fine when it identifies the field on its own (e.g. 'security', 'ml'). Do NOT include seniority words "
            "(intern, junior, senior) and do not include generic words alone such as 'engineer', 'developer', "
            "'software', 'research', 'data', 'analyst'.\n"
            "- exclude: up to 12 lowercase phrases that look similar in a job title but belong to a DIFFERENT field "
            "(e.g. for security: 'security guard', 'security officer', 'social security', 'door supervisor'). "
            "Empty list if there are none.\n"
            "- search: 10-14 short job-board search phrases: real job-title wordings (e.g. 'ai security engineer', 'llm red team "
            "engineer') and different sub-areas of the field, that together would surface the whole field."
        )
        raw = generate_content_with_fallback(prompt, TopicFamily)
        return json.loads(raw)
    except Exception:
        return {}


def _read_cache(path: str) -> Dict[str, Any]:
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def get_family(topic: str, llm: Optional[Callable[[str], Any]] = None, use_cache: bool = True,
               refresh: bool = False) -> Family:
    """
    The cached/LLM family for `topic`. You can edit data/topic_terms.json by hand: add or remove terms under
    include / exclude / search and the next scan uses them (the file is only rewritten when a topic is refreshed).
    """
    key = topic.strip().lower()
    path = _cache_path()
    cache = _read_cache(path) if use_cache else {}
    entry = cache.get(key)
    if isinstance(entry, dict) and not refresh and entry.get("include"):
        return _normalize_family(entry)                        # current format
    fam = _normalize_family((llm or _llm_terms)(topic))        # miss, refresh, or an older narrow list-format entry
    if fam.include and use_cache:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            cache[key] = {"core": fam.core, "include": fam.include, "exclude": fam.exclude, "search": fam.search}
            with open(path, "w", encoding="utf-8") as f:
                json.dump(cache, f, indent=2, sort_keys=True)
        except Exception:
            pass
    return fam


def expand_topic(topic: str, llm: Optional[Callable[[str], Any]] = None, use_cache: bool = True) -> List[str]:
    """Terms that identify `topic` in a job title: its own words plus the field's include terms."""
    return list(dict.fromkeys(_own_terms(topic) + get_family(topic, llm=llm, use_cache=use_cache).include))


# ─── the spec ─────────────────────────────────────────────────────────────────
@dataclass
class RoleSpec:
    topics: List[str] = field(default_factory=list)
    level: str = "any"
    queries: List[str] = field(default_factory=list)
    topic_terms: List[str] = field(default_factory=list)
    topic_all_of: List[List[str]] = field(default_factory=list)  # each group: every word must be in the title
    topic_exclude: List[str] = field(default_factory=list)       # look-alike titles from other fields ("security guard")
    core_terms: List[str] = field(default_factory=list)          # exact-niche terms: a title matching one is "Core", otherwise "Related"
    split: bool = False  # level "all": the scan files each job into the intern / graduate / experienced Excel
    loose: bool = False  # also accept a match in the job description when the title doesn't match

    def __post_init__(self):
        self._topic_re = _compile(self.topic_terms)
        self._level_re = _compile(LEVELS[self.level]["terms"])
        self._group_res = [[_compile([w]) for w in grp] for grp in self.topic_all_of]
        self._exclude_re = _compile(self.topic_exclude)
        named = " ".join(self.topics + self.topic_terms).lower()          # a search that names one of them keeps it
        self._offfield_re = _compile([w for w in _OFF_FIELD if not re.search(rf"(?<![a-z]){re.escape(w)}", named)])
        self._core_re = _compile(self.core_terms)
        self._entry_re = _compile(LEVELS["intern"]["terms"] + LEVELS["graduate"]["terms"] + ["apprentice", "apprenticeship", "student"])

    def _topic_in_title(self, title: str) -> bool:
        if self._topic_re and self._topic_re.search(title):
            return True
        return any(all(r.search(title) for r in grp) for grp in self._group_res)

    def tier(self, title: str) -> str:
        """'Core' if the title names the exact niche you asked for (or all words of one of your topics), else 'Related'."""
        title = title or ""
        if self._core_re and self._core_re.search(title):
            return "Core"
        if any(all(r.search(title) for r in grp) for grp in self._group_res):
            return "Core"
        return "Related"

    def describe(self) -> str:
        bits = []
        if self.topics:
            bits.append(f"topic: {', '.join(self.topics)}")
        bits.append("level: all (split into intern / graduate / experienced)" if self.split else f"level: {self.level}")
        if self.topic_exclude:
            bits.append(f"avoiding: {', '.join(self.topic_exclude[:5])}")
        return " | ".join(bits)

    def matches(self, title: str, description: str = "") -> Tuple[bool, str]:
        """(ok, reason). Strict mode looks at the title only; loose also reads the description."""
        title = title or ""
        if self.level in ("intern", "graduate", "junior") and _SENIOR_TITLE.search(title):
            return False, "senior title"
        if self.level == "experienced" and self._entry_re and self._entry_re.search(title):
            return False, "intern/graduate role (belongs in the intern or graduate Excel)"
        if self._level_re:
            title_level = bool(self._level_re.search(title))
            desc_level = bool(self.loose and description and self._level_re.search(description[:600]))
            if not (title_level or desc_level):
                return False, f"title has no {self.level} keyword"
        if self._offfield_re and self._offfield_re.search(title):
            return False, "not a technical role (legal / admin / recruiting)"
        if self._exclude_re:
            bad = self._exclude_re.search(title)
            if bad:
                return False, f"look-alike from another field ({bad.group(0).lower()})"
        if self._topic_re or self._group_res:
            if self._topic_in_title(title):
                return True, "title match"
            if self.loose and description and self._topic_re:
                hits = len(self._topic_re.findall(description[:4000]))
                if hits >= 3:
                    return True, f"description mentions topic {hits}x"
            return False, "off topic"
        return True, "level match"


def build_queries(topics: List[str], level: str, sub_searches: Optional[List[List[str]]] = None, cap: int = 12) -> List[str]:
    """
    What to type into the job boards. Order matters (the cap trims the tail): every topic first, then each
    topic's sub-field searches (round-robin so no topic starves), then the alternate level wording.
    For level "all" the plain titles come first (they find experienced roles), then the Intern and Graduate variants.
    """
    lists = [l for l in (sub_searches or []) if l]
    if level == "all":
        out = list(topics)
        for i in range(max((len(l) for l in lists), default=0)):
            out += [l[i] for l in lists if i < len(l)]
        for suf in ("Intern", "Graduate"):
            out += [f"{t} {suf}" for t in topics]
            out += [f"{x} {suf}" for l in lists for x in l[:3]]
        return list(dict.fromkeys(q.strip() for q in out if q.strip()))[:max(cap, 28)]
    suffixes = LEVELS[level]["queries"] or [""]
    first = suffixes[0]
    out = [f"{t} {first}".strip() for t in topics]
    for i in range(max((len(l) for l in lists), default=0)):
        for l in lists:
            if i < len(l):
                out.append(f"{l[i]} {first}".strip())
    for suf in suffixes[1:]:
        out += [f"{t} {suf}".strip() for t in topics]
    return list(dict.fromkeys(out))[:cap]


def _typed_topics_and_level(topic, level, request, role):
    topics: List[str] = []
    lvl: Optional[str] = None
    if request:
        t, l = parse_request(request)
        topics += t
        lvl = l
    if topic:
        topics += [p.strip() for p in re.split(r"[,;]", topic) if p.strip()]
    if role:                                   # job titles typed with --role are expanded like any other topic
        topics += [p.strip() for p in re.split(r"[,;]", role) if p.strip()]
    if level:
        lvl = normalize_level(level)
    return list(dict.fromkeys(topics)), lvl, bool(request or topic or role)


def parse_inputs(topic: Optional[str] = None, level: Optional[str] = None, request: Optional[str] = None,
                 role: Optional[str] = None, prefs: Optional[dict] = None) -> Tuple[List[str], Optional[str]]:
    """
    The topics and level a scan will use, with the same precedence as resolve_spec but WITHOUT any LLM call
    (used to name the search's Excel). If you typed a topic / titles but no level the level is "all" (every level,
    split into three Excels); the profile's topics/level are used only when nothing was typed.
    """
    prefs = prefs or {}
    topics, lvl, typed = _typed_topics_and_level(topic, level, request, role)
    if not topics and not typed:
        topics = [t for t in prefs.get("topics", []) if t]
    if not lvl:
        if typed:
            lvl = "all"
        elif prefs.get("level"):
            lvl = normalize_level(prefs.get("level"))
    return topics, lvl


def resolve_spec(
    topic: Optional[str] = None,
    level: Optional[str] = None,
    request: Optional[str] = None,
    role: Optional[str] = None,
    prefs: Optional[dict] = None,
    loose: bool = False,
    exact: bool = False,
    llm: Optional[Callable[[str], Any]] = None,
    refresh: bool = False,
) -> Optional[RoleSpec]:
    """
    Decide what to search for. `--role` gives explicit queries (no topic filtering). Otherwise free text /
    --topic / --level, with anything not typed filled from the profile's `topics` / `level`. With nothing
    typed and no profile defaults: None (legacy behaviour: profile `target_roles`, no filtering).
    An explicit --level always wins over a level found in free text.
    """
    prefs = prefs or {}
    topics, lvl = parse_inputs(topic, level, request, role, prefs)
    if not topics and not lvl:
        return None

    topics = list(dict.fromkeys(topics))
    lvl = lvl or "any"
    split = lvl == "all"
    queries_level = lvl
    if split:
        lvl = "any"                     # the topic filter applies to every level; each job is filed by `job_level.classify`
    terms: List[str] = []
    cores: List[str] = []
    groups: List[List[str]] = []
    excludes: List[str] = []
    searches: List[List[str]] = []
    for t in topics:
        cores += _own_terms(t)                       # what you typed is always the core
        if exact:
            terms += _own_terms(t)
        else:
            fam = get_family(t, llm=llm, refresh=refresh)
            cores += fam.core
            terms += _own_terms(t) + fam.include
            excludes += fam.exclude
            searches.append([q for q in fam.search if q.lower() != t.lower()])
        if _all_of(t):
            groups.append(_all_of(t))
    terms = list(dict.fromkeys(terms))
    return RoleSpec(topics=topics, level=lvl, queries=build_queries(topics, queries_level, searches) if topics else [],
                    topic_terms=terms, topic_all_of=groups, split=split, core_terms=list(dict.fromkeys(cores)),
                    topic_exclude=[e for e in dict.fromkeys(excludes) if e not in terms], loose=loose)
