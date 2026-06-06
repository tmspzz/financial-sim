# Add: Missing Test Coverage

## What changed

Five gaps in test coverage were closed. All new and extended tests live in `tests/test_tax_risk_sim.py`.

### 1. `build_after_tax_sensitivity` — new test

`build_after_tax_sensitivity` was the only exported function with no test at all. The new test `test_build_after_tax_sensitivity_structure_and_breakeven` verifies:

- The returned DataFrame contains the expected columns.
- At a 0% future return, `advantage_vs_selling_today` is exactly zero — selling later at the same price as today produces no advantage.
- At a positive return, the advantage is positive.

### 2. `build_probability_weighted_scenarios` happy path — new test

The existing test only checked that the function raises `ValueError` when probabilities do not sum to 1. It said nothing about whether the expected-value arithmetic is correct.

The new test `test_probability_weighted_scenarios_computes_expected_values` uses a two-scenario Bear / Bull case and verifies:

- `expected_hold_after_tax_value` matches the manually calculated weighted sum.
- `weighted_after_tax_value` in the detail DataFrame sums to the same total.
- `sell_today_after_tax_value` in the summary matches `after_tax_liquidation_value` at the current price.

### 3. `build_bear_recovery_table` financial outputs — extended test

The existing `test_bear_recovery_table_keeps_drawdown_column_for_sorting` only checked column presence and two price fields. Three financial output columns were unverified.

The test now also asserts:

- `after_tax_value_if_sold_at_drawdown` — after-tax proceeds if sold at the drawdown price.
- `after_tax_value_if_recovery_happens` — after-tax proceeds if sold at the recovery price.
- `expected_after_tax_value_if_hold_for_recovery` — the probability-weighted expected value of holding through the drawdown, computed as `p × after_tax_recovery + (1 − p) × after_tax_drawdown`.

### 4. `sell_today_baseline` underwater position — new test

`test_sell_today_baseline_reports_actual_unrealized_gain_for_underwater_position` verifies the corrected behaviour for a position where price is below cost basis:

- `current_unrealized_gain` is negative (actual P&L).
- `tax_if_sold_today` is zero (no tax on a loss).
- `sell_today_after_tax_value` equals the gross liquidation value.

### 5. `compare_stop_reentry_vs_hold` corrected recovery value — extended test

After the pre-tax/after-tax fix, `test_stop_reentry_uses_whole_shares_and_leftover_cash` was extended with two additional assertions:

- `stop_reentry_after_recovery_value` reflects after-tax proceeds using the re-entry price as the new cost basis, plus leftover cash.
- `hold_after_recovery_after_tax` is the expected after-tax liquidation of the original position at the recovery price.

## Why

The agent conventions require tests as part of the definition of done for any calculation change. Several functions were exposed only through notebook execution, which does not catch arithmetic errors. The additions ensure that regressions in any public function in `src/tax_risk_sim.py` are caught by `pytest` before a notebook is re-executed.

## Files affected

- `tests/test_tax_risk_sim.py` — four new tests, two existing tests extended
- `src/tax_risk_sim.py` — `build_after_tax_sensitivity` added to imports in the test file

## Known limitations

Transaction costs at non-zero rates are not yet covered by a test. The double-leg application of `transaction_cost_rate` in `compare_stop_reentry_vs_hold` is intentional (one deduction for selling, one for buying back), but a test with a non-zero rate would make that intent explicit and prevent accidental removal of either leg.
