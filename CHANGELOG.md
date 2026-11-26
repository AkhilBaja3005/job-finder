# Changelog

## Unreleased

### Added
- Mac app: one-click "Review" opens a job in the signed-in Chrome; status changes follow to job-finder.space
  (`POST /applications/status`); a rough token count for the day; "Report a problem" (copies a report with keys removed);
  a daily run through launchd (practice run by default); "Saved answers" for questions the profile cannot answer;
  relevance rules before applying (seniority in the title, location, "no visa sponsorship" lines).
- Daily application limit (`MAX_APPLICATIONS_PER_DAY`, default 25).
- A fake job board and `scripts/agent_bench.py` to test the agent without a real application; `scripts/backup_supabase.py`;
  `scripts/reencrypt_saved_keys.py`; `scripts/dev_setup.sh`; an uptime check workflow; privacy and terms drafts.

- Mac app (Apple Silicon, unsigned for now) for the job search and auto-apply part: `Job Finder.app` is a native-feeling control panel
  for `job-finder scan`. A sidebar app with Run, Applications and Settings; a first-run checklist; a confirmation dialog before applying
  for real; a live activity log with counts; Mac notifications; update checks; one log file per run; a real menu bar (Cmd+C and Cmd+V work
  in every field); a unified title bar; and the Job Finder logo as the app icon. It uses your existing Job Finder folder if you point it at
  one. When `SUPABASE_URL` and a key are in the `.env`, it shows your project's applications and adds any local ones the project is missing.
  The page scraper's browser downloads on first launch, with a visible status and a Retry button. Build it with `macapp/build_mac.sh`, or run
  the "Build Mac app" workflow, which attaches the .dmg to a release. See `macapp/README.md`.

### Fixed
- The web app assumed the backend was on port 8000 whenever it was opened on localhost. It now uses the address it is
  served from, and only the Vite dev server points at 8000.

### Account data
- Account data controls: `GET /user/export` returns everything stored for the account as JSON (saved API keys are left out),
  and `DELETE /user/account` removes the account, resumes and application history after the account email is typed to confirm.
  Both are in the website's extension panel, next to a link to download the Mac app.

## 1.9.2

### Added
- `job-finder outcomes`: how every application attempt ended, with a success rate per job site and the most common reason
  for a miss (`--recent 10` lists the last attempts with their reasons and final-form screenshots). Each attempt is saved
  as one line in `applications_tracker/run_outcomes.jsonl`.

### Changed
- The browser agent's default Claude model is now Sonnet. Haiku kept returning output the agent could not read.
  Text generation still defaults to Haiku. Set `BROWSER_USE_ANTHROPIC_MODEL` to change either.
- Chrome starts a new process after 6 tabs (was 30), and one application has 10 minutes (was 15). Override with
  `JOB_FINDER_MAX_TABS` and `BROWSER_USE_TIMEOUT`.
- A Gemini 503 ("high demand") is retried twice with a short wait before the pipeline moves to another model or provider.

### Fixed
- Resume upload failing with "Node is not a file input element" (seen on Ashby): the agent is now told how to find the real
  file input behind the visible button.

## 1.9.1

### Fixed
- The browser agent failed every step with `Unsupported value: 'temperature' does not support 0.2 with this model`
  when OpenAI was the primary provider with `gpt-6-luna`. browser-use sends `temperature=0.2` and
  `frequency_penalty=0.3` by default, and newer OpenAI models reject them. Only `gpt-4` and `gpt-3` models get them now.

## 1.9.0

### Security
- Sync codes can no longer be brute-forced: failed sync-code lookups are counted per client IP (10 per 10 minutes by
  default, `SYNC_GUESS_MAX` and `SYNC_GUESS_WINDOW_SECONDS`) and then answered with 429. New accounts get 10-character
  codes (about 3.6e15 values). `POST /user/rotate_sync_code` and a "New key" button on the website replace an old
  6-character code. The extension download takes the key in a header instead of the URL.
- Saved LLM API keys are encrypted in the database when `KEY_ENCRYPTION_SECRET` is set (old plain values still read),
  and `/user/me` no longer returns the key, only whether one is set and its last 4 characters. The website keeps a key
  typed into the page in `sessionStorage`, not `localStorage`.
- `/answer_question` and `/user/solve_field` are rate limited per IP and per account, and rate limits use the real
  client IP from `X-Forwarded-For` (`TRUSTED_PROXY_COUNT`, default 1) instead of the proxy's address.
- The interactive API docs and `/openapi.json` are off unless `ENABLE_API_DOCS=1`. CORS no longer allows credentials.
- API-key hints in logs show 4 characters instead of 6. The website no longer shows a sample sync key to signed-out visitors.
- The browser agent's prompt now treats page text as untrusted, keeps the account password to the portal's own login
  form, and forbids guessing answers that are not in the profile.

- The server no longer trusts a public Supabase key silently: it prefers `SUPABASE_SERVICE_KEY` (the secret key),
  warns at startup and in `job-finder doctor` when `SUPABASE_KEY` is a publishable or anon key, and no longer uses
  that key to sign OAuth client IDs. `docs/supabase_rls.sql` turns on row-level security for all four tables.
  With a publishable key and RLS off, anyone who holds the key can read the users, resumes and applications tables.
- The extension accepts the sync key and resume data only from the Job Finder web app (before, any website could
  pair it with its own account), and its host permissions are limited to the backend and the GOV.UK sponsor
  register (3.6.0).
- Server-side fetches refuse private, loopback, link-local and cloud-metadata addresses, including after
  redirects (the job scraper, the apply pre-flight check, the recruiter lookup, and the scraper's browser requests).
  The browser agent is blocked from `localhost`, `127.0.0.1` and `169.254.169.254`; `BROWSER_USE_ALLOWED_DOMAINS`
  can restrict it to a list of sites.
- `PORTALS_PASSWORD_MODE=per_site` gives each job-portal family its own password, derived from `PORTALS_PASSWORD`,
  so one leaked portal password does not open the others. Off by default, because existing accounts use the shared one.

### Added
- Claude, OpenAI and Gemini keys: `/user/solve_field` now uses the account's saved key, the extension has an optional
  LLM-key field (Settings tab, extension 3.6.0), and a user whose own key is rejected is told that the server's default
  model was used instead. The website label no longer says Gemini only.
- PyPI publishing can use Trusted Publishing, which records signed provenance. Set the repository variable
  `PYPI_TRUSTED_PUBLISHING` to `true` after adding the trusted publisher on PyPI. Without it the token upload is used.
- `openai` is now a declared dependency, and `anthropic` and `openai` have version ranges.
- Claude and OpenAI now work for text generation too (cover letter, resume tailoring, job-fit analysis, form
  answers), not only the browser agent. After NVIDIA and Cloudflare (when enabled), the pipeline tries the providers
  in `LLM_PROVIDERS` order, default `gemini,anthropic,openai`, so a Gemini 429/503 falls back to Claude, then OpenAI.
  Providers without an API key are skipped. Models: `LLM_ANTHROPIC_MODEL` (`haiku`, `sonnet`, `opus` or a full ID,
  default newest Haiku) and `LLM_OPENAI_MODEL` (`luna`, `terra` or a full ID, default newest Luna).
- On the hosted server, a user's own key (`X-Gemini-API-Key` header or the key saved on their account) already selects
  the provider by its prefix (`sk-ant-` Claude, `sk-` OpenAI, `AIza` Gemini). Their key is now used with that
  provider's newest Haiku or Luna, looked up with their own key.

### Fixed
- The model-list cache for Claude and OpenAI is kept per API key (a hash, never the key), so on the hosted server
  one user's model list is never used for another user.
- The Claude and OpenAI helpers sent `temperature`, which `gpt-6-luna` and the current Anthropic SDK reject, and
  used fixed old model names (`gpt-4o`, `claude-3-5-*`). They now pick the model dynamically and omit `temperature`.
- Scan results were recorded as submitted when the agent wrote "was NOT submitted" or "nothing was submitted". A run is
  now a success only with an explicit confirmation and no negation.

## 1.8.0

### Added
- Browser-agent provider order. Set `BROWSER_USE_PROVIDERS` (for example `anthropic,openai,gemini`) to choose the
  primary and secondary LLM provider. Without it, a `claude-*` or `gpt-*` model in `--model` or `BROWSER_USE_MODEL`,
  or an explicitly set `BROWSER_USE_ANTHROPIC_MODEL` or `BROWSER_USE_OPENAI_MODEL`, makes that provider the primary.
  Providers without an API key are skipped. With nothing set, the order stays Gemini, then Claude, then OpenAI.
- Dynamic model choice for Claude and OpenAI, like Gemini. By default the agent asks the provider for its model list
  (cached for an hour) and uses the newest Haiku (Anthropic) or Luna (OpenAI). `BROWSER_USE_ANTHROPIC_MODEL`
  accepts a family name (`haiku`, `sonnet`, `opus`) or a full model ID; `BROWSER_USE_OPENAI_MODEL` accepts `luna`,
  `terra` or a full ID. A full ID is always used as given. If the lookup fails, it falls back to
  `claude-haiku-5-5` and `gpt-6-luna`.
- A Gemini API key is no longer required to start the browser agent when another provider is the primary.

### Changed
- Job-fit analysis no longer asks an LLM for the role-fit score, alignment labels, red flags or tailoring
  suggestions. They are computed from the job description and resume by fixed rules, so the same input always
  gives the same result. Set `USE_LLM_SEMANTIC_SCORING=1` to restore the old LLM step. The cover letter and
  resume text still come from the LLM.
- `search_preferences.required_title_keywords` (for example `["intern", "internship", "placement"]`) skips scan
  results whose title lacks one of those whole words. `min_ats_score_threshold` is now read by the scanner.

### Fixed
- The ATS result now reports the real matched and total required-skill counts. They were always 0/0.
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
