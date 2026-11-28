# App API contract (panel JS <-> `macapp/scan_panel.py` Api)

Every method returns JSON. On failure: `{"ok": false, "error": "plain-language message"}`. Every method needs the Google sign-in gate to pass. The logic agent implements these in `scan_panel.py`; the UI agent builds against the same shapes in `panel/dev/mock-api.js`. Existing methods (`get_state`, `poll`, `start_scan`, `get_results`, `save_prefs`, `get_about_you`, `live_view`, ...) stay as they are unless listed here.

## Next step banner
`next_step()` -> `{"ok": true, "stage": "search|review|packs|documents|apply|done", "title": "12 jobs found", "button": "Review them", "goto": "review", "counts": {"scanned": 12, "approved": 0, "packs_ready": 0, "needs_signoff": 0, "ready_to_apply": 0, "applied": 0}}`

## Search
- `list_searches()` -> `{"ok": true, "current": "ai-intern", "searches": [{"name": "ai-intern", "topic": "applied AI", "level": "intern", "location": "London", "jobs": 41, "updated": "2026-11-27"}]}`
- `start_scan(options)` (existing) options gain: `topic`, `level` (`intern|graduate|experienced|all`), `search` (saved name), `into`. Never sends `--auto-apply`. `mode: "practice"` runs `scan --dry-run` and the log ends with the funnel (found per source, removed per stage, dropped titles).

## Review
- `list_jobs(search=None)` -> `{"ok": true, "jobs": [{"id": "12", "role": "AI Engineer Intern", "company": "Acme", "level": "intern", "years": "not stated", "fit": 82, "match": "Core|Related", "closing": "2026-12-15", "url": "https://...", "approved": false}]}`
- `approve_jobs({"ids": ["12","14"]} | {"min_ats": 75} )` -> `{"ok": true, "approved": 2}`
- `revoke_jobs({"ids": ["12"]})` -> `{"ok": true, "revoked": 1}`

## Packs
- `list_packs()` -> `{"ok": true, "packs": [{"id": "12", "role": "...", "company": "...", "state": "not_started|preparing|ready|needs_signoff|signed_off", "error": ""}]}`
- `prepare_packs({"ids": []})` (empty = all approved) -> `{"ok": true}`; progress comes through `poll()` like a scan.

## Documents
- `pack_documents(id)` -> `{"ok": true, "cv_pdf": "path", "cover_letter": "text or empty", "review_md": "text", "fit": "text"}`
- `open_pack_file(id, "cv|cover|jd|review")` -> `{"ok": true}`
- `signoff_pack(id)` -> `{"ok": true}` (wraps `review --ok ID`)
- `signoff_ready_packs()` -> `{"ok": true, "signed_off": 2, "skipped": 0}` (signs off all prepared packs passing `check_signoff_allowed`)

## Apply
- `list_ready()` -> `{"ok": true, "jobs": [...same as list_jobs, signed off only...], "cap": {"used": 3, "limit": 20}}`
- `start_apply(options)` options: `{"mode": "preview|submit", "limit": 5, "headless": false}`. `submit` only after a UI confirm dialog. Builds `apply` (+ `--submit` for submit). Progress through `poll()`.
- Each finished application row carries `grounding`: `{"answered_from_profile": 9, "no_data": [], "stopped": [], "ungrounded": [], "verified": true}` and `questions: []`.

## Applications (existing screen)
Same shape as today, now read from the Excel tracker (`backend/services/excel_tracker.get_tracker()`); CSV only as a fallback when no workbook exists.
- `set_status(url, stage)` -> `{"ok": true}`
- `draft_followup(url="", job_id="")` -> `{"ok": true, "subject": "...", "body": "...", "company": "...", "title": "..."}`

## Settings & State
- `get_state()` also includes `update: {"available": bool, "latest": str, "url": str}`, `boards: {"ready": bool, "updated": str, "indexing": bool, "done": int, "total": int}`, and `saved_answers_count: int`.
- `get_saved_answers()` -> `{"ok": true, "items": [...], "suggestions": [...], "max_entries": 40, "max_chars": 600}`
- `save_saved_answers(items)` -> `{"ok": true, "saved": int}`

## LaTeX CV (Documents tab, Tailored CV)
| Method | Returns |
|---|---|
| `get_pack_latex(id)` | `{ok, tex, source: "saved"\|"generated", available, pages: [png data URIs], in_use}`. Nothing is compiled. |
| `compile_pack_latex(id, tex)` | Saves `cv.tex`, compiles to `cv_latex.pdf` (tightens spacing and font until one page). `{ok, pages, page_count, fill, warnings, tightened}` or `{ok: false, error}`. `warnings` lists numbers, tools or names not found in the resume or profile; they never block. |
| `use_pack_latex_pdf(id)` | Copies `cv_latex.pdf` over `cv.pdf` (what applications upload) and sets `cv_source: "latex"` in `manifest.json`. |
| `reset_pack_latex(id)` | Deletes `cv.tex` and `cv_latex.pdf`; returns the freshly generated source like `get_pack_latex`. |

Compiling needs Tectonic on the computer (`available: false` otherwise; the standard HTML CV keeps working). Page previews need `pypdfium2`.

## Skills the candidate confirms (Documents tab, Evidence & Risk)
| Method | Returns |
|---|---|
| `confirm_experience(skill, evidence, group="")` | Saves `{skill, evidence, group, confirmed_on}` under `candidate.confirmed_experience` in the profile. `skill` is 2-60 characters, `evidence` is the candidate's own sentence (20-500 characters). `{ok, items}` or `{ok: false, error}`. |
| `list_confirmed_experience()` | `{ok, items}` |
| `remove_confirmed_experience(skill)` | `{ok, items}` |

This is the only path by which a skill that the resume does not show can reach a CV. The skill is listed in the chosen skill group (default "Additional skills") on CVs built afterwards; the evidence sentence is used to check claims and is never printed on the CV. The pack's `evidence_panel.keywords_confirmed` lists the job keywords that are met this way.
