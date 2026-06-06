# Add: Shared Inputs Module

## What changed

A new file `src/inputs.py` centralises all position, tax, and model inputs that were previously duplicated across notebooks 01–04. The notebooks now import from it instead of declaring their own copies.

**Plain English:** Before this change, if you wanted to model a different position — say you now hold 50 shares bought at $180 — you had to edit four separate notebooks and hope you didn't miss one. Now you edit one file and every notebook picks up the change automatically on the next run.

**This answers the question:** Where is the single place to change my position, tax rate, stop levels, or scenario parameters?

Example: To model 50 shares at $180 with a 28% tax rate, open `src/inputs.py` and change:

```python
shares = 50
current_price = 180.0
cost_basis_per_share = 45.0
capital_gains_tax_rate = 0.28
```

Re-run any notebook. All tables and charts update automatically.

## Structure of src/inputs.py

Inputs are grouped into sections with inline documentation:

| Section | Variables |
|---|---|
| Position | `shares`, `current_price`, `cost_basis_per_share` |
| Tax | `capital_gains_tax_rate` |
| Stop-loss candidates | `stop_loss_drops` |
| Bear drawdown range | `bear_drawdown_start`, `bear_drawdown_end`, `bear_drawdown_step` |
| Bear recovery formula | `bear_recovery_multiplier`, `bear_min/max_recovery_return`, `bear_base/min_recovery_probability` |
| Stop + re-entry | `reentry_slippage_from_bear_low`, `transaction_cost_rate`, `allow_fractional_reentry_shares` |
| Sensitivity range | `min_return`, `max_return`, `return_step` |
| Benchmark tolerance | `benchmark_recovery_tolerance` |

Each section includes a plain-English description, the units, and an example, following the notebook-conventions prose pattern.

## Notebook 05 is intentionally excluded

`05_probability_weighted_ranking.ipynb` uses a separate older exploratory assumption set (`shares=350`, `basis=123.0`) documented in `.agents/current-model-notes.md`. That set answers a different question and must not be merged into `src/inputs.py`.

## README corrected

The README previously said "Run them in order." This was wrong — notebooks have never had an execution dependency on each other. Each notebook has always imported from `src/tax_risk_sim.py` and set up its own variables independently. The instruction was a narrative suggestion (the numbered prefix reflects the analytical story arc) that was mistakenly written as an execution requirement.

The README now states:

> Each notebook is self-contained and can be run independently in any order.

## Why

The actual problem was assumption duplication, not execution ordering. Changing the modelled position required editing four files. The `src/` directory is already the established home for shared code in this project, making `src/inputs.py` the natural location.

A "notebook of notebooks" pattern (using papermill or `%run` orchestration) was considered but rejected at this stage. It solves execution orchestration, not duplication, and adds fragility — notebooks would no longer be independently runnable if their setup depended on a parent kernel's state. The simpler fix of a shared module achieves the goal without new dependencies.

## Assumptions

Notebook 05's intentionally different assumption set is preserved exactly as it was, inline in that notebook.

## Files affected

- `src/inputs.py` — new file
- `notebooks/01_tax_baseline.ipynb` — inputs cell replaced with import
- `notebooks/02_stop_loss_benchmark.ipynb` — inputs cell replaced with import
- `notebooks/03_bear_recovery_scenarios.ipynb` — inputs cell replaced with import; bear recovery params named explicitly via `inputs`
- `notebooks/04_stop_reentry_vs_hold.ipynb` — inputs cell replaced with import; bear recovery params named explicitly via `inputs`
- `scripts/summarize_results.py` — replaced inline declarations with imports from `inputs`; removed unused `numpy` import (now only needed inside `inputs.py`)
- `AGENTS.md` — `src/inputs.py` added to shared code reference
- `.agents/current-model-notes.md` — updated to point agents to `src/inputs.py` as the canonical place to change assumptions
- `README.md` — corrected execution-order claim; added description of each notebook; documented `src/inputs.py`

## Known limitations

`src/inputs.py` does not validate its values (e.g. it does not enforce that `capital_gains_tax_rate` is between 0 and 1, or that `shares` is positive). Validation happens at the function call sites in `src/tax_risk_sim.py` and is minimal there too. Callers are expected to provide sensible inputs.

The sensitivity sweep improvement (IMPROVEMENT_PLAN item 8) will be easier now that inputs are centralised: a sweep script can import `inputs` and override individual values programmatically without editing notebooks.
