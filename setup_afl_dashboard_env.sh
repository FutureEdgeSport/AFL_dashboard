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

# 4. (Re)install pip requirements for safety (if needed)
pip install --upgrade pip
pip install -r requirements.txt

# 5. Set protobuf workaround for macOS
export PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python

echo "\nAFL Dashboard environment setup complete!"
echo "To run the app:"
echo "  conda activate afl"
echo "  export PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python"
echo "  streamlit run app.py --server.port 8501"
