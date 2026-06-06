# Portfolio Transaction MVP Requirements And Decisions

## What changed
This document records the `/grill-me` interrogation decisions for expanding the
project from a single-position simulator into a multi-security portfolio
simulator with real-input support.

## Selected solution
Use a vertical MVP with synthetic Deutsche Bank-like CSV fixtures:

```text
synthetic broker CSV fixtures
        -> normalized transaction and holdings schemas
        -> validation report
        -> validated CSV and Parquet
        -> transaction lot engine and FX conversion
        -> per-security and portfolio simulation
        -> notebook report
```

## Input strategy
Support both holdings snapshots and transactions.

Transactions are the source of truth when available. Holdings snapshots are used
for reconciliation and validation against broker-reported positions.

## Deutsche Bank PDF strategy
The original MVP decision was to defer a real Deutsche Bank PDF parser until a
redacted/synthetic PDF fixture or real table sample was available.

That follow-up has now been implemented for the Deutsche Bank
Vermögensanlage-Report format:

```text
src/pdf_parser.py
scripts/parse_db_pdf.py
tests/test_pdf_parser.py
```

The parser extracts transaction rows from the `Umsätze` section and holdings
with cost basis from the `Vermögensaufstellung mit Einstandskursen` section. It
returns canonical transaction and holdings DataFrames compatible with the
portfolio simulation layer.

## Required security fields
Validated holdings require:

- `asset_name`
- at least one of `isin` or `wkn`

Lookup and identifier resolution are out of scope for v1.

## Pricing
The original v1 decision was that security prices should come from broker or
validated input data, not automatic market fetching.

The current implementation keeps that reproducible path through
`StaticPriceProvider`, and also adds optional Yahoo-backed security price lookup
through a user-maintained ISIN → Yahoo ticker map. Live security pricing is used
by the real-portfolio snapshot and stop-loss workflows, but it is not required
for the canonical CSV/Parquet simulation path.

## FX
FX rates are fetched through a configurable provider interface.

Defaults:

- reporting currency: configurable, expected first use is EUR
- provider: ECB for EUR reporting
- optional provider: Yahoo
- transaction-date rates where applicable
- missing-date fallback: previous available rate
- alternative fallbacks: next available or nearest

## Tax lots
Tax-lot method is configurable and defaults to FIFO.

## Transaction and corporate-action scope
Model in v1:

- buy
- sell
- fees
- cash dividends
- taxes withheld
- simple splits
- inbound transfers
- outbound transfers

Ingest and classify, but do not simulate yet:

- mergers
- spin-offs
- options

Unsupported events block affected securities from trusted totals by default.
Partial results require explicit opt-in and must produce separate warned totals.

## Tax model
Keep v1 tax logic simplified and explicit:

- configurable flat capital gains tax rate
- configurable flat dividend tax rate
- taxes-withheld rows tracked as cash/tax metadata
- no jurisdiction-specific tax optimization yet

## User-facing workflow
Scripts are the canonical pipeline. The notebook is the inspection and reporting
layer.

Example shape:

```text
scripts/normalize_portfolio_inputs.py
scripts/validate_portfolio_inputs.py
notebooks/06_portfolio_transaction_simulation.ipynb
```

Validated outputs should be written as:

- CSV for human review
- Parquet for notebooks and simulation

## Privacy
Real user data belongs under:

```text
data/private/
```

That path should be gitignored.

Committed examples must be synthetic and live under:

```text
data/examples/
tests/fixtures/
```

## Current implemented workflows

The project now has three portfolio-facing workflows:

```text
scripts/normalize_portfolio_inputs.py
scripts/validate_portfolio_inputs.py
notebooks/06_portfolio_transaction_simulation.ipynb
```

Use these for canonical CSV/Parquet input validation and the synthetic
transaction-aware MVP.

```text
scripts/parse_db_pdf.py
```

Use this to parse a Deutsche Bank Vermögensanlage-Report PDF into canonical
transactions and holdings files.

```text
scripts/portfolio_snapshot.py
scripts/stop_loss_real_portfolio.py
notebooks/07_real_portfolio_stop_loss.ipynb
```

Use these for real-portfolio snapshot reporting and applying stop-loss /
re-entry analysis across holdings seeded from the Deutsche Bank PDF.

## Known limitations

**PDF parser:** Only the Deutsche Bank Vermögensanlage-Report format observed in
the current private sample is supported. Other report types such as
Kontoauszug, Wertpapierabrechnung, or differently formatted PDF statements are
out of scope until fixtures are available.

**German tax simplifications:** The flat capital gains tax rate does not model
the Sparer-Pauschbetrag (annual tax-free allowance: €1,000 single / €2,000
joint as of 2023). A user who has not exhausted their allowance will see
modelled tax that the broker would not have withheld. The solidarity surcharge
(Solidaritätszuschlag, 5.5% of KeSt ≈ 1.375% effective for most investors) and
church tax are also excluded from the flat rate. The `jurisdiction` field in
the transaction schema is reserved for future jurisdiction-aware tax logic.

**Reverse split fractional shares:** Fractional shares resulting from a reverse
split are retained at full precision in the lot ledger. No cash distribution is
generated. The correct tax treatment, potentially dividend-equivalent subject to
KeSt in Germany, is noted but not modelled.
