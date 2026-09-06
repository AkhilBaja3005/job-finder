---
name: ats-resume-tailor
description: >-
  Use this skill when optimizing, scoring, or tailoring a LaTeX resume for a
  specific job listing. Enforces deterministic ATS taxonomy alignment, strict
  1-page PDF budget constraints, and a zero-hallucination policy.
---

# ATS Resume Tailor Skill

This skill teaches agents how to tailor candidate resumes with mathematical ATS precision while strictly preventing hallucinations or layout overflows.

## Golden Rules for Resume Engineering

1. **Zero Hallucination Policy**:
   - Never invent degrees, employers, unverified metrics, or technologies the candidate has never used.
   - Rephrase, emphasize, and reprioritize genuine achievements to mirror target job terminology.

2. **Strict 1-Page Layout Budget**:
   - Always run `compile_latex_metrics` after modifying LaTeX.
   - If `page_count > 1`, tighten spacing commands (e.g. `\vspace{-2pt}`, consolidate bullet points) until `fit_perfect` is true.

## Execution Steps

1. **Run Baseline ATS Audit**:
   - Call `calculate_ats_score` with the candidate's active resume and target JD.
   - Note the `missing_skills` and `matched_skills`.

2. **Tailor LaTeX Resume Code**:
   - Call `tailor_resume_latex`:
     ```json
     {
       "latex_code": "<master_latex>",
       "job_description": "<target_jd>",
       "job_title": "<target_role>",
       "company_name": "<company>"
     }
     ```

3. **Verify Page Budget**:
   - Call `compile_latex_metrics` on the resulting LaTeX code.

4. **Package for Delivery**:
   - Call `export_overleaf_bundle` to produce an instant 1-click Overleaf direct-import link for the user.
