# Portfolio Transaction MVP — Implementation

## What changed

Added a complete multi-security portfolio simulation layer on top of the existing
single-position model. The existing `src/tax_risk_sim.py` and `src/inputs.py` are
unchanged. Notebooks 01–04 are unaffected.

The new code lives entirely in `src/portfolio_sim.py` and is tested by
`tests/test_portfolio_sim.py`. Two CLI scripts handle the input pipeline. Notebook
06 shows the end-to-end workflow.

## Files added

| File | Purpose |
|------|---------|
| `src/portfolio_sim.py` | All portfolio logic: schemas, validation, FX providers, FIFO lot engine, reconciliation, simulation |
| `tests/test_portfolio_sim.py` | 67 tests covering all 8 plan slices |
| `tests/fixtures/transactions_simple.csv` | 5-row synthetic fixture used by validation and simulation tests |
| `tests/fixtures/transactions_with_split.csv` | 3-row fixture covering the split + sell path |
| `tests/fixtures/holdings_simple.csv` | Broker snapshot fixture for reconciliation tests |
| `data/examples/db_transactions_synthetic.csv` | 10-row synthetic Deutsche Bank-like transaction log |
| `data/examples/db_holdings_synthetic.csv` | Broker holdings snapshot for the synthetic example (2023-12-31) |
| `scripts/normalize_portfolio_inputs.py` | Reads a raw CSV, validates it, writes a clean CSV and Parquet |
| `scripts/validate_portfolio_inputs.py` | Validates a portfolio CSV and prints a human-readable report |
| `notebooks/06_portfolio_transaction_simulation.ipynb` | Reads validated Parquet, runs simulation, shows reconciliation and portfolio report |

## Files modified

| File | Change |
|------|--------|
| `requirements-dev.txt` | Added `requests` (ECB/Yahoo HTTP) and `pyarrow` (Parquet I/O) |
| `.github/workflows/ci.yml` | Added `requests pyarrow` to the pip install step |
| `.gitignore` | Added `data/private/` before any real data could be committed |
| `agent-planning/portfolio-transaction-mvp.md` | All 10 slices marked complete |

## Architecture

```text
data/private/            ← gitignored; real broker exports go here
data/examples/           ← synthetic examples committed to the repo
tests/fixtures/          ← minimal synthetic fixtures for unit tests

scripts/normalize_portfolio_inputs.py
   reads raw CSV
   -> validates with validate_transactions() or validate_holdings()
   -> writes normalized CSV (human review)
   -> writes Parquet (notebooks and simulation)

notebooks/06_portfolio_transaction_simulation.ipynb
   reads Parquet
   -> configures FX provider (ECB default, Yahoo or FixedRate alternatives)
   -> checks for unsupported corporate actions
   -> simulate_portfolio_partial() → output DataFrame
   -> reconcile_holdings() against broker snapshot
   -> lots_to_dataframe() + derived unrealised gain per lot
```

## Key design decisions

### Module isolation

All portfolio logic is in `src/portfolio_sim.py`. It does not import from
`src/tax_risk_sim.py` or `src/inputs.py`, and those files were not modified.
This keeps the single-position model stable for notebooks 01–04.

### FIFO lot engine

The lot ledger is a `list[dict]` with fields:
- `isin` — security identifier
- `lot_date` — acquisition date (ISO 8601 string)
- `lot_price_eur` — per-share cost basis in EUR at acquisition
- `remaining_shares` — shares not yet sold

`unrealised_gain` is derived at query time (`current_price - lot_price_eur` ×
`remaining_shares`) and is never stored. This avoids staleness.

### Splits as first-class transaction type

A split row carries the ratio in the `quantity` field (e.g. `2.0` for a 2-for-1
split). `apply_split()` adjusts all open lots for the security proportionally:
`lot_price_eur / ratio` and `remaining_shares × ratio`. Total cost basis is
preserved.

### ECB FX direction

The ECB Statistical Data Warehouse returns rates as units of non-EUR currency per
1 EUR (OBS_VALUE). So:
- USD → EUR: `1 / OBS_VALUE`
- EUR → USD: `OBS_VALUE`

The 7-day lookback window handles weekends and market holidays.

### Unsupported corporate actions

`merger`, `spin_off`, and `option` are ingested and validated but cannot be
simulated. `check_unsupported_actions()` identifies affected ISINs.
`simulate_portfolio()` raises `UnsupportedCorporateAction` if any are present.
`simulate_portfolio_partial()` silently excludes them and returns the excluded
ISINs as a warning list. Partial totals must not be presented as complete
portfolio values.

### jurisdiction field

The `jurisdiction` field (ISO 3166-1 alpha-2, e.g. `DE`, `IE`, `US`) is required
in both transaction and holdings schemas. It is captured in all fixtures and
example data but is not yet used to vary tax logic. It is reserved for future
jurisdiction-aware tax treatment.

## Assumptions

- Security prices at the reporting date are supplied by the caller. The simulation
  does not fetch stock or ETF prices automatically.
- Tax rates are flat across all securities. Jurisdiction-specific rules are not
  applied in v1.
- Transaction-date FX rates are used throughout. Intraday spot rates are not
  modelled.
- The synthetic data uses Deutsche Bank AG (DE), iShares Core MSCI World ETF (IE),
  and Apple Inc (US) as representative examples of domestic, EU, and US securities.

## Known limitations

| Limitation | Details |
|------------|---------|
| Sparer-Pauschbetrag | The German annual capital gains tax-free allowance (€1,000 single / €2,000 joint as of 2023) is not modelled. Users who have not exhausted their allowance will see higher modelled tax than brokers actually withhold. |
| Solidarity surcharge | Not modelled as a separate line. Fold it into the flat rate if needed: 26.375% = 25% Abgeltungsteuer × 1.055 Soli. Church tax is excluded. |
| Reverse-split fractional shares | Retained at full precision in the lot ledger. No cash distribution event is generated. The correct tax treatment (dividend-equivalent subject to KeSt in Germany) is noted but not implemented. |
| Unsupported corporate actions | `merger`, `spin_off`, `option` block the affected ISIN from trusted totals. There is no partial-valuation model for in-progress corporate actions. |
| Jurisdiction-aware tax | `jurisdiction` field is captured and validated but not yet used to branch tax logic by country. Italian or other EU treatments are deferred. |
| Transaction-date FX | Cross-currency lots use the FX rate on the transaction date. If the same security is bought in multiple currencies on different dates the basis is consistent within each lot but no average is taken across lots. |
| PDF parser | Deutsche Bank PDF parsing is deferred. The adapter boundary is defined (validated CSV in canonical schema) but not implemented. |
