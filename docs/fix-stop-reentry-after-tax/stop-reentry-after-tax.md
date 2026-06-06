# Fix: Stop + Re-entry After-Tax Comparison

## What changed

The `compare_stop_reentry_vs_hold` function previously computed `stop_reentry_after_recovery_value` as the gross market value of the re-entered shares plus leftover cash, then compared that against `hold_after_recovery_after_tax`, which is an after-tax liquidation value. This mixed a pre-tax number against an after-tax number, making the stop + re-entry strategy appear better than it actually is.

**Plain English:** When you stop out and buy back in at a lower price, you eventually sell those new shares and pay tax on whatever gain you made from the re-entry price to the recovery price. The old model forgot to deduct that tax. The hold-and-sell scenario did deduct it. So the comparison was unfair: stop + re-entry looked like it produced more money, but only because it hadn't paid its tax bill yet.

**This answers the question:** After accounting for all taxes on both paths — the original position if held, and the re-entered position if eventually sold at recovery — is stop + re-entry actually better, or worse, than holding?

Example: 37 shares re-entered at $257.25 recover to $355.25. Gross value is $13 144. After paying 26% tax on the $98/share gain, the after-tax value is $12 201 — $943 less than the gross figure. The hold side already had its tax applied. Before the fix, the advantage column was overstated by that $943 on every triggered row.

The fix replaces:

```python
stop_reentry_after_recovery_value = (reentry_shares * recovery_price) + leftover_cash_after_reentry
```

with:

```python
stop_reentry_after_recovery_value = after_tax_liquidation_value(
    recovery_price, reentry_shares, reentry_price, tax_rate
) + leftover_cash_after_reentry
```

The re-entry price is used as the new cost basis for the re-entered shares, which is correct: the investor crystallised the original gain (and paid tax on it) at the stop, and the new shares were acquired at the re-entry price.

The leftover cash — the portion of the after-tax stop proceeds that could not be used to buy a whole share — is already liquid and after-tax, so it is included as-is.

Two local variable names were also changed to make the two-leg transaction cost intent explicit: `stop_sale_cash_after_tax` → `cash_after_sell_cost`, `reentry_cash_after_cost` → `cash_after_reentry_cost`. The transaction cost rate is applied once to model the sell-leg cost and once again to model the buy-leg cost, producing a round-trip effective cost of `(1 − rate)²`. This behaviour is now named clearly even though the default rate is 0.00.

## Why

The column `stop_reentry_advantage_vs_hold_after_recovery` is the primary output that notebook 04 uses to decide whether a stop + re-entry strategy beats holding. Systematically overstating that advantage biases every heatmap cell where a stop triggers. The fix aligns both sides of the comparison on the same after-tax liquidation basis.

## Assumptions

- The re-entered shares are assumed to be sold at the recovery price (the same endpoint as the hold scenario). This keeps the comparison symmetric.
- The new cost basis for the re-entered shares is the re-entry price, not the original basis. This reflects that the original position was fully crystallised at the stop.
- Leftover cash is treated as already-liquid after-tax proceeds and is not taxed again.
- Transaction costs are applied per leg (sell cost, then buy cost), not as a single round-trip rate.

## Files affected

- `src/tax_risk_sim.py` — `compare_stop_reentry_vs_hold`, lines around 257–273
- `tests/test_tax_risk_sim.py` — `test_stop_reentry_uses_whole_shares_and_leftover_cash` extended with assertions for `stop_reentry_after_recovery_value` and `hold_after_recovery_after_tax`

## Known limitations

The model is still endpoint-based: it compares wealth at a single recovery price, not along a path. It does not model a second stop being triggered during recovery, the probability of actually re-entering at the assumed slippage price, or the time value of money between the stop and the recovery.
