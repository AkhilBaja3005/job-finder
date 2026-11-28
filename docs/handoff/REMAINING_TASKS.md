# Remaining tasks (handoff for the next agent)

Written when the previous agent ran out of time. Read `docs/handoff/STATUS.md`, `docs/handoff/CV_PIPELINE_AUDIT.md` and `AGENTS.md` first. Work in your own worktree on your own branch from `origin/main`; one PR per task group; merge only when "Distribution & Test Suite", "Windows" and "Mac arm64" pass (Mac x86_64 may fail on runner glitches). Do not publish a numbered release by hand: use the Actions workflows.

Owner: **Agent** = a coding agent can do it. **Owner** = needs the repository owner's account, computer or decision.

## 0. State at hand-over
- Merged to main: PR 167 (master keeps everything from the resume, skill groups, CPI and links render, validator and gate false alarms fixed, tailoring follows the chosen AI), PR 168 (LaTeX CV editor with in-app PDF preview, plan cache, page fill), PR 169 (Tectonic bundled in the app, "I have this" confirmed skills, prompt t3, a rebuild keeps the chosen LaTeX PDF).
- Open branch `fix/cv-guards-new-draft` (PR opened by the previous agent): pack lock with stale-lock cleanup, not-a-fit warning, ATS check on the real PDF text, "New draft" button, confirmed-skills list with Remove, rebuild offer after "I have this", resume-gaps check (banner), the audit document, and `scripts/manual/cv_live_check.py`. Local suite: 1,123 passed; the only failures are the 4 known ones on Python 3.14 (browser-use x3, clean-venv).
- A live run of 23 real postings with cover letters was started and may not have finished. Re-run it: see 3.1.
- Release: `v1.9.5` does not exist. 1.9.4 was only a version bump (never released). The two "Release" attempts stopped at `HTTP 403` when creating the release; PRs 149 and 150 changed the token and added diagnostics but that path has never run to the end.

## 1. Check PR 169's first real build (Agent, as soon as the branch is merged)
- [x] Open the "Build desktop apps" run on main after PR 169. The Mac arm64, Mac x86_64 and Windows jobs download Tectonic 0.16.9 for the first time, warm the cache and run `--latex-check`. *Done when* all three are green and their logs show `"bundled": true, "ok": true`. (Run `46140999138`: Mac arm64 & Windows passed with `"bundled": true, "ok": true`; Mac x86_64 downloaded Tectonic & verified checksum, then failed in smoke test on `cryptography`/`libssl.3.dylib` mismatch fixed by PR #174.)
- [ ] If the Intel Mac job fails with `hdiutil: create failed - Resource busy` that is a runner glitch; re-run it.
- [ ] App size grew by about 90 MB (engine 50 MB, warmed cache 42 MB). If that is too large, ship the cache zipped and unpack on first use.

## 2. Release 1.9.5 (Owner starts it, Agent debugs)
- [ ] Owner: Actions, "Prepare release", bump `patch`. It opens `release: 1.9.5` (changelog from PR titles), merges it when every check passes, then "Release" starts by itself.
- [ ] If "Create the pre-release" fails again with `HTTP 403`, the log prints GitHub's full answer in a "Full answer" group. The `x-accepted-github-permissions` header names the missing permission. Possible causes to check: the `RELEASE_TOKEN` fine-grained token needs Contents: Read and write, Pull requests: Read and write, Workflows: Read and write, Actions: Read and write; token owner must be the repository owner; the workflow `release.yml` creates a pre-release, builds the apps, runs PyPI, then flips it to the latest release.
- [ ] Owner: PyPI. `PYPI_TRUSTED_PUBLISHING` is `true`, so PyPI must list this repository as a trusted publisher (workflow `publish_pypi.yml`, environment `pypi`). Release starts that workflow with `ref` set to the tag. *Done when* a PyPI upload for 1.9.5 succeeds.
- [ ] Owner: set the repository variable `AUTO_PUBLISH_PYPI=true` only if PyPI should publish automatically after each `release:` merge.

## 3. CV tailoring quality
- [x] **3.1 Agent: real-job check.** `scripts/manual/cv_live_check.py` fetches postings from a scan workbook, builds packs with cover letters and compares with the candidate's resume. Run it on all 23 jobs of the owner's search (see the script header for the environment variables) and write the table into `docs/handoff/CV_LIVE_CHECK.md`. Targets: tailored coverage >= the resume's on every job; no new numbers or tool names; one page; page fill 92-100%; ATS check ok; cover letters have no `letter_issues`. Report every miss with the job.
- [ ] **3.2 Agent: GPT.** OpenAI's daily limit (`gpt-6.1-terra`) blocked the five-job GPT run. When it resets, run the same check with `CV_CHECK_PROVIDER=openai` and compare. If OpenAI rejects the structured-output request, fix `_execute_openai` in `backend/services/gemini_client.py`.
- [x] **3.3 Agent: wire the unused CV modules.** See the audit table. Wire, with tests: (a) `cv_writer.check_title_honesty` for summary claims about the target role; (b) never-say / always-keep lists from the profile (`apply_candidate_term_controls`) in the selection step; (c) `cv_selector.score_item` as a check on the model's plan (the plan may not drop the highest-scoring bullet of a role that carries a must-have). Do not wire `cv_renderer_ats` (its HTML renderer is not the one the app uses); delete or archive it, `cv_eval`'s invented one-line golden set and the unused offline tailor in `cv_model_runner` if they stay unused.
- [x] **3.4 Agent: master built entirely from the resume file.** Today only the skill groups come from the resume (`cv_master.resume_skill_groups`); education, projects and bullets come from `candidate_profile.json`. Build the whole master from `MASTER_RESUME_PATH`: a model splits the resume text into roles, bullets, projects, education; code checks that every extracted string appears in the resume text (reject otherwise); cache by file hash; show a diff against the profile once and let the owner confirm. `cv_master.resume_gaps` already reports facts the CV data lacks; the panel shows it as a banner.
- [x] **3.5 Agent: import the owner's own `.tex` as the template.** `backend/utils/latex_utils.py` has `inject_tailored_slots` and `parse_latex_to_resume_dict`. Let the owner pick a `.tex` once; tailoring then edits only the text slots of that file. Fall back to the built-in `resume.cls` template.
- [x] **3.6 Agent: edited-LaTeX sync.** When the owner edits the LaTeX and uses its PDF, `manifest.json` has `cv_source: "latex"` and a rebuild keeps that PDF. Add a way back ("Use the standard CV again") and show in the Packs list that the CV is hand-edited.
- [ ] **3.7 Agent: tailoring ceiling.** Tailoring still mostly reorders and re-emphasises; it never adds a skill the resume lacks (correct). Possible honest improvements: use `jd_analyzer` weights to choose which bullet leads each role; ask the model for a clearer target-role headline only when `check_title_honesty` passes; let the owner pre-approve role headlines in the profile.
- [ ] **3.8 Owner: use "I have this".** For requirements you really meet but the resume does not show (for example LLM evaluation from your agent benchmark), use the button on the Evidence tab and write the sentence. Nothing is added without it.

## 4. Job scan
- [x] **4.1 Agent:** find the silent 2.5-minute gap between the last LinkedIn description and the "Expand" round in `applications_tracker/scheduled_job_scanner.py`. The log now prints phase timings; run a scan and read them. LinkedIn description fetching is throttled (about 2 s apart, deliberate).
- [ ] **4.2 Owner:** run `job-finder boards refresh` once (the company-board index is empty, so that source returns 0 jobs). Indeed is blocked by Cloudflare; do not try to bypass it.
- [x] **4.3 Agent (low):** make the 4 local failures on Python 3.14 skip cleanly instead of failing (`test_browser_use_prototype`, `test_end_to_end_pipeline`, `test_jev_ultrafast_and_phone`, `test_clean_venv_installation`); CI passes.

## 5. Real-device checks (Owner)
- [ ] Mac and Windows: the LaTeX editor with Wi-Fi off (Documents, Tailored CV, LaTeX source, Compile preview).
- [ ] The Chrome dock (Run, Advanced, "Dock beside this window"), the live view on the Run page, Windows run-finished notifications.
- [ ] Signed build: Apple Developer account ($99 a year), then add the signing secrets listed in `macapp/README.md`; the nested `tectonic` binary is signed before the app by `build_mac.sh`.
- [ ] Rotate the Hugging Face token and the Supabase publishable key; clean the two `.env` files; decide `JOB_FINDER_DISABLE_GUARDRAILS`.

## 6. Housekeeping (Agent)
- [x] Remove the scratch worktree `../job-finder-cv-eval` after the open PR merges (`git worktree remove`).
- [x] Keep `docs/handoff/STATUS.md` current when you stop.

## 7. Rules that must not be broken
- No invented facts on any CV or cover letter. A skill the resume lacks reaches a CV only through `Api.confirm_experience` (the owner's own sentence).
- The in-app browser, Google sign-in gate, Chrome dock and the grounding tools stay working.
- Releases go through Actions ("Prepare release", "Release"), not from a terminal.
