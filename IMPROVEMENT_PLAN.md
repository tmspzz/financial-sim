# Tax Risk Simulation Improvement Plan

## Current Model

The focused notebook models:

- Selling today and paying capital gains tax.
- Candidate stop-loss levels.
- Bear drawdowns from -5% to -60% in 1% increments.
- Assumed recovery from each bear low.
- Stop + re-entry versus simply holding.
- Re-entry slippage from the bear low.
- Transaction costs.
- Whole-share re-entry only, with leftover cash held uninvested.

The key heatmap is:

```text
Stop + Re-entry Advantage vs Holding Through Bear Recovery
```

That heatmap compares the final recovery value of:

```text
stop -> sell -> pay tax -> re-enter -> recover
```

against:

```text
hold through drawdown -> recover
```

## Important Limitation

The current model is scenario-based, not path-based.

Each bear case is simplified as:

```text
today -> stop trigger -> bear low -> final recovery price
```

It captures the final effect of owning fewer whole shares after re-entry, plus leftover cash, but it does not model price movement between re-entry and recovery.

It does not yet answer:

- What if price drops further after re-entry?
- What if recovery is volatile?
- What if a second stop is needed after re-entry?
- What if recovery happens gradually rather than as one final price?
- What is the probability that stop + re-entry beats holding?

## Next Improvements

1. Add a path-based simulation section.

   Simulate price paths instead of single drawdown/recovery points:

   ```text
   today -> possible stop trigger -> bear path -> re-entry -> recovery path -> final value
   ```

2. Add Monte Carlo outcomes.

   For each stop-loss rule, report:

   ```text
   probability_stop_reentry_beats_hold
   median_advantage_vs_hold
   mean_advantage_vs_hold
   5th_percentile_advantage
   95th_percentile_advantage
   worst_case_advantage
   ```

3. Add post-re-entry volatility.

   Model the risk that re-entry happens before the true low and the position keeps falling.

4. Add configurable re-entry rules.

   Examples:

   ```text
   re-enter at bear low plus slippage
   re-enter after X% rebound from low
   re-enter in stages
   re-enter only if recovery probability crosses threshold
   ```

5. Add second-stop logic after re-entry.

   This would model:

   ```text
   stop out -> re-enter -> stop out again if recovery fails
   ```

6. Add tax timing assumptions.

   Current model assumes a flat 26% tax and immediate tax impact. Future versions could model:

   ```text
   tax paid immediately
   tax paid at year end
   tax drag on reinvestable capital
   different rates for future sales
   ```

7. Add summary recommendation tables.

   For each stop-loss level, produce a compact decision table:

   ```text
   stop_loss
   expected_advantage
   probability_of_beating_hold
   downside_risk
   required_reentry_quality
   recommendation_flag
   ```

8. Add sensitivity controls.

   Run the same analysis across:

   ```text
   reentry_slippage_from_bear_low
   transaction_cost_rate
   recovery_probability
   recovery_strength
   stop_loss_drops
   ```

9. Add clearer charts.

   Useful additions:

   ```text
   probability heatmap
   median advantage heatmap
   downside percentile heatmap
   line chart of best stop by scenario
   distribution chart per stop-loss rule
   ```

10. Preserve assumptions beside results.

    Every output table/plot should display:

    ```text
    tax rate
    current price
    cost basis
    re-entry slippage
    transaction cost
    fractional-share setting
    bear range
    recovery formula
    ```
