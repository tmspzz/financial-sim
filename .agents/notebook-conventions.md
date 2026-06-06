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

Keep notebooks as thin analysis/reporting layers. Shared calculations belong in:

```text
src/tax_risk_sim.py   ← single-position calculations
src/portfolio_sim.py  ← portfolio calculations and provider interfaces
src/pdf_parser.py     ← Deutsche Bank PDF parsing
```
