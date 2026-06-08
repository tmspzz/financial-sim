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

## ETF constituent data — manual download workflow

Full holdings data (100+ rows) for the four portfolio ETFs is obtained by
manually downloading provider files and importing them with
`scripts/import_etf_holdings.py`. This is necessary because:
- iShares product pages are JavaScript-rendered (Playwright times out inside Docker)
- The vice01.ishares.com AJAX endpoint returns a JS bot-detection challenge
- Vanguard/DWS pages are also JS-heavy

**Source files** (place in `data/private/etf_composition_data_user_provided/`):

| ETF | Provider | File | ISIN source |
|-----|----------|------|-------------|
| iShares NASDAQ-100 (DE000A0F5UF5) | iShares | `EXXT_holdings.csv` | static supplement table |
| Xtrackers MSCI Japan (LU0274209740) | DWS | `Constituent_LU0274209740.xlsx` | from file |
| Xtrackers MSCI EM (IE00BTJRMP35) | DWS | `Constituent_IE00BTJRMP35.xlsx` | from file |
| Vanguard FTSE Dev. Europe (IE00B945VV12) | Vanguard | `Holdings details - Vanguard…xlsx` | skipped (500 EU tickers) |

**Import command:**
```bash
docker run --rm \
  -v "$PWD":/home/jovyan/work \
  -w /home/jovyan/work \
  -e PYTHONPATH=/home/jovyan/work/src \
  financial-sim:latest \
  python scripts/import_etf_holdings.py
```

Coverage after import: iShares 98.8%, DWS Japan 100%, DWS EM 100%, Vanguard 0%.
The `_UNRESOLVED_` residual dropped from ~20% to under 1% of portfolio weight.

## Files affected

- `src/portfolio_sim.py` — added:
  - `ConstituentRow`, `ConstituentResult` dataclasses
  - `ETFConstituentProvider` ABC
  - `CsvConstituentProvider` (iShares/Amundi CSV downloads with sidecar cache)
  - `JustETFConstituentProvider` (bs4 scraping of justetf.com, top 10 holdings)
  - `PlaywrightConstituentProvider` (headless Chromium, full CSV via browser
    automation; runs in dedicated thread to avoid Jupyter asyncio conflict)
  - `YahooTopHoldingsProvider` (Yahoo Finance topHoldings fallback)
  - `ChainedConstituentProvider` (try providers in order)
  - `SecurityMetadata` dataclass, `_YahooTickerCache`, `YahooFinanceMetadataProvider`
  - `CompositionResult` dataclass, `aggregate_portfolio_composition()`
  - `breakdown_by_sector/industry/country/region/currency/asset_class/market_cap_tier/beta_bucket/etf_structure/etf_domicile()`
- `tests/test_portfolio_sim.py` — 216 tests pass, 10 skipped
- `scripts/portfolio_composition.py` — new CLI script
- `notebooks/08_portfolio_composition.ipynb` — new notebook

## Known limitations

- **iShares ISIN supplement** (`_NASDAQ100_ISIN_SUPPLEMENT` in `import_etf_holdings.py`)
  is a 42-entry static table for US-listed tickers that yfinance returns `"-"` for.
  Update after significant NASDAQ-100 rebalances. MRVL (Marvell, reincorporated 2021)
  remains unresolved (~0.3% portfolio weight).
- **Vanguard Europe** has 0% ISIN coverage — 500 EU tickers would saturate yfinance rate
  limits. It is ~1% of the portfolio; use `--etf IE00B945VV12` to force resolution.
- **yfinance ISIN data quality**: some NASDAQ-listed foreign companies receive wrong country
  ISINs (GOOGL → Canadian ISIN, BKR → Argentine ISIN). Affects ~3–5% of iShares weight.
- `CsvConstituentProvider` uses sentinel URLs (`manually_provided://user_downloaded`) in
  `etf_download_urls.json`; if the cache is cleared, the chain falls through to JustETF.
- `JustETFConstituentProvider` returns only the top 10 holdings (20–47% coverage). It is
  the fallback when cache is absent or import has not been run.
- `PlaywrightConstituentProvider` times out on iShares product pages from Docker (JS-heavy;
  `load` event never fires reliably). It falls through to JustETF via the chain.
- Yahoo Finance `topHoldings` returns empty `holdings` for European-listed ETFs — it is
  rarely useful for this portfolio.
- Beta is S&P 500 relative only. Multi-benchmark beta is deferred.
- The `_UNRESOLVED_` row has no sector, country, or beta metadata — it appears in the
  "Unknown" bucket of every breakdown dimension.
- Vorabpauschale, Teilfreistellung, and other jurisdiction-specific ETF tax calculations
  are not implemented. See notebook 08 tax disclaimer cell.
