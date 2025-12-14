#!/usr/bin/env bash
# AFL Dashboard launcher
#
# Primary supported workflow is conda (`environment.yml`). This launcher will:
#  - use conda env `afl` if conda is available
#  - otherwise fall back to a local `.venv` if present

set -e

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"

export PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python

if command -v conda >/dev/null 2>&1; then
  eval "$(conda shell.bash hook)"
  conda activate afl
  exec python -m streamlit run "$ROOT_DIR/app.py" --server.port 8501
fi

if [ -f "$ROOT_DIR/.venv/bin/activate" ]; then
  # Fallback only (not recommended for compiled deps on macOS)
  source "$ROOT_DIR/.venv/bin/activate"
  exec python -m streamlit run "$ROOT_DIR/app.py" --server.port 8501
fi

echo "No conda or .venv found. Recommended: conda env create -f environment.yml" >&2
exit 1
