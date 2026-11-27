# Handoff status

Last updated by: Antigravity on branch `feat/app-staged-ui`

## Where things stand
- PR 125 (staged Excel workflow) and PR 133 (Phase 0: arg builders, Excel tracker read/write, scheduler) are merged on `main`.
- **Phase 1 (UI + `Api` methods)** is complete on `feat/app-staged-ui` (PR #134):
  - `macapp/panel/app.js`, `macapp/panel/styles.css`, `macapp/panel/dev/mock-api.js`: Search, Review, Packs, Documents, Apply, Applications, Settings tabs, `next_step()` banner, and updated guided tour.
  - `macapp/scan_panel.py`: Implemented all 12 `API_CONTRACT.md` Phase 1 methods (`next_step`, `list_searches`, `list_jobs`, `approve_jobs`, `revoke_jobs`, `list_packs`, `prepare_packs`, `pack_documents`, `open_pack_file`, `signoff_pack`, `list_ready`, `start_apply`).
  - `backend/tests/test_mac_app.py`: Added `test_staged_api_workflow_end_to_end`; all `97` tests in `test_mac_app.py` pass locally.

## Plan
- Phase 0 (logic agent, PR #133): merged on `main`.
- Phase 1 (PR #134 on `feat/app-staged-ui`): UI + `scan_panel.py` `Api` methods + tests ready.
- Phase 2 (logic agent): sync from Excel, cover letter only from the reviewed pack, grounding audit on Apply.

## Next step
- Wait for CI checks on PR #134 (`Distribution & Test Suite`, `Windows`, `Mac arm64`, `Mac x64`), then merge PR #134.
- Logic agent: proceed to Phase 2.

## Known problems / not verified
- Live `apply` submission and the live `pywebview` desktop window on Mac/Windows have not been exercised against real job sites.

## How to run
- Tests: `python3 -m pytest backend/tests -q`
- UI preview: serve `macapp/panel/` (`python3 -m http.server`) and open `dev/index.html` (or `dev/index.html?empty`) in a browser.
