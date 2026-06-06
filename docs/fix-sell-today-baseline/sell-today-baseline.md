# Fix: sell_today_baseline Formula and Unrealized Gain

## What changed

Two related corrections to `sell_today_baseline` in `src/tax_risk_sim.py`.

### 1. Formula delegated to shared helpers

The function previously recomputed `unrealized_gain`, `tax_if_sold_today`, and `after_tax_value` inline, duplicating logic that already lived in `taxable_gain_at_sale`, `tax_due_at_sale`, and `after_tax_liquidation_value`. The inline copy and the helpers could silently diverge if the tax formula was ever updated. The fix delegates all three computations to the shared helpers:

```python
# before
unrealized_gain = taxable_gain_at_sale(current_price, shares, basis_per_share)
tax_if_sold_today = unrealized_gain * tax_rate
after_tax_value = gross_value - tax_if_sold_today

# after
unrealized_gain = (current_price - basis_per_share) * shares
tax_if_sold_today = tax_due_at_sale(current_price, shares, basis_per_share, tax_rate)
after_tax_value = after_tax_liquidation_value(current_price, shares, basis_per_share, tax_rate)
```

### 2. Unrealized gain now reflects the actual P&L

The old code called `taxable_gain_at_sale`, which clamps to zero when the position is underwater (price below cost basis). This produced `current_unrealized_gain = 0` for a losing position, which is misleading — the investor is down money, and the baseline table should say so.

**Plain English:** If you paid $50 per share and the stock is now at $40, you are sitting on a $10/share loss. The old model showed that as a $0 gain. The new model shows it as a −$10/share loss.

**This answers the question:** How much is my position up or down right now, before I decide whether to sell?

Example: 100 shares at a current price of $40 with a $50 basis → `current_unrealized_gain = −$1 000`. Tax and after-tax value are correctly unchanged at $0 and $4 000 respectively, because selling a losing position triggers no capital gains tax.

The tax and after-tax value calculations are unaffected because they delegate to `tax_due_at_sale`, which correctly applies the clamp (no tax on a loss) internally.

## Why

`sell_today_baseline` is the anchor for every downstream table: the stop benchmark, the bear recovery table, and the probability-weighted scenario summary all compare against its `sell_today_after_tax_value`. Any silent divergence in the baseline formula would corrupt every "advantage vs selling today" figure without raising an error. Delegating to the shared helpers ensures there is only one place where the tax formula lives.

The `current_unrealized_gain` field exists to give the user a quick read on their position. Showing zero for an underwater position undermines that purpose.

## Assumptions

No behavioral assumptions changed. `tax_due_at_sale` and `after_tax_liquidation_value` were already the single source of truth; `sell_today_baseline` now uses them consistently.

## Files affected

- `src/tax_risk_sim.py` — `sell_today_baseline`, lines 63–66
- `tests/test_tax_risk_sim.py` — new test `test_sell_today_baseline_reports_actual_unrealized_gain_for_underwater_position`

## Known limitations

The `current_unrealized_gain` field reflects a simple endpoint gain: `(current_price − basis_per_share) × shares`. It does not account for dividends received, tax lots with different bases, or any cost basis adjustments from prior partial sales.
