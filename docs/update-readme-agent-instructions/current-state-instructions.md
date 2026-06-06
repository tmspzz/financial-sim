# Current State Instructions Update

## What changed
Updated the README and shared agent instructions to match the current codebase.

## Why
The project now includes more than the original single-position notebooks:

- project Docker image `financial-sim:latest`
- portfolio transaction simulation
- Deutsche Bank PDF parsing
- real-portfolio snapshot and stop-loss workflows
- notebooks 06 and 07

The top-level docs and agent notes still emphasized notebooks 01-05 and
`src/tax_risk_sim.py`, which made future agents likely to miss the implemented
portfolio and PDF layers.

## Files affected
- `README.md` — active notebooks, shared code, scripts, data privacy, Docker
  image setup, and private vs synthetic ticker-map locations.
- `AGENTS.md` — active notebooks, shared code, portfolio/PDF scripts, data
  locations, ticker-map privacy boundary, full quality command.
- `.agents/current-model-notes.md` — portfolio/PDF model notes and gotchas.
- `.agents/python-project-conventions.md` — current source-of-truth modules and
  notebooks, plus council-review triggers for portfolio and PDF parser work.
- `.agents/notebook-conventions.md` — shared notebook logic now points to the
  current source modules.
- `.agents/user-interrogation-skills.md` — discovery-before-questioning now
  includes the portfolio and PDF parser modules, and architecture guidance
  matches the current module split.
- `.agents/execution-and-validation.md` — useful validation commands now run
  inside `financial-sim:latest`, not host Python.

## Validation
No Python behavior changed. This was a documentation and instruction update.
