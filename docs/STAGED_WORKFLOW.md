# Staged workflow: scan, approve, pack, review, apply

This is the Excel-driven workflow added alongside the original commands: every search gets its own Excel, you approve jobs by hand, each approved job gets its own folder with a tailored CV, and only approved and signed-off jobs are applied to.

## The workflow, step by step

### Step 1: Search: `job-finder scan`

```bash
job-finder scan                                       # your saved defaults (profile: topics + level + locations)
job-finder scan cyber security internships            # plain words; level word (intern/graduate/junior/senior) is picked out
job-finder scan --topic "applied AI, cyber security" --level intern
job-finder scan quantum computing graduate roles --timeframe 1m --location "Manchester, UK"
```

What happens:

1. **Topic → field map** (once per topic, cached in `data/topic_terms.json`): the LLM lists title words for every sub-area (`include`), look-alikes to drop (`exclude`, e.g. *security guard*) and extra board searches (`search`). Inspect or rebuild it with `job-finder topic cyber security [--refresh]`; edit the JSON by hand to tune it.
2. **Search** across LinkedIn, Indeed, Jobserve, Greenhouse/Lever/Ashby/Workday/BambooHR company boards and more, using the topic plus the sub-area searches.
3. **Filter** on the *title*: must fit the field, carry a level word, and not be senior (for intern/graduate searches). Every scan prints a sample of what it dropped and why.
4. **Score** each survivor against your profile (section 5) and look for a **closing date** (job text, page metadata, or a quoted deadline).
5. **Save** everything new to `applications_tracker/scanned_jobs.xlsx`. Nothing is applied to.

Useful options: `--limit 20`, `--min-ats 70`, `--loose` (also read descriptions), `--exact` (only your own words), `--no-ai-score`, `--no-enrich`, `--sponsor-only`, `--timeframe 24h|1w|1m`, `--skip-portals none`. See `job-finder scan --help`.

**`job-finder scan ... --dry-run`** is a search-only test: it writes nothing and scores nothing, and prints the whole funnel (postings found per source, how many each stage removed, and *every* removed title with its reason). Use it whenever the number of saved jobs surprises you.

> **Why "130 found" can become 15 saved:** "found" counts everything every source returned. Job boards like Jobserve and Indeed ignore "Intern" and return permanent roles, which the level filter removes; jobs already in your tracker are skipped; off-topic titles are dropped. Real internships come mostly from LinkedIn. **Internships stay open for weeks, so use a month window (`--timeframe 1m`, or `timeframe` in your profile) for the first scans** (a one-week window found 1 new applied-AI internship, a month found about 20).

#### One scan, three Excels: intern / graduate / experienced

Type a topic or a few job titles **without a level** and *every* job found is filed into the Excel for its level, so nothing is lost:

```bash
job-finder scan --role "ai security engineer, ai red team engineer, llm security engineer"
job-finder scan cyber security                       # same: no level typed -> all levels
```

| Excel | What goes in | Extra columns |
|---|---|---|
| **intern** | internships, placements, year-in-industry, summer analyst | |
| **graduate** | graduate schemes, junior / entry-level / early-careers roles, apprenticeships, and roles asking for 0-1 years | **Years Exp** (when stated) |
| **experienced** | everything else: mid, senior, lead ... | **Years Exp** (`3+`, `5-7`, `not stated`) and **Role Level** (Mid / Senior / Lead ...) |

* The **title** decides first ("Graduate ...", "Senior ..."); only a neutral title like "Security Engineer" is judged from the **job description**: 0-1 years of experience means graduate, 2+ means experienced. Company-history lines ("founded 10 years ago") are ignored.
* **Sampling and expansion:** the titles you type are expanded into ~25 realistic job-title variants and searched across every source (plain, `Intern` and `Graduate` wordings). Then a **second round** searches the exact-niche titles the first round found. `--expand 0` (or `--no-expand`) turns this off, `--expand 2` adds another round.
* **Match column:** `Core` = the exact niche you asked for (e.g. "AI Security Engineer"); `Related` = an adjacent role (e.g. "Security Engineer", "AI Safety Researcher"). Expansion only learns from Core titles, so it cannot drift into generic roles. `--core-only` keeps just Core.
* **AI scoring** is spent on intern and graduate roles first (`--ai-limit 60`, `--score-all` for everything); experienced roles get the free keyword score so your LLM quota lasts.
* Type a level (`--level intern|graduate|experienced`, or "internships" / "graduate roles" in the sentence) to search just that one. `--level all` is the default when you typed a topic but no level; with nothing typed at all, your profile's topics and level are used.

#### One Excel per search

Every search has **its own folder, its own Excel files and its own application packs**, so a cyber-security search never mixes with your AI search:

```bash
job-finder scan cyber security graduate roles          # new topic + level  -> NEW Excel   (searches/cyber-security-<id>_graduate/)
job-finder scan cyber security graduate roles          # same search again  -> UPDATES that same Excel with only the new postings
job-finder scan --search cyber-security-graduate       # repeat a saved search by name (its topics, level and location are remembered)
job-finder scan --into cyber-security-graduate ai safety graduate   # add a different query's results to an existing Excel
job-finder scan --into ~/Desktop/my_list.xlsx ...      # ...or to any .xlsx file you choose
job-finder scan applied AI internships --name ai-intern             # choose the Excel's name yourself
```

```bash
job-finder searches                  # list every search: topics, level, jobs, approved, applied, last scan (* = current)
job-finder searches use cyber        # switch the search that approve / prepare / review / apply / open work on (a unique prefix is enough)
job-finder open --search cyber       # or name the search for a single command (works on approve, prepare, review, apply, tracker too)
job-finder searches move --from main --to cyber-security-graduate --ids 46-52   # move not-yet-approved jobs between Excel files
```

* The Excel **is** the source of truth: edit statuses, tick **Approve**, delete or add notes, and every command respects what is in the file.
* The same topic + level always maps to the same Excel (case-insensitive), so repeating a search only adds new postings. After a scan, that search becomes the **current** one.
* **A job applied to in one search is never applied to again from another**, and a scan skips jobs you already applied to in any search.
* Packs live in `applications/<search>/`, so IDs never collide between searches. The original single workbook pair is the search called `main`.

#### Where the jobs come from

| Source | How | Needs |
|---|---|---|
| **Company career boards** (Greenhouse, Lever, Ashby): ~15,000 companies | public job APIs, indexed locally by `job-finder boards refresh` | nothing (run the refresh once, then about weekly) |
| LinkedIn | public guest search | nothing |
| Indeed, Jobserve, TargetJobs, Reed | existing scrapers/APIs | Reed needs a free `REED_API_KEY`; Indeed often blocks automated access |
| **Adzuna** (aggregates many UK boards) | official API | free `ADZUNA_APP_ID` + `ADZUNA_APP_KEY` (https://developer.adzuna.com) |
| Reddit / Hacker News hiring threads | leads only (not saved as jobs) | nothing |

```bash
job-finder boards refresh      # builds data/board_index.db: every open London/UK role on ~8,500 reachable boards (about 6 minutes)
job-finder boards status       # what is indexed and how old it is
```

Scans search that index instantly, so a scan covers thousands of employers (direct application links, which are better to apply through than aggregator links). When the same job appears on LinkedIn and on the company's own board it is saved **once, with the company's link**. Board jobs are *currently open* postings, so the time window does not apply to them. `job-finder scan ... --no-boards` skips the index.

**Sites that are deliberately not scraped:** Glassdoor, Monster, CV-Library, Milkround, Gradcracker and Jooble block automated access (403 / bot protection) and their terms forbid scraping; Trackr and Jack & Jill have no public job listings (login-only app / recruiter chat). Adzuna and Reed (official APIs) are the legitimate way to cover many of those boards' jobs.

### Step 2: Review in Excel and approve

```bash
job-finder open            # opens scanned_jobs.xlsx
```

Sort and filter freely. On the jobs you want, set **Approve = Yes** (dropdown), save and close the file, then:

```bash
job-finder approve                       # moves exactly the ticked rows into approved_jobs.xlsx
job-finder approve --ids 3,7             # or approve by ID without touching Excel
job-finder approve --min-ats 85          # or every open row scoring at least 85
job-finder approve --revoke --ids 7      # take one back out (unless already applied)
job-finder approve --list                # what is waiting
```

Rows that cannot be applied to are refused with a reason (already applied, you fail a hard requirement, closing date passed, no URL).

### Step 3: Application packs: built automatically by `approve`

For every newly approved job, one folder under `applications/` is created (details in section 4):

* the **job description** is saved,
* the **CV is tailored** to the job (reordered/trimmed from *your own* bullets, with a line-by-line change log and a keyword before/after table),
* a **cover letter is written only if the posting asks for one** (`--cover-letter always|never` to force),
* a **`REVIEW.md` checklist** tells you what to check.

```bash
job-finder prepare --ids 3                  # (re)build a pack; keeps your edits to cv.json / cover_letter.txt
job-finder prepare --ids 3 --redo           # regenerate from scratch
job-finder prepare --ids 3 --render-only    # rebuild the PDFs after you edited cv.json / cover_letter.txt (no LLM call)
```

### Step 4: Review and sign off (manual, required)

```bash
job-finder review                  # list packs and whether you signed them off
job-finder review --open 3         # open that job's folder
#   read REVIEW.md, cv.pdf, cv_changes.md, cover_letter.txt; edit cv.json / cover_letter.txt if you want
job-finder review --ok 3           # "I reviewed these documents": allows apply to use them (Docs OK = Yes)
```

Any regeneration or re-render resets the sign-off, so you always approve the documents that will actually be sent.

### Step 5: Apply

```bash
job-finder apply --dry-run --limit 1       # PREVIEW: opens the form, fills it in, STOPS before Submit. Start here.
job-finder apply --submit                  # really submits every signed-off job (shows the list, asks y/N)
job-finder apply --submit --ids 3          # just one
job-finder apply --retry --submit          # also retry rows that ended in Needs Review
job-finder apply "<job url>" --submit      # one job outside the queue
```

`apply` reads **only `approved_jobs.xlsx`**, and only rows with **Docs OK = Yes**. For each job it uploads **that pack's `cv.pdf`**, pastes **that pack's reviewed `cover_letter.txt` verbatim** (the agent is forbidden from writing its own), then records the result in **both** workbooks and in the job's `apply_log.md`:

| Outcome | Status | Meaning |
|---|---|---|
| Submission confirmed | **Applied** | the confirmation page/text was detected |
| CAPTCHA / login wall / unclear result / error | **Needs Review** | reason in *Notes*; a screenshot is copied into the pack |
| Posting removed | **Closed** | |
| Preview run | unchanged | a dated note is added; nothing is marked Applied |

Safety nets: a missing resume file stops the run before any browser opens; applied/skipped/closed jobs (also if *you* mark them in the scanned file) are never applied to again.

---

## Files and folders the tool generates

```
your Job Finder working folder   (everything below is private; do not commit it)
│
├── .env                                  private: API keys and settings
├── candidate_profile.json                private: YOUR profile = the single source of truth for CV / letters / scoring
│
├── applications_tracker/
│   ├── scanned_jobs.xlsx                 private: the original search ("main"): EVERYTHING it found (you review here, tick Approve)
│   ├── approved_jobs.xlsx                private: its queue `apply` reads (only jobs you approved)
│   └── searches/<search-name>/           private: ONE FOLDER PER SEARCH, each with its own
│       ├── search.json                   what was searched (topics, level, location) + scan history
│       ├── scanned_jobs.xlsx             everything that search found
│       └── approved_jobs.xlsx            that search's apply queue
│
├── applications/                         private: ONE FOLDER PER APPROVED JOB (per-search packs are under applications/<search-name>/)
│   └── 0007_acme-ltd_applied-ai-intern/
│       ├── REVIEW.md                     what to check, in order, plus any warnings
│       ├── job.md                        link, location, closing date, scores, why it fits
│       ├── job_description.txt           the full posting text (saved so it cannot disappear)
│       ├── fit_analysis.md               each requirement: met / partial / NOT met, with your evidence
│       ├── cv.pdf                        the tailored CV that will be UPLOADED
│       ├── cv.json  cv.html              editable source of cv.pdf (edit cv.json, then `prepare --render-only`)
│       ├── cv_changes.md                 exactly what changed vs your profile, keyword coverage before/after, gaps
│       ├── cover_letter.txt              only if the job asks for one: pasted VERBATIM into the form
│       ├── cover_letter.pdf              the same letter as a file, for forms that want an upload
│       ├── cover_letter_notes.md         validator warnings, requirements you cannot evidence, alternative openings
│       ├── apply_log.md                  added by `apply`: every preview/submit with time, result, screenshot
│       ├── screenshot_*.png              added by `apply` when the agent stops for review
│       └── manifest.json                 machine-readable summary
│
└── data/                                 private caches (safe to delete)
    ├── topic_terms.json                  the field map per topic: EDITABLE (include / exclude / search)
    ├── board_index.db                    open London/UK jobs from ~8,500 company career boards (`job-finder boards refresh`)
    ├── board_seeds.json                  the list of company boards to visit (refreshed weekly)
    ├── fit_cache.db                      cached fit analyses (stable scores, no repeat LLM calls)
    └── jd_cache.db …                     cached job pages
```

**`scanned_jobs.xlsx` / `approved_jobs.xlsx` columns:** ID · Company · Job Role · Location · Platform · Posted · **Closing Date** · **Applied** · **Status** · **Approve** · ATS % · Skills % · Experience % · Role Fit % · **Scored By** · Matched / Missing Skills · **Fit Summary** · UK Sponsor · Level · **Role Level** · **Years Exp** · **Match** (Core/Related) · Salary · Date Found / Applied · **Notes** · **Docs OK** · **Cover Letter** · **Pack Folder** · Job URL.
Statuses: New → **Approved** → **Applied** (or Needs Review / Closed) · also Shortlisted, Interview, Offer, Rejected, Skipped, Withdrawn. Row colours: green = applied, blue = approved, orange = closes within 7 days, grey = closed. Save and close the file in Excel before running `approve`/`apply`.

---

## How scoring works (and why it is not "keyword matching")

No real ATS gives candidates a number, so this is an **evidence-based fit estimate**, not a prediction of one vendor's system.

* The LLM reads the **full job description** and lists its real requirements (any field, no fixed skill list). Each is marked **met / partial / not met** against your profile **with your evidence quoted**. The numbers are plain arithmetic over those verdicts (must-haves count 3× nice-to-haves), so they are explainable and cached/stable.
* **Hard requirements** (citizenship, clearance, "must be enrolled in a PhD", "must not already hold a degree"…) give **0% and Status = Skipped**; a missing *degree-level* requirement caps the score at 50.
* **Scored By** shows the engine: `AI` (full analysis), `Keyword` (fixed-list fallback if the LLM was unavailable) or `Listing estimate` (no description could be fetched).
* `job-finder ats --jd-url "<link>"` explains the score for one job requirement by requirement.

### How the CV is tailored without inventing anything

The model never writes a free-form CV. It returns a **plan over your existing material** (which bullets to keep and in what order, how to order your skills, a retargeted summary, a few optional rewordings, the job's key terms). Code then verifies it, and anything unverifiable is thrown away:

* roles, companies, dates and degrees are copied untouched; every role keeps at least one bullet,
* a summary or reworded bullet may only use **numbers and tool names that already exist in your profile**, must keep the original's numbers/headline proof, may only use **words your profile already uses**, and may not contain marketing filler ("passionate", "highly motivated"…) or **job keywords you have no evidence for**,
* a skill is shown only if your profile mentions it,
* if the first plan has problems the model is told exactly what was wrong and gets **one** retry; what still fails is dropped and your original wording stays.

`cv_changes.md` lists every change, every rejected suggestion, and the job keywords you do **not** have evidence for (shown as gaps; never added). The CV is a single-column, text-based PDF (an ATS can read it) that is tightened automatically to fit one page. Cover letters use a separate generator with a fact-checker (length, clichés, placeholders, numbers not in your profile) and a plain factual fallback.

---

