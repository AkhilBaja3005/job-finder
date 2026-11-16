"""
cover_letter_generator.py: tailored, evidence-based cover letters.

Safeguards:
- Only an allowlist of non-sensitive profile fields is sent to the LLM (never contact
  details, passwords, tokens or API keys).
- The draft is validated (length, banned phrases, dashes, placeholders, unsupported numbers)
  and regenerated once with the findings fed back to the model.
- If the model is unavailable, a factual template built only from profile fields is returned
  with status "fallback". It never claims experience the profile does not contain.
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional

try:
    from services.gemini_client import generate_content_with_fallback
except ImportError:
    from backend.services.gemini_client import generate_content_with_fallback

logger = logging.getLogger(__name__)

MIN_WORDS = 200
MAX_WORDS = 380
JD_CHAR_LIMIT = 6000

BANNED_PHRASES = (
    "i am writing to apply", "i am writing to express", "passionate about", "team player",
    "hard worker", "go-getter", "think outside the box", "results-driven", "dynamic environment",
    "perfect fit", "i believe i would be", "synergy",
)

# Profile fields that are safe and useful for writing a letter.
_TOP_LEVEL_FIELDS = (
    "name", "location", "notice_period", "work_authorization", "requires_sponsorship",
    "experience_summary", "summary", "core_skills", "skills", "certifications", "achievements",
    "languages",
)
_EXPERIENCE_FIELDS = ("company", "role", "title", "start_date", "end_date", "location", "description", "achievements")
_EDUCATION_FIELDS = ("institution", "school", "degree", "field", "start_date", "end_date", "grade")
_PROJECT_FIELDS = ("name", "title", "description", "technologies", "tech", "impact", "highlights")


def _pick(source: Dict[str, Any], keys) -> Dict[str, Any]:
    return {k: source[k] for k in keys if k in source and source[k] not in (None, "", [], {})}


def build_safe_profile(candidate_profile: Dict[str, Any]) -> Dict[str, Any]:
    """Return only the allowlisted, non-sensitive parts of a candidate profile."""
    cand = candidate_profile.get("candidate", candidate_profile) if isinstance(candidate_profile, dict) else {}
    safe = _pick(cand, _TOP_LEVEL_FIELDS)
    for key, fields in (
        ("work_experience", _EXPERIENCE_FIELDS), ("experience", _EXPERIENCE_FIELDS),
        ("education", _EDUCATION_FIELDS), ("projects", _PROJECT_FIELDS),
    ):
        items = cand.get(key)
        if isinstance(items, list):
            safe[key] = [_pick(i, fields) if isinstance(i, dict) else i for i in items]
    return safe


COVER_LETTER_AGENT_PROMPT = """ROLE
You are a cover letter agent. You write tailored, specific, concise cover letters.
Every claim must come from the CANDIDATE PROFILE or the JOB INPUT. Never invent facts,
employers, numbers, tools or outcomes. If evidence for a requirement is missing, do not claim it.

<job_description>
Title: {job_title}
Company: {company}
Description:
{job_description}
</job_description>

<company_context>
{company_context}
</company_context>

<candidate_profile>
{candidate_profile}
</candidate_profile>

<constraints>
- Length: 250-350 words, 3-4 short paragraphs
- Tone: professional, direct, technical
- Address to: Hiring Team
- Practical details to mention if relevant: {practical_details}
- Lead with results, not duties. Active voice, short sentences.
- Do not use cliches such as "passionate", "team player", "I am writing to apply".
- Do not use em dashes or double hyphens. Use commas or full stops.
- Use only numbers that appear in the candidate profile or the job description.
</constraints>
{feedback}
Plan silently: pick the 2 strongest pieces of evidence for the top requirements, then write.
Run a swap test: the letter must not work for another company with only the name changed.

OUTPUT FORMAT (exactly these headings, nothing before the first heading):
### Cover Letter
(the final letter, ready to send)

### Gaps
(one short bullet per requirement with no evidence in the profile, or "None")

### Alternative Opening Lines
(two alternative opening sentences from different angles)
"""


def _words(text: str) -> int:
    return len(re.findall(r"\b[\w'’-]+\b", text))


def _numbers(text: str) -> set:
    return set(re.findall(r"\d[\d,.]*%?", text))


def validate_letter(letter: str, profile_text: str, job_text: str = "") -> List[str]:
    """Return a list of human-readable problems; empty means the letter passes."""
    issues: List[str] = []
    count = _words(letter)
    if count < MIN_WORDS:
        issues.append(f"Too short ({count} words); aim for 250-350.")
    elif count > MAX_WORDS:
        issues.append(f"Too long ({count} words); aim for 250-350.")

    lowered = letter.lower()
    for phrase in BANNED_PHRASES:
        if phrase in lowered:
            issues.append(f"Contains cliche '{phrase}'.")

    if "—" in letter or "–" in letter or "--" in letter:
        issues.append("Contains dashes used as sentence breaks; use commas or full stops.")
    if re.search(r"\[[^\]]+\]|\{[^}]+\}|<[^>]+>", letter):
        issues.append("Contains an unfilled placeholder.")

    allowed = _numbers(profile_text) | _numbers(job_text)
    unsupported = sorted(n for n in _numbers(letter) if len(n.strip(".,")) >= 2 and n not in allowed)
    if unsupported:
        issues.append("Numbers not found in the profile or job description: " + ", ".join(unsupported[:5]) + ".")
    return issues


_HEADING_RE = re.compile(r"^#{1,4}\s*(?:\d+\.\s*)?(cover letter|gaps(?: & highlights)?|alternative opening lines|role analysis)\s*:?\s*$",
                         re.IGNORECASE | re.MULTILINE)


def parse_sections(output: str) -> Dict[str, str]:
    """Split model output by headings; tolerate numbering, case and missing sections."""
    sections: Dict[str, str] = {}
    matches = list(_HEADING_RE.finditer(output))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(output)
        sections[m.group(1).lower().split(" &")[0]] = output[m.end():end].strip()
    if "cover letter" not in sections:
        # No recognizable heading: drop any markdown heading lines and treat the rest as the letter
        body = "\n".join(l for l in output.splitlines() if not l.lstrip().startswith("#")).strip()
        sections["cover letter"] = body
    return sections


def _fallback_letter(job_title: str, company: str, cand: Dict[str, Any]) -> str:
    """Factual template built only from profile fields. Intentionally plain."""
    name = cand.get("name") or "Candidate"
    skills = cand.get("core_skills") or cand.get("skills") or []
    if isinstance(skills, dict):
        skills = list(skills.keys())
    skill_text = ", ".join(str(s) for s in list(skills)[:5])
    summary = (cand.get("experience_summary") or cand.get("summary") or "").strip()
    lines = [f"Dear Hiring Team at {company},", "", f"I am applying for the {job_title} role."]
    if summary:
        lines += ["", summary]
    if skill_text:
        lines += ["", f"My core skills include {skill_text}."]
    if cand.get("location"):
        lines += ["", f"I am based in {cand['location']}."]
    lines += ["", f"I would welcome a conversation about how I can contribute to {company}.", "", "Sincerely,", name]
    return "\n".join(lines)


def generate_structured_cover_letter(
    job_title: str,
    company: str,
    job_description: str,
    candidate_profile: Dict[str, Any],
    company_context: Optional[str] = None,
    custom_api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Returns {status, cover_letter, alternative_openings, gaps, warnings, full_output}.
    status: "success" (validated), "needs_review" (generated but validation findings remain),
            "fallback" (LLM unavailable; plain factual template, review before sending).
    """
    cand = candidate_profile.get("candidate", candidate_profile) if isinstance(candidate_profile, dict) else {}
    safe_profile = build_safe_profile(candidate_profile)
    profile_text = json.dumps(safe_profile, indent=2, default=str)

    spons = "requires UK Skilled Worker sponsorship" if cand.get("requires_sponsorship") else "authorized to work in the UK"
    practical = f"Location: {cand.get('location', 'not stated')}; work authorization: {spons}; availability: {cand.get('notice_period', 'not stated')}"
    jd = (job_description or "Job details not provided")[:JD_CHAR_LIMIT]
    job_title = job_title or "Target Role"
    company = company or "Target Company"

    def build_prompt(feedback: str = "") -> str:
        return COVER_LETTER_AGENT_PROMPT.format(
            job_title=job_title, company=company, job_description=jd,
            company_context=company_context or f"Target employer: {company}",
            candidate_profile=profile_text, practical_details=practical,
            feedback=f"\nFIX THESE PROBLEMS FROM YOUR PREVIOUS DRAFT:\n{feedback}\n" if feedback else "",
        )

    try:
        output = generate_content_with_fallback(build_prompt(), custom_api_key=custom_api_key, model_tier="strong").strip()
        sections = parse_sections(output)
        issues = validate_letter(sections["cover letter"], profile_text, jd)
        if issues:
            logger.info("[cover-letter] Draft failed validation, retrying: %s", issues)
            retry = generate_content_with_fallback(
                build_prompt("\n".join(f"- {i}" for i in issues)), custom_api_key=custom_api_key, model_tier="strong"
            ).strip()
            retry_sections = parse_sections(retry)
            retry_issues = validate_letter(retry_sections["cover letter"], profile_text, jd)
            if len(retry_issues) <= len(issues):
                output, sections, issues = retry, retry_sections, retry_issues
        return {
            "status": "success" if not issues else "needs_review",
            "full_output": output,
            "cover_letter": sections["cover letter"],
            "gaps": sections.get("gaps", ""),
            "alternative_openings": sections.get("alternative opening lines", ""),
            "role_analysis": sections.get("role analysis", ""),
            "warnings": issues,
        }
    except Exception as e:
        logger.error("[cover-letter] Generation failed: %s", e)
        letter = _fallback_letter(job_title, company, cand)
        return {
            "status": "fallback",
            "full_output": letter,
            "cover_letter": letter,
            "gaps": "",
            "alternative_openings": "",
            "role_analysis": "",
            "warnings": [f"LLM unavailable ({type(e).__name__}); plain template from your profile. Review before sending."],
        }
