#!/bin/bash
set -eo pipefail

# ─────────────────────────────────────────────────────────────────────────────
# run_daily_scanner.sh
# Automated daily job scanner & auto-apply pipeline for macOS
# ─────────────────────────────────────────────────────────────────────────────

PROJECT_DIR="/Users/akhilbaja/Documents/Akhil/Job Finder"
VENV_PYTHON="$PROJECT_DIR/backend/venv/bin/python"
SCANNER_SCRIPT="$PROJECT_DIR/applications_tracker/scheduled_job_scanner.py"
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

# Run the scanner
"$VENV_PYTHON" "$SCANNER_SCRIPT" >> "$LOG_FILE" 2>&1

EXIT_CODE=$?
echo "[$(date '+%Y-%m-%d %H:%M:%S')] 🏁 Scanner finished with exit code: $EXIT_CODE" >> "$LOG_FILE"
echo "" >> "$LOG_FILE"
exit $EXIT_CODE
