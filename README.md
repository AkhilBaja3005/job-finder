---
title: AI Job Finder Agent
emoji: 💼
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 8000
pinned: false
---

# AI Job Finder Agent (v2.1.0)

An AI-powered job search, resume tailoring, and application assistant. Upload a resume once (in `.pdf`, `.docx`, or `.tex`), then let it discover matching job postings, score your ATS fit against job descriptions, tailor a pixel-perfect one-page LaTeX resume and cover letter for specific roles, generate personalized recruiter outreach messages, and auto-fill applications directly on the web.

The project includes:
1. **Full-Stack Web App** — Modular FastAPI backend + React 19 (Vite) dashboard.
2. **Chrome Extension (`Job Finder ATS Tailor v2.1.0`)** — Persistent Chrome Side Panel to score jobs, tailor resumes, auto-fill forms with multimodal intelligence, and dispatch delivery packages on LinkedIn, Indeed, Greenhouse, Lever, Ashby, Workday, and custom career sites.

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

### ⚡ 4. Multimodal & Deterministic Auto-Fill Assistant
- **Zero-Autofill Architecture**: Uses smart field classifiers and deterministic fallbacks for contact info, notice periods, salary expectations, and work authorizations.
- **Embedded `<iframe>` Support**: Injects into both top-level and embedded ATS frames (Greenhouse/Lever).
- **Open-Ended Question Engine**: Instant screening answer generation for essays like *"Why this company?"* or *"Describe a challenging project"*.
- **Inline '✨ AI Answer' Buttons**: Directly embedded beside textareas and form inputs on live job pages.

---

## 🧩 Chrome Extension (`Job Finder ATS Tailor v2.1.0`)

The project includes a Manifest V3 Chrome Extension located in the `/extension` directory for instant in-page analysis while browsing job boards.

### Extension Features
- **Chrome MV3 Persistent Side Panel**: Docks permanently to the right side of the browser, remaining open across form filling, job scrolling, and tab switching without auto-dismissing.
- **Live Tab Synchronization & 🔄 Rescan Tab**: Automatically synchronizes and extracts the active job page when switching tabs; dedicated rescan button forces fresh live extraction.
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
├── frontend/             # React 19 + Vite SPA — Single-page interactive dashboard
├── backend/              # Modular FastAPI application & microservices
│   ├── main.py           # Application entrypoint & APIRouter registration
│   ├── routes/
│   │   ├── ai_routes.py      # /analyze_job, /generate_cover_letter, /send_outreach_email, /answer_question
│   │   ├── resume_routes.py  # /parse_resume, /user/resume, /download_latex, /download_extension
│   │   ├── job_routes.py     # /jobs, /scrape, /apply, /extension_version_hash
│   │   ├── auth_routes.py    # /auth/google, /auth/callback, /user/me, /user/sync_profile
│   │   └── admin_routes.py   # /admin/stats, /admin/clean_storage
│   ├── services/
│   │   ├── resume_parser.py    # Multi-format resume parsing & category extractor
│   │   ├── ats_scorer.py       # Deterministic ATS scoring & timeline analysis engine
│   │   ├── llm_agent.py        # Resume tailoring, cover letter writer, recruiter reviewer
│   │   ├── gemini_client.py    # Multi-LLM provider client (Gemini, Claude, Groq, OpenRouter)
│   │   ├── email_service.py    # SMTP email delivery with styled HTML templates
│   │   ├── job_searcher.py     # LinkedIn & Indeed job scraper and ranking pipeline
│   │   ├── scraper.py          # Playwright headless page scraper
│   │   ├── autofill_agent.py   # Form filling and question answering engine
│   │   └── auth.py             # Supabase & Google OAuth session handlers
│   └── utils/
│       ├── latex_utils.py      # LaTeX sanitization, macro hotfixes, Tectonic compilation
│       └── ssl_utils.py        # Verified TLS context handler
└── extension/            # Chrome Extension (Manifest V3 - Side Panel v2.1.0)
    ├── manifest.json     # Extension permissions, sidePanel, host rules, and metadata
    ├── popup.html / js   # Persistent side panel interface for ATS scoring & tailoring
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