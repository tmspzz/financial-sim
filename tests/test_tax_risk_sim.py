import numpy as np
import pandas as pd
import pytest

from tax_risk_sim import (
    after_tax_liquidation_value,
    build_after_tax_sensitivity,
    build_bear_recovery_cases,
    build_bear_recovery_table,
    build_probability_weighted_scenarios,
    build_stop_benchmark,
    compare_stop_reentry_vs_hold,
    required_price_for_after_tax_value,
    sell_today_baseline,
    tax_due_at_sale,
    taxable_gain_at_sale,
)


def test_tax_functions_only_tax_gains() -> None:
    assert taxable_gain_at_sale(price=100, shares=10, basis_per_share=40) == 600
    assert taxable_gain_at_sale(price=30, shares=10, basis_per_share=40) == 0
    assert tax_due_at_sale(price=100, shares=10, basis_per_share=40, tax_rate=0.26) == 156
    assert (
        after_tax_liquidation_value(price=100, shares=10, basis_per_share=40, tax_rate=0.26) == 844
    )


def test_sell_today_baseline_matches_manual_calculation() -> None:
    baseline = sell_today_baseline(
        shares=35,
        current_price=350,
        basis_per_share=124,
        tax_rate=0.26,
    )

    assert baseline["current_gross_value"] == pytest.approx(12_250)
    assert baseline["current_unrealized_gain"] == pytest.approx(7_910)
    assert baseline["tax_if_sold_today"] == pytest.approx(2_056.60)
    assert baseline["sell_today_after_tax_value"] == pytest.approx(10_193.40)
    assert baseline["required_recovery_price_to_match_selling_today"] == pytest.approx(350)


def test_required_price_solves_target_after_tax_value() -> None:
    target_value = 10_193.40
    required_price = required_price_for_after_tax_value(
        target_after_tax_value=target_value,
        shares=35,
        basis_per_share=124,
        tax_rate=0.26,
        initial_high=350,
    )

    value_at_required_price = after_tax_liquidation_value(
        price=required_price,
        shares=35,
        basis_per_share=124,
        tax_rate=0.26,
    )
    assert value_at_required_price == pytest.approx(target_value)


def test_stop_benchmark_calculates_required_recovery_from_stop() -> None:
    benchmark = build_stop_benchmark(
        stop_loss_drops=np.array([0.20]),
        shares=35,
        current_price=350,
        basis_per_share=124,
        tax_rate=0.26,
    )
    row = benchmark.iloc[0]

    assert row["stop_price"] == pytest.approx(280)
    assert row["after_tax_value_if_stopped"] == pytest.approx(8_380.40)
    assert row["required_recovery_from_stop_to_match_selling_today"] == pytest.approx(0.25)


def test_bear_recovery_cases_are_numeric_and_orderable() -> None:
    cases = build_bear_recovery_cases(start=-0.05, end=-0.08, step=-0.01)

    assert cases["case"].tolist() == ["Bear -5%", "Bear -6%", "Bear -7%", "Bear -8%"]
    assert cases["drawdown"].tolist() == pytest.approx([-0.05, -0.06, -0.07, -0.08])


def test_bear_recovery_table_keeps_drawdown_column_for_sorting() -> None:
    cases = pd.DataFrame(
        {
            "case": ["Bear -20%"],
            "drawdown": [-0.20],
            "recovery_return_from_low": [0.30],
            "recovery_probability": [0.60],
        }
    )
    table = build_bear_recovery_table(
        cases,
        shares=35,
        current_price=350,
        basis_per_share=124,
        tax_rate=0.26,
    )

    assert "drawdown" in table.columns
    assert table.iloc[0]["drawdown_price"] == pytest.approx(280)
    assert table.iloc[0]["recovery_price"] == pytest.approx(364)
    # after-tax at drawdown: 280*35 - (280-124)*35*0.26 = 9800 - 1419.6 = 8380.4
    assert table.iloc[0]["after_tax_value_if_sold_at_drawdown"] == pytest.approx(8380.40)
    # after-tax at recovery: 364*35 - (364-124)*35*0.26 = 12740 - 2184 = 10556
    assert table.iloc[0]["after_tax_value_if_recovery_happens"] == pytest.approx(10556.0)
    # expected hold = 0.60 * 10556 + 0.40 * 8380.4 = 9685.76
    assert table.iloc[0]["expected_after_tax_value_if_hold_for_recovery"] == pytest.approx(9685.76)


def test_stop_reentry_uses_whole_shares_and_leftover_cash() -> None:
    stop_benchmark = build_stop_benchmark(
        stop_loss_drops=np.array([0.05]),
        shares=35,
        current_price=350,
        basis_per_share=124,
        tax_rate=0.26,
    )
    bear_recovery = build_bear_recovery_table(
        pd.DataFrame(
            {
                "case": ["Bear -30%"],
                "drawdown": [-0.30],
                "recovery_return_from_low": [0.45],
                "recovery_probability": [0.40],
            }
        ),
        shares=35,
        current_price=350,
        basis_per_share=124,
        tax_rate=0.26,
    )
    result = compare_stop_reentry_vs_hold(
        stop_benchmark,
        bear_recovery,
        shares=35,
        basis_per_share=124,
        tax_rate=0.26,
        reentry_slippage_from_bear_low=0.05,
        transaction_cost_rate=0,
        allow_fractional_reentry_shares=False,
    )
    row = result.iloc[0]

    assert row["stop_triggers"]
    assert row["reentry_price"] == pytest.approx(257.25)
    assert row["raw_reentry_shares_before_rounding"] == pytest.approx(37.862585034)
    assert row["reentry_shares_after_tax_and_costs"] == pytest.approx(37)
    assert row["leftover_cash_after_reentry"] == pytest.approx(221.90)
    # after-tax recovery value uses reentry_price as new cost basis:
    # recovery_price = 245 * 1.45 = 355.25
    # after_tax = 355.25*37 - (355.25-257.25)*37*0.26 = 13144.25 - 942.76 = 12201.49
    # plus leftover cash: 12201.49 + 221.90 = 12423.39
    assert row["stop_reentry_after_recovery_value"] == pytest.approx(12423.39, rel=1e-4)
    # hold: after_tax_liquidation_value(355.25, 35, 124, 0.26) = 12433.75 - 2104.375 = 10329.375
    assert row["hold_after_recovery_after_tax"] == pytest.approx(10329.375, rel=1e-4)


def test_build_after_tax_sensitivity_structure_and_breakeven() -> None:
    df = build_after_tax_sensitivity(
        shares=35,
        current_price=350,
        basis_per_share=124,
        tax_rate=0.26,
    )
    assert set(
        ["return", "future_price", "after_tax_value_if_sold_later", "advantage_vs_selling_today"]
    ).issubset(df.columns)
    # At 0% return the advantage vs selling today should be zero
    row_zero = df[df["return"].round(4) == 0.0].iloc[0]
    assert row_zero["advantage_vs_selling_today"] == pytest.approx(0, abs=1e-6)
    # At a positive return the advantage should be positive
    row_pos = df[df["return"].round(4) == 0.10].iloc[0]
    assert row_pos["advantage_vs_selling_today"] > 0


def test_sell_today_baseline_reports_actual_unrealized_gain_for_underwater_position() -> None:
    baseline = sell_today_baseline(
        shares=100,
        current_price=40,
        basis_per_share=50,
        tax_rate=0.26,
    )
    # Actual P&L is negative; taxable gain and tax are zero
    assert baseline["current_unrealized_gain"] == pytest.approx(-1000)
    assert baseline["tax_if_sold_today"] == pytest.approx(0)
    assert baseline["sell_today_after_tax_value"] == pytest.approx(4000)


def test_probability_weighted_scenarios_computes_expected_values() -> None:
    scenario_cases = pd.DataFrame(
        {
            "case": ["Bear", "Bull"],
            "return": [-0.20, 0.25],
            "probability": [0.40, 0.60],
        }
    )
    df, summary = build_probability_weighted_scenarios(
        scenario_cases,
        shares=35,
        current_price=350,
        basis_per_share=124,
        tax_rate=0.26,
    )
    # bear: price=280, after_tax = 280*35 - (280-124)*35*0.26 = 9800 - 1419.6 = 8380.4
    # bull: price=437.5, after_tax = 437.5*35 - (437.5-124)*35*0.26 = 15312.5 - 2852.85 = 12459.65
    # expected = 0.40*8380.4 + 0.60*12459.65 = 3352.16 + 7475.79 = 10827.95
    assert summary["expected_hold_after_tax_value"] == pytest.approx(10827.95, rel=1e-4)
    assert df["weighted_after_tax_value"].sum() == pytest.approx(
        summary["expected_hold_after_tax_value"]
    )
    sell_today = after_tax_liquidation_value(350, 35, 124, 0.26)
    assert summary["sell_today_after_tax_value"] == pytest.approx(sell_today)


def test_probability_weighted_scenarios_require_probabilities_to_sum_to_one() -> None:
    scenario_cases = pd.DataFrame(
        {
            "case": ["Bear", "Bull"],
            "return": [-0.20, 0.25],
            "probability": [0.40, 0.40],
        }
    )

    with pytest.raises(ValueError, match="not 1.0"):
        build_probability_weighted_scenarios(
            scenario_cases,
            shares=35,
            current_price=350,
            basis_per_share=124,
            tax_rate=0.26,
        )
