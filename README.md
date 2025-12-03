
# FutureEdge AFL Dashboard

This repository contains a Streamlit dashboard for AFL team and player ratings.

Run instructions and troubleshooting are in this README. For the smoothest
experience on macOS (especially Big Sur / older macOS versions) we recommend
using Conda so binary packages like `pyarrow` and certain `protobuf` builds
are installed as prebuilt wheels.

Quick start (recommended)

1. Create the conda environment from the included `environment.yml`:

```bash
conda env create -f environment.yml
conda activate afl
```

2. Run the app (export protobuf workaround in the same shell before running):

```bash
export PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python
streamlit run app.py --server.port 8501
```

3. Open http://localhost:8501 in your browser.

Notes and troubleshooting

- If you see protobuf-related errors mentioning "Descriptors cannot be created",
	either install `protobuf==3.20.3` into the environment or set
	`PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python` before running Streamlit.
- Installing `pyarrow` via `pip` on macOS often attempts to build from source
	and fails; using `conda` (conda-forge) avoids this.
- The app supports optional interactive tables via `streamlit-aggrid`.
	If you want these, ensure `streamlit-aggrid` is installed in your environment.

Files added/updated

- `requirements.txt` — pip-style dependency list (kept for convenience).
- `environment.yml` — recommended conda environment (preferred on macOS).
- `app.py` — app source (small compatibility shim and image handling robustness added).

If you want, I can push these changes to a remote or further pin versions; tell me how you'd like to proceed.
