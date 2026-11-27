"""Tools handed to the browser agent so it looks answers up in the user's profile instead of making them up.

`profile_answer` returns the user's own data for a question (or says there is none). `verify_answers` checks a list of answers just before
submit. Every call is recorded in an audit that the run reports and that decides whether the run needs the user's review."""

import json
from typing import Any, Dict, List, Optional

from services.grounding import ProfileFacts


class GroundingAudit:
    def __init__(self) -> None:
        self.from_profile: List[str] = []
        self.no_data: List[str] = []
        self.stopped: List[str] = []
        self.ungrounded: List[Dict[str, str]] = []
        self.verified = False

    def summary(self) -> Dict[str, Any]:
        return {"answered_from_profile": len(self.from_profile), "no_data": self.no_data[:25], "stopped": self.stopped[:25],
                "ungrounded": self.ungrounded[:25], "verified": self.verified}

    @property
    def needs_review(self) -> bool:
        return bool(self.ungrounded or self.stopped)


def lookup(facts: ProfileFacts, audit: GroundingAudit, question: str, options: Optional[List[str]] = None, company: Optional[str] = None) -> str:
    out = facts.answer(question, options, company)
    q = str(question)[:140]
    if out["status"] in ("answer", "policy"):
        audit.from_profile.append(q)
    elif out["status"] == "stop":
        audit.stopped.append(q)
    elif out["status"] == "no_data":
        audit.no_data.append(q)
    return json.dumps({k: v for k, v in out.items() if v not in (None, "")}, ensure_ascii=False)


def verify(facts: ProfileFacts, audit: GroundingAudit, answers: Any, company: Optional[str] = None) -> str:
    if isinstance(answers, str):
        try:
            answers = json.loads(answers)
        except ValueError:
            return "Could not read the list. Send a JSON list of {question, answer} items."
    if not isinstance(answers, list):
        return "Send a JSON list of {question, answer} items."
    audit.verified = True
    problems = facts.check([a for a in answers if isinstance(a, dict)], company)
    for p in problems:
        if p not in audit.ungrounded:
            audit.ungrounded.append(p)
    if not problems:
        return "OK: every answer traces to the user's profile."
    return "NOT OK. Fix or clear these before submitting: " + json.dumps(problems, ensure_ascii=False)


def build_tools(facts: ProfileFacts, audit: GroundingAudit, company: Optional[str] = None) -> Optional[Any]:
    """A browser-use Tools registry with the two actions, or None if this browser-use version has no custom tools."""
    try:
        from browser_use import ActionResult, Tools
    except Exception:
        try:
            from browser_use import ActionResult, Controller as Tools  # type: ignore
        except Exception:
            return None
    tools = Tools()

    @tools.action("Look up the answer to ONE form question in the candidate's own profile. Use before typing any answer. Returns the answer, "
                  "or says there is no data (then type nothing). Pass the visible options for dropdowns/radios.")
    async def profile_answer(question: str, options: Optional[List[str]] = None):
        return ActionResult(extracted_content=lookup(facts, audit, question, options, company))

    @tools.action("Before the final submit, check everything you typed. Pass a JSON list like [{\"question\": \"...\", \"answer\": \"...\"}]. "
                  "Fix every problem it reports before submitting.")
    async def verify_answers(answers: str):
        return ActionResult(extracted_content=verify(facts, audit, answers, company))

    return tools
