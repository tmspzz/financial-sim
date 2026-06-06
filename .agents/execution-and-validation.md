# Execution And Validation

## Permissions

Docker commands are pre-approved and run without user confirmation. This is configured in:

```text
.claude/settings.local.json
```

If other commands need pre-approval, add them to the `permissions.allow` array in that file using the pattern `"Bash(command *)"`.

## Environment

**Always use Docker. Never use the host Python.**

The host Python environment is not the project environment. It may be missing NumPy, pandas, matplotlib, Jupyter, pytest, and Ruff. Even if those happen to be installed, versions may differ from the container. Results, test outcomes, and formatting decisions made against the host Python are not trustworthy and must not be committed.

If you are not sure whether a command runs cleanly, run it in Docker first.

### Exploring solutions

If you need to sketch out an approach before committing to it — test an expression, inspect a DataFrame shape, explore a library API — use a scratch notebook or script inside the container, not a local Python REPL:

```bash
docker run --rm -it \
  -v "$PWD":/home/jovyan/work \
  -w /home/jovyan/work \
  -e PYTHONPATH=/home/jovyan/work/src \
  quay.io/jupyter/scipy-notebook:latest \
  python
```

Or write a temporary file to `scratch/` and run it in the container. The `scratch/` directory is ignored by version control and is safe to use as a throwaway workspace. Delete scratch files when done — do not commit them.

The Docker image is:

```text
quay.io/jupyter/scipy-notebook:latest
```

The Compose service bind-mounts the project into:

```text
/home/jovyan/work
```

Start JupyterLab:

```bash
docker compose up
```

Open:

```text
http://localhost:8888/lab
```

## Testing

Use `pytest`.

Tests should cover:

- tax calculation
- after-tax liquidation value
- sell-today baseline
- stop-loss benchmark
- bear scenario generation
- stop + re-entry share rounding
- leftover cash
- probability validation

Run tests after every calculation change:

```bash
docker run --rm \
  -v "$PWD":/home/jovyan/work \
  -w /home/jovyan/work \
  -e PYTHONPATH=/home/jovyan/work/src \
  quay.io/jupyter/scipy-notebook:latest \
  sh -lc "python -m pip install --quiet -r requirements-dev.txt && pytest -q"
```

## Formatting And Linting

Use Ruff for formatting and linting.

Run after every Python change:

```bash
docker run --rm \
  -v "$PWD":/home/jovyan/work \
  -w /home/jovyan/work \
  quay.io/jupyter/scipy-notebook:latest \
  sh -lc "python -m pip install --quiet -r requirements-dev.txt && ruff format src scripts tests && ruff check src scripts tests"
```

Before finishing, run the full quality command:

```bash
docker run --rm \
  -v "$PWD":/home/jovyan/work \
  -w /home/jovyan/work \
  -e PYTHONPATH=/home/jovyan/work/src \
  quay.io/jupyter/scipy-notebook:latest \
  sh -lc "python -m pip install --quiet -r requirements-dev.txt && pytest -q && ruff format --check src scripts tests && ruff check src scripts tests"
```

## Notebook Execution

Execute affected notebooks after notebook or shared calculation changes.

Example:

```bash
docker run --rm \
  -v "$PWD":/home/jovyan/work \
  -w /home/jovyan/work \
  quay.io/jupyter/scipy-notebook:latest \
  jupyter nbconvert --to notebook --execute notebooks/04_stop_reentry_vs_hold.ipynb \
  --output ../executed/04_stop_reentry_vs_hold.executed.ipynb \
  --ExecutePreprocessor.timeout=180
```

Run the summary script:

```bash
docker run --rm \
  -v "$PWD":/home/jovyan/work \
  -w /home/jovyan/work \
  quay.io/jupyter/scipy-notebook:latest \
  python scripts/summarize_results.py
```

Summary output is written to:

```text
executed/results_summary.txt
```

## Useful Validation Commands

Validate notebooks as JSON:

```bash
python3 - <<'PY'
import json
from pathlib import Path
for path in sorted(Path("notebooks").glob("*.ipynb")):
    json.loads(path.read_text())
    print("json ok:", path)
PY
```

Compile notebook code cells without executing imports:

```bash
python3 - <<'PY'
import json
from pathlib import Path
for path in sorted(Path("notebooks").glob("*.ipynb")):
    nb = json.loads(path.read_text())
    for i, cell in enumerate(nb["cells"]):
        if cell["cell_type"] == "code":
            src = "".join(cell.get("source", []))
            if src.strip():
                compile(src, f"{path}:cell-{i}", "exec")
    print("compile ok:", path)
PY
```

Validate shared Python:

```bash
python3 -m py_compile src/tax_risk_sim.py
```
