# Changelog

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
