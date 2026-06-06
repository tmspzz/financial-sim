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
| `src/pdf_parser.py` | Parses Deutsche Bank Vermögensanlage-Report PDFs into canonical transactions and holdings |
| `tests/test_pdf_parser.py` | Unit tests for text parsing plus skipped private-PDF integration tests |
| `scripts/parse_db_pdf.py` | CLI wrapper that writes parsed Deutsche Bank transactions and holdings as CSV and Parquet |
| `scripts/portfolio_snapshot.py` | Parses a Deutsche Bank PDF, seeds lots from broker holdings, fetches prices, and prints a portfolio snapshot |
| `scripts/stop_loss_real_portfolio.py` | Applies stop-loss / re-entry analysis across real PDF-derived holdings |
| `notebooks/07_real_portfolio_stop_loss.ipynb` | Notebook report for real portfolio stop-loss / re-entry analysis |

## Files modified

| File | Change |
|------|--------|
| `requirements-dev.txt` | Added `requests` (ECB/Yahoo HTTP), `pyarrow` (Parquet I/O), and `pdfplumber` (PDF parsing) |
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

scripts/parse_db_pdf.py
   reads Deutsche Bank Vermögensanlage-Report PDF
   -> extracts transactions + holdings/cost basis
   -> writes canonical CSV and Parquet

notebooks/06_portfolio_transaction_simulation.ipynb
   MODE = "pdf"       → parse_db_pdf → tx_df + hld_df; live prices via Yahoo/ECB
   MODE = "synthetic" → reads Parquet from normalize_portfolio_inputs.py (offline)

   PDF mode:
   -> configures ECB FX provider
   -> initialize_lots_from_holdings(hld_df) → seeds lot ledger from broker snapshot
   -> simulate_from_snapshot(new_transactions=empty) → output DataFrame
      (uses broker holdings as authoritative starting state; no transaction replay)

   Synthetic mode:
   -> configures FixedRate stub FX provider
   -> checks for unsupported corporate actions
   -> simulate_portfolio_partial() → output DataFrame

   both modes →
   -> reconcile_holdings() against broker snapshot
   -> lots_to_dataframe() + derived unrealised gain per lot

scripts/portfolio_snapshot.py / notebooks/07_real_portfolio_stop_loss.ipynb
   parse Deutsche Bank PDF
   -> initialize_lots_from_holdings()
   -> fetch current prices from a static map or Yahoo ticker map
   -> report per-ISIN market value and gains

scripts/stop_loss_real_portfolio.py
   parse Deutsche Bank PDF
   -> seed lots from holdings with cost basis
   -> fetch current prices
   -> run the existing single-position stop/re-entry model for every holding
   -> print ranked per-position stop-loss summary
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

### Deutsche Bank PDF parser

The PDF parser is implemented in `src/pdf_parser.py` for the Deutsche Bank
Vermögensanlage-Report format. It parses the `Umsätze` transaction section and
the `Vermögensaufstellung mit Einstandskursen` holdings section. The parser is
text-based because `pdfplumber` did not expose reliable tables for this report.

The parser derives split ratios from Deutsche Bank
`Kapitaltransaktion` rows by replaying prior buy/sell share counts and replacing
the reported new-share count with the ratio expected by `apply_split()`.

### Real portfolio price providers

Security prices were originally planned as broker/validated-input-provided only.
The current implementation also includes optional `PriceProvider` abstractions:

- `StaticPriceProvider` for offline JSON-provided prices.
- `YahooPriceProvider` for live prices using a user-supplied ISIN → Yahoo ticker
  map, with FX conversion through the configured FX provider.

This is used by `scripts/portfolio_snapshot.py`,
`scripts/stop_loss_real_portfolio.py`, and
`notebooks/07_real_portfolio_stop_loss.ipynb`.

## Assumptions

- Security prices at the reporting date can be supplied statically or fetched live.
  The canonical CSV/Parquet path requires caller-supplied prices. The PDF path and
  real-portfolio scripts use `YahooPriceProvider` + a user-maintained ISIN→ticker
  map for automatic live price lookup.
- Tax rates are flat across all securities. Jurisdiction-specific rules are not
  applied in v1.
- Transaction-date FX rates are used throughout. Intraday spot rates are not
  modelled.
- The synthetic data uses anonymized security names and synthetic identifiers as
  representative examples of domestic, EU, and US securities.

## Known limitations

| Limitation | Details |
|------------|---------|
| Sparer-Pauschbetrag | The German annual capital gains tax-free allowance (€1,000 single / €2,000 joint as of 2023) is not modelled. Users who have not exhausted their allowance will see higher modelled tax than brokers actually withhold. |
| Solidarity surcharge | Not modelled as a separate line. Fold it into the flat rate if needed: 26.375% = 25% Abgeltungsteuer × 1.055 Soli. Church tax is excluded. |
| Reverse-split fractional shares | Retained at full precision in the lot ledger. No cash distribution event is generated. The correct tax treatment (dividend-equivalent subject to KeSt in Germany) is noted but not implemented. |
| Unsupported corporate actions | `merger`, `spin_off`, `option` block the affected ISIN from trusted totals. There is no partial-valuation model for in-progress corporate actions. |
| Jurisdiction-aware tax | `jurisdiction` field is captured and validated but not yet used to branch tax logic by country. Italian or other EU treatments are deferred. |
| Transaction-date FX | Cross-currency lots use the FX rate on the transaction date. If the same security is bought in multiple currencies on different dates the basis is consistent within each lot but no average is taken across lots. |
| PDF parser | Implemented for the observed Deutsche Bank Vermögensanlage-Report format only. Other Deutsche Bank report types or changed layouts need fixtures and parser updates. The ISIN detection in `_extract_holdings` uses a date-anchored regex (`_HLD_ISIN_LINE_QUICK_RE`) to avoid false-positive matches on long uppercase company-name tokens (e.g. "ASMLHOLDINGN"). The generic `_has_isin` helper is intentionally not used there. |
| Security price lookup | Optional Yahoo-backed price lookup now exists, but requires a user-maintained ISIN → ticker map. Missing mappings are skipped or warned, so reports can exclude positions without mapped prices. |

Real ticker maps should live in ignored `data/private/ticker_map.json`. The committed
example map is `data/examples/ticker_map_synthetic.json`.
