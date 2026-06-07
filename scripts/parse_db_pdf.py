#!/usr/bin/env python3
"""
Parse a Deutsche Bank Vermögensanlage-Report PDF into canonical CSV and Parquet files.

Extracts:
  - Transactions (Umsätze) → <stem>_transactions.csv / .parquet
  - Holdings with cost basis (Vermögensaufstellung) → <stem>_holdings.csv / .parquet

Usage (inside Docker):
    python scripts/parse_db_pdf.py \\
        --input /path/to/deutsche-bank-report.pdf \\
        --output-dir /path/to/output-dir

    # Or set DB_PDF_PATH in the environment and omit --input:
    source .env.private
    python scripts/parse_db_pdf.py --output-dir data/private/

Output files are written to <output-dir>/<pdf-stem>_{transactions,holdings}.{csv,parquet}.

Real data (input PDF and outputs) must live under data/private/ which is gitignored.
See .env.private.example for the full list of environment variables.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pdf_parser import parse_db_pdf
from portfolio_sim import validate_holdings, validate_transactions


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse a Deutsche Bank PDF report into canonical CSV and Parquet files"
    )
    parser.add_argument(
        "--input",
        default=os.environ.get("DB_PDF_PATH"),
        help="Path to the Deutsche Bank PDF report (default: $DB_PDF_PATH)",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory where output files are written",
    )
    args = parser.parse_args()

    if args.input is None:
        parser.error(
            "--input is required (or set DB_PDF_PATH).\n"
            "See .env.private.example for the full list of environment variables."
        )

    pdf_path = Path(args.input)
    if not pdf_path.exists():
        print(f"ERROR: PDF not found: {pdf_path}", file=sys.stderr)
        sys.exit(1)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Parsing {pdf_path.name} …")

    try:
        tx_df, hld_df = parse_db_pdf(pdf_path)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    stem = pdf_path.stem

    # ── Validate ──────────────────────────────────────────────────────────────
    tx_errors = validate_transactions(tx_df)
    if tx_errors:
        print("WARNING: transaction validation errors:", file=sys.stderr)
        for err in tx_errors:
            print(f"  - {err}", file=sys.stderr)

    from portfolio_sim import HOLDINGS_COLUMNS

    hld_errors = validate_holdings(hld_df[HOLDINGS_COLUMNS])
    if hld_errors:
        print("WARNING: holdings validation errors:", file=sys.stderr)
        for err in hld_errors:
            print(f"  - {err}", file=sys.stderr)

    # ── Write transactions ────────────────────────────────────────────────────
    tx_csv = out_dir / f"{stem}_transactions.csv"
    tx_pq = out_dir / f"{stem}_transactions.parquet"
    tx_df.to_csv(tx_csv, index=False)
    tx_df.to_parquet(tx_pq, index=False)
    print(f"Transactions : {len(tx_df)} rows")
    print(f"  CSV     → {tx_csv}")
    print(f"  Parquet → {tx_pq}")

    # ── Write holdings ────────────────────────────────────────────────────────
    hld_csv = out_dir / f"{stem}_holdings.csv"
    hld_pq = out_dir / f"{stem}_holdings.parquet"
    hld_df.to_csv(hld_csv, index=False)
    hld_df.to_parquet(hld_pq, index=False)
    print(f"Holdings     : {len(hld_df)} rows  (includes cost_basis_eur column)")
    print(f"  CSV     → {hld_csv}")
    print(f"  Parquet → {hld_pq}")

    if tx_errors or hld_errors:
        sys.exit(1)

    print("Done.")


if __name__ == "__main__":
    main()
