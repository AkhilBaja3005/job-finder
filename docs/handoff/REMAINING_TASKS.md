# Remaining tasks (after PRs 167, 168 and 169)

Owner: **Me** = a coding agent can do it. **You** = needs the repository owner's account, computer or decision. Each task ends with how to tell it is done.

## 1. Verify what was just built (first real runs)
- [ ] **Me, after CI.** PR 169 CI: the Intel Mac and Windows builds download Tectonic, verify the checksum, warm the cache and pass `--latex-check`. *Done when* the "Build desktop apps" jobs for Mac arm64, Mac x86_64 and Windows are green and their logs show `"bundled": true, "ok": true`.
- [ ] **You.** Open the built app on a real Mac and a real Windows PC: Documents, Tailored CV, LaTeX source, Compile preview with the network off. *Done when* a preview shows with Wi-Fi off.
- [ ] **You.** Real-device check of the Chrome dock, the live view on the Run page, Windows run-finished notifications, and the "Keyword/AI" pills. *Done when* each works or you send the failure.
- [ ] **You + Me.** Signed build (Apple Developer account, $99 a year): the nested `tectonic` binary is signed and the app opens without the "Not Opened" warning. *Done when* a signed, notarized dmg opens on a clean Mac.

## 2. Release
- [ ] **You, then Me.** Run Actions, "Prepare release" (patch). It collects PRs 167 to 169 into the changelog and opens `release: 1.9.5`; the PR merges itself, then "Release" starts by itself. *Done when* the `v1.9.5` release exists with the Mac and Windows files. The last two attempts stopped at `HTTP 403` when creating the release (PRs 149 and 150 changed the token and added diagnostics, never exercised). If it fails again, send the "Full answer" log section.
- [ ] **You.** Confirm PyPI publishing works (the `PYPI_TRUSTED_PUBLISHING` variable is on, so PyPI must trust the workflow `publish_pypi.yml`, environment `pypi`). *Done when* a PyPI upload for 1.9.5 succeeds.
- [ ] **You.** Rotate the Hugging Face token and the Supabase publishable key, clean the two `.env` files, decide `JOB_FINDER_DISABLE_GUARDRAILS`. *Done when* the old keys are rejected.

## 3. CV tailoring quality
- [ ] **Me (OpenAI limit resets).** Run the five real jobs with GPT Terra; confirm the OpenAI path (`gpt-6.1-terra`) works with the structured-output prompt. *Done when* five tailored CVs from GPT are compared with Claude's.
- [ ] **Me.** A bigger live check: 20 real postings across roles and levels, with cover letters, scored against your original CV (job-term coverage, new facts must be 0, page fill 92-100%). *Done when* a table shows tailored >= original on every job, or lists where not.
- [ ] **Me.** "Regenerate" currently returns the same plan (the cache). Add "New draft" (asks the model again once) next to it. *Done when* the button produces a different draft and the cache is refreshed.
- [ ] **Me.** Build the whole master from the resume file (education, projects, certifications, not only the skill lines): the model splits the resume into items and code checks each item appears in the resume text. *Done when* a profile missing a resume item still gets it on the CV, and every item is checked.
- [ ] **Me.** Import your own `.tex` as the template (slot injection) for users whose LaTeX differs from the repo's `resume.cls`. *Done when* tailoring edits only the slots of an imported file and the output looks like that file.
- [ ] **Me.** Settings list of confirmed skills with Remove; after "I have this", offer "Regenerate this pack" at once. *Done when* the loop confirm -> regenerate shows the skill on the CV in two clicks.
- [ ] **You.** For jobs like Apple's, say honestly which missing requirements you do have (for example LLM evaluation from your agent benchmark) using "I have this". Nothing is added without your sentence.
- [ ] **Me.** Audit the other agent's phases against the plan (weighted must-haves, role archetype, section order, ranking across the whole CV): list what is wired in and what is only a module. *Done when* each plan task is marked wired, partial or missing, with a test for the wired ones.
- [ ] **Me.** Cover letters on the real jobs: confirm `always` produces a letter, the status text matches the real state, and the letter passes the same fact checks. *Done when* five letters are checked against your resume.

## 4. Job scan
- [ ] **Me.** Find the silent 2.5-minute gap between the last LinkedIn description and the "Expand" round (new timings in the log help); LinkedIn description fetching still runs about 2 seconds apart.
- [ ] **You.** Run `job-finder boards refresh` once (the company-board index is empty, so that source finds 0 jobs). Indeed stays blocked by Cloudflare.
- [ ] **Me (low).** On this machine four tests fail on Python 3.14 (browser-use ×3, clean-venv); CI passes. Make them skip or pass locally.

## 5. Housekeeping
- [ ] **Me.** Remove the worktree `../job-finder-cv-eval` and the scratch files after PR 169 merges.
- [ ] **Me.** Tag gap: 1.9.4 was never released (version bump only); the next release is 1.9.5. Nothing to do unless you want 1.9.4 published.
