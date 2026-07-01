import os
import json
import re
from pydantic import BaseModel, Field
from typing import List, Optional, Dict

from services.gemini_client import generate_content_with_fallback, generate_latex_with_strong_model
from services.ats_scorer import compute_ats_score, compute_overall_score

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
    score_breakdown: Dict[str, str] = Field(default_factory=dict, description="Human-readable detail per dimension")
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
    satisfied: bool = Field(description="True ONLY if every rubric item passes. False if ANY item fails.")
    feedback: str = Field(description="Specific, actionable recruiter feedback on exactly what to fix.")


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
    """Truncate job description to avoid ballooning prompt size from scraped HTML noise."""
    return jd[:max_chars] if len(jd) > max_chars else jd

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
    return {k: _escape(v) for k, v in suggestions.items()}

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

RULE 2 — GPA / CPI / GRADES (ZERO TOLERANCE):
  • Find every line in the master Education section that contains a numeric grade, CPI, GPA, or percentage (e.g. "CPI: 8.04", "94.2\\%").
  • Copy those values exactly into the tailored Education section on the SAME line as the degree, right-aligned with \\hfill.
  • Example: {{\\textit{{B.Tech in Engineering Science}}}} \\hfill {{\\em CPI: 8.04}} \\\\
  • If you omit this, the output is REJECTED.

RULE 3 — SECTION & CONTENT COMPLETENESS:
  • Preserve EVERY school, job, and project. Do NOT delete, rename, or merge any.
  • Preserve the EXACT bullet count per job and per project. Do NOT add or remove bullets.
  • Preserve the original nested itemize structure (sub-bullets under parent bullets).

RULE 4 — ONE-PAGE BUDGET (CRITICAL):
  • The entire tailored resume MUST fit on exactly ONE page.
  • Write concise bullets: 1 to 1.5 lines each. Do NOT write sprawling 2-line bullets.
  • Do NOT add extra \\vspace or \\newline commands.

RULE 5 — LATEX STRUCTURE:
  • Preserve \\documentclass, all \\usepackage lines, geometry, and custom macros (\\mybar, etc.).
  • Keep the exact tabular layout in Technical Skills if present.
  • Do NOT add \\linespread, \\pagestyle, or spacing overrides — these are injected by the compiler.

RULE 6 — ATS KEYWORD INTEGRATION:
  • Inject relevant missing keywords into Technical Skills and bullets naturally.
  • Bold existing key metrics (e.g. \\textbf{{50\\%}}) and tools (e.g. \\textbf{{RabbitMQ}}) for visual consistency.
  • CRITICAL: NEVER use markdown asterisks (e.g. **RabbitMQ** or **50%**) for bold text. You MUST use standard LaTeX command: \\textbf{{RabbitMQ}} or \\textbf{{50\\%}} (always escape percent signs: \\%).
  • Translate JD phrases into natural accomplishments — NEVER copy-paste verbatim.

RULE 7 — OUTPUT FORMAT:
  • Return ONLY the raw LaTeX source. No markdown fences, no explanations, no commentary.

MASTER LaTeX (source of truth):
---
{master_latex}
---
"""

    max_retries = 2
    last_err = None
    for attempt in range(max_retries):
        try:
            raw = generate_latex_with_strong_model(prompt, custom_api_key)
            raw = raw.replace("```latex", "").replace("```", "").strip()
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
    custom_api_key: Optional[str] = None,
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
    ats = compute_ats_score(resume_data, jd_truncated)
    print(f"[ATS] skills={ats.skills_score} exp={ats.experience_score} "
          f"matched={ats.matched_required_count}/{ats.total_required_count} "
          f"years={ats.candidate_years}/{ats.required_years}")

    # Prepare inputs for semantic scoring & cover letter
    lean_resume = {
        "name":       resume_data.get("name", ""),
        "current_role": resume_data.get("experience", [{}])[0].get("role", "") if resume_data.get("experience") else "",
        "total_experience_years": ats.candidate_years,
        "skills":     resume_data.get("skills", []),
        "recent_companies": [e.get("company", "") for e in resume_data.get("experience", [])[:3]],
        "education":  [{"institution": e.get("institution", ""), "degree": e.get("degree", "")} for e in resume_data.get("education", [])],
        "projects":   [{"title": p.get("title", "")} for p in resume_data.get("projects", [])],
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

    cover_prompt = f"""You are an expert career writer.
Write a tailored cover letter and resume section updates for this candidate.

CANDIDATE: {json.dumps(lean_resume, indent=2)}
TARGET ROLE: {job_title}
MISSING SKILLS TO ADDRESS: {', '.join(ats.missing_skills[:8])}
JD EXCERPT: {jd_truncated[:1200]}

RULES:
- Cover letter: under 300 words, specific to this JD, no generic filler.
- suggested_resume_updates.experience: MUST have bullet lists matching these counts: {json.dumps(bullet_counts)}
  Do NOT merge, delete, or add bullets.
- suggested_resume_updates.skills: Updated skills list naturally integrating missing skills.
"""

    # ── Phase 2 & 3: Run LLM calls in parallel threads ─────────────────────
    import asyncio
    
    # We use asyncio.to_thread to run synchronous blocking Gemini API calls concurrently
    semantic_task = asyncio.to_thread(
        generate_content_with_fallback,
        semantic_prompt,
        _SemanticScoreResult,
        custom_api_key
    )
    cover_task = asyncio.to_thread(
        generate_content_with_fallback,
        cover_prompt,
        _CoverLetterResult,
        custom_api_key
    )

    semantic_text, cover_text = await asyncio.gather(semantic_task, cover_task)

    semantic = _SemanticScoreResult(**json.loads(semantic_text))
    role_fit = min(100, max(0, semantic.role_fit_score))
    cover_result = _CoverLetterResult(**json.loads(cover_text))

    # ── Phase 4: Compute overall score (formula, not hallucinated) ───────────
    overall = compute_overall_score(ats.skills_score, ats.experience_score, role_fit)

    keyword_stats = {
        "required_matched":  f"{ats.matched_required_count}/{ats.total_required_count}",
        "candidate_years":   str(ats.candidate_years),
        "required_years":    str(ats.required_years) if ats.required_years else "not specified",
    }

    match_analysis = MatchScoreDetails(
        overall_score=overall,
        skills_score=ats.skills_score,
        experience_score=ats.experience_score,
        role_fit_score=role_fit,
        matched_skills=ats.matched_skills,
        missing_skills=ats.missing_skills,
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
        # LaTeX tailoring is run sequentially since it depends on the output of suggestions
        tailored_latex = tailor_latex_code(
            master_latex, job_title, job_description, suggestions,
            ats.missing_skills, custom_api_key
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
        title = proj.get("title", "").strip()
        # Find a distinctive word (>4 chars, not a stopword) to search for
        stopwords = {'the', 'and', 'for', 'from', 'with', 'using', 'deep', 'data'}
        words = [w for w in title.split() if len(w) > 4 and w.lower() not in stopwords]
        key = words[0] if words else title.split()[0] if title else ""
        if key and key not in plain_latex:
            issues.append(
                f"Project '{title}' appears missing from the tailored LaTeX "
                f"(searched for key term '{key}')."
            )

    # 1f. Basic LaTeX structure check
    if "\\documentclass" not in tailored_latex:
        issues.append("CRITICAL: Tailored LaTeX is missing \\documentclass — completely broken output.")
    if "\\begin{document}" not in tailored_latex:
        issues.append("CRITICAL: Tailored LaTeX is missing \\begin{document}.")

    # If structural issues found → return immediately, no LLM needed
    if issues:
        return ResumeReviewResult(satisfied=False, feedback="\n".join(issues))

    # ── Phase 2: LLM soft-quality check ──────────────────────────────────────
    jd_excerpt = _truncate_jd(job_description, max_chars=1200)
    
    # Formulate a clean profile snapshot for validation
    candidate_profile = {
        "skills": original_resume_data.get("skills", []),
        "education": [{"institution": e.get("institution", ""), "degree": e.get("degree", "")} for e in original_resume_data.get("education", [])],
        "experience": [{"company": e.get("company", ""), "role": e.get("role", "")} for e in original_resume_data.get("experience", [])],
        "total_experience_years": 3.1 # Hand-calculated timeline sum
    }

    prompt = f"""You are a senior technical recruiter reviewing a tailored LaTeX resume.
The resume has already passed all structural checks (grades, schools, companies, projects all present).
Evaluate the QUALITY of the tailored resume by comparing it against both the target Job Description (JD) and the candidate's original Profile.

QUALITY RUBRIC:
1. ATS Fit: Are the top 3-5 job keywords from the JD naturally integrated into experience/skill bullets?
   (Check for contextual use, NOT verbatim copy-paste from JD.)
2. Impact Metrics: Do the majority of bullets contain at least one quantified result (%, numbers, scale)?
3. Truthfulness: Does tailored content stay within the candidate's real background?
   - Compare the tailored resume to the Candidate Profile below.
   - Did the tailorer invent new companies, fabricate degrees, or exaggerate years of experience?
   - Ensure the candidate is not falsely claimed to have skills/experience they do not possess.
4. Conciseness: Are bullets tight (1-1.5 lines)? No sprawling multi-line sentences?

If quality passes all 4 criteria → satisfied=true, brief positive feedback.
If any criterion clearly fails → satisfied=false, specific actionable feedback (what exactly to fix).

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
        response_text = generate_content_with_fallback(prompt, ResumeReviewResult, custom_api_key)
        parsed = json.loads(response_text)
        return ResumeReviewResult(**parsed)
    except Exception as e:
        # If LLM quality check fails (malformed JSON, API error), don't crash the pipeline
        print(f"[review_tailored_resume] LLM quality check failed: {e}. Defaulting to satisfied=True.")
        return ResumeReviewResult(
            satisfied=True,
            feedback="Quality check skipped due to API error. Structural checks passed."
        )
