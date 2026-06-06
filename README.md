# Tax Risk Simulation

Docker-based Jupyter workspace for a tax-aware portfolio risk simulation.

## Setup (first time)

Install dependencies and verify the environment:

```bash
./setup.sh
```

Requires Docker Desktop to be installed and running. The script installs [RTK](https://github.com/rtk-ai/rtk) (a token-compression proxy for AI coding agents), pulls the base Docker image, builds the project image, and runs the full quality check suite to confirm the setup is working.

## Start

Start Docker Desktop first, then run:

```bash
docker compose build
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
notebooks/06_portfolio_transaction_simulation.ipynb ← transaction-aware portfolio simulation
notebooks/07_real_portfolio_stop_loss.ipynb ← Deutsche Bank PDF → real portfolio stop-loss analysis
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

Shared code lives in:

```text
src/tax_risk_sim.py   ← single-position tax, stop-loss, bear recovery, and stop/re-entry math
src/portfolio_sim.py  ← portfolio schemas, FX/price providers, lot engine, reconciliation, simulation
src/pdf_parser.py     ← Deutsche Bank Vermögensanlage-Report parser
src/inputs.py         ← shared single-position inputs for notebooks 01–04
```

Portfolio and PDF workflows use scripts:

```text
scripts/normalize_portfolio_inputs.py  ← validate CSV and write CSV + Parquet
scripts/validate_portfolio_inputs.py   ← validate canonical holdings/transactions CSV
scripts/parse_db_pdf.py                ← parse Deutsche Bank PDF to CSV + Parquet
scripts/portfolio_snapshot.py          ← PDF → lots → prices → portfolio snapshot
scripts/stop_loss_real_portfolio.py    ← PDF → per-position stop-loss/re-entry ranking
```

Real portfolio price lookup needs a local ISIN-to-ticker map. Keep the real map
at:

```text
data/private/ticker_map.json
```

That file is gitignored. A committed synthetic example lives at:

```text
data/examples/ticker_map_synthetic.json
```

Real broker files belong under:

```text
data/private/
```

That directory is gitignored. Commit only synthetic examples under
`data/examples/` or test fixtures under `tests/fixtures/`.

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

The environment uses a project Docker image built from the maintained Jupyter
Docker Stacks image:

```text
financial-sim:latest
```

The project image installs `requirements-dev.txt`, so notebooks, scripts, tests,
PDF parsing, Parquet I/O, and linting tools are available inside the same Docker
environment. If `requirements-dev.txt` changes, rebuild with:

```bash
docker compose build
```

## Quality Checks

Run tests, linting, and formatting checks inside Docker:

```bash
docker run --rm \
  -v "$PWD":/home/jovyan/work \
  -w /home/jovyan/work \
  -e PYTHONPATH=/home/jovyan/work/src \
  financial-sim:latest \
  sh -lc "pytest -q && ruff format --check src scripts tests && ruff check src scripts tests"
```
