# Plan: Env-var Convention Rollout

## Goal

Make the two `.env.*` files a first-class project convention: every notebook and
script that touches private data reads the same env vars, an `.env.example`
enables a fully synthetic test-run with no real data, and the rule is codified
in `.agents/notebook-conventions.md` and memory so agents never regress to
hardcoded paths.

## Slices

- [x] Slice 1: `.env.example` — committed synthetic config pointing to data/examples/
- [x] Slice 2: Scripts — add env var defaults to the 4 scripts that touch private data
- [x] Slice 3: `.agents/notebook-conventions.md` — extend rule to scripts, reference both env files
- [x] Slice 4: Memory — save durable rule entry

## Slice details

### Slice 1: `.env.example`

A committed, safe file (no real data) that sources a fully synthetic run:

```bash
export HOLDINGS_PATH=data/examples/db_holdings_synthetic.parquet
export TRANSACTIONS_PATH=data/examples/db_transactions_synthetic.parquet
export TICKER_MAP_PATH=data/examples/ticker_map_synthetic.json
```

With this sourced, `source .env.example && docker compose up` gives a working
JupyterLab session where NB06 (PDF mode reading parquets), NB07, and scripts
run against synthetic data without any PDF or real credentials.

### Slice 2: Script env var defaults

For each script, use `os.environ.get(VAR)` as the argparse default. CLI flags
still override. Pattern:

```python
import os
parser.add_argument(
    "--input",
    default=os.environ.get("DB_PDF_PATH"),
    help="...",
)
```

Scripts to update:
- `parse_db_pdf.py`: `--input` ← `DB_PDF_PATH`
- `portfolio_snapshot.py`: `--pdf` ← `DB_PDF_PATH`, `--ticker-map` ← `TICKER_MAP_PATH`
- `stop_loss_real_portfolio.py`: `--pdf` ← `DB_PDF_PATH`, `--ticker-map` ← `TICKER_MAP_PATH`
- `portfolio_composition.py`: `--holdings` ← `HOLDINGS_PATH`, `--ticker-map` ← `TICKER_MAP_PATH`,
  `--etf-urls` ← `ETF_URLS_PATH`, `--etf-overrides` ← `ETF_OVERRIDES_PATH`

Scripts left as-is (utility/pure CLI, no private data as primary input):
- `normalize_portfolio_inputs.py`: normalizes arbitrary CSVs, no private path default
- `validate_portfolio_inputs.py`: validates arbitrary files
- `summarize_results.py`: reads from `executed/`, not private

### Slice 3: Agent convention rule

Update `.agents/notebook-conventions.md`:
- Extend "Private data paths" section to cover scripts as well as notebooks
- State that every notebook or script that requires a private path MUST have the
  corresponding env var as its source
- State that every such file MUST mention `.env.private.example` and `.env.example`
  in its intro markdown or argparse description
- Raise EnvironmentError (notebooks) or argparse error (scripts) with a pointer
  to `.env.private.example` if a required var is absent

### Slice 4: Memory

Save a `feedback` memory: "All private data paths must be read from env vars. 
Reference .env.private.example and .env.example in error messages."

## Notes

- No `src/` changes. Script changes are argparse defaults only.
- No TDD round needed (no shared function changes).
- Validate scripts by `python -m py_compile` inside Docker.
- Notebooks 06/07/08 already compliant; NB01-05 have no private data (no change needed).
