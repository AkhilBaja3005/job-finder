"""Quality checks for tailored resumes: fact fidelity and PDF text extractability."""

import re
from typing import Iterable, List

_NUMBER_RE = re.compile(r"\d[\d,.]*\s?(?:%|k|m|bn|x)?", re.IGNORECASE)


def _numbers(text: str) -> set:
    # Strip LaTeX escapes (50\% -> 50%) and commands so numbers compare fairly
    cleaned = re.sub(r"\\([%&$#_])", r"\1", text or "")
    cleaned = re.sub(r"\\[a-zA-Z]+", " ", cleaned)
    found = set()
    for m in _NUMBER_RE.finditer(cleaned):
        token = re.sub(r"\s+", "", m.group(0)).lower().rstrip(".,")
        if len(re.sub(r"\D", "", token)) >= 2:  # ignore single digits, they are noise
            found.add(token)
    return found


def find_unsupported_numbers(master_text: str, tailored_text: str) -> List[str]:
    """Numbers (metrics, years, percentages) in the tailored resume that never appear in the master."""
    return sorted(_numbers(tailored_text) - _numbers(master_text))


def check_pdf_text(pdf_path: str, required: Iterable[str] = ()) -> List[str]:
    """
    Extract text the way an ATS parser would and report problems:
    unreadable glyphs, missing required strings (name, email), or no extractable text at all.
    """
    from pypdf import PdfReader

    problems: List[str] = []
    try:
        text = "\n".join((page.extract_text() or "") for page in PdfReader(pdf_path).pages)
    except Exception as exc:
        return [f"Could not read PDF text: {exc}"]

    if len(text.strip()) < 100:
        problems.append("Almost no extractable text; an ATS would see an empty resume (image-only PDF?).")
    if "(cid:" in text or "�" in text:
        problems.append("Unreadable glyphs found (cid/replacement characters); fonts are not text-extractable.")
    flat = re.sub(r"\s+", "", text).lower()
    for item in required:
        if item and re.sub(r"\s+", "", item).lower() not in flat:
            problems.append(f"'{item}' not found in extracted text.")
    return problems
