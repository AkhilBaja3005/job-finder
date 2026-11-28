"""Deterministic verification gates for CV tailoring (Phase 0).

Every fact, number, currency, date, title, entity, verb strength, and claim-to-source
mapping is checked in code rather than trusting model output.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple


_NUM_RE = re.compile(r"\d[\d,.]*%?")
_CURRENCY_RE = re.compile(r"(?:£|\$|€|₹|\b(?:INR|GBP|USD|EUR|Rs\.?|Cr\+?)\b)", re.IGNORECASE)
_DURATION_RE = re.compile(r"\b\d+\+?\s*(?:years?|yrs?|months?|mos?)\b", re.IGNORECASE)
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(?:\+\d{1,3}[\s.-]?)?(?:\(?\d{2,4}\)?[\s.-]?){2,4}\d{2,4}")
_URL_RE = re.compile(r"https?://[^\s)\]>\"']+")
_TECH_RE = re.compile(
    r"\b(?:[A-Z]{2,}[A-Za-z0-9]*|[A-Za-z]+[A-Z][A-Za-z0-9]+|[A-Za-z]+[0-9][A-Za-z0-9.\-]*|[A-Za-z0-9]+(?:\+\+|#))"
)
_PROPER_RE = re.compile(r"\b[A-Z][A-Za-z0-9.+#/-]{1,}\b")

# Common sentence-leading or generic non-entity capitalized words allowed in prose.
_COMMON_CAP_WORDS = {
    "a", "an", "and", "applied", "architected", "assisted", "at", "automated", "available",
    "built", "by", "contributed", "created", "cut", "cutting", "data", "delivered", "designed",
    "developed", "distributed", "during", "earned", "education", "engineered", "engineer",
    "engineering", "experience", "experienced", "flagged", "for", "from", "implemented",
    "improved", "in", "internal", "led", "machine", "managed", "model", "models", "of", "on",
    "or", "owned", "pipeline", "pipelines", "projects", "reduced", "reducing", "research",
    "skills", "software", "static", "summary", "system", "systems", "the", "to", "using",
    "with", "work", "worked",
}

_ESCALATION_PAIRS = (
    (re.compile(r"\baligned\s+with\b", re.I), re.compile(r"\b(?:ensuring\s+compliance|enforced|guaranteed|mandated)\b", re.I),
     "escalates 'aligned with' to stronger compliance claim"),
    (re.compile(r"\b(?:contributed\s+to|assisted\s+with|helped)\b", re.I), re.compile(r"\b(?:led|owned|spearheaded|directed|headed|architected|managed)\b", re.I),
     "escalates supportive role verb to ownership/leadership"),
)

_SCOPE_AND_SENIORITY_WORDS = (
    "production", "enterprise", "scalable", "mission-critical",
    "senior", "lead", "principal", "staff", "head", "director", "chief",
)

_INJECTION_PATTERNS = (
    re.compile(r"ignore\s+(?:all\s+)?previous\s+(?:rules|instructions)", re.I),
    re.compile(r"system\s+override", re.I),
    re.compile(r"disregard\s+(?:all\s+)?(?:rules|instructions)", re.I),
    re.compile(r"(?:you\s+must\s+add|add\s+[A-Za-z0-9_+.#,\s]+\s+to\s+(?:the\s+)?skills)", re.I),
    re.compile(r"state\s+that\s+the\s+candidate\s+worked", re.I),
    re.compile(r"<\s*/?\s*system\s*>|\[INST\]", re.I),
)


@dataclass
class SourceLedger:
    """Maps every source span ID to its exact text from profile / master CV."""
    spans: Dict[str, str] = field(default_factory=dict)

    @property
    def full_text(self) -> str:
        return "\n".join(v for v in self.spans.values() if v)


def build_source_ledger(master: Dict[str, Any]) -> SourceLedger:
    spans: Dict[str, str] = {}
    ident = " ".join(
        str(x) for x in [master.get("name", ""), master.get("email", ""), master.get("phone", ""), *list(master.get("links") or [])] if x
    )
    if ident:
        spans["identity"] = ident
    if master.get("summary"):
        spans["summary"] = str(master["summary"])
    for i, exp in enumerate(master.get("experience") or []):
        spans[f"exp:{i}:meta"] = f"{exp.get('role', '')} at {exp.get('company', '')} ({exp.get('start_date', '')} - {exp.get('end_date', '')}) {exp.get('technologies', '')}"
        for j, b in enumerate(exp.get("description") or []):
            spans[f"exp:{i}:{j}"] = str(b)
    for i, proj in enumerate(master.get("projects") or []):
        spans[f"proj:{i}:meta"] = f"{proj.get('title', '')} {' '.join(proj.get('technologies') or [])}"
        for j, b in enumerate(proj.get("description") or []):
            spans[f"proj:{i}:{j}"] = str(b)
    for i, edu in enumerate(master.get("education") or []):
        spans[f"edu:{i}"] = f"{edu.get('institution', '')} {edu.get('degree', '')} {edu.get('field_of_study', '')} {edu.get('start_date', '')} {edu.get('graduation_date', '')}"
    for i, sk in enumerate(master.get("skills") or []):
        spans[f"skill:{i}"] = str(sk)
    return SourceLedger(spans=spans)


def _has_token(text_lower: str, token: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(token.lower())}(?![a-z0-9])", text_lower) is not None


def _numbers(text: str) -> set:
    return {n.strip(".,") for n in _NUM_RE.findall(text or "") if len(n.strip(".,")) >= 1}


def check_facts(new_text: str, source_text: str, master: Optional[Dict[str, Any]] = None) -> List[str]:
    """Deterministic code check for numbers, currencies, dates, durations, entities, URLs, emails, phones, and tools."""
    if not (new_text or "").strip():
        return []
    issues: List[str] = []
    src = source_text or ""
    if master:
        src = "\n".join([
            src,
            str(master.get("name") or ""),
            str(master.get("email") or ""),
            str(master.get("phone") or ""),
            " ".join(str(x) for x in (master.get("links") or [])),
        ])
    src_low = src.lower()

    # 1. Numbers & percentages
    src_nums = _numbers(src)
    for n in sorted(_numbers(new_text)):
        if n not in src_nums:
            issues.append(f"unsupported number '{n}'")

    # 2. Currencies
    src_curr = {c.lower().rstrip(".") for c in _CURRENCY_RE.findall(src)}
    for c in _CURRENCY_RE.findall(new_text):
        if c.lower().rstrip(".") not in src_curr:
            issues.append(f"unsupported currency '{c}'")

    # 3. Years & durations
    src_years = set(_YEAR_RE.findall(src))
    for y in _YEAR_RE.findall(new_text):
        if y not in src_years:
            issues.append(f"unsupported year '{y}'")
    for dur in _DURATION_RE.findall(new_text):
        if dur.lower() not in src_low:
            issues.append(f"unsupported duration '{dur}'")

    # 4. Emails, URLs, Phones
    for em in _EMAIL_RE.findall(new_text):
        if em.lower() not in src_low:
            issues.append(f"unsupported email '{em}'")
    for u in _URL_RE.findall(new_text):
        if u.lower().rstrip(".,)") not in src_low:
            issues.append(f"unsupported url '{u}'")
    src_digits = {re.sub(r"\D", "", p) for p in _PHONE_RE.findall(src) if len(re.sub(r"\D", "", p)) >= 7}
    for ph in _PHONE_RE.findall(new_text):
        digits = re.sub(r"\D", "", ph)
        if len(digits) >= 7 and digits not in src_digits:
            issues.append(f"unsupported phone '{ph.strip()}'")

    # 5. Technologies & capitalized proper nouns (companies, institutions, titles, locations, degrees)
    for tok in _TECH_RE.findall(new_text):
        if not _has_token(src_low, tok):
            issues.append(f"unsupported tech '{tok}'")
    for prop in _PROPER_RE.findall(new_text):
        if prop.lower() in _COMMON_CAP_WORDS:
            continue
        if not _has_token(src_low, prop):
            issues.append(f"unsupported entity '{prop}'")

    return list(dict.fromkeys(issues))


def check_no_conversions(new_text: str, original_text: str, source_text: str) -> List[str]:
    """Reject currency/unit conversions, rounding, or derived numbers not in original/source."""
    issues: List[str] = []
    orig_nums = _numbers(original_text)
    src_nums = _numbers(source_text)
    for n in sorted(_numbers(new_text)):
        if n not in orig_nums or n not in src_nums:
            issues.append(f"number '{n}' not in original span")
    orig_curr = {c.lower().rstrip(".") for c in _CURRENCY_RE.findall(original_text)}
    for c in _CURRENCY_RE.findall(new_text):
        if c.lower().rstrip(".") not in orig_curr:
            issues.append(f"currency '{c}' differs from original")
    if re.search(r"\b(?:over|averaged|total(?:led)?)\b", new_text, re.I) and not re.search(r"\b(?:over|averaged|total(?:led)?)\b", original_text, re.I):
        issues.append("introduces derived qualifier (over/averaged/total)")
    return list(dict.fromkeys(issues))


def check_strength_escalation(new_text: str, original_text: str, source_text: str) -> List[str]:
    """Reject verbs or seniority/scope modifiers stronger than the original and source."""
    issues: List[str] = []
    for weak_re, strong_re, msg in _ESCALATION_PAIRS:
        if weak_re.search(original_text) and strong_re.search(new_text) and not strong_re.search(original_text):
            issues.append(msg)
    orig_low = original_text.lower()
    src_low = source_text.lower()
    new_low = new_text.lower()
    for word in _SCOPE_AND_SENIORITY_WORDS:
        if _has_token(new_low, word) and not _has_token(orig_low, word) and not _has_token(src_low, word):
            issues.append(f"adds ungrounded strength/seniority term '{word}'")
    return list(dict.fromkeys(issues))


def verify_claim_ledger(claims: List[Dict[str, Any]], ledger: SourceLedger) -> Tuple[bool, List[str]]:
    """Every claim must reference valid source_ids whose combined spans entail all facts in the claim."""
    reasons: List[str] = []
    for idx, claim in enumerate(claims):
        text = str(claim.get("text") or "").strip()
        sids = [str(s) for s in (claim.get("source_ids") or []) if str(s)]
        if not text:
            continue
        if not sids:
            reasons.append(f"claim {idx} has no source_ids")
            continue
        missing = [s for s in sids if s not in ledger.spans]
        if missing:
            reasons.append(f"claim {idx} references unknown source_ids: {', '.join(missing)}")
            continue
        span_text = "\n".join(ledger.spans[s] for s in sids)
        fact_issues = check_facts(text, span_text)
        if fact_issues:
            reasons.append(f"claim {idx} unsupported by {sids}: {'; '.join(fact_issues)}")
        # Ensure meaningful content word overlap with the cited spans
        claim_words = {w.lower()[:5] for w in re.findall(r"[A-Za-z]{4,}", text)}
        span_words = {w.lower()[:5] for w in re.findall(r"[A-Za-z]{4,}", span_text)}
        if claim_words and not (claim_words & span_words):
            reasons.append(f"claim {idx} has no lexical overlap with cited spans {sids}")
    return len(reasons) == 0, reasons


def scan_jd_for_injection(jd_text: str) -> List[str]:
    """Detect prompt-injection attempts inside untrusted JD text."""
    hits: List[str] = []
    for pat in _INJECTION_PATTERNS:
        m = pat.search(jd_text or "")
        if m:
            hits.append(m.group(0))
    return hits


def sanitize_jd(jd_text: str) -> Tuple[str, List[str]]:
    """Strip detected injection lines and return (cleaned_jd, injection_hits)."""
    hits = scan_jd_for_injection(jd_text)
    if not hits:
        return jd_text or "", []
    cleaned_lines = []
    for line in (jd_text or "").splitlines():
        if any(pat.search(line) for pat in _INJECTION_PATTERNS):
            continue
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines), hits


def check_entailment(
    new_text: str,
    source_text: str,
    entailment_llm: Optional[Callable[[str], str]] = None,
) -> Tuple[bool, Optional[str]]:
    """Optional second-pass entailment verification. Returns (accepted, warning)."""
    if entailment_llm is None:
        return True, None
    prompt = (
        "Does the SOURCE text fully support every statement, number, and claim in the NEW text? "
        'Reply with JSON only: {"supported": true or false, "reason": "short explanation"}.\n\n'
        f"SOURCE:\n{source_text[:4000]}\n\nNEW:\n{new_text}"
    )
    try:
        raw = entailment_llm(prompt)
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", str(raw).strip())
        data = json.loads(cleaned)
        if isinstance(data, dict) and data.get("supported") is True:
            return True, None
        reason = str((data or {}).get("reason") or "not entailed by source") if isinstance(data, dict) else "invalid entailment response"
        return False, f"Entailment check rejected rewrite: {reason}"
    except Exception as exc:
        return True, f"Entailment check skipped ({type(exc).__name__}): {str(exc)[:80]}"


def is_non_english(text: str) -> bool:
    """Quick heuristic to catch non-English model output when source is English."""
    if not text:
        return False
    # High ratio of non-ASCII characters or common German/French/Spanish stopword clusters
    non_ascii = sum(1 for ch in text if ord(ch) > 127)
    if len(text) > 20 and non_ascii / len(text) > 0.25:
        return True
    low = f" {text.lower()} "
    foreign_markers = (" ich ", " und ", " mit ", " ein ", " erfahrener ", " años ", " avec ", " pour ")
    return sum(1 for m in foreign_markers if m in low) >= 2
