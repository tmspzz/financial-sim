#!/usr/bin/env python3
"""
Portfolio composition with ETF look-through.

Loads a holdings snapshot (CSV or Parquet), optionally fetches ETF constituent
data and security metadata from Yahoo Finance, and writes breakdown tables to
an output directory.

Usage (inside Docker):
    python scripts/portfolio_composition.py \\
        --holdings data/private/holdings.parquet \\
        --ticker-map data/private/ticker_map.json \\
        --etf-urls data/private/etf_download_urls.json \\
        --output-dir data/private/composition \\
        --snapshot-date 2025-12-31

    # Or set environment variables and omit the flags:
    source .env.private
    python scripts/portfolio_composition.py --output-dir data/private/composition

Options:
    --holdings PATH       Holdings CSV or Parquet (HOLDINGS_COLUMNS schema).
                          Default: $HOLDINGS_PATH.
    --ticker-map PATH     JSON mapping ISIN → Yahoo Finance ticker.
                          Default: $TICKER_MAP_PATH.
    --etf-urls PATH       JSON mapping ETF ISIN → CSV download URL.
                          Default: $ETF_URLS_PATH.
    --etf-overrides PATH  JSON mapping ETF ISIN → "accumulating"/"distributing".
                          Default: $ETF_OVERRIDES_PATH.
    --output-dir PATH     Directory for output CSVs (created if absent).
    --snapshot-date DATE  ISO date for the holdings snapshot (default: $SNAPSHOT_DATE or today).
    --no-fetch            Skip live Yahoo metadata fetches; use broker prices only.
    --coverage-warn PCT   Warn when ETF constituent coverage is below this percentage (default: 80).

See .env.private.example for the full list of environment variables.
See .env.example for a synthetic example that works without real portfolio data.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date as _date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from portfolio_sim import (  # noqa: E402
    ChainedConstituentProvider,
    CsvConstituentProvider,
    YahooFinanceMetadataProvider,
    YahooTopHoldingsProvider,
    aggregate_portfolio_composition,
    breakdown_by_asset_class,
    breakdown_by_beta_bucket,
    breakdown_by_country,
    breakdown_by_currency,
    breakdown_by_etf_domicile,
    breakdown_by_etf_structure,
    breakdown_by_industry,
    breakdown_by_market_cap_tier,
    breakdown_by_region,
    breakdown_by_sector,
)


def _load_holdings(path: Path) -> pd.DataFrame:
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path)


def _load_json(path: Path | None) -> dict:
    if path is None or not path.exists():
        return {}
    return json.loads(path.read_text())


class _NullMetadataProvider:
    """Stand-in when --no-fetch is set; returns empty metadata for every ISIN."""

    def get_metadata(self, isin: str):
        from portfolio_sim import SecurityMetadata

        return SecurityMetadata(
            isin=isin,
            ticker=None,
            sector=None,
            industry=None,
            country=None,
            market_cap_eur=None,
            market_cap_tier="Unknown",
            beta=None,
            etf_structure="unknown",
            etf_domicile=None,
        )


class _NullConstituentProvider:
    """Stand-in when no constituent data is configured; never matches any ISIN."""

    def get_constituents(self, isin: str):
        raise KeyError(isin)


def main() -> None:
    parser = argparse.ArgumentParser(description="Portfolio composition with ETF look-through.")
    parser.add_argument(
        "--holdings",
        type=Path,
        default=Path(os.environ["HOLDINGS_PATH"]) if os.environ.get("HOLDINGS_PATH") else None,
        help="Holdings CSV or Parquet (default: $HOLDINGS_PATH)",
    )
    parser.add_argument(
        "--ticker-map",
        type=Path,
        default=Path(os.environ["TICKER_MAP_PATH"]) if os.environ.get("TICKER_MAP_PATH") else None,
        help="JSON ISIN → Yahoo ticker (default: $TICKER_MAP_PATH)",
    )
    parser.add_argument(
        "--etf-urls",
        type=Path,
        default=Path(os.environ["ETF_URLS_PATH"]) if os.environ.get("ETF_URLS_PATH") else None,
        help="JSON ETF ISIN → CSV URL (default: $ETF_URLS_PATH)",
    )
    parser.add_argument(
        "--etf-overrides",
        type=Path,
        default=Path(os.environ["ETF_OVERRIDES_PATH"])
        if os.environ.get("ETF_OVERRIDES_PATH")
        else None,
        help="JSON ETF ISIN → acc/dist override (default: $ETF_OVERRIDES_PATH)",
    )
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--snapshot-date",
        default=os.environ.get("SNAPSHOT_DATE", _date.today().isoformat()),
        help="ISO date for staleness checks (default: $SNAPSHOT_DATE or today)",
    )
    parser.add_argument("--no-fetch", action="store_true")
    parser.add_argument("--coverage-warn", type=float, default=80.0)
    args = parser.parse_args()

    if args.holdings is None:
        parser.error(
            "--holdings is required (or set HOLDINGS_PATH).\n"
            "See .env.private.example for the full list of environment variables.\n"
            "See .env.example for a synthetic example that works without real portfolio data."
        )

    holdings_df = _load_holdings(args.holdings)
    ticker_map: dict[str, str] = _load_json(args.ticker_map)
    etf_urls: dict[str, str] = _load_json(args.etf_urls)
    etf_overrides: dict[str, str] = _load_json(args.etf_overrides)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = args.output_dir / "etf_constituents_cache"
    meta_cache = args.output_dir / "security_metadata.json"

    # Build providers
    if args.no_fetch:
        constituent_provider = _NullConstituentProvider()
        metadata_provider = _NullMetadataProvider()
    else:
        csv_provider = CsvConstituentProvider(url_map=etf_urls, cache_dir=cache_dir)
        yahoo_fallback = YahooTopHoldingsProvider(
            isin_to_ticker=ticker_map,
            reverse_ticker_map={v: k for k, v in ticker_map.items()},
        )
        constituent_provider = ChainedConstituentProvider([csv_provider, yahoo_fallback])
        metadata_provider = YahooFinanceMetadataProvider(
            isin_to_ticker=ticker_map,
            cache_path=meta_cache,
            etf_structure_overrides=etf_overrides,
        )

    result = aggregate_portfolio_composition(
        holdings_df,
        constituent_provider,
        metadata_provider,
        snapshot_date=args.snapshot_date,
    )

    # Coverage warnings
    threshold = args.coverage_warn / 100.0
    if not result.etf_coverage.empty:
        low = result.etf_coverage[result.etf_coverage["coverage_pct"] < threshold]
        stale = result.etf_coverage[result.etf_coverage["is_stale"]]
        for _, row in low.iterrows():
            pct = round(row["coverage_pct"] * 100, 1)
            print(
                f"WARNING: ETF {row['etf_isin']} constituent coverage is {pct}% "
                f"(below {args.coverage_warn}%)",
                file=sys.stderr,
            )
        for _, row in stale.iterrows():
            print(
                f"WARNING: ETF {row['etf_isin']} constituent data is stale "
                f"(as_of={row['as_of']}, snapshot={args.snapshot_date})",
                file=sys.stderr,
            )

    date_slug = args.snapshot_date.replace("-", "")

    def _save(df: pd.DataFrame, name: str) -> None:
        path = args.output_dir / f"portfolio_composition_{date_slug}_{name}.csv"
        df.to_csv(path, index=False)
        print(f"Wrote {path}")

    _save(result.securities, "securities")
    _save(breakdown_by_sector(result.securities), "by_sector")
    _save(breakdown_by_industry(result.securities), "by_industry")
    _save(breakdown_by_country(result.securities), "by_country")
    _save(breakdown_by_region(result.securities), "by_region")
    _save(breakdown_by_currency(holdings_df), "by_currency")
    _save(breakdown_by_asset_class(result.securities), "by_asset_class")
    _save(breakdown_by_market_cap_tier(result.securities), "by_market_cap_tier")
    _save(breakdown_by_beta_bucket(result.securities), "by_beta_bucket")
    _save(breakdown_by_etf_structure(result.securities), "by_etf_structure")
    _save(breakdown_by_etf_domicile(result.securities), "by_etf_domicile")
    _save(result.etf_coverage, "etf_coverage")


if __name__ == "__main__":
    main()
