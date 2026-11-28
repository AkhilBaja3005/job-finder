# Handoff status

Last updated by: Antigravity on branch `feat/anthropic-thinking-tailor-ui-polish`

## CV tailoring, LaTeX and release (latest)
- Merged: PR 167–170, PR 174, PR 176, PR 177 (`v1.9.6`), PR 178 (merged Packs into Documents, added `/app` page, updated READMEs). Open: PR 179 (parallel `prepare_jobs` + `scan --auto-apply / --direct`).
- Current branch `feat/anthropic-thinking-tailor-ui-polish`:
  - Fixed `gemini_client._execute_anthropic` `ThinkingBlock` leak (verified on 3 live jobs: cover letters 1,350–1,566 chars).
  - Wired `jd_analyzer` bullet-leading + primary-role 3-bullet floor + `approved_headlines` in `cv_tailor.py`.
  - Added per-row checkboxes + `Prepare selected (N)` in Documents (`macapp/panel/app.js`) and widened macOS `curl` box on `/app` (`DesktopAppPage.jsx`).
  - Verified `_execute_openai` structured output on 2 live jobs (`gpt-6.1-terra`) before hitting 50/50 daily RPD 429 limit.
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
