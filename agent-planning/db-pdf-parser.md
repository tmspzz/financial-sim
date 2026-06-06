# Plan: Deutsche Bank PDF Parser

## Document structure (report.pdf, 22 pages)

| Pages | Section | Content |
|-------|---------|---------|
| 1 | Cover | Addressee, date |
| 2–3 | Bestandsaufstellung per 31.03.2026 | Older holdings snapshot |
| 4 | Wichtige Hinweise | Legal boilerplate |
| 5–7 | Vermögensaufstellung mit Einstandskursen per 06.06.2026 | Current holdings + cost basis |
| 8–20 | Umsätze vom 01.01.2024 bis 06.06.2026 | All transactions (13 pages) |
| 21–22 | Wichtige Hinweise | More legal boilerplate |

## Transaction text format (pages 8–20)

Each transaction spans 2–3 text lines. pdfplumber finds no tables — text-only parsing required.

**Primary line** (always):
```
DD.MM.YYYY 000000000000 <Umsatzart> <qty> <name_fragment> <WKN> <CCY> [<price>] <amount>
```

**Continuation line(s)** (when name wraps — observed for ~40% of rows):
```
<name_rest>
```

**ISIN line** (always, terminates the block):
- EUR security: `DD.MM.YYYY 000000000000EUR <ISIN> EUR`
- Foreign CCY:  `DD.MM.YYYY 000000000000USD <ISIN> <fx_rate> EUR`
- Kapitaltransaktion (no depot prefix): `DD.MM.YYYY <ISIN> EUR`

### Transaction types observed

| Umsatzart | canonical type | count (approx) |
|-----------|---------------|---------------|
| Kauf | buy | ~25 |
| Verkauf | sell | ~10 |
| Divid./Ausschütt. | dividend | ~60 |
| Kapitaltransaktion | split | 1 (Nvidia 10-for-1, 2024-06-10) |

### Trailing token layout (parsed right-to-left)

| Type | Trailing tokens |
|------|----------------|
| Kauf / Verkauf / Kapitaltransaktion | WKN CCY PRICE AMOUNT |
| Divid./Ausschütt. | WKN CCY AMOUNT |

Price and amount use German decimal format: `8.448,72` → 8448.72.

### Split ratio derivation

The PDF stores `new_shares_added` (342 for Nvidia), not the split ratio.
The parser performs a single post-processing pass — tracking running share
counts from buy/sell rows — to derive `ratio = (existing + new) / existing`
before emitting the split row. This ensures the output can be fed directly to
`apply_split()` without changes to the simulation.

## Holdings text format (pages 5–7)

Section header lines to skip: `AktienEuropa`, `AktienUSA`, `Gesamtsumme`, etc.

**Primary line**:
```
<qty> <name_fragment> <WKN> <cost_basis>(a?) <CCY> <current_price> <gain_eur> <market_value> <pct>
```
(a) = annotation suffix — strip before parsing numbers.

**Continuation line(s)**: remaining name fragments (same as transactions).

**ISIN line**:
```
<last_booking_date> <ISIN> <gain_pct> <accrued_interest>
```

Output schema: canonical HOLDINGS_COLUMNS with `price` = current_price.
Extra column `cost_basis_eur` added (outside canonical schema — for lot-engine
initialisation or cross-check).

## Module boundaries

- `src/pdf_parser.py` — new; depends on `pdfplumber` (not in requirements-dev.txt today)
- `src/portfolio_sim.py` — unchanged
- `scripts/parse_db_pdf.py` — new CLI: `--input PDF --output-dir DIR`
- `tests/test_pdf_parser.py` — new; unit tests use text fixtures (no PDF);
  integration tests skip if `data/private/*.pdf` absent

## Files to create

```
src/pdf_parser.py
scripts/parse_db_pdf.py
tests/test_pdf_parser.py
```

## Files to modify

```
requirements-dev.txt           — add pdfplumber
.github/workflows/ci.yml       — add pdfplumber to pip install
```

## Slices (TDD)

- [ ] helper functions: _parse_german_number, _parse_date, _jurisdiction_from_isin
- [ ] primary-line tokeniser: _parse_primary_line (buy/sell/dividend/split)
- [ ] ISIN-line parser: _parse_isin_line
- [ ] block collector and block parser: _parse_tx_block
- [ ] split ratio post-processing: _derive_split_ratios
- [ ] page classifier: identify Umsätze vs Einstandskursen pages
- [ ] holdings block parser: _parse_holdings_block
- [ ] top-level: parse_db_pdf -> (tx_df, holdings_df)
- [ ] integration test: real PDF produces valid DataFrames (skipped in CI)
- [ ] CLI script: scripts/parse_db_pdf.py

## Known limitations (v1)

- Fees/commissions not shown in this report format — all rows output fees=0.
- Tax withheld not shown — all rows output tax_withheld=0.
- Reverse splits with fractional shares: same treatment as portfolio_sim (retain
  precision, no cash distribution).
- Only Deutsche Bank Vermögensanlage-Report format is supported. Other report
  types (Kontoauszug, Wertpapierabrechnung) are out of scope.
- The Bestandsaufstellung (pages 2–3, older date) is not parsed; only the
  Vermögensaufstellung mit Einstandskursen (pages 5–7, current date) is used.
