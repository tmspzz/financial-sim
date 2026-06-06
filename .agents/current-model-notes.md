# Current Model Notes

## Current Core Assumptions

The canonical inputs for notebooks 01–04 live in a single file:

```text
src/inputs.py
```

To change the position, tax rate, stop levels, or any model parameter, edit that file. All notebooks that share these inputs will pick up the change automatically on the next run.

The current values are:

```text
shares = 35
current_price = 350.0
cost_basis_per_share = 124.0
capital_gains_tax_rate = 0.26
reentry_slippage_from_bear_low = 0.05
transaction_cost_rate = 0.00
allow_fractional_reentry_shares = False
```

Notebook 05 (`05_probability_weighted_ranking.ipynb`) intentionally preserves a separate older exploratory assumption set defined inline in that notebook:

```text
shares = 350
current_price = 350.0
cost_basis_per_share = 123.0
Bear/Base/Bull probabilities = 45% / 15% / 40%
```

Do not silently merge these two assumption sets into `src/inputs.py`. They answer different questions.

Notebook 06 (`06_portfolio_transaction_simulation.ipynb`) uses validated
portfolio CSV/Parquet inputs and `src/portfolio_sim.py`. It does not use
`src/inputs.py`.

Notebook 07 (`07_real_portfolio_stop_loss.ipynb`) parses a Deutsche Bank
Vermögensanlage-Report PDF, seeds lots from broker holdings with cost basis,
fetches prices through a static map or Yahoo ticker map, and applies the
single-position stop/re-entry model to every holding.

Portfolio/PDF inputs are separate from the single-position inputs:

```text
src/portfolio_sim.py  ← portfolio schemas, FX/price providers, lot engine, reconciliation
src/pdf_parser.py     ← Deutsche Bank Vermögensanlage-Report parser
data/private/         ← gitignored real broker files and generated outputs
data/private/ticker_map.json  ← gitignored real ISIN-to-ticker map for local simulations
data/examples/        ← synthetic examples
tests/fixtures/       ← synthetic test fixtures
```

## Important Modeling Notes

The stop + re-entry heatmap answers a conditional scenario question:

```text
If this bear drawdown and recovery happen, is stop + re-entry better than holding?
```

It does not assign probabilities to bear drawdowns.

The probability-weighted notebook answers a different expected-value question and uses explicit scenario probabilities.

The current stop + re-entry model is endpoint-based, not path-based:

```text
today -> stop trigger -> bear low -> recovery price
```

It does not yet model interim volatility, second stops, stochastic paths, or the chance of re-entering before the true low.

The portfolio model is transaction/snapshot based, not a replacement for the
single-position scenario model. It supports FIFO lots by default, flat tax rates,
ECB/Yahoo FX providers, optional Yahoo security price lookup through an ISIN →
ticker map, and partial exclusion of unsupported corporate actions.

## Known Gotchas

- Bear scenarios must be ordered numerically by `drawdown`, not by labels like `Bear -6%`; string sorting creates confusing column order.
- Re-entry uses whole shares by default. Leftover cash is tracked in `leftover_cash_after_reentry`.
- `reentry_price` is the bear low adjusted by `reentry_slippage_from_bear_low`.
- The main heatmap in notebook 04 already includes tax, re-entry slippage, whole-share rounding, leftover cash, and transaction costs.
- Notebooks 06–07 require the project Docker image `financial-sim:latest`; do not rely on ad hoc package installs inside Jupyter.
- The Deutsche Bank parser currently supports the observed Vermögensanlage-Report format only. Other Deutsche Bank PDF layouts need fixtures and parser updates.
- Real broker files must stay under `data/private/`; do not commit them.
- Real ticker maps must stay in ignored `data/private/ticker_map.json`; commit only synthetic ticker maps under `data/examples/`.
- If notebooks are open in JupyterLab while files are edited on disk, reload the notebook tab before rerunning.

Longer-term modeling improvements are tracked in:

```text
IMPROVEMENT_PLAN.md
```
