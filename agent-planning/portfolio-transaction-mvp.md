# Plan: Portfolio transaction MVP

## Goal
Build a vertical MVP for real portfolio inputs using synthetic Deutsche
Bank-like CSV fixtures before implementing a real PDF parser. The MVP supports
multi-security transaction-aware simulation, holdings reconciliation, FX
conversion, and portfolio-level reporting.

## Decisions Recorded From `/grill-me`
- Start from both holdings snapshots and transactions.
- Treat transactions as source of truth when available.
- Use holdings snapshots for reconciliation and validation.
- Require broker/validated-input-provided security prices in v1.
- Fetch FX rates through a configurable provider interface.
- Default FX provider to ECB for EUR reporting; allow Yahoo by configuration.
- Use transaction-date FX where applicable.
- Default missing-date FX fallback to previous available rate; allow next or
  nearest by configuration.
- Use configurable tax-lot method, default FIFO.
- Model buy, sell, fees, cash dividends, taxes withheld, simple splits, and
  inbound/outbound transfers.
- Ingest and classify mergers, spin-offs, and options, but flag them
  unsupported for simulation until rules are defined.
- Block affected securities from trusted totals by default.
- Allow partial results only through explicit opt-in, with separate warned
  totals.
- Keep v1 tax logic simplified: flat capital gains tax, flat dividend tax, and
  taxes-withheld rows tracked as metadata.
- Use scripts as the canonical pipeline and a notebook as the inspection and
  reporting layer.
- Write validated CSV for human review and Parquet for notebooks/simulation.
- Ignore real data under `data/private/`.
- Commit only synthetic fixtures under `tests/fixtures/` or `data/examples/`.
- Defer Deutsche Bank PDF parser implementation until a redacted/synthetic PDF
  fixture or real table sample is available.

## Module boundaries

Portfolio logic lives in a new module, separate from the existing single-position engine:

```text
src/portfolio_sim.py   ← new: lot engine, FX conversion, portfolio simulation
src/tax_risk_sim.py   ← unchanged: single-position calculations used by notebooks 01–04
src/inputs.py         ← unchanged: single-position inputs used by notebooks 01–04
```

`src/inputs.py` and `src/tax_risk_sim.py` must not be modified as part of this MVP.
Notebooks 01–04 must continue to run without change.

Portfolio inputs come from the validated pipeline output (Parquet), not from
`src/inputs.py`. Notebook 06 reads validated Parquet directly.

## Council review conditions (incorporated)

Conditions from three-round council review (Python Staff Engineer, Senior Financial
Model Reviewer, Germany/Italy/EU Tax Reviewer, Senior Market Analyst):

- Every slice requires a failing pytest written before implementation. Test against
  synthetic fixtures in `tests/fixtures/`.
- Lot ledger schema named in Slice 1. Stored fields: `isin`, `lot_date`,
  `lot_price_EUR`, `remaining_shares`. `unrealised_gain` is derived at query time
  (current price minus lot basis) — never stored.
- Portfolio simulation output schema named in Slice 7.
- `jurisdiction` field (`DE`, `IT`, or ISO 3166-1 alpha-2) added to transaction
  and holdings schemas to support future jurisdiction-aware tax logic.
- Splits are a first-class transaction type, not a mutation of existing rows.
  A split event adjusts `lot_price` and `remaining_shares` proportionally for all
  open lots in the affected security, preserving total cost basis. Fractional shares
  from reverse splits are treated as a cash distribution in v1.
- Known limitations added to requirements doc: Sparer-Pauschbetrag, solidarity
  surcharge, and reverse-split fractional treatment are not modelled in v1.

## Slices
- [x] define canonical schemas: holdings, transaction (with `jurisdiction`), lot ledger (stored fields: `isin`, `lot_date`, `lot_price_EUR`, `remaining_shares`), FX, validation, and portfolio simulation output (`isin`, `reporting_date`, `market_value_EUR`, `unrealised_gain_EUR`, `realised_gain_ytd_EUR`, `tax_paid_ytd_EUR`). Write failing schema-validation tests first.
- [x] add synthetic Deutsche Bank-like CSV fixtures (`data/examples/`, `tests/fixtures/`) and confirm `data/private/` is gitignored. Write fixture-loading tests first.
- [x] implement normalization and validation scripts writing CSV and Parquet. Write failing round-trip tests first.
- [x] implement FX provider interface in `src/portfolio_sim.py` with ECB default and Yahoo option. Write failing provider tests first (mock HTTP).
- [x] implement lot engine in `src/portfolio_sim.py`: FIFO default, configurable method, split handling as first-class transaction type. Write failing tests first including `test_fifo_partial_sell_reduces_oldest_lot_first` and `test_forward_split_halves_lot_price_and_doubles_shares`.
- [x] reconcile transaction-derived holdings against holdings snapshots. Write failing reconciliation tests first.
- [x] implement per-security and portfolio aggregate simulation in `src/portfolio_sim.py` producing the named output schema. Write failing simulation tests first.
- [x] add partial-result handling for unsupported corporate actions with warned totals. Write failing tests for blocked-security behaviour first.
- [x] add notebook `06_portfolio_transaction_simulation.ipynb` reading validated Parquet and producing the portfolio report.
- [x] document implementation, known limitations (Pauschbetrag, solidarity surcharge, reverse-split fractional treatment), and files affected.
