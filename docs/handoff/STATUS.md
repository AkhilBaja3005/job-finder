# Handoff status

Last updated by: Antigravity (UI agent) on branch `feat/app-staged-ui`

## Where things stand
- PR 125 (staged Excel workflow: scan, approve, prepare, review, apply) is merged on `main`.
- **UI agent (Phase 1)** is implemented on `feat/app-staged-ui` (`macapp/panel/app.js`, `macapp/panel/styles.css`, `macapp/panel/dev/mock-api.js`):
  - Left-nav tabs: Search, Review, Packs, Documents, Apply, Applications, Settings (`Cmd/Ctrl+1..7`).
  - Next-step banner on top of every tab driven by `next_step()`.
  - Search tab: topic, level, location, timeframe, saved searches (`list_searches()`), Run / Dry-run (`mode: "practice"`), symmetric scrollable Activity log.
  - Review tab: jobs table (`list_jobs`), Approve/Revoke checkboxes & per-row actions, "Approve ≥ N%" (`approve_jobs`, `revoke_jobs`).
  - Packs tab: approved pack states (`list_packs`), "Prepare packs" with `poll()` progress (`prepare_packs`).
  - Documents tab: master-detail viewer for `REVIEW.md`, Cover Letter, Fit Analysis, Tailored CV (`pack_documents`, `open_pack_file`), and "Docs OK" (`signoff_pack`).
  - Apply tab: signed-off jobs only (`list_ready`), daily cap bar, Preview vs Submit (with confirm dialog), `start_apply`, and per-application grounding audit & form questions.
  - Applications tab: Grounding audit dialog on rows with `grounding`.
  - Guided tour updated to the staged workflow order; empty states verified (`?empty`).
  - All new `API_CONTRACT.md` methods implemented in `macapp/panel/dev/mock-api.js` and verified in browser with 0 console errors.

## Plan
- Phase 0 (logic agent, small PR): fix arg builders, Excel tracker read/write, scheduler.
- Phase 1 (UI agent + logic agent): UI done on `feat/app-staged-ui`; logic agent implements the `API_CONTRACT.md` methods in `macapp/scan_panel.py`.
- Phase 2 (logic agent): sync from Excel, cover letter only from the reviewed pack, grounding audit on Apply.

## Next step
- Logic agent: finish Phase 0 / Phase 1 `macapp/scan_panel.py` methods matching `docs/handoff/API_CONTRACT.md`, then test `macapp/panel/` against the real Python `Api`.
- UI agent: open PR for `feat/app-staged-ui` once ready or after integrating with logic agent's `scan_panel.py` changes.

## Known problems / not verified
- UI has only been verified against `macapp/panel/dev/mock-api.js` in a local browser (`1280x820`), not inside the live pywebview desktop window on Mac/Windows.
- Live `apply` submission through the staged path is unverified (PR 125 notes this too).

## How to run
- Tests: `python -m pytest backend/tests -q`
- UI preview: serve `macapp/panel/` (`python3 -m http.server`) and open `dev/index.html` (or `dev/index.html?empty`) in a browser.
