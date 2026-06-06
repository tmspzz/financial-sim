# Tax Risk Simulation

Docker-based Jupyter workspace for a tax-aware portfolio risk simulation.

## Setup (first time)

Install dependencies and verify the environment:

```bash
./setup.sh
```

Requires Docker Desktop to be installed and running. The script installs [RTK](https://github.com/rtk-ai/rtk) (a token-compression proxy for AI coding agents), pulls the Docker image, and runs the full quality check suite to confirm the setup is working.

## Start

Start Docker Desktop first, then run:

```bash
docker compose up
```

Open:

```text
http://localhost:8888/lab
```

The active notebooks are:

```text
notebooks/01_tax_baseline.ipynb           ← sell-today baseline and sensitivity table
notebooks/02_stop_loss_benchmark.ipynb    ← candidate stop levels and required recovery
notebooks/03_bear_recovery_scenarios.ipynb ← bear drawdown and recovery assumptions
notebooks/04_stop_reentry_vs_hold.ipynb   ← stop + re-entry advantage heatmap
notebooks/05_probability_weighted_ranking.ipynb ← probability-weighted scenario ranking
```

Each notebook is self-contained and can be run independently in any order. The numbered
prefix reflects the narrative progression of the analysis, not an execution dependency.

Shared inputs (position, tax rate, stop levels, model parameters) live in:

```text
src/inputs.py
```

Change that file to model a different position or scenario. Notebooks 01–04 import from it
directly. Notebook 05 uses a separate intentionally different assumption set defined in
that notebook.

Shared calculation code lives in:

```text
src/tax_risk_sim.py
```

The previous exploratory notebooks were kept in:

```text
archive/notebooks
```

The project folder is bind-mounted into the container, so edits made on your Mac are visible inside Jupyter at:

```text
/home/jovyan/work
```

If a notebook is already open in JupyterLab while the file changes on disk, Jupyter may show a reload prompt. Use that prompt, or close and reopen the notebook tab to pick up the latest file contents.

## Stop

Press `Ctrl+C` in the terminal running Docker Compose.

## Notes

The environment uses the maintained Jupyter Docker Stacks image:

```text
quay.io/jupyter/scipy-notebook:latest
```

It includes JupyterLab, NumPy, pandas, SciPy, matplotlib, and related scientific Python packages.

## Quality Checks

Run tests, linting, and formatting checks inside Docker:

```bash
docker run --rm \
  -v "$PWD":/home/jovyan/work \
  -w /home/jovyan/work \
  -e PYTHONPATH=/home/jovyan/work/src \
  quay.io/jupyter/scipy-notebook:latest \
  sh -lc "python -m pip install --quiet -r requirements-dev.txt && pytest -q && ruff format --check src scripts tests && ruff check src scripts tests"
```
