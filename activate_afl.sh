#!/bin/bash
# AFL Dashboard - Quick Environment Activation
# Usage: source activate_afl.sh

# Initialize conda for this shell session
eval "$(/opt/homebrew/bin/conda shell.bash hook)"

# Activate the AFL environment
conda activate afl

# Set protobuf workaround
export PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python

echo "✅ AFL environment activated!"
echo "   Python: $(python --version)"
echo "   Conda env: $CONDA_DEFAULT_ENV"
echo ""
echo "To run the dashboard:"
echo "   python -m streamlit run app.py"
echo ""
