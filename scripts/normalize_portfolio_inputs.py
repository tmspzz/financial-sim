#!/usr/bin/env python3
"""
Normalize and validate a portfolio CSV input file.

Reads a raw broker CSV, validates it against the canonical schema,
normalizes date formatting, and writes both a clean CSV (for human
review) and a Parquet file (for notebooks and simulation).

Usage:
    python scripts/normalize_portfolio_inputs.py \\
        --input data/private/my_transactions.csv \\
        --output-csv data/private/normalized_transactions.csv \\
        --output-parquet data/private/normalized_transactions.parquet \\
        --type transactions

    python scripts/normalize_portfolio_inputs.py \\
        --input data/private/my_holdings.csv \\
        --output-csv data/private/normalized_holdings.csv \\
        --output-parquet data/private/normalized_holdings.parquet \\
        --type holdings

Real input data must live under data/private/ which is gitignored.
Synthetic examples live under data/examples/.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from portfolio_sim import validate_holdings, validate_transactions


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize and validate portfolio CSV inputs")
    parser.add_argument("--input", required=True, help="Path to input CSV file")
    parser.add_argument("--output-csv", required=True, help="Path for normalized CSV output")
    parser.add_argument("--output-parquet", required=True, help="Path for Parquet output")
    parser.add_argument(
        "--type",
        choices=["transactions", "holdings"],
        required=True,
        help="Schema type to validate against",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"ERROR: Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    df = pd.read_csv(input_path)

    # Normalize date to ISO 8601
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")

    # Validate
    errors = validate_transactions(df) if args.type == "transactions" else validate_holdings(df)

    if errors:
        print(f"INVALID: {input_path}", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        sys.exit(1)

    # Write CSV
    out_csv = Path(args.output_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_csv, index=False)
    print(f"Written CSV:     {out_csv}")

    # Write Parquet
    out_parquet = Path(args.output_parquet)
    out_parquet.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_parquet, index=False)
    print(f"Written Parquet: {out_parquet}")

    print(f"OK: {len(df)} rows validated and written.")


if __name__ == "__main__":
    main()
