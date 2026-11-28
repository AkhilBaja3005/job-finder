"""Phase 4: Honest CV writer and style/format/link guards.

Enforces multiset preservation of numbers & tools on rewrites,
honest summary selection (master summary is base; replaces only if verified
and higher scoring), title honesty, style consistency, voice similarity,
HTML/LaTeX escaping, link verification, and candidate term controls.
"""
from __future__ import annotations

import html
import re
from collections import Counter
from typing import Any, Dict, List, Optional, Sequence, Tuple

from backend.services.cv_verifier import (
    check_facts,
    check_no_conversions,
    check_strength_escalation,
)


_KNOWN_TOOLS = (
    "python", "pytorch", "tensorflow", "fastapi", "django", "flask", "sql",
    "postgresql", "docker", "kubernetes", "langgraph", "langchain", "rag",
    "llm", "llms", "aws", "gcp", "azure", "react", "typescript", "go", "rust",
)

_PLACEHOLDER_DOMAINS = ("example.com", "example.org", "janedoe", "johndoe", "placeholder", "localhost")


def _number_multiset(text: str) -> Counter:
    nums = re.findall(r"(?:INR\s*)?\d+(?:[.,]\d+)?(?:%|[kKmMbB]|Cr\+?)?", text or "")
    return Counter(n.lower().replace(" ", "") for n in nums)


def _tool_set(text: str) -> set[str]:
    low = (text or "").lower()
    return {t for t in _KNOWN_TOOLS if re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", low)}


def check_rewrite_preserves_numbers_and_tools(original: str, new_text: str) -> Tuple[bool, List[str]]:
    """Verify a rewrite keeps the exact multiset of numbers and set of tools."""
    reasons: List[str] = []
    orig_nums = _number_multiset(original)
    new_nums = _number_multiset(new_text)
    if orig_nums != new_nums:
        reasons.append(f"number_multiset_changed: {dict(orig_nums)} != {dict(new_nums)}")

    orig_tools = _tool_set(original)
    new_tools = _tool_set(new_text)
    if orig_tools != new_tools:
        reasons.append(f"tool_set_changed: {sorted(orig_tools)} != {sorted(new_tools)}")

    return len(reasons) == 0, reasons


def format_rewrite_log(pairs: Sequence[Dict[str, str]]) -> str:
    """Render side-by-side original vs new rewrites with reasons for cv_changes.md."""
    lines = ["## Rewrites", ""]
    for idx, p in enumerate(pairs, 1):
        lines.append(f"### Rewrite {idx}")
        lines.append(f"- **Original:** {p.get('original', '')}")
        lines.append(f"- **Tailored:** {p.get('new_text', '')}")
        lines.append(f"- **Reason:** {p.get('reason', '')}")
        lines.append("")
    return "\n".join(lines).strip()


def check_title_honesty(target_title: str, source_text: str) -> bool:
    """Return True only if the candidate's source supports the target title."""
    src_low = (source_text or "").lower()
    title_low = (target_title or "").lower()
    if "machine learning" in title_low and ("ml" in re.findall(r"[a-z0-9]+", src_low) or "machine learning" in src_low):
        return True
    tokens = [
        t for t in re.findall(r"[a-z0-9]+", title_low)
        if t not in {"engineer", "developer", "of", "and", "the", "for", "in", "a"} and len(t) >= 2
    ]
    if not tokens:
        return True
    matched = sum(1 for t in tokens if re.search(rf"\b{re.escape(t)}\b", src_low))
    return matched >= max(1, (len(tokens) + 1) // 2)


def build_honest_summary(
    *,
    master_summary: str,
    candidate_summary: str,
    source_text: str,
    target_role: str = "",
    master_score: float = 0.0,
    candidate_score: float = 0.0,
) -> str:
    """Keep master_summary unless candidate_summary passes all checks and scores higher."""
    cand = (candidate_summary or "").strip()
    if not cand or candidate_score <= master_score:
        return master_summary
    if target_role and not check_title_honesty(target_role, source_text):
        return master_summary
    if check_facts(cand, source_text):
        return master_summary
    if check_no_conversions(cand, source_text, source_text):
        return master_summary
    if check_strength_escalation(cand, source_text, source_text):
        return master_summary
    return cand


def check_style_consistency(text: str, *, is_current_role: bool = False) -> List[str]:
    """Lint for first-person pronouns, ALL-CAPS shouting, and filler."""
    issues: List[str] = []
    if re.search(r"\b(I|me|my|mine|we|our|ours)\b", text or ""):
        issues.append("first_person_pronoun")
    caps_words = [
        w for w in re.findall(r"\b[A-Z]{4,}\b", text or "")
        if w not in {"HTTP", "HTTPS", "HTML", "JSON", "REST", "CUDA", "FAISS", "LLMS", "OPENAI", "LANGGRAPH", "PYTORCH"}
    ]
    if caps_words:
        issues.append(f"all_caps:{','.join(caps_words)}")
    if not is_current_role and re.match(r"^\s*(Build|Design|Develop|Create|Lead|Manage)s?\b", text or ""):
        issues.append("present_tense_on_past_role")
    return issues


def measure_style_distance(master_text: str, candidate_text: str) -> float:
    """Measure sentence-length and vocabulary/buzzword distance from master CV."""
    def _avg_len(t: str) -> float:
        sents = [s.strip() for s in re.split(r"[.!?]+", t) if s.strip()]
        if not sents:
            return 0.0
        return sum(len(s.split()) for s in sents) / len(sents)

    m_len = _avg_len(master_text)
    c_len = _avg_len(candidate_text)
    len_diff = abs(m_len - c_len) / max(1.0, m_len, c_len)

    m_words = set(re.findall(r"[a-z]+", (master_text or "").lower()))
    c_words = set(re.findall(r"[a-z]+", (candidate_text or "").lower()))
    union = m_words | c_words
    jaccard_dist = 1.0 - (len(m_words & c_words) / len(union)) if union else 0.0
    return round(0.4 * len_diff + 0.6 * jaccard_dist, 3)


def escape_for_html(text: str) -> str:
    """Escape special characters for HTML while preserving Unicode/emoji."""
    return html.escape(text or "", quote=True)


def escape_for_latex(text: str) -> str:
    """Escape LaTeX special characters without dropping accents or Unicode."""
    s = text or ""
    replacements = [
        ("\\", r"\textbackslash{}"),
        ("&", r"\&"),
        ("%", r"\%"),
        ("#", r"\#"),
        ("$", r"\$"),
        ("_", r"\_"),
        ("{", r"\{"),
        ("}", r"\}"),
        ("~", r"\textasciitilde{}"),
        ("^", r"\textasciicircum{}"),
    ]
    for old, new in replacements:
        s = s.replace(old, new)
    return s


def validate_links(urls: Sequence[str], source_urls: Sequence[str]) -> Tuple[bool, List[str]]:
    """Verify every URL exists in source_urls and reject placeholder/dead patterns."""
    src_norm = {u.strip().rstrip("/").lower() for u in source_urls if u}
    errors: List[str] = []
    for u in urls:
        norm = (u or "").strip().rstrip("/").lower()
        if any(p in norm for p in _PLACEHOLDER_DOMAINS):
            errors.append(f"placeholder_link:{u}")
        elif norm not in src_norm:
            errors.append(f"invented_link:{u}")
    return len(errors) == 0, errors


def apply_candidate_term_controls(
    items: Sequence[Dict[str, Any]],
    *,
    never_say: Sequence[str] = (),
    always_keep: Sequence[str] = (),
) -> List[Dict[str, Any]]:
    """Drop items matching never_say unless explicitly protected by always_keep."""
    never_low = [t.lower() for t in never_say if t]
    keep_low = [t.lower() for t in always_keep if t]
    out: List[Dict[str, Any]] = []
    for item in items:
        txt = (item.get("text") or "").lower()
        if any(k in txt for k in keep_low):
            out.append(dict(item))
            continue
        if any(n in txt for n in never_low):
            continue
        out.append(dict(item))
    return out
