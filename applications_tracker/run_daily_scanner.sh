#!/bin/bash
set -eo pipefail

# ─────────────────────────────────────────────────────────────────────────────
# run_daily_scanner.sh
# Automated daily job scanner & auto-apply pipeline for macOS
# ─────────────────────────────────────────────────────────────────────────────

PROJECT_DIR="/Users/akhilbaja/Documents/Akhil/Job Finder"
VENV_PYTHON="$PROJECT_DIR/backend/venv/bin/python"
SCANNER_SCRIPT="$PROJECT_DIR/applications_tracker/scheduled_job_scanner.py"
LINKEDIN_SCANNER_SCRIPT="$PROJECT_DIR/applications_tracker/linkedin_top_applicant_scanner.py"
LOG_DIR="$PROJECT_DIR/applications_tracker/logs"

mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/scanner_$(date +'%Y-%m-%d').log"

echo "================================================================" >> "$LOG_FILE"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] 🚀 Starting Daily Scheduled Job Scanner & Auto-Apply Pipeline" >> "$LOG_FILE"
echo "================================================================" >> "$LOG_FILE"

# Load environment variables from backend/.env if present
if [ -f "$PROJECT_DIR/backend/.env" ]; then
    set -a
    source "$PROJECT_DIR/backend/.env"
    set +a
fi

# Enable Auto-Submit (Guardrails disabled for autonomous application submission)
export BROWSER_USE_DISABLE_GUARDRAILS="1"
export BROWSER_USE_HEADLESS="false"

# Phase 1: Run the scheduled ATS portal scanner
echo "[$(date '+%Y-%m-%d %H:%M:%S')] 🔍 [Phase 1] Running Scheduled ATS Portal Scanner..." >> "$LOG_FILE"
"$VENV_PYTHON" "$SCANNER_SCRIPT" >> "$LOG_FILE" 2>&1 || echo "⚠️ ATS Scanner completed with non-zero exit code" >> "$LOG_FILE"

# Phase 2: Run LinkedIn Top Applicant Scanner & Auto-Apply
echo "[$(date '+%Y-%m-%d %H:%M:%S')] 🌟 [Phase 2] Running LinkedIn 'Top Applicant' Scanner & Auto-Apply..." >> "$LOG_FILE"
"$VENV_PYTHON" "$LINKEDIN_SCANNER_SCRIPT" --limit 10 --auto-submit >> "$LOG_FILE" 2>&1 || echo "⚠️ LinkedIn Top Applicant Scanner completed with non-zero exit code" >> "$LOG_FILE"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] 🏁 Daily Pipeline Completed Successfully" >> "$LOG_FILE"
echo "" >> "$LOG_FILE"
exit 0
