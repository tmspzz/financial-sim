import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, "src")

from inputs import (  # noqa: E402
    allow_fractional_reentry_shares,
    bear_base_recovery_probability,
    bear_drawdown_end,
    bear_drawdown_start,
    bear_drawdown_step,
    bear_max_recovery_return,
    bear_min_recovery_probability,
    bear_min_recovery_return,
    bear_recovery_multiplier,
    benchmark_recovery_tolerance,
    capital_gains_tax_rate,
    cost_basis_per_share,
    current_price,
    reentry_slippage_from_bear_low,
    shares,
    stop_loss_drops,
    transaction_cost_rate,
)
from tax_risk_sim import (  # noqa: E402
    build_bear_recovery_cases,
    build_bear_recovery_table,
    build_probability_weighted_scenarios,
    build_stop_benchmark,
    compare_stop_reentry_vs_hold,
    sell_today_baseline,
)

pd.options.display.float_format = "{:,.2f}".format

bear_cases = build_bear_recovery_cases(
    start=bear_drawdown_start,
    end=bear_drawdown_end,
    step=bear_drawdown_step,
    recovery_multiplier=bear_recovery_multiplier,
    min_recovery_return=bear_min_recovery_return,
    max_recovery_return=bear_max_recovery_return,
    base_recovery_probability=bear_base_recovery_probability,
    min_recovery_probability=bear_min_recovery_probability,
)
baseline = sell_today_baseline(shares, current_price, cost_basis_per_share, capital_gains_tax_rate)
stop_benchmark = build_stop_benchmark(
    stop_loss_drops, shares, current_price, cost_basis_per_share, capital_gains_tax_rate
)
bear_recovery = build_bear_recovery_table(
    bear_cases, shares, current_price, cost_basis_per_share, capital_gains_tax_rate
)
strategy = compare_stop_reentry_vs_hold(
    stop_benchmark,
    bear_recovery,
    shares,
    cost_basis_per_share,
    capital_gains_tax_rate,
    reentry_slippage_from_bear_low=reentry_slippage_from_bear_low,
    transaction_cost_rate=transaction_cost_rate,
    allow_fractional_reentry_shares=allow_fractional_reentry_shares,
)

eligible = stop_benchmark[
    stop_benchmark["required_recovery_from_stop_to_match_selling_today"]
    <= benchmark_recovery_tolerance
]
best_benchmark = eligible.tail(1).iloc[0] if not eligible.empty else stop_benchmark.head(1).iloc[0]

best_by_case = (
    strategy[strategy["stop_triggers"]]
    .sort_values("stop_reentry_advantage_vs_hold_after_recovery", ascending=False)
    .groupby("bear_case", as_index=False)
    .first()
)

representative = best_by_case[
    best_by_case["bear_drawdown"].round(2).isin([-0.10, -0.20, -0.30, -0.40, -0.50, -0.60])
]
representative = representative[
    [
        "bear_case",
        "bear_drawdown",
        "stop_loss_drop",
        "stop_price",
        "reentry_price",
        "reentry_shares_after_tax_and_costs",
        "leftover_cash_after_reentry",
        "stop_reentry_advantage_vs_hold_after_recovery",
        "stop_reentry_advantage_vs_hold_after_recovery_pct",
    ]
].sort_values("bear_drawdown", ascending=False)

scenario_cases = pd.DataFrame(
    {
        "case": ["Bear", "Base", "Bull"],
        "return": [-0.20, 0.05, 0.25],
        "probability": [0.45, 0.15, 0.40],
    }
)
_, weighted_summary = build_probability_weighted_scenarios(
    scenario_cases,
    350,
    350.0,
    123.0,
    0.26,
)

summary_path = Path("executed/results_summary.txt")
summary_path.parent.mkdir(exist_ok=True)
with summary_path.open("w") as f:
    f.write("Tax Risk Simulation Results Summary\n")
    f.write("===================================\n\n")
    f.write("Core stop/re-entry assumptions\n")
    f.write(
        f"shares={shares}, current_price={current_price}, "
        f"basis={cost_basis_per_share}, tax={capital_gains_tax_rate:.0%}\n"
    )
    f.write(
        "reentry_slippage_from_bear_low="
        f"{reentry_slippage_from_bear_low:.1%}, transaction_cost_rate={transaction_cost_rate:.1%}, "
        f"fractional_shares={allow_fractional_reentry_shares}\n\n"
    )
    f.write("Sell today baseline\n")
    f.write(baseline.to_string())
    f.write("\n\n")
    f.write("Stop benchmark table\n")
    f.write(stop_benchmark.to_string(index=False))
    f.write("\n\n")
    tol = benchmark_recovery_tolerance
    f.write(f"Best benchmark stop with <={tol:.0%} required recovery from stop\n")
    f.write(best_benchmark.to_string())
    f.write("\n\n")
    f.write("Best stop + re-entry by representative bear cases\n")
    f.write(representative.to_string(index=False))
    f.write("\n\n")
    f.write("Probability-weighted scenario summary from notebook 05\n")
    f.write(weighted_summary.to_string())
    f.write("\n")

print(summary_path)
print()
print("Sell today baseline:")
print(baseline)
print()
print("Best benchmark stop <=30% required recovery:")
print(best_benchmark)
print()
print("Representative best stop + re-entry by bear case:")
print(representative.to_string(index=False))
