# Plan: Portfolio Composition with ETF Look-Through

## Goal

Add a full portfolio composition view that aggregates exposure across direct
holdings and ETF constituents. A holding like ASML that appears both as a
direct stock and inside an ETF is summed into a single total weight. Breakdowns
by sector, industry, country, region, currency, asset class, market cap tier,
beta bucket, and ETF structure (accumulating vs distributing) are produced.
Output is both a new notebook (`notebooks/08_portfolio_composition.ipynb`) and
a headless script (`scripts/portfolio_composition.py`).

## Design Decisions (from grilling session 2026-06-07)

- **ETF constituent source:** iShares/Amundi CSV downloads (free, full
  coverage). `yfinance` top-holdings used as fallback for ETFs not covered by
  those providers.
- **Security metadata source:** New `YahooFinanceMetadataProvider` in
  `src/portfolio_sim.py`; returns sector, industry, country, market cap tier,
  beta, and ETF structure. Results cached to
  `data/private/security_metadata.json` with a `fetched_at` timestamp.
- **Incomplete look-through:** Track `coverage_pct` per ETF. Show an explicit
  "Unresolved / other" row in every breakdown. Never inflate known weights to
  sum to 100%. Flag ETFs with coverage below 80%.
- **Weight basis:** Share of total portfolio market value in EUR (consistent
  with existing `market_value_eur` column).
- **Breakdown dimensions:** security (look-through), sector, industry, country,
  geographic region (continent-level grouping), currency, asset class, market
  cap tier (Large ≥ €10B / Mid €2B–10B / Small < €2B), beta bucket (low
  <0.8 / market 0.8–1.2 / high >1.2), ETF structure (accumulating /
  distributing / unknown).

## Council Amendments (2026-06-07)

After three-round council review (Python Staff Engineer, Senior Financial Model
Reviewer, Germany/Italy/EU Tax Reviewer), the following amendments were
incorporated into the slices below:

1. **Shared yfinance ticker cache** — add a session-scoped `_YahooTickerCache`
   (in-memory dict) shared by both the price and metadata providers so
   `yf.Ticker()` is called at most once per ticker per run. Metadata cache
   (sector, country, etc.) may be persisted to disk; price data must always be
   fetched live.
2. **Acc/Dist classification** — `etf_structure_overrides.json` is primary
   source; name-keyword heuristic is last-resort fallback only.
3. **ETF domicile** — add `etf_domicile` (ISIN country prefix: IE / LU / DE /
   Other) to Slice 2 metadata and Slice 4 breakdown dimension.
4. **Constituent staleness warning** — `ConstituentResult.as_of` must be
   surfaced visibly in the notebook; flag ETFs where `as_of` is more than 90
   days before the holdings snapshot date.
5. **Beta benchmark label** — beta breakdown must carry explicit
   "vs S&P 500 (yfinance)" label everywhere it appears.
6. **Tax disclaimer** — Slice 6 notebook must include a markdown cell stating
   that ETF structure and domicile are informational only; no Vorabpauschale
   or tax liability is calculated.

## Slices

- [x] **Slice 1 — ETF constituent provider**
  - Add `ETFConstituentProvider` ABC to `src/portfolio_sim.py` with a
    `get_constituents(isin: str) -> ConstituentResult` interface.
  - Implement `iSharesAmundiConstituentProvider`: detects iShares (IE-prefix)
    vs Amundi/Xtrackers (LU-prefix) ETFs from the ISIN, fetches the
    provider's published CSV, parses constituent ISIN + weight rows.
  - Implement `YahooFallbackConstituentProvider`: calls
    `yf.Ticker(ticker).funds_data.top_holdings` for ETFs not covered above.
  - `ConstituentResult` carries: `isin`, `constituents: list[ConstituentRow]`,
    `coverage_pct: float`, `as_of: date`, `source: str`.
  - `ConstituentResult.as_of` must be surfaced in the notebook; flag if more
    than 90 days older than the holdings snapshot date.
  - Sidecar cache: `data/private/etf_constituents/<isin>.json` (gitignored).
  - Tests: synthetic CSV fixture → correct parse, coverage_pct, fallback path,
    staleness flag triggered at 91-day delta.

- [x] **Slice 2 — Security metadata provider**
  - Add `YahooFinanceMetadataProvider` to `src/portfolio_sim.py`.
  - For each ticker returns: `sector`, `industry`, `country`, `market_cap_eur`,
    `beta`, `etf_structure` (accumulating / distributing / unknown).
  - Market cap tier derived in the provider from `market_cap_eur`.
  - ETF structure: `data/private/etf_structure_overrides.json` is primary
    source; fund name keyword heuristic (Acc/Dist suffix) is last-resort
    fallback only.
  - Add `etf_domicile` derived from ISIN country prefix (IE → Ireland,
    LU → Luxembourg, DE → Germany, other → Other).
  - Session-scoped `_YahooTickerCache` (in-memory dict) shared with the
    existing price provider — `yf.Ticker()` called at most once per ticker
    per session. Metadata fields may be persisted; price must always be live.
  - Cache: `data/private/security_metadata.json` (gitignored), keyed by ISIN,
    with `fetched_at`.
  - Tests: mock `yfinance` call → correct field extraction, tier assignment,
    domicile derivation, and override-beats-heuristic for Acc/Dist.

- [x] **Slice 3 — Look-through aggregation**
  - Add `aggregate_portfolio_composition(holdings_df, constituent_provider,
    metadata_provider) -> CompositionResult` to `src/portfolio_sim.py`.
  - For each holding: if it is an ETF, expand into constituent rows scaled by
    `market_value_eur * constituent_weight`. If direct equity, treat as 100%
    weight in that security.
  - Sum across securities: `direct_weight_pct`, `etf_weight_pct`,
    `total_weight_pct`.
  - Attach metadata (sector, country, etc.) to each aggregated row.
  - Include "Unresolved / other" residual row per ETF where
    `coverage_pct < 1.0`.
  - `CompositionResult` carries: per-security DataFrame + per-ETF
    coverage summary.
  - Tests: two holdings (one direct ASML + one ETF containing ASML) → total
    weight equals sum; unresolved residual equals `1 - coverage_pct`.

- [x] **Slice 4 — Dimension breakdown functions**
  - Add breakdown functions to `src/portfolio_sim.py`:
    `breakdown_by_sector`, `breakdown_by_industry`, `breakdown_by_country`,
    `breakdown_by_region`, `breakdown_by_currency`, `breakdown_by_asset_class`,
    `breakdown_by_market_cap_tier`, `breakdown_by_beta_bucket`,
    `breakdown_by_etf_structure`, `breakdown_by_etf_domicile`.
  - Each takes the `CompositionResult` DataFrame and returns a summary
    DataFrame with columns: `dimension_value`, `weight_pct`, `note` (e.g.
    coverage warning).
  - Region map: static dict in `src/portfolio_sim.py` mapping country →
    continent-level region (North America, Europe, Asia-Pacific, Other).
  - Beta breakdown labels must include "vs S&P 500 (yfinance)" explicitly.
  - Tests: known composition → correct sector totals, region grouping,
    unresolved propagation, domicile grouping.

- [x] **Slice 5 — Script `scripts/portfolio_composition.py`**
  - CLI: reads holdings parquet or CSV (path argument), runs full composition
    analysis, writes output tables to
    `data/private/portfolio_composition_<YYYYMMDD>.csv` (one file per
    breakdown dimension, or a multi-sheet approach).
  - Prints coverage warnings to stdout for ETFs below 80%.
  - No new financial logic — thin wrapper over Slice 3 + 4 functions.
  - Tests: smoke test with synthetic holdings fixture.

- [x] **Slice 6 — Notebook `notebooks/08_portfolio_composition.ipynb`**
  - Thin reporting layer: loads holdings, calls composition functions, renders:
    1. Security look-through table (direct + ETF weight + total, sorted by
       total descending).
    2. Sector and industry breakdown bar charts.
    3. Country and geographic region breakdown.
    4. Currency exposure pie.
    5. Asset class breakdown.
    6. Market cap tier breakdown.
    7. Beta bucket distribution.
    8. ETF structure table.
    9. Per-ETF coverage summary with `as_of` date and staleness warnings
       (>90 days before holdings snapshot date).
    10. ETF domicile breakdown.
  - All coverage gaps surfaced inline.
  - Markdown cell explicitly stating: ETF structure and domicile are
    informational only; no Vorabpauschale or tax liability is calculated;
    consult a tax professional for your specific situation.
  - No financial formulas in the notebook cell code.

## Files Affected

```
src/portfolio_sim.py              ← new providers, aggregation, breakdown fns
tests/test_portfolio_sim.py       ← new tests for all slices
scripts/portfolio_composition.py  ← new script
notebooks/08_portfolio_composition.ipynb  ← new notebook
data/private/etf_constituents/    ← gitignored cache dir
data/private/security_metadata.json  ← gitignored metadata cache
data/examples/etf_constituents_synthetic.json  ← committed synthetic fixture
```
