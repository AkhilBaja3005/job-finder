# Brief: make the desktop app drive the staged workflow

Read `AGENTS.md` and `API_CONTRACT.md` first.

## Problem
PR 125 split the CLI into `scan` (Excel only) -> `approve` -> `prepare` -> `review --ok` -> `apply`. The app still calls `scan --auto-apply` (now ignored), reads the CSV tracker, and schedules a scan that never applies.

## Phase 0 (logic agent, own small PR)
1. `build_scan_args` in `macapp/scan_panel.py`: never `--auto-apply`; practice = `scan --dry-run`. New `build_apply_args(options)`: `apply`, `--submit` only for a real run, plus limit and headless.
2. `read_tracker`, `_csv_all`, `set_status`, `_sync_and_report` read the Excel tracker (`get_tracker()`), CSV as fallback.
3. `macapp/scheduler.py`: daily `scan` then `apply` (preview unless the user chose real); "real" means `--submit`. Mac launchd and Windows schtasks.

## Phase 1 (UI agent for `panel/*`, logic agent for the Api methods)
Left-nav tabs: Search, Review, Packs, Documents, Apply, Applications, Settings. A "next step" banner on top of every tab: says where the user is and has one button for the next action ("12 jobs found: Review them", "3 approved: Prepare packs", "2 packs need sign-off", "1 ready: Apply"). Driven by `next_step()`.
- Search: topic, level, location, timeframe, saved searches, Run and Dry-run (funnel counts, dropped titles). Live log stays scrollable and symmetric with the other panes.
- Review: table of jobs, Approve checkboxes, "approve all at or above N%", Revoke.
- Packs: state per approved job, "Prepare packs" with progress.
- Documents: view tailored CV, cover letter, REVIEW.md in the app; "Docs OK" button.
- Apply: signed-off jobs only; Preview or Submit (confirm dialog); daily cap; per-application grounding audit and questions.
- Update the guided tour to this order with empty states ("nothing approved yet").
- Every new method goes in `panel/dev/mock-api.js` and `panel/dev/index.html`.

## Phase 2 (logic agent)
Account sync reads Excel rows. Cover letter at apply time is pasted only from the reviewed pack, never generated live. `apply` uses the grounding tools and returns the audit. The Google sign-in gate covers every stage.

## Done means
- [x] Phase 0 (PR #133): arg builders, Excel tracker read/write, scheduler (Mac and Windows).
- [x] Phase 1 (PR #134): left-nav tabs (`Search`, `Review`, `Packs`, `Documents`, `Apply`, `Applications`, `Settings`), `next_step()` banner, guided tour, `macapp/panel/dev/mock-api.js`, all 12 `API_CONTRACT.md` methods on `Api` in `macapp/scan_panel.py`, and unit tests in `backend/tests/test_mac_app.py`.
- [x] Phase 2 verified: `_csv_all` / `sync_to_cloud` reads Excel rows, `job_finder/commands/apply.py` pastes `cover_letter.txt` from the reviewed pack only, `browser_use_agent.py` runs `grounding.py` and returns `grounding` summary, and `_guarded` covers all new `Api` methods.
- [ ] Merge PR #134 once CI checks (`Distribution & Test Suite`, `Windows`, `Mac arm64`, `Mac x64`) pass, and verify the live desktop window on Mac/Windows.
