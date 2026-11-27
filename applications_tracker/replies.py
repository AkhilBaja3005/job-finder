"""Finds replies from employers in the user's mailbox and says how each application should be marked.

Opt-in: it needs a mailbox address and an app password in the .env (REPLY_IMAP_USER, REPLY_IMAP_PASSWORD, and REPLY_IMAP_HOST,
default imap.gmail.com). It only reads message headers and the first part of the text, never marks anything read, never
sends or deletes mail, and only looks at the last few weeks. Automated "we received your application" mails are ignored.
Matching is by company name, so it is a helper: the user can always change a status by hand."""
from __future__ import annotations

import email
import email.header
import imaplib
import re
from datetime import datetime, timedelta
from email.utils import parseaddr
from typing import Any, Dict, Iterable, List, Optional

# Statuses in the order an application moves through them. Only a later stage replaces an earlier one.
RANK = {"applied": 0, "replied": 1, "rejected": 2, "interview": 3, "offer": 4}
ACK = re.compile(r"(thank you for (?:applying|your application|your interest)|we(?:'ve| have) received your application|application (?:received|confirmation)|your application (?:has been|was) (?:received|submitted)|we will review your application)", re.I)
REJECT = re.compile(r"(unfortunately|regret to inform|not (?:be )?(?:moving|proceeding) forward|will not be proceeding|other candidates|decided not to (?:proceed|move)|not (?:been )?successful|position has been filled)", re.I)
INTERVIEW = re.compile(r"(interview|phone screen|schedule a (?:call|chat|time)|book a (?:call|slot|time)|speak with you|next (?:steps|stage|round)|technical assessment|coding (?:test|challenge)|availability)", re.I)
OFFER = re.compile(r"(pleased to offer|offer of employment|we(?:'d| would) like to offer you|job offer)", re.I)


def classify(subject: str, body: str) -> Optional[str]:
    """'offer', 'interview', 'rejected', 'replied', or None for automated acknowledgements."""
    text = f"{subject}\n{body}"
    if OFFER.search(text):
        return "offer"
    if REJECT.search(text):
        return "rejected"
    if INTERVIEW.search(text):
        return "interview"
    if ACK.search(text):
        return None
    return "replied"


def _words(name: str) -> List[str]:
    stop = {"ltd", "limited", "inc", "llc", "plc", "the", "group", "company", "co", "uk", "labs", "technologies", "technology"}
    return [w for w in re.findall(r"[a-z0-9]+", (name or "").lower()) if w not in stop and len(w) > 1]


def mentions_company(company: str, sender: str, subject: str, body: str) -> bool:
    words = _words(company)
    if not words:
        return False
    domain = (parseaddr(sender)[1].split("@")[-1] if "@" in sender else "").lower()
    haystack = " ".join([sender.lower(), subject.lower(), body.lower()[:1500]])
    phrase = " ".join(words)
    return phrase in haystack or (len(words) == 1 and (words[0] in domain or re.search(rf"\b{re.escape(words[0])}\b", haystack) is not None))


def decode(value: Any) -> str:
    if not value:
        return ""
    parts = []
    for text, charset in email.header.decode_header(str(value)):
        parts.append(text.decode(charset or "utf-8", "replace") if isinstance(text, bytes) else text)
    return "".join(parts)


def plain_text(msg: email.message.Message, limit: int = 2000) -> str:
    for part in msg.walk() if msg.is_multipart() else [msg]:
        if part.get_content_type() == "text/plain":
            payload = part.get_payload(decode=True) or b""
            return payload.decode(part.get_content_charset() or "utf-8", "replace")[:limit]
    return ""


def best_stage(current: str, found: Iterable[str]) -> Optional[str]:
    """The furthest stage among the found replies, if it is further than the current one."""
    top = max(found, key=lambda s: RANK[s], default=None)
    return top if top and RANK[top] > RANK.get(current, 0) else None


def stage_of(status: str) -> str:
    s = (status or "").lower()
    for key in ("offer", "interview", "rejected", "replied"):
        if s.startswith(key):
            return key
    return "applied"


def fetch_messages(host: str, user: str, password: str, days: int = 30, limit: int = 300) -> List[Dict[str, str]]:
    since = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
    conn = imaplib.IMAP4_SSL(host, timeout=30)
    try:
        conn.login(user, password)
        conn.select("INBOX", readonly=True)
        _, data = conn.search(None, "SINCE", since)
        ids = (data[0] or b"").split()[-limit:]
        out = []
        for mid in ids:
            _, parts = conn.fetch(mid, "(BODY.PEEK[]<0.6000>)")  # the first 6 KB only, without marking it read
            raw = next((p[1] for p in parts if isinstance(p, tuple)), b"")
            msg = email.message_from_bytes(raw)
            out.append({"from": decode(msg.get("From")), "subject": decode(msg.get("Subject")), "body": plain_text(msg)})
        return out
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def find_updates(applications: List[Dict[str, str]], messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """[{url, company, stage, subject}] for every application that has a further-along reply than its current status."""
    updates = []
    for app in applications:
        company, url = app.get("company", ""), app.get("url", "")
        if not company or not url:
            continue
        found, seen_subject = [], ""
        for m in messages:
            if mentions_company(company, m["from"], m["subject"], m["body"]):
                stage = classify(m["subject"], m["body"])
                if stage:
                    found.append(stage)
                    seen_subject = m["subject"] if RANK[stage] >= max((RANK[s] for s in found), default=0) else seen_subject
        new = best_stage(stage_of(app.get("status", "")), found)
        if new:
            updates.append({"url": url, "company": company, "stage": new, "subject": seen_subject[:120]})
    return updates
