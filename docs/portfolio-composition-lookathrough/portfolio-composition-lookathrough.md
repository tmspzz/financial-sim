# Portfolio Composition with ETF Look-Through

## What changed

**Plain English:** The project can now show the aggregated weight of every security
across your whole portfolio — direct holdings and ETF holdings combined. If you own
ASML shares outright and also hold an ETF that contains ASML, both are summed into
one total exposure figure.
**This answers the question:** What is my real exposure to each security, sector,
country, and risk factor once I look through the funds I hold?
**Example:** You hold 10 ASML shares (€4,000, 13.3% of portfolio) and a €20,000
ETF that is 10% ASML. The look-through shows ASML at €6,000 total — 20% of the
portfolio — not just 13.3%.

## Why

The single-position stop-loss model already works per ISIN. This feature answers
the prior step: "what do I actually own, and how concentrated am I?" before deciding
which positions to analyse for stop-loss candidates.

ETF holdings made the question non-trivial: a broad-market ETF can silently double
your ASML exposure without appearing in the direct holdings list.

## Assumptions

- ETF constituent weights are as published by the fund provider (iShares/Amundi CSV)
  or as returned by Yahoo Finance `topHoldings` (top ~10–15 only).
- Coverage below 100% is handled with an explicit `_UNRESOLVED_` residual row.
  Weights are never inflated to sum to 100% — the unresolved bucket is real money.
- Market cap tier thresholds: Large ≥ €10B, Mid €2B–€10B, Small < €2B.
- Beta is the yfinance value measured against the S&P 500. European or EM holdings
  may have understated sensitivity to local market moves.
- ETF structure (accumulating / distributing) is taken from `etf_structure_overrides.json`
  first; fund name keyword heuristic (Acc/Dist suffix) is the fallback.
- ETF domicile is derived from the two-letter ISIN country prefix (IE → Ireland, etc.).
- **No tax calculation is performed.** ETF structure and domicile are display-only.

## Files affected

- `src/portfolio_sim.py` — added:
  - `ConstituentRow`, `ConstituentResult` dataclasses
  - `ETFConstituentProvider` ABC
  - `CsvConstituentProvider` (iShares/Amundi CSV downloads with sidecar cache)
  - `YahooTopHoldingsProvider` (Yahoo Finance topHoldings fallback)
  - `ChainedConstituentProvider` (try providers in order)
  - `SecurityMetadata` dataclass, `_YahooTickerCache`, `YahooFinanceMetadataProvider`
  - `CompositionResult` dataclass, `aggregate_portfolio_composition()`
  - `breakdown_by_sector/industry/country/region/currency/asset_class/market_cap_tier/beta_bucket/etf_structure/etf_domicile()`
- `tests/test_portfolio_sim.py` — added tests for all new classes and functions
  (Slice 1–5 test classes; 47 new tests; total suite 196 passed)
- `scripts/portfolio_composition.py` — new CLI script
- `notebooks/08_portfolio_composition.ipynb` — new notebook

## Known limitations

- `CsvConstituentProvider` requires the user to maintain `data/private/etf_download_urls.json`
  mapping ETF ISINs to their provider CSV download URLs. There is no auto-discovery from ISIN
  alone; URL formats differ per provider and require a one-time setup.
- Yahoo Finance `topHoldings` returns only the top ~10–15 holdings. For broad-market ETFs
  this typically covers 5–15% of the fund by weight — useful as a fallback but not a
  substitute for full constituent data.
- Beta is S&P 500 relative only. Multi-benchmark beta is deferred.
- The `_UNRESOLVED_` row has no sector, country, or beta metadata — it appears in the
  "Unknown" bucket of every breakdown dimension.
- Vorabpauschale, Teilfreistellung, and other jurisdiction-specific ETF tax calculations
  are not implemented. See notebook 08 tax disclaimer cell.
