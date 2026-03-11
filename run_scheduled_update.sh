#!/usr/bin/env bash
# AFL Dashboard – Cron/LaunchAgent Wrapper
# ==========================================
# This script is called by cron or launchd to run the scheduled update.
# It handles conda activation and environment setup.
#
# Cron entry (Mon & Fri at 7:00 AM):
#   0 7 * * 1,5 /Users/marcuswagner/coding/AFL_dashboard/run_scheduled_update.sh
#
# To install:
#   chmod +x /Users/marcuswagner/coding/AFL_dashboard/run_scheduled_update.sh
#   crontab -e   # then add the line above

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

export PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python

echo "=========================================="
echo "AFL Dashboard – Scheduled Update"
echo "$(date)"
echo "=========================================="

# --- Try conda first ---
if command -v conda >/dev/null 2>&1; then
    eval "$(conda shell.bash hook 2>/dev/null)" || true
    if conda activate afl 2>/dev/null; then
        echo "Using conda env: afl"
        python scheduled_update.py "$@"
        exit $?
    fi
fi

# --- Try Homebrew conda path (Apple Silicon) ---
if [ -f /opt/homebrew/bin/conda ]; then
    eval "$(/opt/homebrew/bin/conda shell.bash hook 2>/dev/null)" || true
    if conda activate afl 2>/dev/null; then
        echo "Using conda env: afl (homebrew)"
        python scheduled_update.py "$@"
        exit $?
    fi
fi

# --- Try Intel Mac conda path ---
if [ -f /usr/local/bin/conda ]; then
    eval "$(/usr/local/bin/conda shell.bash hook 2>/dev/null)" || true
    if conda activate afl 2>/dev/null; then
        echo "Using conda env: afl (Intel)"
        python scheduled_update.py "$@"
        exit $?
    fi
fi

# --- Fallback to .venv ---
if [ -f "$SCRIPT_DIR/.venv/bin/activate" ]; then
    echo "Using .venv"
    source "$SCRIPT_DIR/.venv/bin/activate"
    python scheduled_update.py "$@"
    exit $?
fi

echo "ERROR: No conda env 'afl' or .venv found" >&2
exit 1
