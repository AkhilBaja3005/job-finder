# AI Job Finder Agent

An AI-powered job search and application assistant. Upload a resume once, then let it discover matching job postings, score your fit against a job description, tailor a one-page LaTeX resume and cover letter for a specific role, and (optionally) auto-fill the job application form in a real browser.

The app is a single FastAPI backend serving a React (Vite) single-page frontend, packaged together in one Docker image.

## Features

- **Resume parsing** — upload a PDF/DOCX/TEX resume and extract structured data (contact info, skills, experience, education, projects, GPA) via an LLM.
- **ATS fit scoring** — deterministic skills/experience matching (`ats_scorer.py`) combined with an LLM-based semantic "role fit" score, blended into an overall match percentage.
- **Resume tailoring** — rewrites the candidate's master LaTeX resume for a specific job description, enforces a one-page layout (mechanical spacing adjustments first, LLM condensation as a last resort), and runs an automated "recruiter review" loop that can reject and retry the tailoring before it's shown to the user.
- **Cover letter generation** — produced alongside the tailored resume.
- **Job discovery** — searches LinkedIn and Indeed for postings matching the candidate's resume, dedupes, scores, and ranks them.
- **Export to Overleaf** — one-click export of the tailored (or original) resume as a LaTeX project opened directly in Overleaf.
- **Autofill agent** — drives a real (persistent, visible) Chromium browser via Playwright to fill out a job application form, uploading the tailored resume PDF and answering free-text questions with an LLM, with an interactive or fully-automated mode.
- **Google OAuth login** — with a guest mode and per-browser guest token for unauthenticated use.
- **Multi-provider LLM support** — Gemini (default), Anthropic Claude, Groq, or OpenRouter, selected automatically from the shape of a user-supplied API key, with automatic model fallback and 429/rate-limit backoff.

## Architecture

```
frontend/   React 19 + Vite SPA — single-page dashboard (App.jsx)
backend/
  main.py               FastAPI app, HTTP endpoints, session store, streaming pipelines
  services/
    resume_parser.py    PDF/DOCX/TEX -> structured resume JSON (LLM)
    ats_scorer.py        Deterministic skills/experience scoring (no LLM)
    llm_agent.py          Job-fit analysis, cover letter, LaTeX tailoring, recruiter review
    gemini_client.py     Multi-provider LLM client with model fallback + retry
    job_searcher.py       LinkedIn/Indeed scraping + job ranking
    scraper.py             Single job-posting page scraper (Playwright)
    resume_generator.py  Structured JSON -> PDF (Jinja2 + Playwright), used for autofill uploads
    autofill_agent.py    Playwright browser automation for job applications
    auth.py                Supabase-backed users/sessions + Google OAuth
    log_queue.py          Thread-safe log relay for streaming LLM progress to the client
  utils/latex_utils.py  LaTeX post-processing/hotfixes and JSON->LaTeX generation
```

The backend streams progress (NDJSON) to the frontend for long-running operations (job analysis, tailoring, job search, autofill status) so the UI can show a live log.

## Prerequisites

- Python 3.11+
- Node.js 20+
- [Tectonic](https://tectonic-typesetting.github.io/) (LaTeX compiler) on `PATH` — used to compile tailored resumes to PDF
- Playwright browsers (`playwright install chromium`) — used for scraping, autofill, and PDF generation
- A Gemini API key (or Anthropic/Groq/OpenRouter key) for the LLM features

## Environment variables

No `.env.example` is checked in; create a `backend/.env` with whichever of these you need:

| Variable | Required | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | Yes (for default provider) | Gemini API key used for parsing, scoring, tailoring, autofill Q&A. Users can also supply their own key (Gemini/Anthropic/Groq/OpenRouter) at runtime via the frontend settings screen. |
| `SUPABASE_URL` | No | Supabase project URL, for persisting user accounts/sessions/resumes. Without it, everything falls back to in-memory/guest sessions. |
| `SUPABASE_KEY` | No | Supabase API key. |
| `GOOGLE_CLIENT_ID` | No | Google OAuth client ID, for "Sign in with Google". |
| `GOOGLE_CLIENT_SECRET` | No | Google OAuth client secret. |
| `GOOGLE_REDIRECT_URI` | No | OAuth redirect URI (default `http://localhost:8000/auth/callback`). |
| `FRONTEND_URL` | No | Frontend origin used for the post-login redirect (default `http://localhost:5173`). |
| `PORT` | No | Backend port (default `8000`). |

On localhost, the frontend also offers a "Mock Dev Login" that bypasses Google OAuth entirely.

## Running locally

**Backend:**
```bash
cd backend
pip install -r requirements.txt
playwright install chromium
uvicorn main:app --reload --port 8000
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev
```

The frontend dev server auto-detects `http://127.0.0.1:8000` as the API base when run on localhost.

## Running with Docker

```bash
docker build -t job-finder .
docker run -p 8000:8000 --env-file backend/.env job-finder
```

The Dockerfile builds the frontend, then serves the built static assets directly from the FastAPI backend (single container, single port).

## Key API endpoints

| Endpoint | Purpose |
|---|---|
| `POST /upload_resume` | Upload and parse a resume (PDF/DOCX/TEX) |
| `POST /scrape_job` | Scrape a job posting URL into title + description |
| `POST /analyze_job` | Streamed: ATS scoring, and (unless skipped) full resume tailoring + cover letter |
| `POST /generate_tailored_resume` | Render tailored resume JSON to PDF |
| `POST /compile_latex` / `POST /download_latex` | Compile or download tailored LaTeX |
| `POST /open_in_overleaf` / `POST /open_original_in_overleaf` | Export LaTeX project to Overleaf |
| `POST /search_matching_jobs` | Streamed: search + rank matching jobs from LinkedIn/Indeed |
| `POST /apply` / `GET /apply/status/{task_id}` | Kick off and poll the browser autofill agent |
| `GET /auth/url`, `GET /auth/callback`, `POST /auth/mock` | Google OAuth / mock login |
| `POST /clear_cache` | Reset in-memory caches and temporary files |

## Notes

- Uploaded files and generated output live in `backend/uploads/` and `backend/output/`, which are purged on startup and periodically (every 30 minutes) to avoid unbounded growth on long-running deployments.
- LinkedIn/Indeed job search relies on scraping (no official API), so selectors may need maintenance if those sites change their markup.
- The autofill agent opens a real, visible browser window and persists its session in `backend/user_data/` so logins to job sites/portals survive across runs.
