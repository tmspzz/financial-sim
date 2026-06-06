#!/usr/bin/env python3
"""
Stop-loss / re-entry analysis on a real portfolio from a Deutsche Bank PDF.

Connects: PDF holdings → lot ledger → live prices → per-position stop-loss analysis.

For each position the script runs:
  1. build_stop_benchmark  — after-tax value at various stop levels
  2. build_bear_recovery_table  — scenario grid of bear drawdowns + recoveries
  3. compare_stop_reentry_vs_hold  — cross-product of stop levels × bear scenarios

Output is a ranked summary table showing, for each ISIN, which stop-loss
trigger (if any) is expected to benefit the investor vs. holding through a
bear market and recovery.

Usage (inside Docker):
    python scripts/stop_loss_real_portfolio.py \\
        --pdf /path/to/deutsche-bank-report.pdf \\
        --ticker-map data/private/ticker_map.json \\
        --tax-rate 0.26375 \\
        --stop-drops 0.05,0.10,0.15,0.20,0.25,0.30

    # Offline with pre-fetched prices:
    python scripts/stop_loss_real_portfolio.py \\
        --pdf /path/to/deutsche-bank-report.pdf \\
        --static-prices /path/to/prices.json \\
        --tax-rate 0.26375

Use `data/private/ticker_map.json` for your real local map; it is gitignored. The
committed synthetic example is `data/examples/ticker_map_synthetic.json`.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date as _date
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pdf_parser import parse_db_pdf
from portfolio_sim import (
    StaticPriceProvider,
    YahooPriceProvider,
    fetch_current_prices,
    initialize_lots_from_holdings,
    make_fx_provider,
)
from tax_risk_sim import (
    build_bear_recovery_cases,
    build_bear_recovery_table,
    build_stop_benchmark,
    compare_stop_reentry_vs_hold,
)


def _load_ticker_map(path: str | None) -> dict[str, str]:
    if path is None:
        return {}
    p = Path(path)
    if not p.exists():
        print(f"WARNING: ticker-map file not found: {p}", file=sys.stderr)
        return {}
    with p.open() as f:
        return json.load(f)


def _analyse_position(
    isin: str,
    shares: float,
    basis_eur: float,
    current_price_eur: float,
    stop_drops: list[float],
    tax_rate: float,
    bear_cases,
    reentry_slippage: float,
    transaction_cost_rate: float,
) -> dict:
    """Run the full stop+re-entry simulation for one position and return a summary row."""
    stop_benchmark = build_stop_benchmark(
        np.array(stop_drops), shares, current_price_eur, basis_eur, tax_rate
    )
    bear_recovery_df = build_bear_recovery_table(
        bear_cases, shares, current_price_eur, basis_eur, tax_rate
    )
    comparison = compare_stop_reentry_vs_hold(
        stop_benchmark,
        bear_recovery_df,
        shares,
        basis_eur,
        tax_rate,
        reentry_slippage_from_bear_low=reentry_slippage,
        transaction_cost_rate=transaction_cost_rate,
        allow_fractional_reentry_shares=False,
    )

    triggered = comparison[comparison["stop_triggers"]]
    unrealised_gain_pct = (current_price_eur - basis_eur) / basis_eur if basis_eur > 0 else 0.0

    if triggered.empty:
        return {
            "isin": isin,
            "shares": shares,
            "basis_eur": basis_eur,
            "current_price_eur": current_price_eur,
            "market_value_eur": shares * current_price_eur,
            "unrealised_gain_pct": unrealised_gain_pct,
            "best_stop_drop": None,
            "best_stop_price_eur": None,
            "best_advantage_eur": None,
            "best_advantage_pct": None,
            "best_at_bear_case": None,
            "verdict": "no-stop-triggered",
        }

    # Best advantage across all stop × scenario combinations
    best_row = triggered.loc[triggered["stop_reentry_advantage_vs_hold_after_recovery"].idxmax()]

    return {
        "isin": isin,
        "shares": shares,
        "basis_eur": basis_eur,
        "current_price_eur": current_price_eur,
        "market_value_eur": shares * current_price_eur,
        "unrealised_gain_pct": unrealised_gain_pct,
        "best_stop_drop": best_row["stop_loss_drop"],
        "best_stop_price_eur": best_row["stop_price"],
        "best_advantage_eur": best_row["stop_reentry_advantage_vs_hold_after_recovery"],
        "best_advantage_pct": best_row["stop_reentry_advantage_vs_hold_after_recovery_pct"],
        "best_at_bear_case": best_row["bear_case"],
        "verdict": "beneficial"
        if best_row["stop_reentry_advantage_vs_hold_after_recovery"] > 0
        else "harmful",
    }


def _print_summary(rows: list[dict], reporting_date: str) -> None:
    import pandas as pd

    df = pd.DataFrame(rows)
    if df.empty:
        print("No positions to analyse.")
        return

    df = df.sort_values("best_advantage_eur", ascending=False, na_position="last")

    header_line = (
        f"\nStop-Loss Analysis — {reporting_date}\n"
        f"{'ISIN':<14}  {'Shares':>8}  {'Basis €':>10}  {'Price €':>10}  "
        f"{'MV €':>12}  {'Gain %':>8}  {'Best Stop':>10}  {'Advantage €':>13}  Verdict"
    )
    print(header_line)
    print("─" * 110)

    for _, row in df.iterrows():
        gain_pct = f"{row['unrealised_gain_pct']:+.1%}"
        if row["best_stop_drop"] is None:
            stop_str = "   —"
            adv_str = "            —"
            verdict = row["verdict"]
        else:
            stop_str = f"{row['best_stop_drop']:.0%}"
            adv = row["best_advantage_eur"]
            adv_str = f"{adv:+13,.0f}"
            verdict = f"{row['verdict']} @ {row['best_at_bear_case']}"

        print(
            f"{row['isin']:<14}  {row['shares']:>8,.1f}  {row['basis_eur']:>10,.2f}  "
            f"{row['current_price_eur']:>10,.2f}  {row['market_value_eur']:>12,.0f}  "
            f"{gain_pct:>8}  {stop_str:>10}  {adv_str}  {verdict}"
        )

    print("─" * 110)
    total_mv = df["market_value_eur"].sum()
    beneficial = (df["verdict"] == "beneficial").sum()
    print(f"Total market value: EUR {total_mv:,.0f}")
    print(f"Positions with beneficial stop-loss: {beneficial}/{len(df)}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stop-loss/re-entry analysis on a real DB portfolio"
    )
    parser.add_argument("--pdf", required=True, help="Path to the Deutsche Bank PDF report")
    parser.add_argument("--ticker-map", default=None, help="JSON file mapping ISIN → Yahoo ticker")
    parser.add_argument(
        "--tax-rate", type=float, default=0.26375, help="Flat capital-gains tax rate"
    )
    parser.add_argument(
        "--stop-drops",
        default="0.05,0.10,0.15,0.20,0.25,0.30",
        help="Comma-separated stop-loss drops to test (default: 5%%–30%%)",
    )
    parser.add_argument(
        "--reentry-slippage",
        type=float,
        default=0.05,
        help="Slippage above bear low on re-entry (default: 5%%)",
    )
    parser.add_argument(
        "--transaction-cost",
        type=float,
        default=0.001,
        help="Per-trade transaction cost rate (default: 0.1%%)",
    )
    parser.add_argument(
        "--static-prices",
        default=None,
        help="JSON mapping ISIN → price in EUR (offline mode)",
    )
    parser.add_argument(
        "--reporting-date", default=None, help="ISO date for the report (default: today)"
    )
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        print(f"ERROR: PDF not found: {pdf_path}", file=sys.stderr)
        sys.exit(1)

    reporting_date = args.reporting_date or _date.today().isoformat()
    stop_drops = [float(x) for x in args.stop_drops.split(",")]

    # ── 1. Parse PDF ──────────────────────────────────────────────────────────
    print(f"Parsing {pdf_path.name} …")
    try:
        _tx_df, hld_df = parse_db_pdf(pdf_path)
    except Exception as exc:
        print(f"ERROR parsing PDF: {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"  Holdings found: {len(hld_df)} positions")

    # ── 2. Seed lot ledger ────────────────────────────────────────────────────
    lots = initialize_lots_from_holdings(hld_df)
    print(f"  Lot ledger seeded: {len(lots)} lots")

    # ── 3. Fetch live prices ──────────────────────────────────────────────────
    isins = list(hld_df["isin"].dropna().unique())

    if args.static_prices:
        with open(args.static_prices) as f:
            static_map = json.load(f)
        price_provider = StaticPriceProvider(prices=static_map)
    else:
        ticker_map = _load_ticker_map(args.ticker_map)
        unmapped = sorted(i for i in isins if i not in ticker_map)
        if unmapped:
            print(
                f"  WARNING: no ticker mapping for {len(unmapped)} ISINs: {unmapped}",
                file=sys.stderr,
            )
        price_provider = YahooPriceProvider(
            isin_to_ticker=ticker_map, fx_provider=make_fx_provider("ecb")
        )

    current_prices = fetch_current_prices(isins, price_provider, reporting_date)
    print(f"  Prices fetched: {len(current_prices)}/{len(isins)} ISINs")

    if not current_prices:
        print("ERROR: no prices available", file=sys.stderr)
        sys.exit(1)

    # ── 4. Build bear scenarios (shared across all positions) ─────────────────
    bear_cases = build_bear_recovery_cases()

    # ── 5. Per-position stop-loss analysis ────────────────────────────────────
    n_stops = len(stop_drops)
    n_scenarios = len(bear_cases)
    print(
        f"\nRunning stop-loss analysis ({n_stops} stop levels x {n_scenarios} scenarios each) ..."
    )
    results = []
    for _, lot in lots.iterrows():
        isin = lot["isin"]
        if isin not in current_prices:
            continue
        summary = _analyse_position(
            isin=isin,
            shares=float(lot["remaining_shares"]),
            basis_eur=float(lot["lot_price_eur"]),
            current_price_eur=current_prices[isin],
            stop_drops=stop_drops,
            tax_rate=args.tax_rate,
            bear_cases=bear_cases,
            reentry_slippage=args.reentry_slippage,
            transaction_cost_rate=args.transaction_cost,
        )
        results.append(summary)

    # ── 6. Print report ───────────────────────────────────────────────────────
    _print_summary(results, reporting_date)


if __name__ == "__main__":
    main()
