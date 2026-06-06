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

**Never hardcode a filename from `data/private/` in a notebook cell.**
That directory is gitignored but the notebook source is committed, so a
hardcoded filename leaks account numbers, dates, or other identifying
information into the repository.

For any path that points into `data/private/`, read it from an environment
variable and raise a clear error if the variable is not set:

```python
import os
_pdf = os.environ.get("DB_PDF_PATH")
if not _pdf:
    raise EnvironmentError(
        "Set DB_PDF_PATH to the path of your Deutsche Bank PDF report.\n"
        "Example:  export DB_PDF_PATH=/path/to/data/private/report.pdf"
    )
PDF_PATH = PROJECT_ROOT / _pdf if not Path(_pdf).is_absolute() else Path(_pdf)
```

Generic fixed filenames like `data/private/ticker_map.json` may be referenced
in comments or markdown, but not as the default value of a path variable.

---

Keep notebooks as thin analysis/reporting layers. Shared calculations belong in:

```text
src/tax_risk_sim.py   ← single-position calculations
src/portfolio_sim.py  ← portfolio calculations and provider interfaces
src/pdf_parser.py     ← Deutsche Bank PDF parsing
```
