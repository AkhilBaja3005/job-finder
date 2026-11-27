# Working rules for any coding agent (Claude Code, Antigravity, others)

Job Finder: browser agent that finds jobs, tailors resumes and fills applications. CLI (`job_finder/`), FastAPI server (`backend/`), Chrome extension, desktop app (`macapp/`, pywebview).

## Before you start
1. Read `docs/handoff/STATUS.md` (where the last agent stopped) and the brief it points to.
2. Read `docs/STAGED_WORKFLOW.md` for the scan, approve, prepare, review, apply stages.
3. Work on your own branch from `origin/main`. Never edit the same branch as another agent at the same time.

## Rules
- Run tests with `python -m pytest backend/tests -q` (a venv with `backend/requirements.txt` plus `pytest-asyncio`).
- Add tests for every change. Keep new-code coverage at 90% or more.
- Never commit secrets, `.env`, `.coverage`, or binaries. Never print or repeat a generated key or password.
- Show UI changes locally before pushing: open `macapp/panel/dev/index.html` (uses `panel/dev/mock-api.js`). Add every new `Api` method to the mock.
- Keep the Google sign-in gate, the grounding tools (`backend/services/grounding.py`, `browser_use_tools.py`) and the Chrome dock working.
- One PR per phase. Merge only when "Distribution & Test Suite", "Windows" and "Mac arm64" pass. Do not publish a numbered release.
- Do not change `.github/workflows/sync_hf.yml` behaviour (Hugging Face rejects binary files).

## When you stop (even half-done)
Commit, push your branch, and update `docs/handoff/STATUS.md`: done, not done, how to run, known problems, exact next step.

## File ownership (so two agents do not collide)
- Logic agent: `macapp/scan_panel.py`, `macapp/scheduler.py`, `backend/`, `job_finder/`, tests.
- UI agent: `macapp/panel/app.js`, `macapp/panel/styles.css`, `macapp/panel/dev/*`.
- Shared contract: `docs/handoff/API_CONTRACT.md`. Change it only in a commit both sides can see, and tell the other agent in `STATUS.md`.
