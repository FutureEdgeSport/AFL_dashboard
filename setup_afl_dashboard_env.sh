#!/bin/bash
# AFL Dashboard Environment Setup Script
# This script will recreate the exact environment for the AFL Dashboard app.
# Usage: bash setup_afl_dashboard_env.sh

set -e

# 1. Remove any existing environment (optional, uncomment if needed)
# conda env remove -n afl || true

# 2. Create the conda environment from environment.yml
conda env create -f environment.yml || conda env update -f environment.yml

# 3. Activate the environment
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate afl

# 4. Optional: pip extras
#
# IMPORTANT: avoid `pip install -r requirements.txt` inside this conda env.
# Mixing conda + pip for compiled packages (numpy/pyarrow/pandas) is a common
# cause of ABI/import errors on macOS (e.g. "numpy.core.multiarray failed to import").
#
# If you *must* install a pure-python helper lib, do it ad-hoc:
#   pip install <package>

# 5. Set protobuf workaround for macOS
export PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python

echo "\nAFL Dashboard environment setup complete!"
echo "To run the app:"
echo "  conda activate afl"
echo "  export PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python"
echo "  streamlit run app.py --server.port 8501"
