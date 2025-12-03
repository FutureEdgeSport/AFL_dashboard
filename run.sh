#!/usr/bin/env bash
# AFL Dashboard – Quick launcher
# Activates the conda 'afl' environment, sets the protobuf workaround,
# and starts Streamlit on port 8501.

set -e

CONDA_ENV="afl"
STREAMLIT_PORT="8501"

# Source conda initialization
eval "$(conda shell.bash hook)"

# Activate environment
conda activate "$CONDA_ENV"

# Export protobuf workaround for macOS Big Sur compatibility
export PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python

echo "🏉 Starting FutureEdge AFL Dashboard..."
echo "   Environment: $CONDA_ENV"
echo "   Port: $STREAMLIT_PORT"
echo "   Local URL: http://localhost:$STREAMLIT_PORT"
echo ""

python -m streamlit run app.py --server.port "$STREAMLIT_PORT"
