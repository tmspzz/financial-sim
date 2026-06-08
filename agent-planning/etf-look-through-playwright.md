# ETF Look-Through: Playwright-Based Constituent Fetching

## Problem

Notebook 08 shows 40.99% of the portfolio as `_UNRESOLVED_` / Unknown.
All 4 ETFs return 0% coverage from `YahooTopHoldingsProvider`:

| ISIN          | Name                     | Portfolio % | Coverage |
|---------------|--------------------------|-------------|----------|
| DE000A0F5UF5  | iShares NASDAQ-100       | 32.45%      | 0%       |
| IE00B945VV12  | Vanguard FTSE Dev Europe | 1.13%       | 0%       |
| LU0274209740  | Xtrackers MSCI Japan     | 1.34%       | 0%       |
| IE00BTJRMP35  | Xtrackers MSCI EM        | 0.82%       | 0%       |

iShares/Vanguard/Xtrackers provider pages are JavaScript-rendered — plain
`requests` returns HTML without the download URLs or holdings data.
The existing `CsvConstituentProvider` already parses iShares CSV format
perfectly; the blocker is discovering the download URL.

## Root Cause of 0% from Yahoo

Yahoo Finance `topHoldings` API returns empty `holdings` lists for these
European-listed ETFs (EXXT.DE, VEUR.AS, DBXJ.DE, XMME.DE). The crumb
auth works but the data simply isn't there for non-US-listed ETFs.

## Strategy

### Tier 1 — Playwright browser automation (primary)

Add `playwright` + headless Chromium to the Docker image. Implement a
`PlaywrightConstituentProvider` that:

1. Navigates to the provider's product page (iShares, Vanguard, Xtrackers)
2. Waits for the page JS to fully render
3. Intercepts the network request triggered by clicking the "Download" button
   — capturing the actual CSV URL
4. Downloads the CSV and hands it off to the existing `CsvConstituentProvider`
   parser (`_parse_csv`)

This gives **full holdings** (100+ rows for NASDAQ-100) with ISIN + weight,
using the official provider CSV — identical to what a user gets in a browser.

Provider page URLs to navigate to:
- DE000A0F5UF5 → https://www.ishares.com/de/privatanleger/de/produkte/251896/ishares-nasdaq100-ucits-etf-de-fund
- IE00B945VV12 → https://www.vanguardinvestor.co.uk/investments/vanguard-ftse-developed-europe-ucits-etf-eur-distributing
- LU0274209740 → https://etf.dws.com/en/LU0274209740-msci-japan-ucits-etf-1c/
- IE00BTJRMP35 → https://etf.dws.com/en/IE00BTJRMP35-msci-em-markets-1c/

### Tier 2 — JustETF scraping fallback (top 10 only)

If Playwright fails (network unavailable, provider page changed), fall back to
scraping `justetf.com/en/etf-profile.html?isin={ISIN}` with `requests` +
`bs4` (both already in the image). Returns top 10 holdings with ISINs. Coverage
~20–47% per ETF but ISIN-resolved. Reduces unknown from 41% → ~25%.

### Tier 3 — Yahoo topHoldings (existing, keep as last resort)

### Provider chain

```
CsvConstituentProvider          ← user-supplied URL in etf_download_urls.json
  → PlaywrightConstituentProvider  ← new: full holdings via browser automation
    → JustETFConstituentProvider   ← new: top 10 via HTML scraping (bs4)
      → YahooTopHoldingsProvider   ← existing: top 10 via Yahoo API
```

## Implementation Plan

### [x] Step 0 — Docker image
- [x] Add `playwright` to `requirements-dev.txt`
- [x] Update `Dockerfile`: install Chromium OS deps as root (`libasound2t64`
  on Ubuntu Noble, NOT `libasound2`), run `playwright install chromium` as jovyan
- [x] Rebuild image succeeded; Chromium launches inside container

### [x] Step 1 — Tests first (TDD)
- [x] `TestJustETFConstituentProvider` (9 tests): parses holdings, weights,
  coverage, DD/MM/YYYY date, HTTP error, no holdings, bs4 missing, cache,
  chain fallthrough
- [x] `TestPlaywrightConstituentProvider` (4 tests): unknown ISIN, playwright
  missing, cache, default URL map
- All 216 tests pass, 10 skipped

### [x] Step 2 — Implement `JustETFConstituentProvider`
- [x] Scrapes `https://www.justetf.com/en/etf-profile.html?isin={isin}`
- [x] bs4 parser; `source = "justetf_top_holdings"`
- [x] `_parse_ishares_date` updated for DD/MM/YYYY format

### [x] Step 3 — Implement `PlaywrightConstituentProvider`
- [x] Async playwright in dedicated thread (avoids Jupyter asyncio conflict)
- [x] `wait_until="load"` (30s timeout) — iShares pages never reach
  networkidle from Docker; `load` fires faster and falls through correctly
- [x] Thread join timeout 45s; any exception re-raised as `ValueError` so
  `ChainedConstituentProvider` catches it and falls through to JustETF
- [x] `source = "playwright_csv"`; default URL map for 4 portfolio ETFs

### [x] Step 4 — Wire into chain in notebook 08
Chain order: `CsvConstituentProvider → PlaywrightConstituentProvider →
JustETFConstituentProvider → YahooTopHoldingsProvider`

### [x] Step 5 — Run tests, re-execute notebook, verify
- [x] 216 tests pass, ruff clean
- [x] Notebook 08 executed successfully with private env
- [x] `_UNRESOLVED_` dropped from **40.99% → 19.67%** (−21 pp)
  - All 4 ETFs resolved via JustETF (Playwright timed out on iShares pages,
    chain fell through correctly)
  - Coverage per ETF: NASDAQ-100 46.9%, VEUR 19.7%, Japan 27.6%, EM 32.9%

### [x] Step 6 — Reconcile docs
- [x] Updated `docs/portfolio-composition-lookathrough/portfolio-composition-lookathrough.md`
- [x] Updated `.agents/current-model-notes.md` with ETF look-through section

### [x] Step 7 — User-provided holdings files + ISIN supplement (second session)
User manually downloaded ETF constituent files from fund providers.

- [x] `scripts/import_etf_holdings.py` written — parses iShares CSV, DWS XLSX,
  Vanguard XLSX; resolves ISINs via `yahoo_isin_from_ticker` + `_NASDAQ100_ISIN_SUPPLEMENT`
  (42-entry hardcoded table for tickers Yahoo doesn't embed ISIN for);
  validates ISINs against regex; writes `{cache_dir}/{isin}.json` as fraction
  coverage_pct (0–1, matching `ConstituentResult.coverage_pct` convention)
- [x] `tests/test_import_etf_holdings.py` — 25 tests (all passing):
  iShares CSV, DWS XLSX, Vanguard XLSX parsing; cache writing; ISIN validation;
  supplement fallback; dash-ISIN treated as unresolved
- [x] `_validate_isin()` added — filters `"-"` and non-ISIN strings to `None`
- [x] `_NASDAQ100_ISIN_SUPPLEMENT` — 42 entries covering all major NASDAQ-100
  US stocks Yahoo doesn't embed ISIN for
- [x] Notebook 08 — warning cell added above Step 0 documenting the manual
  download requirement and refresh procedure
- [x] `scripts/portfolio_composition.py` — prints `⚠ WARNING` to stderr when
  any ETF's constituent cache `source == "user_provided_file"`
- [x] 241 tests pass, ruff clean

### [x] Step 8 — Unified Yahoo Finance integration; remove Playwright (third session)

- [x] `yahoo_isin_from_ticker(ticker)` added to `src/portfolio_sim.py` — uses
  `_yahoo_crumb_session()` to call Yahoo Finance search page; single unified
  Yahoo integration, no yfinance SDK
- [x] `PlaywrightConstituentProvider` removed from `src/portfolio_sim.py`
  (class + `_DEFAULT_ETF_PRODUCT_URLS` dict)
- [x] `import_etf_holdings.py` updated: `yfinance` removed, imports
  `yahoo_isin_from_ticker` from `portfolio_sim`; `_REGION_TO_SUFFIX` no longer
  used for candidate generation (Yahoo search handles region internally)
- [x] `playwright` and `yfinance` removed from `requirements-dev.txt`
- [x] Dockerfile: Chromium OS deps and `playwright install chromium` removed
- [x] Notebook 08: `PlaywrightConstituentProvider` removed from imports and chain
- [x] 240 tests pass (3 new `TestYahooIsInFromTicker` tests added), ruff clean

**Final coverage after user-provided files:**
| ISIN          | Name              | Coverage | Source            |
|---------------|-------------------|----------|-------------------|
| DE000A0F5UF5  | iShares NASDAQ-100 | **98.8%** | user_provided_file |
| LU0274209740  | Xtrackers Japan   | **100%** | user_provided_file |
| IE00BTJRMP35  | Xtrackers EM      | **100%** | user_provided_file |
| IE00B945VV12  | Vanguard Europe   | 0%       | user_provided_file (ISIN resolution skipped — 500 EU tickers) |

`_UNRESOLVED_` no longer appears at top of security table; NVIDIA, ASML, Apple,
Microsoft are the leading positions.

## Known limitations

- **iShares ISIN supplement** is a static table; update `_NASDAQ100_ISIN_SUPPLEMENT`
  if index constituents change significantly (annual rebalances are minor).
- **MRVL** (Marvell Technology, reincorporated 2021) remains unresolved (~1%
  of NASDAQ-100, ~0.3% portfolio) — new US ISIN not yet in supplement.
- **Vanguard Europe** has 0% ISIN coverage — 500 Yahoo Finance search calls would
  be heavily rate-limited. Use `--etf IE00B945VV12` flag to force resolution if
  needed; it is a ~1% portfolio position.
- **vice01.ishares.com AJAX endpoint** returns JS challenge (bot protection);
  direct download automation remains blocked.
- Some Yahoo Finance search results for non-US NASDAQ-listed stocks may embed the
  wrong country ISIN (e.g., GOOGL → Canadian ISIN; BKR → Argentine ISIN). These
  affect ~3-5% of iShares holdings weight but do not affect the major direct-overlap
  calculations.
