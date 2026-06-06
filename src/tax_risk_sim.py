from __future__ import annotations

import numpy as np
import pandas as pd


def taxable_gain_at_sale(price: float, shares: float, basis_per_share: float) -> float:
    return max((price - basis_per_share) * shares, 0)


def tax_due_at_sale(
    price: float,
    shares: float,
    basis_per_share: float,
    tax_rate: float,
) -> float:
    return taxable_gain_at_sale(price, shares, basis_per_share) * tax_rate


def after_tax_liquidation_value(
    price: float,
    shares: float,
    basis_per_share: float,
    tax_rate: float,
) -> float:
    gross_value = price * shares
    return gross_value - tax_due_at_sale(price, shares, basis_per_share, tax_rate)


def required_price_for_after_tax_value(
    target_after_tax_value: float,
    shares: float,
    basis_per_share: float,
    tax_rate: float,
    initial_high: float,
) -> float:
    low = 0.0
    high = max(initial_high, basis_per_share * 10, 1.0)

    while (
        after_tax_liquidation_value(high, shares, basis_per_share, tax_rate)
        < target_after_tax_value
    ):
        high *= 2

    for _ in range(100):
        mid = (low + high) / 2
        value = after_tax_liquidation_value(mid, shares, basis_per_share, tax_rate)
        if value < target_after_tax_value:
            low = mid
        else:
            high = mid

    return high


def sell_today_baseline(
    shares: float,
    current_price: float,
    basis_per_share: float,
    tax_rate: float,
) -> pd.Series:
    gross_value = current_price * shares
    unrealized_gain = (current_price - basis_per_share) * shares
    tax_if_sold_today = tax_due_at_sale(current_price, shares, basis_per_share, tax_rate)
    after_tax_value = after_tax_liquidation_value(current_price, shares, basis_per_share, tax_rate)
    required_recovery_price = required_price_for_after_tax_value(
        after_tax_value,
        shares,
        basis_per_share,
        tax_rate,
        initial_high=current_price * 10,
    )

    return pd.Series(
        {
            "shares": shares,
            "current_price": current_price,
            "cost_basis_per_share": basis_per_share,
            "current_gross_value": gross_value,
            "current_unrealized_gain": unrealized_gain,
            "tax_if_sold_today": tax_if_sold_today,
            "sell_today_after_tax_value": after_tax_value,
            "required_recovery_price_to_match_selling_today": required_recovery_price,
        }
    )


def build_after_tax_sensitivity(
    shares: float,
    current_price: float,
    basis_per_share: float,
    tax_rate: float,
    min_return: float = -0.80,
    max_return: float = 1.00,
    return_step: float = 0.01,
) -> pd.DataFrame:
    n = round((max_return - min_return) / return_step) + 1
    future_returns = np.round(np.linspace(min_return, max_return, n), 6)
    df = pd.DataFrame(
        {
            "return": future_returns,
            "future_price": current_price * (1 + future_returns),
        }
    )
    sell_today = sell_today_baseline(shares, current_price, basis_per_share, tax_rate)[
        "sell_today_after_tax_value"
    ]
    df["after_tax_value_if_sold_later"] = df["future_price"].apply(
        lambda price: after_tax_liquidation_value(price, shares, basis_per_share, tax_rate)
    )
    df["tax_if_sold_later"] = df["future_price"].apply(
        lambda price: tax_due_at_sale(price, shares, basis_per_share, tax_rate)
    )
    df["advantage_vs_selling_today"] = df["after_tax_value_if_sold_later"] - sell_today
    return df


def build_stop_benchmark(
    stop_loss_drops: np.ndarray,
    shares: float,
    current_price: float,
    basis_per_share: float,
    tax_rate: float,
) -> pd.DataFrame:
    baseline = sell_today_baseline(shares, current_price, basis_per_share, tax_rate)
    sell_today_after_tax = baseline["sell_today_after_tax_value"]
    required_recovery_price = baseline["required_recovery_price_to_match_selling_today"]
    rows = []

    for drop in stop_loss_drops:
        stop_price = current_price * (1 - drop)
        after_tax_at_stop = after_tax_liquidation_value(
            stop_price, shares, basis_per_share, tax_rate
        )
        rows.append(
            {
                "stop_loss_drop": drop,
                "stop_price": stop_price,
                "after_tax_value_if_stopped": after_tax_at_stop,
                "after_tax_loss_vs_selling_today": after_tax_at_stop - sell_today_after_tax,
                "after_tax_loss_vs_selling_today_pct": (after_tax_at_stop / sell_today_after_tax)
                - 1,
                "required_recovery_price_to_match_selling_today": required_recovery_price,
                "required_recovery_from_stop_to_match_selling_today": (
                    required_recovery_price / stop_price
                )
                - 1,
            }
        )

    return pd.DataFrame(rows)


def build_bear_recovery_cases(
    start: float = -0.05,
    end: float = -0.60,
    step: float = -0.01,
    recovery_multiplier: float = 1.50,
    min_recovery_return: float = 0.10,
    max_recovery_return: float = 1.50,
    base_recovery_probability: float = 0.70,
    min_recovery_probability: float = 0.10,
) -> pd.DataFrame:
    n = round((end - start) / step) + 1
    drawdowns = np.round(np.linspace(start, end, n), 4)
    df = pd.DataFrame({"drawdown": drawdowns})
    df["case"] = df["drawdown"].apply(lambda value: f"Bear {value:.0%}")
    df["recovery_return_from_low"] = np.maximum(
        min_recovery_return,
        np.minimum(max_recovery_return, df["drawdown"].abs() * recovery_multiplier),
    )
    df["recovery_probability"] = np.maximum(
        min_recovery_probability,
        base_recovery_probability - df["drawdown"].abs(),
    )
    return df[["case", "drawdown", "recovery_return_from_low", "recovery_probability"]]


def build_bear_recovery_table(
    bear_recovery_cases: pd.DataFrame,
    shares: float,
    current_price: float,
    basis_per_share: float,
    tax_rate: float,
) -> pd.DataFrame:
    baseline = sell_today_baseline(shares, current_price, basis_per_share, tax_rate)
    sell_today_after_tax = baseline["sell_today_after_tax_value"]
    required_recovery_price = baseline["required_recovery_price_to_match_selling_today"]
    rows = []

    for _, case in bear_recovery_cases.iterrows():
        drawdown_price = current_price * (1 + case["drawdown"])
        recovery_price = drawdown_price * (1 + case["recovery_return_from_low"])
        after_tax_at_drawdown = after_tax_liquidation_value(
            drawdown_price, shares, basis_per_share, tax_rate
        )
        after_tax_after_recovery = after_tax_liquidation_value(
            recovery_price,
            shares,
            basis_per_share,
            tax_rate,
        )
        expected_hold_for_recovery = (
            case["recovery_probability"] * after_tax_after_recovery
            + (1 - case["recovery_probability"]) * after_tax_at_drawdown
        )

        rows.append(
            {
                "case": case["case"],
                "drawdown": case["drawdown"],
                "drawdown_price": drawdown_price,
                "after_tax_value_if_sold_at_drawdown": after_tax_at_drawdown,
                "recovery_return_from_low": case["recovery_return_from_low"],
                "recovery_price": recovery_price,
                "recovery_probability": case["recovery_probability"],
                "after_tax_value_if_recovery_happens": after_tax_after_recovery,
                "expected_after_tax_value_if_hold_for_recovery": expected_hold_for_recovery,
                "expected_difference_vs_selling_today": expected_hold_for_recovery
                - sell_today_after_tax,
                "required_recovery_price_to_match_selling_today": required_recovery_price,
                "required_recovery_return_from_low_to_match_selling_today": (
                    required_recovery_price / drawdown_price
                )
                - 1,
            }
        )

    return pd.DataFrame(rows)


def compare_stop_reentry_vs_hold(
    stop_benchmark_df: pd.DataFrame,
    bear_recovery_df: pd.DataFrame,
    shares: float,
    basis_per_share: float,
    tax_rate: float,
    reentry_slippage_from_bear_low: float = 0.0,
    transaction_cost_rate: float = 0.0,
    allow_fractional_reentry_shares: bool = False,
) -> pd.DataFrame:
    rows = []

    for _, stop in stop_benchmark_df.iterrows():
        for _, scenario in bear_recovery_df.iterrows():
            stop_triggers = abs(scenario["drawdown"]) >= stop["stop_loss_drop"]
            bear_low_price = scenario["drawdown_price"]
            recovery_price = scenario["recovery_price"]
            reentry_price = bear_low_price * (1 + reentry_slippage_from_bear_low)

            hold_after_recovery_after_tax = after_tax_liquidation_value(
                recovery_price,
                shares,
                basis_per_share,
                tax_rate,
            )

            if stop_triggers:
                cash_after_sell_cost = stop["after_tax_value_if_stopped"] * (
                    1 - transaction_cost_rate
                )
                cash_after_reentry_cost = cash_after_sell_cost * (1 - transaction_cost_rate)
                raw_reentry_shares = cash_after_reentry_cost / reentry_price
                reentry_shares = (
                    raw_reentry_shares
                    if allow_fractional_reentry_shares
                    else np.floor(raw_reentry_shares)
                )
                leftover_cash_after_reentry = cash_after_reentry_cost - (
                    reentry_shares * reentry_price
                )
                stop_reentry_after_recovery_value = (
                    after_tax_liquidation_value(
                        recovery_price, reentry_shares, reentry_price, tax_rate
                    )
                    + leftover_cash_after_reentry
                )
                note = "Stop triggered; re-entered"
            else:
                raw_reentry_shares = shares
                reentry_shares = shares
                leftover_cash_after_reentry = 0.0
                stop_reentry_after_recovery_value = hold_after_recovery_after_tax
                note = "Stop not triggered; same as hold"

            advantage = stop_reentry_after_recovery_value - hold_after_recovery_after_tax
            rows.append(
                {
                    "stop_loss_drop": stop["stop_loss_drop"],
                    "stop_price": stop["stop_price"],
                    "bear_case": scenario["case"],
                    "bear_drawdown": scenario["drawdown"],
                    "stop_triggers": stop_triggers,
                    "bear_low_price": bear_low_price,
                    "reentry_price": reentry_price,
                    "reentry_slippage_from_bear_low": reentry_slippage_from_bear_low,
                    "raw_reentry_shares_before_rounding": raw_reentry_shares,
                    "reentry_shares_after_tax_and_costs": reentry_shares,
                    "leftover_cash_after_reentry": leftover_cash_after_reentry,
                    "recovery_price": recovery_price,
                    "hold_after_recovery_after_tax": hold_after_recovery_after_tax,
                    "stop_reentry_after_recovery_value": stop_reentry_after_recovery_value,
                    "stop_reentry_advantage_vs_hold_after_recovery": advantage,
                    "stop_reentry_advantage_vs_hold_after_recovery_pct": (
                        stop_reentry_after_recovery_value / hold_after_recovery_after_tax
                    )
                    - 1,
                    "note": note,
                }
            )

    return pd.DataFrame(rows)


def build_probability_weighted_scenarios(
    scenario_cases: pd.DataFrame,
    shares: float,
    current_price: float,
    basis_per_share: float,
    tax_rate: float,
) -> tuple[pd.DataFrame, pd.Series]:
    probability_sum = scenario_cases["probability"].sum()
    if not np.isclose(probability_sum, 1.0):
        raise ValueError(f"Scenario probabilities add up to {probability_sum:.4f}, not 1.0")

    sell_today = sell_today_baseline(shares, current_price, basis_per_share, tax_rate)[
        "sell_today_after_tax_value"
    ]
    df = scenario_cases.copy()
    df["future_price"] = current_price * (1 + df["return"])
    df["after_tax_value"] = df["future_price"].apply(
        lambda price: after_tax_liquidation_value(price, shares, basis_per_share, tax_rate)
    )
    df["tax_due"] = df["future_price"].apply(
        lambda price: tax_due_at_sale(price, shares, basis_per_share, tax_rate)
    )
    df["difference_vs_selling_today"] = df["after_tax_value"] - sell_today
    df["weighted_after_tax_value"] = df["after_tax_value"] * df["probability"]
    df["weighted_difference_vs_selling_today"] = (
        df["difference_vs_selling_today"] * df["probability"]
    )

    summary = pd.Series(
        {
            "sell_today_after_tax_value": sell_today,
            "expected_hold_after_tax_value": df["weighted_after_tax_value"].sum(),
            "expected_hold_advantage_vs_selling_today": df[
                "weighted_difference_vs_selling_today"
            ].sum(),
        }
    )
    return df, summary
