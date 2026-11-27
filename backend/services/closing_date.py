"""
closing_date.py - best-effort extraction of a job posting's application closing date.

Most ATS boards (Greenhouse, Lever, Ashby) publish no deadline at all, so this module
returns None rather than guessing. Sources, in order of reliability:

1. Structured fields already on a scraped job (``closing_date`` / ``valid_through`` / ``deadline``)
2. schema.org ``JobPosting.validThrough`` in the page's JSON-LD
3. Cue phrases in the description text ("Closing date: 30 November 2026", "apply by ...")
"""

import json
import re
from datetime import date, datetime, timedelta
from typing import Any, Iterable, Optional

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}
_MONTH_RE = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"

_DMY_TEXT = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({_MONTH_RE})\.?,?\s+(\d{{4}})\b", re.I)
_MDY_TEXT = re.compile(rf"\b({_MONTH_RE})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", re.I)
_ISO = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")  # also matches 2026-12-31T23:59:00Z
_SLASH = re.compile(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{4})\b")  # UK day-first

_CUES = re.compile(
    r"(?:closing\s+date|close\s+date|applications?\s+clos(?:e|es|ing)(?:\s+on)?|clos(?:es|ing)\s+on|"
    r"closing\s+on|application\s+deadline|deadline(?:\s+for\s+applications?)?|apply\s+(?:by|before)|"
    r"applications?\s+(?:must\s+be\s+)?(?:received|submitted)\s+by|last\s+date\s+(?:to\s+apply|for\s+applications?)|"
    r"applications?\s+(?:are\s+)?open\s+until|open\s+until)",
    re.I,
)
_WINDOW = 70  # characters after a cue phrase searched for a date


def parse_date(value: Any) -> Optional[date]:
    """Parse the date formats seen on job boards. Slash dates are read day-first (UK)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    if not s:
        return None
    m = _ISO.search(s)
    if m:
        return _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = _DMY_TEXT.search(s)
    if m:
        return _safe_date(int(m.group(3)), _MONTHS[m.group(2).lower().rstrip(".")], int(m.group(1)))
    m = _MDY_TEXT.search(s)
    if m:
        return _safe_date(int(m.group(3)), _MONTHS[m.group(1).lower().rstrip(".")], int(m.group(2)))
    m = _SLASH.search(s)
    if m:
        return _safe_date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    return None


def _safe_date(y: int, m: int, d: int) -> Optional[date]:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _plausible(d: Optional[date], today: Optional[date] = None) -> Optional[date]:
    """Reject dates that are almost certainly parse noise (decades away)."""
    if d is None:
        return None
    today = today or date.today()
    if d < today - timedelta(days=366) or d > today + timedelta(days=366 * 2):
        return None
    return d


def extract_from_text(text: str, today: Optional[date] = None) -> Optional[date]:
    """Find a date that follows a closing/deadline cue phrase in free text."""
    if not text:
        return None
    for cue in _CUES.finditer(text):
        window = text[cue.end(): cue.end() + _WINDOW]
        d = _plausible(parse_date(window), today)
        if d:
            return d
    return None


def extract_from_jsonld(html: str, today: Optional[date] = None) -> Optional[date]:
    """Read ``validThrough`` from any schema.org JobPosting block in the HTML."""
    if not html:
        return None
    for block in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.S | re.I):
        try:
            data = json.loads(block.strip())
        except (ValueError, TypeError):
            continue
        for node in _walk(data):
            if isinstance(node, dict) and "validThrough" in node:
                d = _plausible(parse_date(node.get("validThrough")), today)
                if d:
                    return d
    return None


def _walk(node: Any) -> Iterable[Any]:
    yield node
    if isinstance(node, dict):
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def from_job(job: dict, today: Optional[date] = None) -> Optional[date]:
    """Closing date from a scraped job dict: structured fields first, then description text."""
    for key in ("closing_date", "valid_through", "validThrough", "deadline", "application_deadline"):
        d = _plausible(parse_date(job.get(key)), today)
        if d:
            return d
    return extract_from_text(job.get("description") or job.get("full_description") or "", today)


# Boards that block simple HTTP fetches or never expose JSON-LD to anonymous clients.
_SKIP_FETCH_HOSTS = ("linkedin.com", "indeed.com", "reed.co.uk")


async def fetch_closing_date(url: str, client: Any, today: Optional[date] = None) -> Optional[date]:
    """Fetch the job page and read JSON-LD ``validThrough``. Never raises; returns None on any failure."""
    if not url or any(h in url.lower() for h in _SKIP_FETCH_HOSTS):
        return None
    try:
        resp = await client.get(url, follow_redirects=True)
        if resp.status_code != 200:
            return None
        return extract_from_jsonld(resp.text, today)
    except Exception:
        return None
