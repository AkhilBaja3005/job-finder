# Better CV tailoring: task list

Goal: the tailored CV is at least as good as the master CV for every job, reads as written for the job, and contains **nothing that is not in the candidate's own material**. Zero invented facts is a hard gate, not a goal.

Status key: `[ ]` to do. Each task has an acceptance test (AT). Phases are in build order; a later phase never ships before the gates of an earlier one.

Where things live today: `backend/services/cv_tailor.py` (plan, validation, change log), `backend/services/application_pack.py` (pack, render, one-page fit), `backend/services/html_resume_renderer.py`, `backend/services/resume_audit.py`, `backend/services/fit_scorer.py` (the model call used by tailoring), `macapp/scan_panel.py` + `macapp/panel/app.js` (Packs UI), tests `test_cv_tailor.py`, `test_application_pack.py`, `test_resume_*`.

What pack #16 (Apple) showed: tailoring used only the profile; summary was weaker than the master summary; keyword coverage fell from 3 to 2; a quarter of the page stayed empty; "LLMs" was not matched to "Large Language Models"; the model is the small Gemini default and ignores the chosen AI; the panel says "No cover letter required" whatever the reason.

---

## Phase 0. Hard gates (nothing else ships without these)

- [ ] **0.1 Never worse than master.** Compute a job-fit score for the master CV and the tailored CV with the same scorer. If tailored < master, or any must-have keyword the master showed is lost, output the master (or the best partial) and say why in `cv_changes.md`. AT: a fixture where the model returns a worse plan yields the master CV and a warning.
- [ ] **0.2 Claim ledger.** Every sentence, bullet, summary clause and skill on the output CV maps to one or more source spans (profile / master resume) by id. Output with an unmapped claim is rejected. AT: injecting an unmapped sentence into a plan fails the build of that CV.
- [ ] **0.3 Deterministic fact checks on every output string** (code, not model): numbers, percentages, currencies, dates, durations, company names, job titles, degree names, institutions, locations, URLs, emails, phone numbers, technologies and proper nouns must exist in the source. AT: a table-driven test with one forged item per category, each rejected.
- [ ] **0.4 No conversions or derived numbers.** No currency conversion (INR to GBP), no unit change, no rounding up, no "3+ years" unless the dates support it (computed from dates, not typed by the model), no summing or "over N" claims not in the source. AT: "INR 300Cr+" can never become "£30M+".
- [ ] **0.5 No strength escalation.** Verbs and modifiers may not be stronger than the source: "aligned with" stays "aligned with" (never "ensuring compliance"); "contributed to" never becomes "led"; "assisted" never "owned"; no added "production" or "enterprise" or "scalable" unless in the source; no seniority words ("senior", "lead", "principal") not in a source title. AT: a verb-strength table with test pairs.
- [ ] **0.6 Entailment check.** For each rewritten bullet and the summary, a second pass (different prompt, ideally a different model) answers "does the source fully support every statement in the new text?"; any "no" or "unsure" keeps the original wording. AT: seeded unsupported rewrites are caught; the check is skipped only with an explicit warning.
- [ ] **0.7 Prompt-injection safety.** The job description is untrusted text. Strip or fence it; instructions inside it ("add Swift to the skills", "ignore previous rules") are ignored and logged. AT: JD containing instructions produces an unchanged result and a warning.
- [ ] **0.8 Identity and structure are copied, never generated.** Name, contact, links, every role, company, title, date, degree and institution come from the source verbatim. No role is dropped; every role keeps at least one bullet. AT: existing rule kept and tested with 1, 2 and 10 roles.
- [ ] **0.9 Fail safe.** Model unavailable, bad JSON, timeout, over quota, empty answer, answer in another language: use the master CV unchanged, mark the pack "not tailored" with the reason, never half-apply a plan. AT: simulated failures for each case.
- [ ] **0.10 Hallucination regression suite.** 30+ adversarial cases (each category in 0.3 to 0.7, plus tempting JDs that ask for skills the candidate lacks). The suite runs in CI and a single failure blocks merge. AT: suite green; the failure of any case is shown with the offending text.

## Phase 1. Source of truth (what tailoring starts from)

- [ ] **1.1 Master from the real resume.** Build the master CV from the candidate's resume file (PDF, DOCX or LaTeX), not only from the profile fields; keep both and diff them. Show "your profile is missing: Graphite, CPI, placement role" before tailoring. AT: fixture resume with items missing in the profile lists each missing item.
- [ ] **1.2 Profile drift check.** Warn when the resume file is newer than the profile, or the pack is older than the profile; offer one click to rebuild the profile and regenerate. AT: touching the resume sets the warning.
- [ ] **1.3 Structured master schema.** Contact, summary variants, roles (title, company, location, start, end, current flag), bullets with ids and tags (skills, outcome, metric), projects, education (degree, institution, dates, grade), certifications, awards, publications, languages, volunteering, links, clearance, work authorisation. Every field optional, none invented. AT: schema round-trips the three sample resumes.
- [ ] **1.4 Bullet metadata.** Each bullet gets: skills used, outcome type, metric, recency, seniority signal; computed once and cached with the source hash. AT: metadata present and stable across runs.
- [ ] **1.5 Alias and synonym map** (code, editable): LLM = large language model(s); ML = machine learning; GenAI = generative AI; RAG; K8s = Kubernetes; CI/CD; NLP; CV = computer vision (careful: also curriculum vitae); agentic workflows / multi-agent systems; etc. Used for evidence only; never to add words the source lacks. AT: "LLMs" counts as evidence for "Large Language Models"; "LangGraph agents" counts for "agentic workflows" only with the stated mapping.
- [ ] **1.6 Evidence snippets.** For each job keyword the tool reports the exact source span that supports it, or "no evidence". AT: change log lists spans.
- [ ] **1.7 User-approved extras.** Let the candidate add facts once (a new project, a certification) in the profile; tailoring uses only these. Never auto-adds from the job description. AT: no path writes JD terms into the profile.

## Phase 2. Understanding the job

- [ ] **2.1 Parse the JD into sections** (about the role, responsibilities, required, preferred, benefits, legal/EEO boilerplate). Boilerplate and benefits never produce keywords. AT: fixtures with long benefits sections yield no benefit keywords.
- [ ] **2.2 Weighted requirements.** Rank by: in title, in "required" section, repeated, years attached, tool vs concept. Output must-have, strong, nice-to-have lists. AT: ranking order matches a hand-labelled set of 10 JDs.
- [ ] **2.3 Role archetype.** Classify the job (applied ML, research, platform, data science, SWE with ML, docs/dev-relations, management...) and choose the section order and emphasis from it. AT: Apple "Developer Publications" is classed as tooling/documentation-leaning.
- [ ] **2.4 Seniority and years.** Read the years, level words and title; compare with the candidate's real years (computed from dates); report over- and under-qualification. AT: "5+ years" vs 3 years gives a clear gap note.
- [ ] **2.5 Hard requirements and knockouts** (work authorisation, location, clearance, degree, language, security checks, "must be able to travel"). Show them in the pack; never alter the CV to hide a mismatch. AT: each class is detected on fixtures.
- [ ] **2.6 Company and team context.** Product area, mission lines and values from the JD, only to choose emphasis and tone; never quoted as the candidate's experience. AT: no company text appears on the CV.
- [ ] **2.7 JD quality handling.** Empty, under ~200 characters, a login wall, a closed job, boilerplate-only, duplicated text, wrong language, HTML junk, a job with 40 bullets: each gets a defined result (master CV plus a note, or ask for the text). AT: one fixture per case.
- [ ] **2.8 Language.** Non-English JD: translate for understanding, produce the CV in the language the candidate chooses (default: the CV's language). AT: German JD does not produce a German CV unless asked.
- [ ] **2.9 Spelling variant.** British or American English follows the job location and the master CV; one variant throughout. AT: "optimise" vs "optimize" consistent.

## Phase 3. Choosing the content

- [ ] **3.1 Score every bullet, project and skill against the weighted requirements** (code scoring using aliases, plus the model's relevance judgement as a tie-break). AT: scores are reproducible for the same input.
- [ ] **3.2 Select by score across the whole CV, with floors:** every role keeps at least one bullet, the most recent role keeps at least 3, older roles fewer, projects ranked by relevance, and keep the strongest quantified result of each role. AT: selection tests for 1, 2, 5 and 10 roles.
- [ ] **3.3 Fill the page.** After selection, if space remains, add the next best material (more bullets, the CPI, the placement role, coursework, awards, certifications, publications, languages) until the page is full, never past one page. AT: pack #16 fixture leaves less than 8% blank.
- [ ] **3.4 Page budget by seniority.** One page up to about 8 years, two pages allowed above that or for academic and research roles; a setting and a per-job override. AT: both modes render within their limit.
- [ ] **3.5 Section order by archetype and level.** Experience first for experienced candidates; education first for students and recent graduates; projects above experience for research and portfolio-led roles; skills near the top for keyword-heavy roles. AT: order changes with level and archetype.
- [ ] **3.6 Education rules.** Include grade only if the source has it and it is strong (configurable); upcoming degrees marked "expected" with the correct dates; relevant coursework only if in the source; high school only if no degree. AT: future-dated MSc shows "Sept 2026 – Sept 2027" exactly as in the source.
- [ ] **3.7 Skills section.** Group by category (as in the master), put job-relevant groups first, limit length, never list a skill without a source mention, never duplicate near-synonyms ("LLMs" and "Large Language Models"). AT: grouped output, no duplicates.
- [ ] **3.8 Projects.** Include the most relevant 2 to 4, with links as source text; open-source and published projects kept when relevant; no project invented, merged or renamed. AT: names and links exact.
- [ ] **3.9 Older and unrelated roles.** Condense, never delete (no gaps in the timeline); internships and short roles shown as in the source. AT: timeline dates all remain.
- [ ] **3.10 Career-change and gap cases.** Keep gaps visible as in the source; a career changer's relevant projects and transferable bullets move up; never relabel a title. AT: a fixture with a gap year and a switch of field.

## Phase 4. Writing (honest rewrites only)

- [ ] **4.1 Rewrite rules.** A rewrite may reorder clauses, lead with the job's matching term when the source already has it, shorten, and fix tense. It may not add facts, tools, numbers, outcomes or scope. Keep every number and tool of the original. AT: diff-checker confirms the multiset of numbers and tools is unchanged.
- [ ] **4.2 Rewrite budget.** Allow more than 3 rewrites, but every one must pass 0.3 to 0.6; show original and new side by side with the reason. AT: the change log lists each pair.
- [ ] **4.3 Summary builder.** 2 to 4 lines: target-role title the candidate can truthfully claim, years computed from dates, two or three top proof points (with their numbers), one honest match to the company, optional education line. Use the master summary as the default and the base. A new summary replaces it only if it passes 0.1 and scores higher. AT: pack #16 keeps "Applied AI/ML engineer with 3+ years..." style positioning.
- [ ] **4.4 Title honesty.** The summary may name the target role only if the candidate's real titles or work support it ("Applied ML engineer" only if the source says applied ML work). A configurable "headline" setting. AT: unsupported target titles are rejected.
- [ ] **4.5 Style consistency.** Tense by role (past for finished roles, present for the current one), no repeated openings, consistent punctuation, no first person, one date format, no filler (keep the existing list), no unexplained jargon, no all-caps shouting. AT: linter test on outputs.
- [ ] **4.6 Voice.** Match the candidate's own style (sentence length, verbs) from the master CV, not a generic "AI voice". AT: a style-distance check against the master stays under a threshold.
- [ ] **4.7 Currency, units, number formats, date formats and locale** stay exactly as in the source (INR 300Cr+ stays; UK dates stay UK). AT: formats preserved.
- [ ] **4.8 Special characters** (& % # $ _ ~ ^ \ { } < > quotes, accents, non-Latin names, emoji): escape correctly for HTML and LaTeX, never drop or alter them. AT: round-trip test through each renderer.
- [ ] **4.9 Link text.** Show links as readable text (the ATS can read it), verify each URL matches the source, never invent a URL, mark dead or placeholder links ("example.com", "janedoe") as errors. AT: placeholder and invented links rejected.
- [ ] **4.10 Candidate-controlled terms.** A "never say" list and an "always keep" list (for example the candidate never wants a certain employer's project mentioned). AT: both lists respected.

## Phase 5. Layout, ATS and rendering

- [ ] **5.1 One-page and two-page fit without shrinking text below readable size** (floor around 9pt); if content does not fit, drop the lowest-scoring bullet instead of shrinking further. AT: no font below the floor; page count as set.
- [ ] **5.2 Real page-fill measurement.** Render, measure the used height, and loop: add, trim or reflow until between 92% and 100% full. AT: loop terminates; a hard cap on iterations.
- [ ] **5.3 ATS parse test.** Extract the PDF text back and confirm: reading order correct, sections found by standard headings, name and contact extracted, no ligature or glyph loss, no text in images, no tables or columns that scramble order, fonts embedded. AT: round-trip extraction equals the intended text for 3 samples.
- [ ] **5.4 Standard headings** (Summary, Experience, Education, Skills, Projects) and a plain bullet glyph. AT: heading names fixed.
- [ ] **5.5 Region rules.** UK: no photo, no age or marital status, A4. US: Letter, no photo. EU: per candidate choice. A setting per job country. AT: A4 vs Letter output.
- [ ] **5.6 Names and personal details.** Long names, hyphens, accents, non-Latin names, multiple phone formats, no phone, no LinkedIn: layout never breaks. AT: fixture set.
- [ ] **5.7 Overflow and wrapping.** Very long company names, titles, URLs, technology lists, one-word lines; hyphenation off for URLs. AT: no clipped or overlapping text.
- [ ] **5.8 Accessibility.** PDF tagged, document title and language set, selectable text, sensible metadata (name and role only, no tool traces). AT: PDF metadata checked.
- [ ] **5.9 File naming and versions.** `Name_Company_Role.pdf` style names, no illegal characters, keep every generated version, never overwrite the user's edited `cv.json` without `--redo`. AT: re-running keeps edits.
- [ ] **5.10 Rendering failures.** Missing Chromium or Tectonic, timeout, empty PDF: fall back to the simple renderer, then to the master PDF, with a clear message. AT: simulated failures.

## Phase 6. Model and cost

- [ ] **6.1 Respect the chosen AI** (Gemini, Claude, OpenAI) for tailoring, and default to a stronger model than the "lite" tier for this step; the model name is recorded in `manifest.json`. AT: choosing Claude calls Claude.
- [ ] **6.2 Determinism.** Temperature 0 or the lowest allowed, fixed prompt version, hash of (master, JD, prompt version, model) as the cache key; the same inputs give the same CV. AT: two runs equal.
- [ ] **6.3 Two-pass generation.** Pass 1 plan; code validates; pass 2 repairs only the rejected items with the exact reasons; at most 2 repairs, then fall back to the original wording for those items. AT: the repair loop terminates.
- [ ] **6.4 Candidate comparison.** Optionally generate 2 candidate CVs (different emphasis), score both with the 0.1 scorer, keep the better. AT: the higher-scoring one is chosen.
- [ ] **6.5 Rate limits, retries and backoff** with clear user-facing messages; respect quotas shared with scoring. AT: 429 handling tested.
- [ ] **6.6 Privacy.** Send only what the model needs; log no full CV text outside the pack folder; no secrets in prompts. AT: log scan test.
- [ ] **6.7 Offline mode.** Rule-based tailoring (selection, ordering, skills, alias matching, no rewriting) works with no model at all. AT: no network, still a valid CV.

## Phase 7. Review experience

- [ ] **7.1 Side-by-side diff** master vs tailored (summary, bullets, skills, projects) with a reason per change and one-click revert of any change; the PDF rebuilds. AT: revert restores the original bullet.
- [ ] **7.2 Evidence and risk panel:** keywords found, keywords with no evidence (listed, never added), requirements gap, knockouts, alias matches, claims changed, entailment results. AT: panel shows every item.
- [ ] **7.3 Scores shown:** master score, tailored score, keyword coverage before and after, with the blocked-regression note from 0.1.
- [ ] **7.4 Honest messages.** Replace "No cover letter required" with the real reason (not asked / skipped / failed / not generated yet). Same for "not tailored". AT: each state has its own text.
- [ ] **7.5 Edit and re-render:** edit `cv.json` in the app, rebuild the PDF without a model call, keep edits on regenerate unless told otherwise. AT: edits survive.
- [ ] **7.6 Sign-off gate:** "Docs OK" is blocked while a flagged claim, a failed fact check, or a missing link is unresolved. AT: cannot approve a pack with an unresolved claim.
- [ ] **7.7 Bulk operations:** regenerate many packs after a profile fix, show which improved and which got worse. AT: summary table after a bulk run.

## Phase 8. Cover letter and application consistency

- [ ] **8.1 Cover letter from the same ledger.** Same fact checks as the CV (0.2 to 0.6); no claim beyond the CV or profile; length and tone settings; the company paragraph uses only the JD and an optional note you provide. AT: unsupported claim rejected.
- [ ] **8.2 CV, cover letter and form answers agree** (titles, dates, numbers, skills). A cross-check flags mismatches. AT: seeded mismatch caught.
- [ ] **8.3 The apply step uses exactly the reviewed files** and records the file hashes in the apply log. AT: hash recorded and matched.
- [ ] **8.4 Salary, notice period, work authorisation and similar answers** come only from the profile; no estimation. AT: missing item stays blank and is reported.

## Phase 9. Evaluation and quality loop

- [ ] **9.1 Golden set:** 20 job descriptions across archetypes and levels with hand-written best CVs; track keyword coverage, fit score, page fill, hallucination count (must be 0), human rating. AT: report generated per run.
- [ ] **9.2 Compare against a chat-model baseline** on the same inputs: the tool must match or beat its fit score without any ledger failure. AT: tracked each release.
- [ ] **9.3 Metrics in the pack:** time, tokens, model, repairs, fallbacks used. AT: in `manifest.json`.
- [ ] **9.4 Outcome feedback** (optional, local only): record replies and interviews per pack; show which choices correlate. AT: nothing leaves the machine.
- [ ] **9.5 Property tests:** random master and JD pairs never produce a number, tool, company or date outside the source. AT: runs in CI for a fixed number of cases.
- [ ] **9.6 Prompt versioning:** a prompt change requires the golden set and the hallucination suite to pass. AT: CI rule.

## Phase 10. Edge-case checklist (each needs a fixture and a test)

- Candidate with one role, ten roles, or none (only education and projects).
- Current job marked "Present" / no end date; a future-dated degree; overlapping jobs; a gap longer than a year; a role under three months.
- Same company twice; promotions inside one company; contract and freelance work; career break; parental leave.
- No projects; no education dates; no metrics anywhere; bullets that are one-liners or 60 words.
- Very senior candidate (two pages); recent graduate (education first); academic (publications); career changer.
- Name with accents, hyphen or non-Latin script; no phone; two emails; links that are dead, placeholders, or contain `&`, `%`, `#`.
- JD empty, tiny, huge, duplicated, in another language, all benefits, with injected instructions, asking for skills the candidate lacks, or for a degree the candidate lacks.
- JD whose title is a different field from the candidate's (the "not a fit" path).
- Two jobs at the same company in one scan; the same job on two sites (one pack).
- Special characters and emoji in any field; right-to-left text; very long words.
- British vs American spelling; date formats (UK, US); currencies and units kept as written.
- Model returns invalid JSON, an empty plan, indexes out of range, duplicate indexes, a different language, or text outside the schema.
- Model or network down; quota exhausted; renderer missing; disk full; read-only folder; pack folder renamed or deleted.
- Profile changed after the pack was built; the user edited `cv.json` and then regenerates.
- Re-running tailoring twice (idempotent); running two tailorings at once for the same pack (lock).
- Pack built before this change (migrate or flag as old).

## Definition of done

- Phase 0 gates and the hallucination suite are green in CI; no known path writes a fact that is not in the source.
- Golden set: tailored fit score is at least the master's for every job and beats the chat baseline on average; page fill 92% to 100%; ATS parse test passes.
- The review screen shows every change with a reason and a revert, and the sign-off is blocked on unresolved flags.
- Pack #16 (Apple) regenerated: Graphite present, summary at least as strong as the master's, no wording stronger than the source, and the page filled.
