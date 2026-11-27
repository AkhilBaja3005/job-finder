# Handoff status

Last updated by: Claude Code (setup only, no app code changed)

## Where things stand
- PR 125 (staged Excel workflow: scan, approve, prepare, review, apply) is merged on `main`.
- The desktop app (`macapp/`) was NOT updated for it and is broken: a real run only discovers jobs, the Applications screen and sync read the old CSV, the daily schedule never applies.
- Nothing from `APP_STAGED_UI.md` has been built yet.

## Plan
- Phase 0 (logic agent, small PR): fix arg builders, Excel tracker read/write, scheduler.
- Phase 1 (UI agent + logic agent): tabs Search, Review, Packs, Documents, Apply, plus a "next step" banner. Contract in `API_CONTRACT.md`.
- Phase 2 (logic agent): sync from Excel, cover letter only from the reviewed pack, grounding audit on Apply.

## Next step
Logic agent: do Phase 0 on branch `feat/app-staged-logic`. UI agent: start Phase 1 against the mock in `macapp/panel/dev/mock-api.js` on branch `feat/app-staged-ui`, after reading `API_CONTRACT.md`.

## Known problems / not verified
- Nothing in the staged flow has been tried on a real Mac or Windows PC.
- Live `apply` submission through the staged path is unverified (PR 125 notes this too).

## How to run
- Tests: `python -m pytest backend/tests -q`
- UI preview: open `macapp/panel/dev/index.html` in a browser.
