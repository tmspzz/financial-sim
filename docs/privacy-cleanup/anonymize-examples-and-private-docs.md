# Anonymize Examples And Private Docs

## What changed
Committed example data, test fixtures, parser text fixtures, and ticker-map
examples now use synthetic security names, synthetic ISIN-like identifiers, and
synthetic WKN/ticker values.

Private report examples were changed to generic placeholders or the
`DB_PDF_TEST_PATH` environment variable.

Real ticker maps are not committed. Use ignored `data/private/ticker_map.json` for real
local simulations and committed `data/examples/ticker_map_synthetic.json` for
examples and demos.

## Why
Examples and public documentation must not expose real broker statement
filenames, account-like values, real portfolio identifiers, or real security
names. Real broker files remain local-only and gitignored.

## Files affected
- `data/examples/` — anonymized CSV examples and regenerated CSV/Parquet outputs.
- `data/examples/ticker_map_synthetic.json` — synthetic ISIN-to-ticker mappings.
- `.gitignore` — ignores `data/private/ticker_map.json` so real local ticker maps stay
  private.
- `tests/fixtures/` — synthetic fixture identifiers and names.
- `tests/test_pdf_parser.py` — synthetic parser text fixtures and
  `DB_PDF_TEST_PATH` integration-test opt-in.
- `tests/test_portfolio_sim.py` — synthetic identifiers/names in test data.
- `scripts/` and `notebooks/` — examples no longer name a private report file.
- `agent-planning/db-pdf-parser.md` and portfolio docs — removed specific private
  report filename references and real security example names.

## Validation
Docker quality command passed:

```text
130 passed, 10 skipped
14 files already formatted
All checks passed
```

The skipped tests are private-PDF integration tests that only run when
`DB_PDF_TEST_PATH` points to a local private report.
