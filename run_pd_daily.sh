#!/usr/bin/env bash
# Daily PD TeamTracker sync — invoked by com.afldashboard.pd.plist
set -euo pipefail

REPO="/Users/marcuswagner/coding/AFL_dashboard"
VENV="$REPO/.venv"
LOG_DIR="$REPO/logs/pd_scraper"
mkdir -p "$LOG_DIR"

TS="$(date +%Y-%m-%d_%H-%M-%S)"
LOG="$LOG_DIR/daily_${TS}.log"

cd "$REPO"
"$VENV/bin/python" -m pd_scraper.cli daily-sync >>"$LOG" 2>&1
