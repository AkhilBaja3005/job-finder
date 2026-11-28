# Handoff status

Last updated by: Claude Code on branch `fix/cv-guards-new-draft`

## CV tailoring, LaTeX and release (latest)
- Merged: PR 167 (master keeps everything from the resume, grouped skills, CPI and links render, validator and gate false alarms fixed, tailoring follows the chosen AI), PR 168 (LaTeX CV editor with in-app PDF preview, repeatable tailoring cache, page fill in the manifest).
- Merged PR 169: Tectonic bundled with the app, "I have this" confirmed skills, prompt t3, rebuild keeps a chosen LaTeX PDF.
- Open (branch `fix/cv-guards-new-draft`): pack lock, not-a-fit warning, ATS check on the real PDF, New draft, confirmed-skills list, resume-gaps banner, pipeline audit, `scripts/manual/cv_live_check.py`.
- Not done and how to continue: see `docs/handoff/REMAINING_TASKS.md`. Next step: wait for PR 169 CI (Intel Mac and Windows download Tectonic for the first time), merge, then run Actions, "Prepare release".
- How to run: `python macapp/fetch_tectonic.py` then the tests with `python -m pytest backend/tests -q`. Known local failures on Python 3.14: browser-use (3) and clean-venv (1); CI is green.

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
