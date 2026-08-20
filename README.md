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

An AI-powered job search, resume tailoring, and application assistant. Upload a resume once (in `.pdf`, `.docx`, or `.tex`), then let it discover matching job postings, score your ATS fit against job descriptions, tailor a pixel-perfect one-page LaTeX resume and cover letter for specific roles, generate personalized recruiter outreach messages, and auto-fill applications directly on the web.

The project includes:
1. **Full-Stack Web App** — FastAPI backend + React (Vite) dashboard.
2. **Chrome Extension (`Job Finder ATS Tailor`)** — In-browser sidebar to score jobs, tailor resumes, and generate cover letters on LinkedIn, Indeed, Greenhouse, Lever, Workday, etc.

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

### ✍️ 3. One-Page LaTeX Resume & Cover Letter Tailoring
- **Strict One-Page Budgeting**: Automatically scales fonts, line spreads, and margins via Tectonic PDF compilation to produce a single-page document.
- **Automated Recruiter Review Loop**: Multi-attempt validation loop evaluating 4 criteria: ATS fit, measurable impact metrics, strict truthfulness against original experience, and conciseness.
- **Overleaf Integration**: One-click direct export to Overleaf for both tailored and original master resumes.

### 🌐 4. Automated Job Discovery & Application Assistant
- **Live Scraping & Scoring**: Discovers jobs across LinkedIn and Indeed, scrapes full descriptions, and ranks them by ATS fit score.
- **Browser Autofill Assistant**: Integrated Playwright browser agent for automated application form filling with interactive Q&A solving.

---

## 🧩 Chrome Extension (`Job Finder ATS Tailor`)

The project includes a Manifest V3 Chrome Extension located in the `/extension` directory for instant in-page analysis while browsing job boards.

### Extension Features
- **In-Page Job Extraction**: Auto-detects Job Title, Company Name, and Full Description on **LinkedIn**, **Indeed**, **Workday**, **Greenhouse**, **Lever**, **Oracle Cloud HCM**, and custom career sites.
- **Instant ATS Match Check**: Computes your ATS score and lists matched vs. missing keywords right in the extension popup.
- **1-Click Resume Tailoring & Download**: Tailors your resume to the open job page and triggers instant LaTeX/PDF compilation & download.
- **Cover Letter & Recruiter Outreach Generator**: Drafts tailored cover letters (<300 words) and personalized LinkedIn cold outreach messages.
- **1-Click Sync**: Automatically syncs your active session, resume data, and custom API keys with the local or hosted Job Finder web app.

### Installing the Chrome Extension
1. Open Google Chrome (or any Chromium browser like Brave / Edge / Arc).
2. Navigate to `chrome://extensions/`.
3. Enable **Developer mode** in the top-right corner.
4. Click **Load unpacked** and select the [`extension/`](file:///Users/akhilbaja/Documents/Akhil/Job%20Finder/extension) directory from this repository.
5. In the extension popup, configure your backend URL (e.g., `http://127.0.0.1:8000` for local dev or your hosted domain).

---

## 🏗️ Architecture

```
Job Finder/
├── frontend/             # React 19 + Vite SPA — Single-page interactive dashboard
├── backend/              # FastAPI application & microservices
│   ├── main.py           # FastAPI app, SSE streaming endpoints, session management
│   ├── services/
│   │   ├── resume_parser.py    # Multi-format resume parsing & deterministic category extractor
│   │   ├── ats_scorer.py       # Deterministic ATS scoring & timeline analysis engine
│   │   ├── llm_agent.py        # Resume tailoring, cover letter writer, recruiter reviewer
│   │   ├── gemini_client.py    # Multi-LLM provider client (Gemini, Claude, Groq, OpenRouter)
│   │   ├── job_searcher.py     # LinkedIn & Indeed job scraper and ranking pipeline
│   │   ├── scraper.py          # Playwright headless page scraper
│   │   ├── resume_generator.py # HTML/PDF template renderer
│   │   ├── outreach_generator.py # Recruiter outreach message composer
│   │   └── auth.py             # Supabase & Google OAuth session handlers
│   └── utils/
│       ├── latex_utils.py      # LaTeX sanitization, macro hotfixes, Tectonic metric compilation
│       └── ssl_utils.py        # Verified TLS context handler
└── extension/            # Chrome Extension (Manifest V3)
    ├── manifest.json     # Extension permissions, host rules, and metadata
    ├── popup.html / js   # Popup interface for ATS scoring, tailoring & cover letters
    ├── content.js        # Universal job page text and metadata extractor
    └── background.js     # Service worker handling storage sync and backend communication
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
PORT=8000
```

---

## 🐳 Running with Docker

```bash
docker build -t job-finder .
docker run -p 8000:8000 --env-file backend/.env job-finder
```

The Docker container builds the frontend, packages the Tectonic LaTeX compiler, installs Playwright Chromium, and serves the complete application from a single port (`8000`).

---

## 🧪 Testing

Run backend unit and pipeline test suites:
```bash
pytest backend/tests/test_ats_scorer.py backend/tests/test_resume_pipeline.py -v
```