# Job Finder & Career Engine: Agent Harness Setup Guide

This directory contains pre-configured MCP definitions and agent runbooks to connect any external AI assistant directly to your Job Finder platform.

---

## 1. Claude Code / Claude Desktop

Add the contents of `claude_desktop_config.json` to your Claude configuration file:
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Claude Code CLI**: Run `claude mcp add job-finder -- /Users/akhilbaja/Documents/Akhil/Job\ Finder/backend/venv/bin/python /Users/akhilbaja/Documents/Akhil/Job\ Finder/backend/mcp/server.py`

---

## 2. Google Antigravity & Gemini CLI

Copy or symlink `gemini_mcp_config.json` to:
- `~/.gemini/config/mcp_config.json` or `.gemini/antigravity/mcp_config.json`

The agent skills in `.agents/skills/` are **automatically discovered** whenever Antigravity runs in this workspace!

---

## 3. Cursor IDE

In Cursor:
1. Go to **Settings > Cursor Settings > Features > MCP**.
2. Click **+ Add New MCP Server**.
3. Choose **Type: Stdio**.
4. Set Command to `/Users/akhilbaja/Documents/Akhil/Job Finder/backend/venv/bin/python`.
5. Set Args to `/Users/akhilbaja/Documents/Akhil/Job Finder/backend/mcp/server.py`.
6. Add Environment Variable: `PYTHONPATH=/Users/akhilbaja/Documents/Akhil/Job Finder/backend`.

---

## 4. Windsurf & Zed

Add the `mcpServers` block to:
- **Windsurf**: `~/.codeium/windsurf/mcp_config.json`
- **Zed**: Add to `.zed/settings.json` under context servers.

---

## Available MCP Tools:
- **Discovery**: `search_jobs`, `scrape_job_posting`
- **ATS Scoring**: `calculate_ats_score`, `analyze_skill_gap`, `extract_seniority_salary`
- **Resume & LaTeX**: `tailor_resume_latex`, `compile_latex_metrics`, `export_overleaf_bundle`
- **Recruiter Intel**: `extract_recruiter_profile`, `generate_outreach_inmail`
- **Interview Prep**: `generate_interview_pack`, `company_culture_brief`
- **Application CRM**: `track_application`, `list_applications`, `check_duplicate_application`
