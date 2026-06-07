# Notebook Conventions

Every notebook explanation should include:

```markdown
**Plain English:**
...

**This answers the question:** ...

Example:
...
```

Every non-obvious variable should be explained near where it is defined.

Notebook inputs should explain:

- what the variable means
- expected units
- whether it is a percentage, price, share count, or tax rate
- one concrete example

Charts should explain:

- what the x-axis means
- what the y-axis means
- how to interpret positive/negative values
- what decision the chart supports

Tables should explain key columns before or immediately after the table.

## Private data paths

This rule applies to **notebooks AND scripts**. Any file that touches a path under
`data/private/` — or any path that could contain real broker data — must follow
the env-var convention below.

**The two environment files:**

| File | Purpose | Committed? |
|------|---------|-----------|
| `.env.private.example` | Template for real private data. Copy to `.env.private`, fill in, source before JupyterLab. | Yes |
| `.env.example` | Synthetic example that works out of the box — points to `data/examples/`. Source for testing without real data. | Yes |
| `.env.private` | Your actual private paths (real PDF, real parquets). | **No** (gitignored) |

**Rule for notebooks:**

Never hardcode a filename from `data/private/` in a notebook cell.
That directory is gitignored but the notebook source is committed, so a
hardcoded filename leaks account numbers, dates, or other identifying
information into the repository.

For any path that points into `data/private/`, read it from an environment
variable and raise a clear `EnvironmentError` that points to `.env.private.example`:

```python
import os
_hld_env = os.environ.get("HOLDINGS_PATH")
if not _hld_env:
    raise EnvironmentError(
        "Set HOLDINGS_PATH to the parquet file produced by parse_db_pdf.py.\n"
        "See .env.private.example at the project root for the full list."
    )
HOLDINGS_PATH = Path(_hld_env) if Path(_hld_env).is_absolute() else PROJECT_ROOT / _hld_env
```

**Rule for scripts:**

Scripts accept CLI flags. Each flag that maps to a private data path must read
the corresponding env var as its `argparse` default, with a `None`-guard after
parsing that emits a clear error pointing to `.env.private.example`:

```python
import os
parser.add_argument(
    "--input",
    default=os.environ.get("DB_PDF_PATH"),
    help="Path to the PDF (default: $DB_PDF_PATH)",
)
args = parser.parse_args()
if args.input is None:
    parser.error(
        "--input is required (or set DB_PDF_PATH).\n"
        "See .env.private.example for the full list of environment variables."
    )
```

**Canonical env var → flag mapping:**

| Env var | Notebook var | Script flag | Description |
|---------|-------------|-------------|-------------|
| `DB_PDF_PATH` | `PDF_PATH` | `--pdf` / `--input` | Source Deutsche Bank PDF |
| `HOLDINGS_PATH` | `HOLDINGS_PATH` | `--holdings` | Pre-parsed holdings parquet |
| `TRANSACTIONS_PATH` | `TRANSACTIONS_PATH` | — | Pre-parsed transactions parquet |
| `TICKER_MAP_PATH` | `TICKER_MAP_PATH` | `--ticker-map` | ISIN → Yahoo ticker JSON |
| `ETF_URLS_PATH` | `ETF_URLS_PATH` | `--etf-urls` | ETF ISIN → CSV URL JSON |
| `ETF_OVERRIDES_PATH` | `ETF_OVERRIDES_PATH` | `--etf-overrides` | ETF structure overrides JSON |
| `SNAPSHOT_DATE` | `SNAPSHOT_DATE` | `--snapshot-date` | ISO date for staleness checks |

Generic fixed filenames like `data/private/ticker_map.json` may be referenced
in comments or markdown, but never as the default value of a path variable.

---

Keep notebooks as thin analysis/reporting layers. Shared calculations belong in:

```text
src/tax_risk_sim.py   ← single-position calculations
src/portfolio_sim.py  ← portfolio calculations and provider interfaces
src/pdf_parser.py     ← Deutsche Bank PDF parsing
```
