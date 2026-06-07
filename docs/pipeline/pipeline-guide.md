# Portfolio Analysis Pipeline

## Overview

The portfolio analysis pipeline turns a Deutsche Bank Vermögensanlage-Report PDF
into three complementary views of your portfolio. The steps are:

```
DB_PDF_PATH
     │
     ▼
scripts/parse_db_pdf.py
     │
     ├──► HOLDINGS_PATH       (data/private/<stem>_holdings.parquet)
     └──► TRANSACTIONS_PATH   (data/private/<stem>_transactions.parquet)
                │
     ┌──────────┼──────────────────────────┐
     ▼          ▼                          ▼
NB 06           NB 07                    NB 08
P&L simulation  Stop-loss analysis       Composition look-through
"What did I     "Which positions         "What do I actually own
make/lose?"     need a stop order?"      after looking through ETFs?"
```

The three notebooks answer **orthogonal questions** and can be run in any order.
They all share the same input files — run `parse_db_pdf.py` once and reuse.

---

## One-time setup

### 1. Copy and fill in `.env.private`

```bash
cp .env.private.example .env.private
# edit .env.private — set DB_PDF_PATH, HOLDINGS_PATH, TRANSACTIONS_PATH, TICKER_MAP_PATH
```

The file is gitignored. Never commit it. See `.env.private.example` for the full
list of variables and explanations.

### 2. Populate `data/private/ticker_map.json`

Map each ISIN in your holdings to its Yahoo Finance ticker symbol:

```json
{
  "NL0010273215": "ASML.AS",
  "IE00B4L5Y983": "IWDA.AS",
  "US0378331005": "AAPL"
}
```

Start with the ISINs that appear in the holdings snapshot. ISINs without a ticker
will use broker-imputed prices (market_value / quantity from the PDF) in NB06/07
and will show `Unknown` for metadata in NB08.

### 3. (Optional) Populate `data/private/etf_download_urls.json`

For full ETF look-through in NB08, add the constituent CSV download URL for each
ETF you hold. Find the "Download holdings" link on the fund provider's website
(iShares, Amundi, etc.).

```json
{
  "IE00B4L5Y983": "https://www.ishares.com/.../holdings.csv?...",
  "DE000A0F5UF5": "https://www.ishares.com/.../holdings.csv?..."
}
```

Without this file, NB08 falls back to Yahoo Finance top-holdings (top ~10 only).
The notebook still runs and produces breakdowns, but ETF look-through is partial.

---

## Running the pipeline

### Step 1 — Parse the PDF (run once per new report)

```bash
source .env.private
docker run --rm \
  -v "$PWD":/home/jovyan/work \
  -w /home/jovyan/work \
  -e PYTHONPATH=/home/jovyan/work/src \
  financial-sim:latest \
  python scripts/parse_db_pdf.py \
    --input "$DB_PDF_PATH" \
    --output-dir data/private/
```

This writes `<stem>_holdings.parquet` and `<stem>_transactions.parquet` under
`data/private/`. Set `HOLDINGS_PATH` and `TRANSACTIONS_PATH` in `.env.private`
to the output paths.

**Shortcut:** If you haven't run `parse_db_pdf.py` yet, NB06 and NB07 will parse
the PDF automatically on their first run (when `DB_PDF_PATH` is set) and save the
parquets. NB08 also has a `PARSE_PDF = True` control in its Step 0 cell.

### Step 2 — Start JupyterLab

```bash
source .env.private
docker compose up
# → http://localhost:8888/lab
```

All environment variables are available to every notebook for the duration of
the JupyterLab session.

### Step 3 — Open notebooks

| Notebook | Question | Key inputs |
|----------|----------|------------|
| [06_portfolio_transaction_simulation.ipynb](../../notebooks/06_portfolio_transaction_simulation.ipynb) | P&L, unrealised gains, tax paid YTD | `HOLDINGS_PATH`, `TRANSACTIONS_PATH`, `TICKER_MAP_PATH` |
| [07_real_portfolio_stop_loss.ipynb](../../notebooks/07_real_portfolio_stop_loss.ipynb) | Which positions need stop orders? | `HOLDINGS_PATH`, `TICKER_MAP_PATH` |
| [08_portfolio_composition.ipynb](../../notebooks/08_portfolio_composition.ipynb) | Real exposure after ETF look-through | `HOLDINGS_PATH`, `TICKER_MAP_PATH`, `ETF_URLS_PATH` |

---

## Refreshing data

### New PDF report

Re-run Step 1 with the new PDF path, then restart JupyterLab (or re-source
`.env.private` with updated `HOLDINGS_PATH`/`TRANSACTIONS_PATH`).

### Refresh without leaving NB08

NB08 has three optional controls in the **Step 0** cell:

```python
PARSE_PDF        = False   # set True to re-run parse_db_pdf.py
REFRESH_ETF_DATA = False   # set True to delete the ETF constituent cache
CLEAR_META_CACHE = False   # set True to delete security_metadata.json
```

Setting any flag to `True` and re-running that cell triggers the corresponding
refresh. The flags default to `False` so running all cells never re-does
expensive work unintentionally.

---

## File reference

| File | Description | Gitignored |
|------|-------------|-----------|
| `.env.private.example` | Template for env var setup | No (committed) |
| `.env.private` | Your actual env vars with real paths | Yes |
| `data/private/<stem>_holdings.parquet` | Holdings snapshot from parse step | Yes |
| `data/private/<stem>_transactions.parquet` | Transaction history from parse step | Yes |
| `data/private/ticker_map.json` | ISIN → Yahoo ticker map | Yes |
| `data/private/etf_download_urls.json` | ETF ISIN → constituent CSV URL | Yes |
| `data/private/etf_structure_overrides.json` | ETF ISIN → acc/dist override | Yes |
| `data/private/security_metadata.json` | Metadata cache (sector, beta, etc.) | Yes |
| `data/private/etf_constituents_cache/` | ETF constituent data cache | Yes |

---

## Headless (script) mode

All three analytical views can also be produced as CSV files without opening
JupyterLab:

```bash
# Composition (NB08 equivalent)
source .env.private
docker run --rm \
  -v "$PWD":/home/jovyan/work \
  -w /home/jovyan/work \
  -e PYTHONPATH=/home/jovyan/work/src \
  financial-sim:latest \
  python scripts/portfolio_composition.py \
    --holdings "$HOLDINGS_PATH" \
    --ticker-map "$TICKER_MAP_PATH" \
    --etf-urls "$ETF_URLS_PATH" \
    --output-dir data/private/composition/
```

Outputs 12 CSV files: `portfolio_composition_YYYYMMDD_{name}.csv`.

---

## Known limitations

- `parse_db_pdf.py` supports Deutsche Bank Vermögensanlage-Report format only.
  Other broker PDFs require a custom parser.
- ETF constituent data requires manual URL setup in `etf_download_urls.json`.
  URL formats differ per provider and change occasionally.
- Yahoo Finance `topHoldings` fallback returns only the top ~10–15 holdings.
  For broad-market ETFs this covers a small fraction of the fund weight.
- Beta is S&P 500 relative only. European or EM holdings may have understated
  sensitivity to local market moves.
- No tax calculations are performed in NB08. ETF structure and domicile are
  informational only. Consult a qualified tax professional.
