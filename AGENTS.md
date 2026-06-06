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

If the user types one of these slash-style workflow names, treat it as an
explicit trigger and read `.agents/user-interrogation-skills.md` before
answering:

```text
/grill-me
/to-prd
/to-issues
/tdd
/improve-codebase-architecture
```

Local entry points are provided for tool-specific discovery:

```text
.codex/skills/      ← Codex project skill wrappers
.claude/commands/   ← Claude Code slash-command wrappers
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

Before stopping, reconcile implementation against durable docs:

```text
1. Re-read the active plan in agent-planning/.
2. Mark completed slices [x] and leave unfinished slices [ ].
3. Re-read relevant docs/ pages and update stale assumptions or limitations.
4. Search docs/plans for contradicted phrases such as "deferred",
   "not implemented", or "out of scope" when the feature was implemented.
5. If the user corrected a mistake or changed a decision, update affected
   README, AGENTS.md, .agents notes, plans, docs, scripts, notebooks, examples,
   and tests in the same turn.
6. Run git status --short and report remaining unrelated or untracked files.
```

Do not finish a multi-step implementation while plans or docs contradict the
actual code, tests, notebooks, or scripts.

Active notebooks:

```text
notebooks/01_tax_baseline.ipynb
notebooks/02_stop_loss_benchmark.ipynb
notebooks/03_bear_recovery_scenarios.ipynb
notebooks/04_stop_reentry_vs_hold.ipynb
notebooks/05_probability_weighted_ranking.ipynb
notebooks/06_portfolio_transaction_simulation.ipynb
notebooks/07_real_portfolio_stop_loss.ipynb
```

Shared code:

```text
src/tax_risk_sim.py   ← single-position tax, stop-loss, bear recovery, stop/re-entry math
src/portfolio_sim.py  ← portfolio schemas, FX/price providers, lot engine, reconciliation
src/pdf_parser.py     ← Deutsche Bank Vermögensanlage-Report parser
src/inputs.py         ← shared single-position inputs for notebooks 01–04
```

Portfolio and PDF scripts:

```text
scripts/normalize_portfolio_inputs.py
scripts/validate_portfolio_inputs.py
scripts/parse_db_pdf.py
scripts/portfolio_snapshot.py
scripts/stop_loss_real_portfolio.py
```

Data:

```text
data/private/     ← gitignored real broker PDFs, CSVs, Parquet, price files
data/private/ticker_map.json ← gitignored real ISIN-to-ticker map for local simulations
data/examples/    ← committed synthetic examples only
tests/fixtures/   ← committed synthetic parser/model fixtures only
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
  financial-sim:latest \
  sh -lc "pytest -q && ruff format --check src scripts tests && ruff check src scripts tests"
```
