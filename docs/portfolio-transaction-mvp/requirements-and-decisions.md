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
Do not implement the real Deutsche Bank PDF parser in the first slice. Define
the schema, validation, simulation engine, adapter interface, and synthetic
fixtures first. Add the real parser once a redacted/synthetic PDF fixture or
real table sample is available.

## Required security fields
Validated holdings require:

- `asset_name`
- at least one of `isin` or `wkn`

Lookup and identifier resolution are out of scope for v1.

## Pricing
Security prices must come from broker or validated input data in v1. Do not
fetch stock or ETF market prices automatically yet.

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

## Known limitations

**PDF parser:** The first implementation will not parse real Deutsche Bank PDFs.
It will create the adapter boundary and use synthetic Deutsche Bank-like CSV
fixtures to prove the pipeline and model behavior.

**German tax simplifications:** The flat capital gains tax rate does not model
the Sparer-Pauschbetrag (annual tax-free allowance: €1,000 single / €2,000
joint as of 2023). A user who has not exhausted their allowance will see
modelled tax that the broker would not have withheld. The solidarity surcharge
(Solidaritätszuschlag, 5.5% of KeSt ≈ 1.375% effective for most investors) and
church tax are also excluded from the flat rate. The `jurisdiction` field in
the transaction schema is reserved for future jurisdiction-aware tax logic.

**Reverse split fractional shares:** Fractional shares resulting from a reverse
split are treated in v1 as a cash distribution at the prevailing price. The
correct tax treatment (dividend-equivalent subject to KeSt in Germany) is noted
but not modelled. This is flagged in the output as a known approximation.
