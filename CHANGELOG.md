# Changelog

## Unreleased

### Fixed
- MCP `search_jobs` returned up to 120 jobs with their full descriptions, 150,000 to 210,000 characters in
  one result, which clients rejected as too large. It now returns at most 25 jobs by default, with descriptions
  shortened to 300 characters and the whole result capped at 60,000 characters. A new `limit` argument (max 100)
  controls the count, and `count` still reports how many jobs matched. Use `scrape_job_posting` for a job's full
  text.

## 1.7.1

### Security
- Portal password: the profile template no longer ships a placeholder `portals_password`, and the apply agent
  ignores the old placeholder. Before this, a user who never set a password could have real job-board accounts
  created with a publicly known one. `PORTALS_PASSWORD` in the environment now takes priority over a value in a
  profile file.
- `job-finder setup` asks for the portal password with hidden input and stores it in `.env` (owner-only),
  not in `candidate_profile.json`. Profile files written by the profile tools are chmod 600, and
  `get_candidate_profile` no longer returns the password.
- Cloud server: `/mcp` rejects tokens that match no account (401 `invalid_token`) instead of running tools for
  a throwaway guest, and answers 503 with `Retry-After` when account lookup is unavailable. The `test_` and
  `mock_` token shortcut works only under pytest. `POST /user/profile` no longer copies each user's details into
  the server's shared profile file.
- Cloud server: `save_candidate_profile` and `sync_candidate_profile_from_resume` wrote to one shared
  `candidate_profile.json` instead of the signed-in user's profile. They now require a token, write only to that
  user's profile, and return `UNAUTHENTICATED` otherwise.

### Fixed
- `get_candidate_profile` always returned an empty `work_experience` and no LinkedIn or GitHub link for
  profiles built from an uploaded resume. Both now come from the parsed resume. Work history is stored once,
  under `experience`.
- Trailing periods on skills (`SQL.`, `MCP.`) are removed.
- The wheel left out `manifest.json`, `robots.txt`, `sitemap.xml` and image files (`.ico`, `.png`) of the web app, so a
  pip-installed server had no favicon. They are now packaged, and a test checks that every file in `frontend/public`
  is covered.
- The profile tools refuse to write to `candidate_profile.example.json`.

### Added
- `save_candidate_profile` accepts `work_experience` and `skill_categories`, and no field is required.
- Cloud `sync_candidate_profile_from_resume` rebuilds the profile from the resume you already uploaded when no
  readable file path is given.
- The MCP server reports a title and icons, and the site serves `favicon.ico` and `favicon-192.png`, so MCP
  clients show the Job Finder icon.
- A test guard fails any test that modifies `backend/config/candidate_profile.example.json` and restores it.

## 1.7.0

### Changed
- ATS scoring: unrelated jobs no longer score about 60. A job description with no preferred skills no longer
  grants free preferred-skill points, and when the skills match is low (below 40) the overall score is capped
  at `skills * 1.5 + 20`. Relevant roles keep their high scores. Scores for poor matches are now much lower, so
  a profile's minimum ATS threshold filters more strictly.
- `job_finder/cli.py` was split into modules: `cli_parser.py`, `updates.py` and one module per subcommand under
  `job_finder/commands/`. Behavior and flags are unchanged.
- `scan` prints an end-of-run summary table, including jobs blocked or needing review.

### Fixed
- `job-finder ats --json` no longer mixes log lines into its JSON output.
- Modals for the cover letter and the extension guide close on Escape and expose dialog roles.
- Leftover empty icon markup from the emoji cleanup was removed from the extension popup and two pages.

### Added
- The ATS golden set grew from 4 to 12 cases. Run `python scripts/eval_ats.py` to see the results.
- Regression test that `job-finder setup` creates `.env` and `candidate_profile.json` in a fresh workspace.
- The MCP harness guide lists all 21 tools.

## 1.6.1

### Fixed
- CI: the ATS golden-set fixture (`backend/tests/fixtures/ats_golden.json`) was hidden by the `*.json`
  rule in `.gitignore` and was never committed, so the test suite failed at collection on a clean checkout.
  The fixture is now tracked and `.gitignore` allows JSON files under `backend/tests/fixtures/`.

## 1.6.0

### Security
- OAuth: `/oauth/authorize` requires a registered client, a matching `redirect_uri` and PKCE S256.
  `/oauth/token` requires `code_verifier` and checks `client_id` and `redirect_uri`.
- OAuth: removed the `refresh_token` grant, which returned any submitted string as a valid access token.
- OAuth: authorization sessions expire after 10 minutes and codes after 5. Guest users can no longer be
  authorized. `/oauth/quick-approve` is rate limited and issues a dedicated session token instead of reusing
  the sync code.
- OAuth: `client_id` values are signed (HMAC), so registrations survive restarts and multiple workers.
  Set `OAUTH_CLIENT_SECRET` in production (falls back to `ENCRYPTION_KEY`, then `SUPABASE_KEY`).
  Connectors registered before this release must be re-added once.
- `/mcp` returns 401 with a `WWW-Authenticate` header to unauthenticated cloud callers.
- Cover letters no longer send contact details, passwords or tokens to the LLM (field allowlist).
- `job-finder profile` masks secrets in its output.
- LaTeX: all injected text is escaped; commands such as `\input` and `\write` are stripped.
- Removed hardcoded personal email addresses and phone numbers. Set `NOTIFY_EMAIL`, `OWNER_EMAIL` and
  `CONTACT_EMAIL` where needed (the contact form returns 503 until `CONTACT_EMAIL` is set).

### Fixed
- `/auth/google` redirects browser navigations; `/auth/callback` no longer redirects MCP consent to the SPA dev
  server or builds `?a?b` URLs.
- ATS: the target seniority is read from the job title instead of any mention of "Director" in the body;
  `work_experience` is honored everywhere; ambiguous aliases removed; duplicate `vector database` entry
  merged; clearly overqualified candidates get a small penalty.
- LaTeX slot injection turned `\textbf` into a TAB plus `extbf`; the achievements slot was never applied.
- The tailoring prompt contained the author's own metrics as examples.
- The `--json` output of the CLI is no longer polluted by update notices or progress lines.

### Added
- CLI: rich tables, `--quiet`, `--verbose`, `--debug`, `--no-color`, logging to `~/.job-finder/logs`,
  friendly errors, `doctor`, `config`, `export`, `cover-letter`, `ats --jd-file/--jd-url`, `--json` on
  `status`, `tracker` and `ats`, `--dry-run` on `scan` and `apply`, optional shell completion
  (`pip install job-finder-ai[completion]`). Unknown flags are now errors.
- MCP: `ping`, protocol version negotiation, tool annotations, argument validation, concurrent stdio handling,
  and `confirm_submit` required for auto-submit tools.
- browser-use: total run timeout (`BROWSER_USE_TIMEOUT`), CAPTCHA and login-wall detection, review
  screenshots, `Needs Review (Blocked: ...)` status.
- Cover letters: validation (length, cliches, dashes, unsupported numbers) with one automatic retry;
  the fallback is a plain factual template flagged `fallback`.
- Resume tailoring: warns about numbers not present in the master resume; PDF text extractability check.
- ATS golden-set tests and `scripts/eval_ats.py`.

### Changed
- `backend/mcp` is now `backend/job_finder_mcp` so it no longer shadows the official `mcp` package.
- Root `test_*.py` scripts moved to `scripts/manual/`.
- Version numbers aligned across the package.
