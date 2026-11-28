# Handoff status

Last updated by: Antigravity on branch `feat/cv-live-check`

## CV tailoring, LaTeX and release (latest)
- Merged: PR 167, PR 168, PR 169, PR 170 (`fix/cv-guards-new-draft`).
- Combined PR on `feat/cv-live-check` (supersedes PRs #171–#175):
  - **Section 1**: Verified `main` build `46140999138` (`Mac arm64` & `Windows` green with `"bundled": true, "ok": true`; `Mac x86_64` `cryptography`/`libssl.3.dylib` fix from PR #174 included).
  - **Section 3.1**: Ran 23-job `scripts/manual/cv_live_check.py` (Anthropic); results in `docs/handoff/CV_LIVE_CHECK.md`. Found `ThinkingBlock(signature=...)` leak in `cover_letter.txt` (`gemini_client._execute_anthropic`).
  - **Section 3.3**: Wired `cv_writer.check_title_honesty`, `apply_candidate_term_controls` (`never_say`/`always_keep`), and `cv_selector.score_item` must-have protection into `cv_tailor._apply_plan`; removed unused `cv_renderer_ats`, `cv_eval`, and `offline_tailor`.
  - **Section 3.4**: Added `cv_master.extract_master_from_resume` (verbatim verification + SHA-256 cache + diff) and `Api.preview_resume_master` / `confirm_resume_master`.
  - **Sections 3.5 & 3.6**: Added `Api.import_latex_template` / `clear_latex_template` (`cv_latex.cv_to_latex` via `inject_tailored_slots`), `Api.use_standard_cv_pdf`, and `Hand-edited CV` badge in Packs UI.
  - **Sections 4.1 & 4.3**: Logged post-LinkedIn discovery/filter gaps in `discovery_tools.py` & `scheduled_job_scanner.py`; skipped the 4 env-gated tests cleanly on Python 3.14.
- How to run: `python3 -m pytest backend/tests/test_cv_*.py backend/tests/test_mac_app.py backend/tests/test_fetch_tectonic.py -q` (296 passed, 4 skipped across targeted suite).
- Next step: Wait for CI (`CI Verification & Tests`, `Mac arm64`, `Windows`, `Mac x86_64`) on the combined PR, merge, and fix `gemini_client._execute_anthropic` `ThinkingBlock` leak for cover letters.

## Where things stand
- **Phase 0 (PR #133)**: Merged on `main` (`build_scan_args`, `build_apply_args`, Excel tracker read/write, `scheduler.py`).
- **Phase 1 (PR #134 on `feat/app-staged-ui`)**: Complete:
  - UI (`macapp/panel/app.js`, `macapp/panel/styles.css`, `macapp/panel/dev/mock-api.js`): Search, Review, Packs, Documents, Apply, Applications, Settings tabs, `next_step()` banner, and updated guided tour.
  - Python bridge (`macapp/scan_panel.py`): All 12 `API_CONTRACT.md` methods (`next_step`, `list_searches`, `list_jobs`, `approve_jobs`, `revoke_jobs`, `list_packs`, `prepare_packs`, `pack_documents`, `open_pack_file`, `signoff_pack`, `list_ready`, `start_apply`).
  - Tests (`backend/tests/test_mac_app.py`): Added `test_staged_api_workflow_end_to_end`; all `97` tests in `test_mac_app.py` pass locally.
- **Phase 2**: Verified in place:
  - Account sync (`_csv_all` / `sync_to_cloud`) reads Excel workbooks (`_excel_rows`), CSV fallback only when no workbook exists.
  - `job_finder/commands/apply.py` reads `cover_letter.txt` / `cover_letter.pdf` only from the reviewed pack (`ap.read_cover_letter`).
  - `backend/services/browser_use_agent.py` runs `services.grounding` and attaches `"grounding": grounding_audit.summary()`.
  - Google sign-in gate (`_guarded` in `macapp/scan_panel.py`) covers all 12 new `Api` methods.

## Next step
- Wait for CI checks on PR #134 (`CI Verification & Tests`, `Mac arm64`, `Mac x64`, `Windows`) to finish green, then merge PR #134.

## Known problems / not verified
- Live `apply` submission and the live `pywebview` desktop window on Mac/Windows have not been exercised against real job sites.

## How to run
- Tests: `python3 -m pytest backend/tests -q`
- UI preview: serve `macapp/panel/` (`python3 -m http.server`) and open `dev/index.html` (or `dev/index.html?empty`) in a browser.
