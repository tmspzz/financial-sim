#!/usr/bin/env python3
"""
Validate a portfolio CSV file and print a human-readable report.

Exits 0 if the file is valid, 1 if validation errors are found.

Usage:
    python scripts/validate_portfolio_inputs.py \\
        --input data/examples/db_transactions_synthetic.csv \\
        --type transactions

    python scripts/validate_portfolio_inputs.py \\
        --input data/examples/db_holdings_synthetic.csv \\
        --type holdings
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from portfolio_sim import validate_holdings, validate_transactions


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a portfolio CSV input file")
    parser.add_argument("--input", required=True, help="Path to CSV file")
    parser.add_argument(
        "--type",
        choices=["transactions", "holdings"],
        required=True,
        help="Schema type to validate against",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"ERROR: File not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    df = pd.read_csv(input_path)

    errors = validate_transactions(df) if args.type == "transactions" else validate_holdings(df)

    if errors:
        print(f"INVALID: {input_path} ({len(df)} rows)")
        for error in errors:
            print(f"  - {error}")
        sys.exit(1)

    print(f"OK: {input_path} ({len(df)} rows)")


if __name__ == "__main__":
    main()
