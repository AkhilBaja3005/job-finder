---
title: AI Job Finder Agent
emoji: 💼
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 8000
pinned: false
---

# AI Job Finder Agent

<div align="center">

**Production-ready, local-first & cloud-deployable autonomous career agent, ATS resume tailor & job search copilot.**

[![Python](https://img.shields.io/badge/Python-3.11%2B%20%7C%203.12%20%7C%203.14-blue?logo=python&logoColor=white)](https://www.python.org/)
[![Google Gemini](https://img.shields.io/badge/Google%20GenAI-Gemini%20Flash%20%26%20Flash--Lite-orange?logo=google&logoColor=white)](https://ai.google.dev/)
[![React](https://img.shields.io/badge/Web%20UI-React%2019%20%2B%20Vite-blue?logo=react&logoColor=white)](https://react.dev/)
[![FastAPI](https://img.shields.io/badge/API-FastAPI-emerald?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Chrome Extension](https://img.shields.io/badge/Chrome%20Extension-Manifest%20V3-red?logo=googlechrome&logoColor=white)](https://developer.chrome.com/docs/extensions/mv3/)
[![LaTeX](https://img.shields.io/badge/Typesetting-XeLaTeX%20%2B%20Tectonic-darkgreen?logo=latex&logoColor=white)](https://tectonic-typesetting.github.io/)
[![MCP](https://img.shields.io/badge/Protocol-Model%20Context%20Protocol%20(MCP)-purple)](https://modelcontextprotocol.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

</div>

An AI-powered job search, resume tailoring, and application assistant. Upload a resume once (in `.pdf`, `.docx`, or `.tex`), then let it discover matching job postings, score your ATS fit against job descriptions, tailor a pixel-perfect one-page LaTeX resume and cover letter for specific roles, generate personalized recruiter outreach messages, and auto-fill applications directly on the web.

The project includes:
1. **Full-Stack Web App** — Modular FastAPI backend + React 19 (Vite) dashboard.
2. **Chrome Extension (`Job Finder ATS Tailor`)** — Persistent Chrome Side Panel to score jobs, tailor resumes, auto-fill forms with multimodal intelligence, and dispatch delivery packages on LinkedIn, Indeed, Greenhouse, Lever, Ashby, Workday, and custom career sites.

---

## Key Features

### 📄 1. Multi-Format Master Resume Parsing & Category Preservation
- Supports **PDF**, **DOCX**, and native **LaTeX (`.tex`)** uploads.
- **Deterministic Category Preservation**: Automatically extracts and locks candidate-defined skill categories (`Languages`, `AI/ML & GenAI`, `Data & Platforms`, `Software & Infrastructure`) and protects against unwanted AI re-categorization or truncation.
- Accurately captures multi-line wrapped text, parentheses, grades/CPI, and nested project/experience structures.

### 🎯 2. Deterministic ATS Scoring & Semantic Fit Analysis
- **Dual-Engine Evaluation**: Combines deterministic keyword & experience matching (`ats_scorer.py`) with semantic LLM role-fit analysis.
- **Context Density & Time-Decay**: Weighted scoring based on skill recency, timeline flattening, and anti-keyword stuffing controls.
- **Matched vs. Missing Keywords Breakdown**: Identifies exact hard skills and qualification gaps.
- **Top Missing Keywords Selector**: Click missing skill chips to explicitly authorize and weave them into your tailored resume with intelligent category routing.

### ✍️ 3. One-Page LaTeX Resume & Cover Letter Tailoring
- **Strict One-Page Multi-Pass Budgeting**: Automatically optimizes `linespread` and `spacing_scale` via Tectonic PDF compilation to guarantee a single-page document.
- **Automated Recruiter Review Loop**: Multi-attempt validation loop evaluating 4 criteria: ATS fit, measurable impact metrics, strict truthfulness against original experience, and conciseness.
- **Overleaf Integration**: One-click direct export to Overleaf for both tailored and original master resumes.
- **On-Demand Styled Email Delivery**: 1-click delivery of tailored resume PDFs with full metadata (`Target Role`, `Company`, `ATS Score`) to candidate inboxes.

### ⚡ 4. Autonomous Web Autofill Engine (`browser-use` + Gemini)
- **Two-Phase Adaptive Execution**: Fast pure-DOM pass (`use_vision=False`, `use_thinking=False`) for sub-10s filling, with an adaptive fallback to **Vision + Deep Reasoning (`use_thinking=True`)** for custom canvas widgets or shadow DOM hurdles.
- **Pre-Flight HTTP Probing**: Follows redirects to resolve direct ATS destinations (e.g. LinkedIn $\rightarrow$ Ashby) and exits in **~200ms** on closed/expired listings without launching Chrome.
- **Persistent Chrome Instance**: Reuses a dedicated Chrome daemon on CDP port 9222 with performance flags (disabled image painting, timer throttling bypass).
- **Safety Guardrails**: Default `REVIEW_ONLY` mode navigates through multi-step forms and pauses on the final preview step; `AUTO_SUBMIT` mode autonomously submits when enabled.
- 📖 **Full Architecture Guide**: See [`docs/AUTONOMOUS_AUTOFILL_README.md`](file:///Users/akhilbaja/Documents/Akhil/Job%20Finder/docs/AUTONOMOUS_AUTOFILL_README.md).

### 🧩 5. In-Page Chrome Extension Assistant
- **Zero-Autofill Architecture**: Uses smart field classifiers and deterministic fallbacks for contact info, notice periods, salary expectations, and work authorizations.
- **Embedded `<iframe>` Support**: Injects into both top-level and embedded ATS frames (Greenhouse/Lever).
- **Open-Ended Question Engine**: Instant screening answer generation for essays like *"Why this company?"* or *"Describe a challenging project"*.
- **Inline '✨ AI Answer' Buttons**: Directly embedded beside textareas and form inputs on live job pages.

### 🌐 6. Grounding with Google Search & Verified Recruiter Discovery
- **Native Google Search Grounding**: Connects Gemini models with search tools directly to real-time web content using `tools=[{"google_search": {}}]` with citation and source link extraction.
- **Verified Recruiter & Hiring Manager Intel**: Discovers active technical recruiters, talent sourcers, and engineering hiring managers on LinkedIn for any target role and company (`POST /jobs/find_recruiter`).
- **7-Day TTL Smart Caching**: Normalizes corporate suffixes (e.g. `Stripe, Inc.` $\rightarrow$ `stripe`) to eliminate duplicate billing queries.

### 📬 6. Automated Daily Job Matches Digest
- **Multi-Source Daily Scanning**: Aggregates up to **20 top matching roles** from LinkedIn, Reed, Indeed, and direct ATS portals (Greenhouse, Ashby, Lever).
- **Recruiter Cards & 1-Click Tailoring**: Direct links to recruiter LinkedIn profiles and instant 1-click LaTeX resume tailoring.
- **Instant Trigger Endpoint**: Dispatch test digests on demand (`POST /user/cron/trigger_now`) without waiting for the scheduled delivery time.

---

## 🧩 Chrome Extension (`Job Finder ATS Tailor`)

The project includes a Manifest V3 Chrome Extension located in the `/extension` directory for instant in-page analysis while browsing job boards.

### Extension Features
- **Chrome MV3 Persistent Side Panel**: Docks permanently to the right side of the browser, remaining open across form filling, job scrolling, and tab switching without auto-dismissing.
- **Offline Fallback & Cached Resilience**: When offline or if the backend server is non-responsive, the extension automatically falls back to local storage and displays a cached ATS score indicator (`⚡ Offline Cached Score`).
- **Live Tab Synchronization & 🔄 Rescan Tab**: Automatically synchronizes and extracts the active job page when switching tabs; dedicated rescan button forces fresh live extraction.
- **Auto-Update Detection Banner**: Notifies you directly in the side panel when an updated extension version is available with a 1-click zip download button.
- **Zero-Config Download Package**: Pre-bakes your 6-digit Sync Key and backend server endpoint directly into the downloaded extension zip for instant zero-configuration onboarding.
- **In-Page Job Extraction**: Auto-detects Job Title, Company Name, and Full Description on **LinkedIn**, **Indeed**, **Workday**, **Greenhouse**, **Lever**, **Ashby**, and custom career sites.
- **Interactive JD Paste & Edit**: Paste raw JD text or adjust job titles on complex single-page apps (SPAs) or iframe job listings with live ATS rescoring.
- **1-Click Email Tailored Package**: Compiles the single-page LaTeX resume and emails the PDF package to your inbox in one click.
- **1-Click Tailor & Download PDF**: Compiles and opens the tailored single-page PDF in your browser.
- **Cover Letter & Recruiter Outreach Generator**: Drafts tailored cover letters (<300 words) and personalized LinkedIn cold outreach messages.

### Installing the Chrome Extension
1. Open Google Chrome (or any Chromium browser like Brave / Edge / Arc).
2. Navigate to `chrome://extensions/`.
3. Enable **Developer mode** in the top-right corner.
4. Click **Load unpacked** and select the [`extension/`](file:///Users/akhilbaja/Documents/Akhil/Job%20Finder/extension) directory (or unzip the package downloaded from the web dashboard).
5. Click the extension icon in your Chrome toolbar to open the docked Side Panel!

---

## 🏗️ Architecture

```
Job Finder/
├── docs/                 # Architectural specifications & engine guides
│   └── AUTONOMOUS_AUTOFILL_README.md  # Detailed browser-use autofill architecture
├── frontend/             # React 19 + Vite SPA — Single-page interactive dashboard
├── backend/              # Modular FastAPI application & microservices
│   ├── main.py           # Application entrypoint & APIRouter registration
│   ├── routes/
│   │   ├── ai_routes.py      # /analyze_job, /generate_cover_letter, /send_outreach_email, /answer_question (TTLCache Bounded)
│   │   ├── resume_routes.py  # /parse_resume, /user/resume, /download_latex, /download_extension
│   │   ├── job_routes.py     # /jobs, /scrape, /apply, /extension_version_hash
│   │   ├── auth_routes.py    # /auth/google, /auth/callback, /user/me, /user/sync_profile
│   │   └── admin_routes.py   # /admin/stats, /admin/clean_storage
│   ├── services/
│   │   ├── browser_use_agent.py# Autonomous application filling engine (browser-use + Gemini)
│   │   ├── resume_parser.py    # Multi-format resume parsing & category extractor
│   │   ├── ats_scorer.py       # Deterministic ATS scoring & timeline analysis engine
│   │   ├── recruiter_finder.py # Google Search Grounding for verified LinkedIn recruiters
│   │   ├── llm_agent.py        # Resume tailoring, cover letter writer, recruiter reviewer
│   │   ├── gemini_client.py    # Multi-LLM provider client (Gemini Grounding, Claude, Groq)
│   │   ├── email_service.py    # SMTP email delivery with styled HTML templates
│   │   ├── job_searcher.py     # LinkedIn & Indeed job scraper and ranking pipeline
│   │   ├── scraper.py          # Playwright headless page scraper with crash auto-recovery watchdog
│   │   ├── autofill_agent.py   # Form filling and question answering engine
│   │   └── auth.py             # Supabase & Google OAuth session handlers
│   └── utils/
│       ├── latex_utils.py      # Pre-flight syntax validation, sanitization, macro hotfixes, Tectonic compilation
│       ├── ttl_cache.py        # Thread-safe bounded TTL cache for sub-millisecond memory safety
│       └── ssl_utils.py        # Verified TLS context handler
├── applications_tracker/ # Scheduled batch scanner, tailoring pipeline & ledger
│   └── scheduled_job_scanner.py
└── extension/            # Chrome Extension (Manifest V3 - Side Panel)
    ├── manifest.json     # Extension permissions, sidePanel, host rules, and metadata
    ├── popup.html / js   # Persistent side panel interface with offline fallback & rescan
    ├── content.js        # Universal job page extractor, iframe support & form autofiller
    └── background.js     # MV3 service worker configuring side panel behavior
```

---

## ⚙️ Prerequisites

- **Python**: 3.11+
- **Node.js**: 20+
- **Tectonic**: [Tectonic LaTeX compiler](https://tectonic-typesetting.github.io/) installed on system `PATH` (used for compiling resumes to PDF).
  - macOS: `brew install tectonic`
  - Linux: `sudo apt-get install tectonic` or download release binary.
- **Playwright**: `playwright install chromium` (for scraping and headless autofill).
- **API Key**: Gemini API key (default) or Anthropic/Groq/OpenRouter keys.

---

## 🚀 Running Locally

### 1. Backend Setup
```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
uvicorn main:app --reload --port 8000
```

### 2. Frontend Setup
```bash
cd frontend
npm install
npm run dev
```
The frontend will run at `http://localhost:5173` and automatically proxy API calls to `http://127.0.0.1:8000`.

### 3. Environment Variables
Create a `backend/.env` file:
```env
GEMINI_API_KEY=your_gemini_api_key
# Optional integrations:
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_supabase_anon_key
GOOGLE_CLIENT_ID=your_google_client_id
GOOGLE_CLIENT_SECRET=your_google_client_secret
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email@gmail.com
SMTP_PASSWORD=your_app_password
PORT=8000
```

---

## 🐳 Running with Docker / Hugging Face Spaces

```bash
docker build -t job-finder .
docker run -p 8000:8000 --env-file backend/.env job-finder
```

The Docker container builds the frontend, packages the Tectonic LaTeX compiler, installs Playwright Chromium, and serves the complete application from a single port (`8000`).

---

## 🧪 Testing

Run complete backend test suite:
```bash
cd backend
pytest tests/ -v
```

---

## 🤖 MCP Server & Universal Agent Skills

Job Finder provides a production-grade **Model Context Protocol (MCP)** server and **8 Universal Agent Skills** enabling seamless integration with AI harnesses: **Antigravity**, **Claude Code**, **Claude Desktop**, **Cursor IDE**, and **Gemini CLI**.

### ⚡ Low-Latency & High-Precision Architecture
- **Sub-Second Execution (`flash-lite` Prioritization)**: All search grounding and LLM tasks prioritize fast-lite models (configured dynamically via `backend/config/constants.py`), providing ultra-high RPM allowances and eliminating `429 RESOURCE_EXHAUSTED` rate limits.
- **Zero-Latency Profile Auto-Resolution**: When resume data or keyword arguments are omitted, tools automatically read from [`backend/config/candidate_profile.json`](file:///Users/akhilbaja/Documents/Akhil/Job%20Finder/backend/config/candidate_profile.json) for instant in-memory scoring in `<10ms`.
- **Precompiled Taxonomy & Deterministic Rules**: Regex and seniority matching are fully precompiled, avoiding runtime compilation overhead.

### 🛠️ 18 Production MCP Tools
The MCP server exposes 18 specialized tools across the end-to-end career lifecycle:
- **Profile & Preferences**: `save_candidate_profile`, `get_candidate_profile`
- **Discovery**: `search_jobs` (multi-role concurrent search), `scrape_job_posting`
- **ATS & Fit**: `calculate_ats_score`, `analyze_skill_gap`, `extract_seniority_salary`
- **Resume & LaTeX**: `parse_and_convert_to_latex` (PDF/DOCX/TXT to LaTeX), `tailor_resume_latex`, `compile_latex_metrics`, `export_overleaf_bundle`
- **Networking**: `extract_recruiter_profile`, `generate_outreach_inmail`
- **Interview Prep**: `generate_interview_pack`, `company_culture_brief`
- **CRM & Tracking**: `track_application`, `list_applications`, `check_duplicate_application`

### 🧠 8 Universal Agent Skills
Located in `.agents/skills/` (with YAML frontmatter compatible across all major agent orchestrators):
1. **`candidate-profile-config`**: Ingest and save profile, target roles, locations, 24h timeframe, and reference strategies.
2. **`career-discovery`**: Multi-board job query orchestration with compensation & seniority filtering.
3. **`ats-resume-tailor`**: Deterministic ATS keyword alignment and strict 1-page LaTeX optimization.
4. **`company-intelligence`**: Deep-dive culture briefs, tech-stack analysis, and salary benchmarks.
5. **`recruiter-networking`**: High-converting, 3-sentence recruiter cold outreach & InMails.
6. **`cover-letter-crafting`**: Hyper-targeted 3-paragraph motivation letters.
7. **`interview-mastery`**: Tailored behavioral, system design, and role-specific technical question packs.
8. **`application-tracker-crm`**: Pipeline tracking, duplicate submission prevention, and stage updates.

### 💻 Profile & Preferences CLI
Users can also view and configure their preferences directly via the terminal:
```bash
# View active configuration
python backend/mcp/cli_profile.py show

# Update search preferences
python backend/mcp/cli_profile.py set --roles "AI Engineer,LLM Engineer" --locations "London,Remote" --timeframe "past_24_hours" --ats 65
```

### 🔌 Connecting to AI Harnesses
Pre-built configuration templates are located in [`harness_configs/`](file:///Users/akhilbaja/Documents/Akhil/Job%20Finder/harness_configs/):

- **Claude Desktop / Claude Code**: Copy snippet from [`harness_configs/claude_desktop_config.json`](file:///Users/akhilbaja/Documents/Akhil/Job%20Finder/harness_configs/claude_desktop_config.json) into `claude_desktop_config.json`.
- **Cursor IDE**: Place [`harness_configs/cursor_mcp.json`](file:///Users/akhilbaja/Documents/Akhil/Job%20Finder/harness_configs/cursor_mcp.json) into `.cursor/mcp.json`.
- **Antigravity / Gemini CLI**: Add snippet from [`harness_configs/gemini_mcp_config.json`](file:///Users/akhilbaja/Documents/Akhil/Job%20Finder/harness_configs/gemini_mcp_config.json) into `~/.gemini/antigravity/mcp_config.json`.

### 🧪 Running Comprehensive MCP Tests
Verify all 18 MCP tools and 8 Skills end-to-end:
```bash
cd backend
python mcp/comprehensive_test.py
```

---

## 🌐 Autonomous Job Scanner & Browser-Use Pipeline

Job Finder includes an autonomous discovery, ATS evaluation, LaTeX resume tailoring, and browser auto-fill engine powered by **`browser-use`** with **`gemini-3.5-flash-lite`** and dual-persistence (Supabase + CSV).

### Workflow & Decision Engine:
1. **Multi-Platform Discovery**: Searches Greenhouse, Ashby, Lever direct ATS portals, LinkedIn, Indeed, and Reed for active postings matching candidate search preferences within the past 24 hours.
2. **ATS Threshold Scoring & Selective Tailoring**:
   - **ATS Score $\ge 80\%$ (Direct Apply)**: Directly submits the candidate's master resume without needing modifications.
   - **ATS Score $65\% - 79\%$ (Tailor & Apply)**: Automatically drafts and compiles a tailored 1-page LaTeX & PDF resume aligned with the job's missing keywords before submitting.
   - **ATS Score $< 65\%$ (Saved & Scored)**: Logged to the tracker for manual review without triggering automatic submission.
3. **Rigorous Post-Submission Verification & Error Detection**:
   - Clicking "Submit" is **never** assumed to be successful without confirmation.
   - Checks for definitive confirmation screens/redirects (`/confirmation`, `/thank-you`, `Thank you for applying`, `Application submitted`).
   - If blocked by unfulfilled required fields (e.g. telephone country code `.iti__selected-country`), missing dynamic flyouts, captchas, or server endpoint errors (e.g. `'Something went wrong. Please try again.'`), it strictly classifies the status as:
     ```
     Needs Review (Unsubmitted)
     ```
4. **Automated User Failure Notification Emails**:
   - At the conclusion of any scanning run (`scheduled_job_scanner.py`, `adhoc_auto_filler.py`, `linkedin_top_applicant_scanner.py`), if any applications encountered errors or could not be submitted, the agent immediately sends an email alert to the candidate.
   - Includes a formatted summary table with the job title, company name, exact blocking error reason, and a direct `[Review & Submit]` action button to finish the submission manually.
5. **Universal "Sign in / Sign up with Google" Authentication**:
   - When application portals demand user authentication or registration (such as **Reed.co.uk**, Workday, or custom portals), the agent automatically uses **"Sign in with Google" / "Continue with Google"** with the persistent authenticated Chrome session.
6. **Multi-Key LLM Cascading (`429 RESOURCE_EXHAUSTED` Resilience)**:
   - Integrates `MultiFallbackAgent` across all configured Gemini API keys (`GEMINI_API_KEY` through `GEMINI_API_KEY_7`) and model tiers (`gemini-3.5-flash-lite`, `gemini-3.1-flash-lite`, `gemini-3.5-flash`).
   - If free-tier RPM quotas are saturated, it seamlessly rotates to the next available API key in real-time without crashing the scan.
7. **Query-Aware Job Deduplication (`normalize_job_url`)**:
   - Preserves unique job query identifiers (e.g. `jk=` on Indeed, `currentJobId=` on LinkedIn) during deduplication across Supabase, CSV, and search streams, preventing multiple listings from collapsing into duplicate skips.
8. **Cloudflare Turnstile & Verification Handling**:
   - Automatically rewrites Indeed viewjob URLs (`/viewjob?jk=...` $\rightarrow$ `/jobs?q=engineer&vjk=...`) to load job details cleanly in search side-panes without triggering bot blocks.
   - For local development runs, includes an autonomous `extract_jd_with_browser_use` fallback that interacts with and clicks "Verify you are human" / Turnstile checkboxes to extract full JDs.
9. **Multi-Tier Execution Timeouts & Hang Prevention**:
   - **LLM Call Timeout (30s)**: Strictly bounds each individual Gemini API call to 30s. If Google's API hangs, it rotates immediately to the next candidate key or fallback model (`gemini-3.8-flash` $\rightarrow$ `gemini-3.7-flash` $\rightarrow$ `gemini-3.5-flash`).
   - **Resume Tailoring Timeout (90s)**: Bounding LaTeX tailoring and compilation; automatically falls back to the master resume if the 90s window expires.
   - **Turnstile JD Extraction Timeout (60s)**: Prevents browser-use JD extraction from hanging the scanner.
   - **Autofill Application Timeout (5 min / 300s)**: Limits complex multi-step application autofill sessions to 5 minutes (`BROWSER_USE_TIMEOUT=300`) and 50 steps (`max_steps=50`). If timed out, the job is cleanly marked as `Needs Review (Unsubmitted)` and added to the failure notification email.
   - **Non-blocking Storage Uploads**: Hugging Face bucket PDF synchronization runs asynchronously in a worker thread without freezing the async event loop.
10. **Dual Persistence Tracking**: Every application attempt is recorded to Supabase (`applications` table) with automatic fallback to `applications_tracker/job_applications_tracker.csv`.
11. **Already-Applied Detection**: Queries Supabase and local CSV to prevent duplicate submissions, and utilizes in-page visual detection to instantly exit if an application was already submitted on the target platform.
12. **Visa Sponsorship & Compliance Handling**: Explicitly evaluates visa knockout constraints (`requires_sponsorship: true`), ensuring truthful answering on all multiple-choice ATS screening questionnaires.

### Running the Scanner:
```bash
# Preview mode (Safety Guardrails active — reviews before final submit):
source backend/venv/bin/activate
python applications_tracker/scheduled_job_scanner.py

# Autonomous Auto-Submit Mode (Submits applications directly):
source backend/venv/bin/activate
BROWSER_USE_DISABLE_GUARDRAILS=1 python applications_tracker/scheduled_job_scanner.py

# Direct single-URL autofill:
source backend/venv/bin/activate
BROWSER_USE_DISABLE_GUARDRAILS=1 python applications_tracker/scheduled_job_scanner.py "https://uk.linkedin.com/jobs/view/..."

# Custom application timeout (e.g. 180s instead of default 300s):
BROWSER_USE_TIMEOUT=180 BROWSER_USE_DISABLE_GUARDRAILS=1 python applications_tracker/scheduled_job_scanner.py
```

---

## ⚡ Ad-Hoc Master Resume Auto-Filler (`adhoc_auto_filler.py`)

When you have a list of job URLs or an existing tracker and want to **immediately auto-fill using your Master Resume** without LaTeX recompilation or tailoring overhead:

### Features:
- **Zero Tailoring Compilation**: Directly attaches your macOS Red-tagged Master Resume from iCloud or repository fallback.
- **Multiple Input Formats**: Takes jobs directly from a CSV file (`--csv`), an Excel spreadsheet (`--excel`), or command-line URLs (`--url`).
- **Status & Limit Filtering**: Selectively runs on specific statuses (e.g. `--filter "Ready to Apply"`) and controls batch sizes (`--limit 5`).
- **Safety Modes**: Supports preview/review mode (default) or autonomous submission (`--auto-submit`).

### CLI Usage:
```bash
# 1. Apply to specific URL(s) using Master Resume
python applications_tracker/adhoc_auto_filler.py \
  --url "https://job-boards.greenhouse.io/company/jobs/123"

# 2. Process top 5 jobs from the applications tracker CSV
python applications_tracker/adhoc_auto_filler.py \
  --csv applications_tracker/job_applications_tracker.csv \
  --limit 5

# 3. Process jobs from an Excel sheet with autonomous auto-submit
python applications_tracker/adhoc_auto_filler.py \
  --excel target_jobs.xlsx \
  --auto-submit

# 4. Filter by status in CSV
python applications_tracker/adhoc_auto_filler.py \
  --filter "Ready to Apply" \
  --limit 10
```

---

## 🌟 LinkedIn 'Top Applicant' Scanner & Auto-Apply (`linkedin_top_applicant_scanner.py`)

Dedicated autonomous scanner that specifically targets LinkedIn postings where your profile has the **"You’d be a top applicant"** (or top 10% / top 25% / stand out) badge, auto-applying with zero-tailoring latency using your Master Resume.

### Key Capabilities:
- **Persistent Chrome Session (CDP Port 9222)**: Reuses your authenticated Chrome profile (`backend/user_data/browser_use_chrome_session`), eliminating repetitive LinkedIn logins, captcha prompts, and session resets.
- **Top Applicant Badge DOM Filter**: Evaluates rendered search listing cards and detail views to pinpoint roles where you have an unfair competitive advantage.
- **Master Resume Direct Dispatch**: Dispatches your macOS Red-tagged Master Resume directly without unnecessary LaTeX recompilation.
- **Automated Email OTP Retrieval via Gmail Tab**: If an external application portal (e.g. micro1, Ashby, Workday) asks for an email verification code, the agent automatically opens `https://mail.google.com` in a new tab, extracts the latest OTP code, and enters it seamlessly.
- **Dual Persistence**: Every submission is automatically logged to Supabase and tracked in `job_applications_tracker.csv`.

### CLI Usage:
```bash
# 1. Preview Mode (Safety Guardrails active):
python applications_tracker/linkedin_top_applicant_scanner.py

# 2. Autonomous Auto-Submit Mode:
python applications_tracker/linkedin_top_applicant_scanner.py --auto-submit

# 3. Custom keywords and limit:
python applications_tracker/linkedin_top_applicant_scanner.py \
  --keywords "Machine Learning Engineer, AI Engineer" \
  --limit 10 \
  --auto-submit
```

---

## ⏰ Automated Daily macOS Scheduling (`launchd`)

The pipeline includes an automated daily scheduler that executes every morning at **9:00 AM** on macOS via `launchd`:

- **Execution Script**: [`applications_tracker/run_daily_scanner.sh`](file:///Users/akhilbaja/Documents/Akhil/Job%20Finder/applications_tracker/run_daily_scanner.sh)
- **LaunchAgent Plist**: `~/Library/LaunchAgents/com.jobfinder.daily_scanner.plist`
- **Execution Workflow**:
  1. **Phase 1 (ATS Scanner)**: Searches Ashby, Greenhouse, Lever, Workday for high-fit roles and applies/tailors resumes.
  2. **Phase 2 (LinkedIn Top Applicant)**: Scans LinkedIn for Top Applicant badge matches and executes autonomous auto-submission.
- **Daily Logs**: Stored under `applications_tracker/logs/scanner_YYYY-MM-DD.log`.

