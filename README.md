
# FutureEdge AFL Dashboard

This repository contains a Streamlit dashboard for AFL team and player ratings.

Run instructions and troubleshooting are in this README. For the smoothest
experience on macOS (especially Big Sur / older macOS versions) we recommend
using Conda so binary packages like `pyarrow` and certain `protobuf` builds
are installed as prebuilt wheels.


## Quick Start (Recommended)

1. **Create the conda environment from the included `environment.yml`:**

	```bash
	conda env create -f environment.yml
	conda activate afl
	```

2. **(Optional but recommended) Reinstall pip requirements for safety:**

	```bash
	pip install --upgrade pip
	pip install -r requirements.txt
	```

3. **Run the app (export protobuf workaround in the same shell before running):**

	```bash
	export PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python
	streamlit run app.py --server.port 8501
	```

4. **Open** [http://localhost:8501](http://localhost:8501) **in your browser.**

---

## Troubleshooting

- If you see protobuf-related errors mentioning "Descriptors cannot be created":
  - Make sure `protobuf==3.20.3` is installed (see requirements).
  - Always set `PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python` before running Streamlit.
- Installing `pyarrow` via `pip` on macOS often attempts to build from source and fails; using `conda` (conda-forge) avoids this.
- The app supports optional interactive tables via `streamlit-aggrid`. If you want these, ensure `streamlit-aggrid` is installed in your environment.

---

## Files added/updated

- `requirements.txt` — pip-style dependency list (fully pinned for reproducibility)
- `environment.yml` — recommended conda environment (preferred on macOS)
- `setup_afl_dashboard_env.sh` — one-step environment setup script
- `app.py` — app source (compatibility and image handling improvements)

---

**To fully reset your environment, run:**

```bash
bash setup_afl_dashboard_env.sh
```

This will recreate the environment exactly as required for the AFL Dashboard.
