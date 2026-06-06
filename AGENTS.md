# Agent Notes

This project is a Docker-based Jupyter workspace for tax-aware stop-loss and re-entry simulations.

## Read First

Before making changes, read:

```text
.agents/python-project-conventions.md
.agents/execution-and-validation.md
.agents/current-model-notes.md
```

For notebook changes, also read:

```text
.agents/notebook-conventions.md
```

For financial model changes, also read:

```text
.agents/financial-modeling-conventions.md
```

For specialist review or domain-specific critique, use:

```text
.agents/specialist-personas.md
```

When the task needs structured user interrogation or clarification, use:

```text
.agents/user-interrogation-skills.md
```

For durable learning capture and shell-tooling notes, read:

```text
.agents/learning-and-tooling.md
```

## Project Quick Reference

Planning and documentation:

```text
agent-planning/   ← write a plan file here before starting any change
docs/             ← write human-readable change documentation here when done
```

Active notebooks:

```text
notebooks/01_tax_baseline.ipynb
notebooks/02_stop_loss_benchmark.ipynb
notebooks/03_bear_recovery_scenarios.ipynb
notebooks/04_stop_reentry_vs_hold.ipynb
notebooks/05_probability_weighted_ranking.ipynb
```

Shared code:

```text
src/tax_risk_sim.py   ← all financial calculations
src/inputs.py         ← shared position, tax, and model inputs for notebooks 01–04
```

Previous exploratory notebooks:

```text
archive/notebooks
```

Full quality command:

```bash
docker run --rm \
  -v "$PWD":/home/jovyan/work \
  -w /home/jovyan/work \
  -e PYTHONPATH=/home/jovyan/work/src \
  quay.io/jupyter/scipy-notebook:latest \
  sh -lc "python -m pip install --quiet -r requirements-dev.txt && pytest -q && ruff format --check src scripts tests && ruff check src scripts tests"
```
