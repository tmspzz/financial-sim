# Plan: Portfolio Pipeline Integration

## Goal

Connect `parse_db_pdf.py`, `portfolio_composition.py`, and notebooks 06–08 into
a single coherent pipeline driven by a shared set of environment variables.
Users set paths once, run parse once, and all notebooks read the same files.
Notebook 08 gains optional regeneration controls so the user can refresh any
upstream artifact without leaving the notebook.

## Background

Currently:
- NB06 and NB07 each re-parse the Deutsche Bank PDF inline via `parse_db_pdf()`.
- NB08 reads a pre-parsed holdings parquet but has no way to trigger the parse step.
- Each notebook uses slightly different env var names (`DB_PDF_PATH` for 06/07,
  `HOLDINGS_PATH` for 08, `TICKER_MAP_PATH` used inconsistently).
- There is no single reference listing all required env vars.
- Users must run `parse_db_pdf.py` manually before NB08, but nothing documents
  the sequence or connects the steps.

## Pipeline Design

```
DB_PDF_PATH  (source — user sets this once)
      │
      ▼
scripts/parse_db_pdf.py
      │
      ├──► HOLDINGS_PATH     (data/private/<stem>_holdings.parquet)
      └──► TRANSACTIONS_PATH (data/private/<stem>_transactions.parquet)
                │
                ├──► NB06 (transaction simulation — reads TRANSACTIONS_PATH + HOLDINGS_PATH)
                ├──► NB07 (stop-loss analysis — reads HOLDINGS_PATH)
                └──► NB08 (composition — reads HOLDINGS_PATH + TICKER_MAP_PATH + ETF_URLS_PATH)
                           optional: re-runs parse_db_pdf.py, refreshes ETF/metadata caches
```

## Slices

- [x] Slice 1: `.env.private.example` — canonical env var reference + `.gitignore` update
- [x] Slice 2: NB06 — switch PDF mode from inline re-parse to reading HOLDINGS_PATH +
               TRANSACTIONS_PATH; fall back to parsing DB_PDF_PATH if parquet files absent
- [x] Slice 3: NB07 — read HOLDINGS_PATH directly instead of re-parsing DB_PDF_PATH inline
- [x] Slice 4: NB08 — add "Step 0: Pipeline bootstrap" section with optional regeneration
               controls (PARSE_PDF, REFRESH_ETF_DATA, CLEAR_META_CACHE flags)
- [x] Slice 5: Documentation — `docs/pipeline/pipeline-guide.md`, update each notebook's
               intro markdown cell to show its place in the pipeline

## Env Vars (canonical set)

| Variable            | Used by            | Description                                      |
|---------------------|--------------------|--------------------------------------------------|
| `DB_PDF_PATH`       | parse, NB06, NB07  | Source Deutsche Bank PDF                         |
| `HOLDINGS_PATH`     | NB06, NB07, NB08   | Pre-parsed holdings parquet                      |
| `TRANSACTIONS_PATH` | NB06               | Pre-parsed transactions parquet                  |
| `TICKER_MAP_PATH`   | NB06, NB07, NB08   | JSON ISIN → Yahoo Finance ticker                 |
| `ETF_URLS_PATH`     | NB08, script       | JSON ETF ISIN → constituent CSV URL              |
| `ETF_OVERRIDES_PATH`| NB08, script       | JSON ETF ISIN → accumulating/distributing        |
| `SNAPSHOT_DATE`     | NB08               | ISO date for staleness checks (default: today)   |

## Notes

- No `src/` changes — all changes are notebooks, scripts, and docs.
  No TDD round required. Notebooks validated by JSON parse and cell compile.
- NB06 synthetic mode is untouched.
- Backward compatibility: if HOLDINGS_PATH / TRANSACTIONS_PATH are not set and
  DB_PDF_PATH is set, NB06 and NB07 parse inline (existing behavior preserved).
- `.env.private` (user copy, real paths) is already covered by `.env.*` in .gitignore.
  Only `.env.private.example` (committed template) needs a gitignore exemption.
