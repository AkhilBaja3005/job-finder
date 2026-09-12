# Job Finder AI 💼

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![MCP](https://img.shields.io/badge/Protocol-Model%20Context%20Protocol%20(MCP)-purple)](https://modelcontextprotocol.io/)

**Production-grade autonomous career agent, ATS resume tailor, and job application copilot.**

Upload your resume once, and let Job Finder AI:
1. Concurrently search Greenhouse, Ashby, Lever, LinkedIn, Indeed, and Reed for fresh job postings.
2. Calculate deterministic ATS match scores against your candidate profile.
3. Automatically tailor pixel-perfect 1-page LaTeX resumes when required.
4. Autonomously fill out web application forms via browser automation (`browser-use`).

---

## ⚡ Quick Start & Installation

Install the package directly from PyPI:

```bash
pip install job-finder-ai
```

Or install with all cloud & database integrations:

```bash
pip install "job-finder-ai[all]"
```

Playwright browser dependencies (for browser auto-fill & web scraping):

```bash
playwright install chromium
```

---

## 🚀 Setup Wizard (`job-finder setup`)

Run the interactive setup wizard to configure your `.env`, import your master resume, and review your candidate profile:

```bash
job-finder setup
```

The wizard will:
- Initialize your local `.env` configuration template with safe local defaults (`BROWSER_USE_HEADLESS=false`, `JOB_FINDER_DISABLE_GUARDRAILS=0`).
- Prompt for your **Gemini API Key** (required for LLM reasoning and resume parsing).
- Prompt whether you want to configure **Email Notifications** (Optional): if enabled (`y`), it asks for your sender email and SMTP App Password so you receive automated email confirmations when applications are submitted, and alerts if an application requires manual review.
- Auto-detect and parse your master resume (`.pdf` / `.docx` / `.tex`).
- Verify demographic, work authorization, and portal fields, interactively prompting for any missing details.

---

## 🛠️ Unified CLI Commands

### 1. Autonomous Job Discovery & Tailoring Scanner (`job-finder scan`)
Search job boards, score postings against your candidate profile, tailor resumes, and auto-apply:

```bash
# Preview mode (Safety Guardrails active — reviews before submission):
job-finder scan

# Autonomous mode (Submits applications directly):
job-finder scan --auto-apply

# Direct single-URL application:
job-finder scan "https://boards.greenhouse.io/company/jobs/12345" --auto-apply

# Advanced tuning (timeouts, steps, ATS thresholds, roles, freshness):
job-finder scan   --role "AI Systems Engineer"   --location "London, UK"   --timeframe "24h"   --min-ats 70   --timeout 180   --auto-apply
```

### 2. Direct Application Autofill (`job-finder apply`)
Run ad-hoc browser auto-filler on any specific job application URL:

```bash
job-finder apply "https://jobs.ashbyhq.com/company/abc-123" --submit
```

### 3. Candidate Profile Management (`job-finder profile`)
Inspect or re-sync your candidate background from your resume:

```bash
# View active candidate profile & preferences:
job-finder profile --show

# Re-sync profile from a new resume PDF:
job-finder profile --sync /path/to/resume.pdf
```

### 4. Local Web Server & Dashboard (`job-finder server`)
Launch the backend server locally on port 8000:

```bash
job-finder server --port 8000
```

### 5. Model Context Protocol Server (`job-finder mcp`)
Launch the stdio MCP server for integration with **Cursor IDE**, **Claude Code**, **Claude Desktop**, and **Antigravity**:

```bash
job-finder mcp
```

---

## 🧩 Browser Extension (Chrome & Brave)

Job Finder AI includes a lightweight Chrome/Brave browser extension for 1-click job scoring, autofill, and pipeline sync while browsing job boards:

- **Instant ATS Scoring**: Inspect any active tab on Greenhouse, Ashby, Lever, or LinkedIn to instantly calculate compatibility against your master profile.
- **One-Click Autofill**: Automatically populate form inputs, screening questions, and upload your resume directly from your browser toolbar.
- **Live Sync**: Syncs application status seamlessly with your local CLI tracker or the cloud dashboard at [job-finder.space](https://www.job-finder.space).

### Installing the Extension:
1. Download or generate the extension ZIP from your local server or [https://www.job-finder.space](https://www.job-finder.space).
2. In Chrome / Brave, navigate to `chrome://extensions`.
3. Enable **Developer mode** in the top right corner.
4. Click **Load unpacked** and select the extracted `extension/` directory.

---

## ⚙️ Environment Variables

You can configure environment settings in a local `.env` file or export them directly:

| Variable | Description |
| :--- | :--- |
| `GEMINI_API_KEY` | Google Gemini API Key for LLM operations & browser-use |
| `PORTALS_PASSWORD` | Password for automated job board account creation |
| `BROWSER_USE_TIMEOUT` | Autofill session timeout in seconds (default: `300`) |
| `TAILORING_TIMEOUT` | Resume tailoring timeout in seconds (default: `90`) |
| `MASTER_RESUME_PATH` | Path to master resume PDF (or iCloud Drive Red tag) |

---

## 📄 License



MIT License. Designed and maintained by [Akhil Baja](https://github.com/AkhilBaja3005).
