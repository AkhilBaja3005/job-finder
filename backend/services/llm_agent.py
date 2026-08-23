from asyncio import base_events
import os
import json
import re
# pyrefly: ignore [missing-import]
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Callable, Any

from services.gemini_client import generate_content_with_fallback, generate_latex_with_strong_model
from services.ats_scorer import compute_ats_score, compute_overall_score, calculate_flattened_experience

# ─────────────────────────────────────────
# Pydantic schemas
# ─────────────────────────────────────────

class MatchScoreDetails(BaseModel):
    # Deterministic scores (reproducible, not LLM-generated)
    overall_score: int = Field(description="Weighted overall ATS score: 40% skills + 35% experience + 25% role_fit")
    skills_score: int  = Field(description="Keyword match score (deterministic): required skills found in resume")
    experience_score: int = Field(description="Years of experience match score (deterministic)")
    # LLM-derived score
    role_fit_score: int = Field(description="Semantic role fit score (LLM): domain, seniority, industry alignment")
    # Skill lists (deterministic)
    matched_skills: List[str] = Field(description="Skills found in both resume and JD")
    missing_skills: List[str] = Field(description="Required JD skills absent from resume")
    # Qualitative (LLM)
    tailoring_suggestions: List[str] = Field(description="Actionable suggestions to improve match")
    # Metadata
    score_breakdown: Dict[str, Any] = Field(default_factory=dict, description="Human-readable detail per dimension")
    keyword_stats: Dict[str, str] = Field(default_factory=dict, description="Keyword match counts and year stats")

class SectionUpdate(BaseModel):
    summary: Optional[str] = Field(default=None, description="Tailored professional summary")
    skills: Optional[List[str]] = Field(default=None, description="Updated skills list")
    experience: Optional[List[List[str]]] = Field(default=None, description="List of bullet lists per job (same order as resume)")
    projects: Optional[List[List[str]]] = Field(default=None, description="List of bullet lists per project")

class AnalysisResponse(BaseModel):
    match_analysis: MatchScoreDetails
    suggested_resume_updates: SectionUpdate = Field(
        description="Tailored suggestions per section"
    )
    cover_letter: str = Field(description="A highly tailored cover letter under 300 words")
    latex_code: str = Field(default="", description="LaTeX code placeholder (compiled in Step 2)")

class ResumeReviewResult(BaseModel):
    ats_fit_ok: bool = Field(description="True if top JD keywords are naturally integrated into experience/skill bullets.")
    impact_metrics_ok: bool = Field(description="True if the majority of bullets contain at least one quantified result (%, numbers, scale).")
    truthfulness_ok: bool = Field(description="True if tailored content stays strictly within the candidate's real background — no fabricated companies, degrees, or exaggerated experience.")
    conciseness_ok: bool = Field(description="True if bullets are tight (1-1.5 lines), with no sprawling multi-line sentences.")
    feedback: str = Field(description="Specific, actionable recruiter feedback on exactly what to fix for any failing criterion.")

    @property
    def satisfied(self) -> bool:
        """Derived from the four rubric booleans rather than trusting a separate
        LLM-emitted 'satisfied' flag directly — removes a class of
        self-contradictory outputs where the model says satisfied=true while
        also failing one of the rubric items in its own feedback text."""
        return self.ats_fit_ok and self.impact_metrics_ok and self.truthfulness_ok and self.conciseness_ok


# ─────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────

def _strip_latex_commands(text: str) -> str:
    """Remove LaTeX markup so we can do plain-text substring searches."""
    text = re.sub(r'\\[a-zA-Z]+\{([^}]*)\}', r'\1', text)   # \cmd{content} → content
    text = re.sub(r'\\[a-zA-Z]+', '', text)                   # bare commands like \hfill
    text = re.sub(r'[{}\[\]]', '', text)                       # strip braces
    return text

def _truncate_jd(jd: str, max_chars: int = 3000) -> str:
    """
    Truncate and clean job description using oc-style distillation rules
    to avoid ballooning prompt tokens from scraped boilerplate.
    """
    if not jd:
        return ""
    # Strip common boilerplate tracking strings, cookie notices, and excessive whitespace
    cleaned = re.sub(r'data:image/[^;]+;base64,[A-Za-z0-9+/=]+', '', jd)
    cleaned = re.sub(r'(?:Cookie Policy|Privacy Notice|Manage Preferences|Terms and Conditions|All rights reserved).*$', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned).strip()
    return cleaned[:max_chars] if len(cleaned) > max_chars else cleaned

def _parse_llm_json(raw_text: str, label: str = "LLM JSON") -> dict:
    """
    Parses JSON out of an LLM response defensively.

    Native Gemini enforces response_mime_type=application/json, so its output
    is already clean. But this pipeline's fallback chain can also land on
    Cloudflare/Groq/OpenRouter, which are only *prompted* to return raw JSON —
    they can still wrap the payload in ```json fences, add a stray preamble
    line, or trail extra commentary despite instructions. Strip fences and,
    if that's not enough, fall back to extracting the outermost {...} block
    before parsing, so a well-formed-but-wrapped response doesn't blow up
    with a JSONDecodeError.
    """
    text = raw_text.strip()
    if text.startswith("```"):
        text = re.sub(r'^```(?:json)?\s*', '', text)
        text = re.sub(r'\s*```$', '', text)
        text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Fall back to grabbing the outermost JSON object if there's
        # leading/trailing prose around it.
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if not match:
            raise ValueError(f"{label}: could not locate a JSON object in the response: {text[:300]}")
        return json.loads(match.group(0))

def _sanitize_suggestions(suggestions) -> dict:
    """
    Escape LaTeX-unsafe characters in LLM-generated suggestion strings.
    Accepts either a SectionUpdate object or a plain dict.
    """
    if hasattr(suggestions, 'model_dump'):
        suggestions = suggestions.model_dump(exclude_none=True)
    LATEX_ESCAPES = {
        '&': r'\&',
        '%': r'\%',
        '$': r'\$',
        '#': r'\#',
        '^': r'\^{}',
        '~': r'\textasciitilde{}',
    }
    def _escape(val):
        if isinstance(val, str):
            for ch, esc in LATEX_ESCAPES.items():
                val = re.sub(r'(?<!\\)' + re.escape(ch), esc, val)
            return val
        elif isinstance(val, list):
            return [_escape(v) for v in val]
        elif isinstance(val, dict):
            return {k: _escape(v) for k, v in val.items()}
        return val
    if isinstance(suggestions, dict):
        return {k: _escape(v) for k, v in suggestions.items()}
    elif isinstance(suggestions, list):
        return [_escape(v) for v in suggestions]
    return _escape(suggestions)

def _validate_latex_output(latex: str, label: str = "tailor") -> str:
    """
    Raise ValueError early if the LLM returned empty or obviously broken LaTeX,
    so the caller can retry rather than silently compiling garbage.
    """
    stripped = latex.strip()
    if not stripped:
        raise ValueError(f"{label}: LLM returned an empty response.")
    if "\\documentclass" not in stripped:
        raise ValueError(f"{label}: LLM response is missing \\documentclass — not valid LaTeX.")
    if "\\begin{document}" not in stripped:
        raise ValueError(f"{label}: LLM response is missing \\begin{{document}}.")
    return stripped


# ─────────────────────────────────────────
# Core agent functions
# ─────────────────────────────────────────

def tailor_latex_code(
    master_latex: str,
    job_title: str,
    job_description: str,
    suggestions,          # SectionUpdate or dict
    missing_skills: List[str],
    custom_api_key: Optional[str] = None,
    reviewer_feedback: Optional[str] = None,
    on_log: Optional[Callable[[str], None]] = None,
) -> str:
    """
    Step 2: Directly tailors the master LaTeX code for a target job.
    Uses a stronger model for LaTeX generation to reduce structure corruption.
    Validates output before returning.
    """
    jd_truncated = _truncate_jd(job_description)
    safe_suggestions = _sanitize_suggestions(suggestions)
    feedback_str = (
        f"\n⚠️  CRITICAL REVIEWER FEEDBACK — You MUST fix EVERY point listed below before returning:\n{reviewer_feedback}\n"
        if reviewer_feedback else ""
    )

    prompt = f"""You are an expert LaTeX CV typesetter and ATS optimizer.
Take the candidate's MASTER LaTeX resume code below and tailor it for the target job: "{job_title}".
{feedback_str}
TARGET JOB DESCRIPTION (excerpt):
---
{jd_truncated}
---

ATS KEYWORDS TO INTEGRATE (weave naturally — do NOT copy-paste verbatim from JD):
{", ".join(missing_skills)}

TAILORED CONTENT SUGGESTIONS (use these as guides, not verbatim copy):
{json.dumps(safe_suggestions, indent=2)}

════════════════════════════════════════════
CRITICAL RULES — READ EVERY RULE BEFORE WRITING:
════════════════════════════════════════════

RULE 1 — CONTACT HEADER (ABSOLUTE ZERO TOLERANCE):
  • Copy \\name{{...}} and \\address{{...}} character-for-character from master. NEVER rewrite them.
  • Do NOT change the name, email, phone, or LinkedIn URL.

RULE 2 — GPA / CPI / GRADES & EDUCATION HIGHLIGHTS (ZERO TOLERANCE):
  • Find every line in the master Education section that contains a numeric grade, CPI, GPA, or percentage (e.g. "CPI: 8.04", "94.2\\%").
  • Copy those values exactly into the tailored Education section on the SAME line as the degree, right-aligned with \\hfill.
  • Example: {{\\textit{{B.Tech in Engineering Science}}}} \\hfill {{\\em CPI: 8.04}} \\\\
  • EDUCATION LEADERSHIP & HIGHLIGHTS: Any leadership line under an education entry (e.g., "\\textit{{\\textbf{{Internship and Placement Cell Coordinator}} — Managed corporate outreach...}}") MUST be kept directly inside the Education section under that degree. Do NOT move it to Achievements or drop it.

RULE 3 — SECTION & CONTENT COMPLETENESS & FACTUAL PRESERVATION (ZERO TOLERANCE):
  • Preserve EVERY school, job, and project. Do NOT delete, rename, or merge any.
  • PRESERVE ORIGINAL FACTUAL ACCOMPLISHMENTS & METRICS: 
    - The candidate's original work experience bullets contain real quantified achievements and proprietary metrics (e.g. AST-based dependency extraction across Java/Python/C++, 46% accuracy boost, RabbitMQ async queues, 84% deployment failure cut, Isolation Forest £30M+ portfolio loss exposure, Dynamic Risk Rating).
    - NEVER replace these specific technical achievements with vague generic summaries (e.g., do NOT turn "Isolation Forest anomaly detection model for Gold Loans flagging branch-level risk £30M+" into generic "Built anomaly detection models").
    - Tailoring means emphasizing relevant technologies and naturally aligning terminology to the target role while KEEPING the specific facts, metrics, awards, and technical depths intact!
  • ABSOLUTE CRITICAL FOR SUB-PROJECTS (e.g. Quartz, DMAP, Argus): When a company experience entry has sub-projects/modules (e.g. "Quartz (Context-as-a-Service & LLM Engineering):"), NEVER duplicate the parent title on multiple \\item bullets!
  • You MUST render sub-projects using a nested itemize structure with dot bullets (e.g. \\begin{{itemize}}[label=\\textbullet]):
    \\item \\textbf{{Quartz (Context-as-a-Service \\& LLM Engineering):}}
    \\begin{{itemize}}
        \\item Developed a cross-language dependency extraction tool...
        \\item Orchestrated the integration of Jedi, ccls, and Doxygen...
    \\end{{itemize}}
  • NEVER output repeated standalone \\item bullets with duplicate sub-project title prefixes.

RULE 4 — ONE-PAGE BUDGET, BOLDING & STUDENT/DEGREE TIMELINE ACCURACY (CRITICAL):
  • STUDENT / DEGREE TIMELINE STATUS (ABSOLUTE TRUTHFULNESS):
    - Check the candidate's Education timeline:
      * Ongoing / Future Education (e.g. "Sept 2026 – Sept 2027" or "Oct 2024 – Present"): The candidate is currently a **Student / MSc Candidate / Postgraduate Scholar**.
      * In the Professional Summary, NEVER write "Holds an MSc" or "Graduated with an MSc".
      * ALWAYS phrase ongoing degrees as: "MSc Candidate in Artificial Intelligence at Imperial College London" or "Postgraduate Researcher in AI at Imperial College London".
      * Completed Past Education (e.g. "Aug 2019 – May 2023"): Use "B.Tech graduate from IIT Hyderabad" or "B.Tech in Engineering Science from IIT Hyderabad".
  • Professional Summary MUST be placed at the top (below header), kept to 2-3 lines visually, reflecting their exact student/graduate standing, actual professional years, and targeted domain skills.
  • BOLDING RULES: You MUST automatically bold key technical models/frameworks, metrics (e.g. `\\textbf{{40\\%}}`, `\\textbf{{60\\%}}`, `\\textbf{{£30M+}}`), awards (e.g. `\\textbf{{[BIU Star Award]}}`), and key institutions explicitly present in the candidate's text.
  • The entire tailored resume MUST fit on exactly ONE page.
  • Write concise bullets using the Playbook formula: Action + Technology + Problem + Measurable Metric. Each bullet MUST occupy between 70% and 150% of one line.
  • Do NOT add extra \\vspace or \\newline commands.

RULE 5 — LATEX PREAMBLE, FONT & SECTION PATTERN (ZERO DEVIATION):
  • PREAMBLE LOCK: You MUST preserve the exact preamble, document class `\\documentclass[12pt]{{resume}}`, packages (`\\usepackage[T1]{{fontenc}}`, `\\usepackage[left=0.35in,top=0.25in,right=0.35in,bottom=0.22in]{{geometry}}`, `\\usepackage{{fontawesome}}`, `\\usepackage{{times}}`, `\\usepackage{{hyperref}}`), and the custom macro `\\newcommand\\mybar{{\\kern1pt\\rule[-\\dp\\strutbox]{{.8pt}}{{\\baselineskip}}\\kern1pt}}`.
  • FONT: Use ONLY `times` font package as defined in master. Do NOT change, replace, or add other font packages (helvet, lmodern, etc.).
  • BULLET SYMBOLS & SPACING: Preamble MUST include `\\renewcommand{{\\labelitemi}}{{$\\\\bullet$}}` and `\\renewcommand{{\\labelitemii}}{{$\\\\bullet$}}`. Use `\\setlength{{\\itemsep}}{{-0.20em}}` and `\\setlength{{\\parsep}}{{0em}}` inside `itemize` blocks.
  • TECHNICAL SKILLS (MANDATORY, PRESERVE MASTER CATEGORIZATION & ZERO OVERLAP): You MUST include `\\begin{{rSection}}{{Technical Skills}}`.
    - If the master resume already has categorized skills (e.g. `\\textbf{{Languages:}}`, `\\textbf{{AI/ML & GenAI:}}`, `\\textbf{{Data & Platforms:}}`, `\\textbf{{Software & Infrastructure:}}`), PRESERVE THOSE EXACT CATEGORY NAMES and original skills from the master resume. Do NOT re-categorize, drop, or scramble the master categories!
    - Group Technical Skills into distinct, non-overlapping categories where every skill exists in EXACTLY ONE category. Format each category line as `\\textbf{{Category:}} skill1, skill2 \\\\`. Do NOT use `\\begin{{tabular}}` or `\\end{{tabular}}` environments. Omitting the Technical Skills section is an INSTANT FAILURE.
  • ABSOLUTE CRITICAL SECTION SEQUENCE: You MUST render sections in this exact order:
    1. Professional Summary (`\\begin{{rSection}}{{Professional Summary}}`)
    2. Work Experience (`\\begin{{rSection}}{{Work Experience}}`)
    3. Technical Skills (`\\begin{{rSection}}{{Technical Skills}}`)
    4. Education (`\\begin{{rSection}}{{Education}}`)
    5. Projects (`\\begin{{rSection}}{{Projects}}`)
  • NEVER omit Technical Skills or alter this section sequence under any circumstances.

RULE 6 — ATS KEYWORD INTEGRATION & INLINE AWARDS:
  • Inject relevant missing keywords into Technical Skills and bullets naturally ONLY IF they match or extend the candidate's actual experience.
  • INLINE AWARDS (NO SEPARATE ACHIEVEMENTS SECTION): Keep awards inline inside Work Experience bullets. NEVER create a separate `Achievements & Leadership` section!
  • Bold key metrics AND important tool names using \\textbf{{}} — e.g. \\textbf{{50\\%}}, \\textbf{{3x}}. Apply \\textbf to at least 2 items per bullet section.
  • ABSOLUTE CRITICAL: NEVER use markdown asterisks for bold (**word** or __word__). You MUST use ONLY LaTeX \\textbf{{word}}. If you write ** anywhere in the output it will BREAK the PDF compilation.
  • Translate JD phrases into natural accomplishments — NEVER copy-paste verbatim.

RULE 7 — OUTPUT FORMAT:
  • Return ONLY the raw LaTeX source. No markdown fences, no explanations, no commentary.

RULE 8 — TRUTHFULNESS & CREDENTIALS (ABSOLUTE TRUST & ZERO FABRICATION):
  • NEVER fabricate security clearances, specialized government clearances, certifications, technologies, languages, or frameworks (e.g. PyTorch, RAG, R, C) unless they are explicitly present in the original master resume.
  • Keep years of experience accurate and consistent with the candidate's actual timeline history. Never exaggerate the candidate's total years of experience in summaries.
  • Do NOT invent expert proficiency in major frameworks, libraries, tools, or compliance/regulatory standards if they are completely absent from the master profile. Focus on highlighting real transferable skills and conceptual alignment instead.

RULE 9 — EMPLOYMENT DATES LOCK (ZERO TOLERANCE):
  • You MUST copy all employment start and end dates (e.g., June 2023 - Present) character-for-character from the master resume.
  • You are strictly prohibited from modifying, shifting, or creating new dates for any job or education entry. Dates are historical facts and must remain unchanged.

MASTER LaTeX (source of truth):
---
{master_latex}
---
"""

    max_retries = 2
    last_err = None
    for attempt in range(max_retries):
        try:
            raw = generate_latex_with_strong_model(prompt, custom_api_key, on_log=on_log)
            # Sanitize markdown bold that the LLM sometimes emits despite the rule
            import re as _re
            raw = _re.sub(r'\*\*(.+?)\*\*', r'\\textbf{\1}', raw)
            raw = _re.sub(r'__(.+?)__', r'\\textbf{\1}', raw)
            # Ensure any unbolded key metrics (percentages, numbers like 50%, 10x, $2M) get bolded automatically
            raw = _re.sub(r'(?<!\\textbf\{)(?<![\w\\])(\d+%\+|\d+%\b|\$\d+[\d\.]*[MBK]?\b|\d+x\b)', r'\\textbf{\1}', raw)
            return _validate_latex_output(raw, label=f"tailor attempt {attempt+1}")
        except ValueError as e:
            last_err = e
            print(f"[tailor_latex_code] Attempt {attempt+1} produced invalid output: {e}")
            continue

    # If both attempts fail, return master as safe fallback
    print(f"[tailor_latex_code] All retries failed. Returning master as fallback. Last error: {last_err}")
    return master_latex


# ── LLM-only schema for the semantic part of scoring ─────────────────────────
class _SemanticScoreResult(BaseModel):
    role_fit_score: int = Field(
        description="0-100: How well does the candidate's domain, seniority, and industry background "
                    "semantically match the target role? 100=perfect match, 0=completely wrong domain."
    )
    tailoring_suggestions: List[str] = Field(
        description="3-5 specific, actionable suggestions to better tailor the resume for this role."
    )

class _CoverLetterResult(BaseModel):
    cover_letter: str = Field(description="A highly tailored cover letter under 300 words")
    suggested_resume_updates: SectionUpdate = Field(description="Tailored suggestions per section")


async def analyze_job_fit(
    resume_data: dict,
    job_title: str,
    job_description: str,
    master_latex: Optional[str] = None,
    recruiter_name: Optional[str] = None,
    custom_api_key: Optional[str] = None,
    on_log: Optional[Callable[[str], None]] = None,
    user_selected_skills: Optional[List[str]] = None,
) -> AnalysisResponse:
    """
    Hybrid ATS scoring pipeline:
      Phase 1 (deterministic) → skills_score, experience_score, matched_skills, missing_skills
      Phase 2 & 3 (LLM Parallel) → role_fit_score, tailoring_suggestions, cover_letter, SectionUpdate
      Phase 4 (formula)       → overall_score = 0.40×skills + 0.35×experience + 0.25×role_fit
      Phase 5 (LLM)           → LaTeX tailoring
    """
    jd_truncated = _truncate_jd(job_description)

    # ── Phase 1: Deterministic ATS scoring ──────────────────────────────────
    # If user selected added skills, incorporate them into a copy of resume_data so score reflects tailored profile
    scoring_resume_data = resume_data
    if user_selected_skills and len(user_selected_skills) > 0:
        import copy
        scoring_resume_data = copy.deepcopy(resume_data)
        raw_s = scoring_resume_data.get("skills", [])
        if isinstance(raw_s, dict):
            # Add to first list or dedicated list
            for cat, items in raw_s.items():
                if isinstance(items, list):
                    items.extend([s for s in user_selected_skills if s not in items])
                    break
        elif isinstance(raw_s, list):
            raw_s.extend([s for s in user_selected_skills if s not in raw_s])
            scoring_resume_data["skills"] = raw_s

    ats = compute_ats_score(scoring_resume_data, jd_truncated)

    # Use getattr to prevent crashes if fields are missing from ATSScoreResult
    matched_count = getattr(ats, "matched_required_count", 0)
    total_count   = getattr(ats, "total_required_count", 0)
    cand_years    = getattr(ats, "candidate_years", 0)
    req_years     = getattr(ats, "required_years", "not specified")

    print(f"[ATS] skills={ats.skills_score} exp={ats.experience_score} "
        f"matched={matched_count}/{total_count} "
        f"years={cand_years}/{req_years}")

    # Prepare inputs for semantic scoring & cover letter
    experience_list = resume_data.get("experience", [])
    current_role = ""
    if experience_list and isinstance(experience_list[0], dict):
        current_role = experience_list[0].get("role", "")

    lean_resume = {
        "name":       resume_data.get("name", ""),
        "current_role": current_role,
        "total_experience_years": ats.candidate_years,
        "skills":     resume_data.get("skills", []),
        "recent_companies": [e.get("company", "") for e in experience_list if isinstance(e, dict)][:3],
        "education":  [{"institution": e.get("institution", ""), "degree": e.get("degree", "")} for e in resume_data.get("education", []) if isinstance(e, dict)],
        "projects":   [{"title": p.get("title", "")} for p in resume_data.get("projects", []) if isinstance(p, dict)],
    }

    semantic_prompt = f"""You are a senior technical recruiter.
Evaluate how well this candidate's background semantically fits the target role.

CANDIDATE SNAPSHOT:
{json.dumps(lean_resume, indent=2)}

TARGET ROLE: {job_title}
JOB DESCRIPTION (excerpt):
---
{jd_truncated}
---

NOTE: Keyword/skill matching and years-of-experience scoring are already done separately.
Focus ONLY on:
  1. role_fit_score (0-100): Domain alignment, seniority level match, industry fit.
     - 90-100: Same domain, same level, same industry
     - 70-89:  Adjacent domain or slightly different level
     - 50-69:  Transferable skills but domain mismatch
     - 30-49:  Significant domain/seniority gap
     - 0-29:   Wrong domain entirely
  2. tailoring_suggestions: 3-5 specific resume improvements for this role.
"""

    bullet_counts = {
        e.get("company", f"job_{i}"): len(e.get("description", []))
        for i, e in enumerate(resume_data.get("experience", []))
    }
    project_bullet_counts = {
        p.get("title", f"project_{i}"): len(p.get("description", []))
        for i, p in enumerate(resume_data.get("projects", []))
    }
    missing_skills_list = getattr(ats, "missing_skills", []) or []
    cover_prompt = f"""You are an expert career writer.
Write a tailored cover letter and resume section updates for this candidate.

CANDIDATE: {json.dumps(lean_resume, indent=2)}
TARGET ROLE: {job_title}
RECRUITER/HIRING MANAGER NAME: {recruiter_name or 'Not specified'}
MISSING SKILLS TO ADDRESS: {', '.join(missing_skills_list[:8])}
JD EXCERPT: {jd_truncated[:1200]}

RULES:
- Cover letter: under 300 words, specific to this JD.
- SALUTATION: If RECRUITER/HIRING MANAGER NAME is provided and valid (e.g. "John Doe"), start the cover letter addressing them directly (e.g. "Dear John Doe," or "Dear Mr./Ms. Doe,"). If not specified or unknown, default to "Dear Hiring Manager,".
- WRITING STYLE CONSTRAINTS:
  1. STRICTLY NO EM-DASHES (--) OR HYPHENS AS SENTENCE BREAKS. Use commas, periods, or split sentences.
  2. STRICTLY NO CLICHES or generic filler phrases. Cut statements like: "I am passionate about", "I believe I would be a great fit", "leverage my skills", "hit the ground running", "drive results", or "synergies".
  3. NO apologetic/passive phrases. Be confident, warm, and direct. Use first-person active voice ("I built", "I managed").
  4. FORWARD-LOOKING FRAMING: Focus on task-solving — what problems/tasks you can solve for the employer and how, rather than repeating CV details.
- suggested_resume_updates.experience: MUST have bullet lists matching these counts: {json.dumps(bullet_counts)}
  Do NOT merge, delete, or add bullets.
- suggested_resume_updates.projects: MUST have bullet lists matching these counts: {json.dumps(project_bullet_counts)}
  Do NOT merge, delete, or add bullets. Only include this field if the candidate has projects.
- TRUTHFULNESS: Never claim security clearances, certifications, or specialized regulatory compliance standards if the candidate does not possess them in their profile. Emphasize transferable skills honestly. Never exaggerate the candidate's total years of experience history in the summary or cover letter.
- suggested_resume_updates.skills: Updated skills list naturally integrating missing skills (only include adjacent skills that are reasonable extensions of their background, do not fabricate unrelated expert skills).
"""

    # ── Phase 2 & 3: Run LLM calls in parallel threads ─────────────────────
    import asyncio

    # We use asyncio.to_thread to run synchronous blocking Gemini API calls concurrently
    semantic_task = asyncio.to_thread(
        generate_content_with_fallback,
        semantic_prompt,
        _SemanticScoreResult,
        custom_api_key,
        on_log=on_log
    )
    cover_task = asyncio.to_thread(
        generate_content_with_fallback,
        cover_prompt,
        _CoverLetterResult,
        custom_api_key,
        on_log=on_log
    )

    semantic_text, cover_text = await asyncio.gather(semantic_task, cover_task)

    # NOTE: parsed defensively — see _parse_llm_json docstring. Non-Gemini
    # providers in the fallback chain (Cloudflare/Groq/OpenRouter) are only
    # prompted to emit raw JSON and can still wrap it in ```json fences.
    semantic = _SemanticScoreResult(**_parse_llm_json(semantic_text, label="semantic scoring"))
    role_fit = min(100, max(0, semantic.role_fit_score))
    cover_result = _CoverLetterResult(**_parse_llm_json(cover_text, label="cover letter"))

    # ── Phase 4: Compute overall score (formula, not hallucinated) ───────────
    overall = compute_overall_score(ats.skills_score, ats.experience_score, role_fit)

    # ── Phase 4: Compute overall score ───────────────────────────────────────
    keyword_stats = {
        "required_matched":  f"{getattr(ats, 'matched_required_count', 0)}/{getattr(ats, 'total_required_count', 0)}",
        "candidate_years":   str(getattr(ats, "candidate_years", 0)),
        "required_years":    str(getattr(ats, "required_years", "not specified")),
    }

    match_analysis = MatchScoreDetails(
        overall_score=overall,
        skills_score=ats.skills_score,
        experience_score=ats.experience_score,
        role_fit_score=role_fit,
        matched_skills=getattr(ats, "matched_skills", []), # Safe fallback to empty list
        missing_skills=getattr(ats, "missing_skills", []), # Safe fallback to empty list
        tailoring_suggestions=semantic.tailoring_suggestions,
        score_breakdown=ats.score_breakdown,
        keyword_stats=keyword_stats,
    )

    response_obj = AnalysisResponse(
        match_analysis=match_analysis,
        suggested_resume_updates=cover_result.suggested_resume_updates,
        cover_letter=cover_result.cover_letter,
        latex_code="",
    )

    # ── Phase 5: LaTeX tailoring ─────────────────────────────────────────────
    if master_latex:
        suggestions  = response_obj.suggested_resume_updates
        # Run LaTeX tailoring inside a background thread to prevent thread locking the event loop
        tailored_latex = await asyncio.to_thread(
            tailor_latex_code,
            master_latex, job_title, job_description, suggestions,
            ats.missing_skills, custom_api_key, on_log=on_log
        )
        response_obj.latex_code = tailored_latex
    return response_obj


# ─────────────────────────────────────────
# Deterministic + LLM review pipeline
# ─────────────────────────────────────────

def review_tailored_resume(
    tailored_latex: str,
    original_resume_data: dict,
    job_title: str,
    job_description: str,
    custom_api_key: Optional[str] = None,
    on_log: Optional[Callable[[str], None]] = None,
    user_selected_skills: Optional[List[str]] = None,
) -> ResumeReviewResult:
    """
    Two-phase review:
    Phase 1 — Deterministic structural checks (fast, reliable, no LLM hallucination).
    Phase 2 — LLM soft-quality check (only runs if Phase 1 passes).
    """
    issues = []
    plain_latex = _strip_latex_commands(tailored_latex)

    # ── Phase 1: Deterministic structural checks ──────────────────────────────

    education = original_resume_data.get("education", [])

    # 1a. CPI/GPA numeric values
    for edu in education:
        gpa_raw = edu.get("gpa") or edu.get("cpi") or ""
        if not gpa_raw:
            continue
        nums = re.findall(r'[\d]+\.[\d]+|[\d]{2,}', gpa_raw)
        for num in nums:
            # Check both raw LaTeX and stripped version (handles \textbf{8.04} etc.)
            if num not in tailored_latex and num not in plain_latex:
                issues.append(
                    f"CRITICAL: Grade/CPI value '{num}' (from {edu.get('institution', 'education')}) "
                    f"is MISSING from the tailored LaTeX Education section. "
                    f"Add it right-aligned: {{\\textit{{<degree>}}}} \\hfill {{\\em CPI: {num}}} \\\\"
                )

    # 1b. Percentage values (e.g. "94.2%" in gpa field)
    for edu in education:
        gpa_raw = edu.get("gpa") or ""
        pct_matches = re.findall(r'([\d\.]+)\s*%', gpa_raw)
        for pct in pct_matches:
            if pct not in plain_latex:
                issues.append(
                    f"CRITICAL: Percentage '{pct}%' from {edu.get('institution', 'education')} "
                    f"is MISSING from the tailored Education section."
                )

    # 1c. All schools present
    for edu in education:
        school = edu.get("institution", "").strip()
        if school and school not in plain_latex:
            issues.append(f"CRITICAL: School '{school}' is missing from the tailored LaTeX.")

    # 1d. All companies present
    for exp in original_resume_data.get("experience", []):
        company = exp.get("company", "").strip()
        if company and company not in plain_latex:
            issues.append(f"CRITICAL: Company '{company}' is missing from the tailored LaTeX.")

    # 1e. Projects — use longest unique keyword (3+ chars) from title for fuzzy match
    for proj in original_resume_data.get("projects", []):
        try:
            title = proj.get("title", "").strip() if proj else ""
            # Find a distinctive word (>4 chars, not a stopword) to search for
            stopwords = {'the', 'and', 'for', 'from', 'with', 'using', 'deep', 'data'}
            title_words = title.split() if title else []
            words = [w for w in title_words if len(w) > 4 and w.lower() not in stopwords]
            key = words[0] if words else (title_words[0] if title_words else "")
            if key and key not in plain_latex:
                issues.append(
                    f"Project '{title}' appears missing from the tailored LaTeX "
                    f"(searched for key term '{key}')."
                )
        except Exception as e:
            print(f"[Review] Error processing project: {e}")
            continue

    # 1f. Basic LaTeX structure check
    if "\\documentclass" not in tailored_latex:
        issues.append("CRITICAL: Tailored LaTeX is missing \\documentclass — completely broken output.")
    if "\\begin{document}" not in tailored_latex:
        issues.append("CRITICAL: Tailored LaTeX is missing \\begin{document}.")

    # If structural issues found → return immediately, no LLM needed
    if issues:
        return ResumeReviewResult(
            ats_fit_ok=False, impact_metrics_ok=False, truthfulness_ok=False, conciseness_ok=False,
            feedback="\n".join(issues)
        )

    # ── Phase 2: LLM soft-quality check ──────────────────────────────────────
    jd_excerpt = _truncate_jd(job_description, max_chars=1200)

    computed_years, avg_tenure, weighted_segments, _ = calculate_flattened_experience(original_resume_data)
    
    approved_user_skills_str = ", ".join(user_selected_skills) if user_selected_skills else "None"

    # Formulate a clean profile snapshot for validation. Include full
    # experience/project bullets (not just company+role) — the reviewer's
    # truthfulness check compares tailored content against this profile, and
    # if a skill/tool the candidate actually used only appears in their bullet
    # text (e.g. "Used Cloudera and Azure OpenAI for...") rather than in the
    # flat `skills` list, omitting bullets here caused false "fabrication"
    # rejections for tools the candidate genuinely has experience with.
    orig_skills = original_resume_data.get("skills", [])
    if isinstance(orig_skills, dict):
        flat_skills = []
        for v in orig_skills.values():
            if isinstance(v, list):
                flat_skills.extend(v)
            elif isinstance(v, str):
                flat_skills.append(v)
    elif isinstance(orig_skills, list):
        flat_skills = list(orig_skills)
    else:
        flat_skills = [str(orig_skills)]

    candidate_profile = {
        "skills": list(set(flat_skills + (user_selected_skills or []))),
        "education": [{"institution": e.get("institution", ""), "degree": e.get("degree", "")} for e in original_resume_data.get("education", [])],
        "experience": [
            {"company": e.get("company", ""), "role": e.get("role", ""), "bullets": e.get("description", [])}
            for e in original_resume_data.get("experience", [])
        ],
        "projects": [
            {"title": p.get("title", ""), "bullets": p.get("description", [])}
            for p in original_resume_data.get("projects", [])
        ],
        "total_experience_years": computed_years
    }

    prompt = f"""You are a senior technical recruiter reviewing a tailored LaTeX resume.
The resume has already passed all structural checks (grades, schools, companies, projects all present).
Evaluate the QUALITY of the tailored resume by comparing it against both the target Job Description (JD) and the candidate's original Profile.

USER EXPLICITLY APPROVED SKILLS: [{approved_user_skills_str}]
(The candidate has manually selected and authorized these skills for inclusion. You MUST ACCEPT these skills as authentic and NEVER flag them as untruthful or fabricated!)

QUALITY RUBRIC — evaluate each item independently and set its boolean field accordingly:
1. ats_fit_ok: Are the top 3-5 job keywords from the JD naturally integrated into experience/skill bullets?
   (Check for contextual use, NOT verbatim copy-paste from JD. NOTE: If the JD excerpt below is empty or not provided, automatically set ats_fit_ok = true.)
2. impact_metrics_ok: Do the majority of bullets contain at least one quantified result (%, numbers, scale)?
3. truthfulness_ok: Does tailored content stay within the candidate's real background?
   - The CANDIDATE ORIGINAL PROFILE below — including each job's/project's "bullets" field and the USER EXPLICITLY APPROVED SKILLS list above —
     is the FULL ground truth of the candidate's real experience. A skill or tool is
     NOT fabricated if it appears ANYWHERE in the profile, including inside bullets,
     even if it is not also listed in the flat "skills" array.
   - USER EXPLICIT OVERRIDE: Any skills listed in the candidate's "skills" array below (e.g. AWS, GCP, RAG, Vector Databases, Hugging Face) have been explicitly approved by the user for inclusion. DO NOT flag these user-selected skills as fabrication or untruthful under any circumstances!
   - Only flag truthfulness if the tailored resume mentions an unapproved company, degree, or unapproved tool that appears NOWHERE in the candidate profile.
4. conciseness_ok: Are bullets tight (1-1.5 lines)? No sprawling multi-line sentences?

Set each boolean independently and truthfully — do NOT set all four to true just because most pass.
If no JD description was provided, set ats_fit_ok to true automatically.
In feedback, name exactly which criterion(s) failed and what to fix. If all four pass, give brief positive feedback.

Target Job Title: {job_title}
JD Excerpt:
---
{jd_excerpt}
---

CANDIDATE ORIGINAL PROFILE:
{json.dumps(candidate_profile, indent=2)}

TAILORED LaTeX:
---
{tailored_latex[:4500]}
---
"""

    try:
        response_text = generate_content_with_fallback(prompt, ResumeReviewResult, custom_api_key, on_log, model_tier='strong')
        parsed = _parse_llm_json(response_text, label="resume review")
        return ResumeReviewResult(**parsed)
    except Exception as e:
        # Re-raise API failures (e.g. Rate Limit 429) so they bubble up to the frontend UI
        print(f"[review_tailored_resume] LLM quality check failed: {e}")
        raise RuntimeError(f"Recruiter review model check failed: {str(e)}")