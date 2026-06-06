#!/usr/bin/env python3
"""
End-to-end portfolio snapshot: PDF → lot ledger → live prices → simulation report.

Parses a Deutsche Bank PDF report, seeds the lot ledger from the cost-basis
holdings section, fetches current market prices via Yahoo Finance, and prints
a simulation report with unrealised gains and YTD realised gains.

Usage (inside Docker):
    python scripts/portfolio_snapshot.py \\
        --pdf data/private/report.pdf \\
        --ticker-map data/ticker_map.json \\
        --tax-rate 0.26375

ticker-map is a JSON object mapping ISIN → Yahoo Finance ticker symbol, e.g.:
    { "US67066G1040": "NVDA", "DE0005140008": "DBK.DE" }

ISINs without a ticker mapping are reported but excluded from live pricing.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date as _date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pdf_parser import parse_db_pdf
from portfolio_sim import (
    StaticPriceProvider,
    YahooPriceProvider,
    fetch_current_prices,
    initialize_lots_from_holdings,
    make_fx_provider,
    simulate_from_snapshot,
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


def _print_report(result, reporting_date: str) -> None:
    """Pretty-print the simulation output."""
    if result.empty:
        print("No positions to report.")
        return

    header = (
        f"{'ISIN':<14}  {'Market Value €':>16}  {'Unrealised Gain €':>20}"
        f"  {'Realised YTD €':>22}  {'Tax Paid YTD €':>16}"
    )
    print(f"\nPortfolio Snapshot — {reporting_date}")
    print("─" * len(header))
    print(header)
    print("─" * len(header))

    total_mv = 0.0
    total_unrealised = 0.0
    total_realised = 0.0
    total_tax = 0.0

    for _, row in result.iterrows():
        mv = row["market_value_eur"]
        unr = row["unrealised_gain_eur"]
        rea = row["realised_gain_ytd_eur"]
        tax = row["tax_paid_ytd_eur"]
        total_mv += mv
        total_unrealised += unr
        total_realised += rea
        total_tax += tax

        unr_sign = "+" if unr >= 0 else ""
        rea_sign = "+" if rea >= 0 else ""
        print(
            f"{row['isin']:<14}  {mv:>16,.2f}  {unr_sign}{unr:>19,.2f}"
            f"  {rea_sign}{rea:>21,.2f}  {tax:>16,.2f}"
        )

    print("─" * len(header))
    unr_sign = "+" if total_unrealised >= 0 else ""
    rea_sign = "+" if total_realised >= 0 else ""
    print(
        f"{'TOTAL':<14}  {total_mv:>16,.2f}  {unr_sign}{total_unrealised:>19,.2f}"
        f"  {rea_sign}{total_realised:>21,.2f}  {total_tax:>16,.2f}"
    )
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Snapshot portfolio: PDF → lots → live prices → report"
    )
    parser.add_argument(
        "--pdf",
        required=True,
        help="Path to the Deutsche Bank PDF report",
    )
    parser.add_argument(
        "--ticker-map",
        default=None,
        help="Path to a JSON file mapping ISIN → Yahoo Finance ticker",
    )
    parser.add_argument(
        "--tax-rate",
        type=float,
        default=0.26375,
        help="Flat capital-gains and dividend tax rate (default: 0.26375 for Germany)",
    )
    parser.add_argument(
        "--static-prices",
        default=None,
        help="Path to JSON mapping ISIN → price in EUR (offline mode; overrides Yahoo)",
    )
    parser.add_argument(
        "--reporting-date",
        default=None,
        help="ISO date for the report (default: today)",
    )
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        print(f"ERROR: PDF not found: {pdf_path}", file=sys.stderr)
        sys.exit(1)

    reporting_date = args.reporting_date or _date.today().isoformat()

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
        provider_label = "static (offline)"
    else:
        ticker_map = _load_ticker_map(args.ticker_map)
        mapped_isins = {isin for isin in isins if isin in ticker_map}
        unmapped = sorted(set(isins) - mapped_isins)
        if unmapped:
            print(
                f"  WARNING: no ticker mapping for {len(unmapped)} ISINs — "
                f"excluded from live pricing: {unmapped}",
                file=sys.stderr,
            )
        fx = make_fx_provider("ecb")
        price_provider = YahooPriceProvider(isin_to_ticker=ticker_map, fx_provider=fx)
        provider_label = "Yahoo Finance (live)"

    print(f"  Fetching prices via {provider_label} …")
    current_prices = fetch_current_prices(isins, price_provider, reporting_date)
    print(f"  Prices fetched: {len(current_prices)}/{len(isins)} ISINs")

    if not current_prices:
        print("ERROR: no prices available — check ticker-map or --static-prices", file=sys.stderr)
        sys.exit(1)

    # ── 4. Simulate from snapshot ─────────────────────────────────────────────
    import pandas as pd

    result = simulate_from_snapshot(
        initial_lots=lots,
        new_transactions=pd.DataFrame(),
        current_prices_eur=current_prices,
        capital_gains_tax_rate=args.tax_rate,
        dividend_tax_rate=args.tax_rate,
        reporting_date=reporting_date,
    )

    # ── 5. Print report ───────────────────────────────────────────────────────
    _print_report(result, reporting_date)


if __name__ == "__main__":
    main()
