"""Import user-provided ETF holdings files into the constituent cache.

Reads:  data/private/etf_composition_data_user_provided/
Writes: data/private/etf_constituents_cache/{ISIN}.json  (CsvConstituentProvider format)
        data/private/etf_download_urls.json               (adds sentinel entries)

Run once after downloading updated holdings files:

    docker run --rm \\
      -v "$PWD":/home/jovyan/work \\
      -w /home/jovyan/work \\
      -e PYTHONPATH=/home/jovyan/work/src \\
      financial-sim:latest \\
      python scripts/import_etf_holdings.py

WARNING: Holdings data comes from manually downloaded provider files — not live
API data.  Re-run this script after downloading fresh files to update the cache.
Staleness is based on the as-of date embedded in each source file.

ISIN resolution for ticker-only files (iShares, Vanguard) uses yfinance.
Rows whose ISIN cannot be resolved are stored with isin=null and will appear
in the _UNRESOLVED_ bucket during portfolio look-through analysis.
"""

from __future__ import annotations

import json
import re
import warnings
from datetime import date as _date
from pathlib import Path

import pandas as pd

# ── Source file configuration ─────────────────────────────────────────────────

_ETF_CONFIGS: dict[str, dict] = {
    "DE000A0F5UF5": {
        "file": "EXXT_holdings.csv",
        "format": "ishares_csv",
        "name": "iShares NASDAQ-100 UCITS ETF (DE)",
    },
    "IE00B945VV12": {
        "file": (
            "Holdings details - Vanguard FTSE Developed Europe"
            " UCITS ETF (EUR) Distributing - 6_7_2026.xlsx"
        ),
        "format": "vanguard_xlsx",
        "name": "Vanguard FTSE Developed Europe UCITS ETF EUR Distributing",
    },
    "LU0274209740": {
        "file": "Constituent_LU0274209740.xlsx",
        "format": "dws_xlsx",
        "name": "Xtrackers MSCI Japan UCITS ETF 1C",
    },
    "IE00BTJRMP35": {
        "file": "Constituent_IE00BTJRMP35.xlsx",
        "format": "dws_xlsx",
        "name": "Xtrackers MSCI Emerging Markets UCITS ETF 1C",
    },
}

_SOURCE_TAG = "user_provided_file"

# Sentinel URL: never fetched (cache is always found first).
# If the cache is cleared, CsvConstituentProvider will try this URL, fail,
# and the chain falls through to JustETFConstituentProvider.
_SENTINEL_URL = "manually_provided://user_downloaded"

# Region → Yahoo Finance exchange suffix for ISIN lookup
_REGION_TO_SUFFIX: dict[str, str] = {
    "NL": ".AS",
    "GB": ".L",
    "FR": ".PA",
    "DE": ".DE",
    "CH": ".SW",
    "SE": ".ST",
    "DK": ".CO",
    "NO": ".OL",
    "IT": ".MI",
    "ES": ".MC",
    "FI": ".HE",
    "BE": ".BR",
    "AT": ".VI",
    "IE": ".IR",
    "PT": ".LS",
    "LU": ".LU",
}

# ISIN format: 2 alpha country + 9 alphanumeric + 1 numeric check digit
_ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")


def _validate_isin(s: object) -> str | None:
    """Return s if it looks like a valid ISIN, otherwise None."""
    if not s or not isinstance(s, str):
        return None
    s = s.strip()
    return s if _ISIN_RE.match(s) else None


# Hardcoded fallback for NASDAQ-100 constituents that yfinance returns "-" for.
# yfinance's .isin property is unreliable for US-listed stocks; these ISINs are
# from public records (DTCC CUSIP, SEC filings) and are stable.
_NASDAQ100_ISIN_SUPPLEMENT: dict[str, str] = {
    "ABNB": "US0090661010",  # Airbnb
    "AEP": "US0255371017",  # American Electric Power
    "AMZN": "US0231351067",  # Amazon.com
    "APP": "US03783C1009",  # AppLovin
    "BKNG": "US09857L1089",  # Booking Holdings
    "CEG": "US21037T1097",  # Constellation Energy
    "CMCSA": "US20030N1019",  # Comcast
    "COST": "US22160K1051",  # Costco Wholesale
    "CRWD": "US22788C1053",  # CrowdStrike Holdings
    "CSCO": "US17275R1023",  # Cisco Systems
    "CTAS": "US1729081059",  # Cintas
    "CTSH": "US1924461023",  # Cognizant Technology
    "DASH": "US23804L1035",  # DoorDash
    "EXC": "US30161N1019",  # Exelon
    "FAST": "US3116831020",  # Fastenal
    "GEHC": "US36266G1067",  # GE HealthCare Technologies
    "IDXX": "US4514241070",  # IDEXX Laboratories
    "INSM": "US4578001014",  # Insmed
    "INTC": "US4581401001",  # Intel
    "KHC": "US5007541064",  # Kraft Heinz
    "LRCX": "US5128071082",  # Lam Research
    "MAR": "US5719032022",  # Marriott International
    "MCHP": "US5765001098",  # Microchip Technology
    "MDLZ": "US5900071036",  # Mondelez International
    "MNST": "US61175W1018",  # Monster Beverage
    "MSFT": "US5949181045",  # Microsoft
    "NVDA": "US67066G1040",  # NVIDIA
    "ORLY": "US67103H1077",  # O'Reilly Automotive
    "PLTR": "US69608A1088",  # Palantir Technologies
    "PYPL": "US70450Y1038",  # PayPal Holdings
    "QCOM": "US7475251036",  # Qualcomm
    "SBUX": "US8552441094",  # Starbucks
    "TMUS": "US8725901040",  # T-Mobile US
    "TXN": "US8825081040",  # Texas Instruments
    "TSLA": "US88160R1014",  # Tesla
    "TTWO": "US8740541094",  # Take-Two Interactive
    "VRTX": "US92532F1003",  # Vertex Pharmaceuticals
    "WBD": "US9344231041",  # Warner Bros. Discovery
    "WDC": "US9581021055",  # Western Digital
    # Non-US incorporated, NASDAQ-listed
    "CCEP": "GB00BDCPN049",  # Coca-Cola Europacific Partners (UK)
    "FER": "ES0062767001",  # Ferrovial (Spain/Netherlands)
    "STX": "IE00BKVD2N49",  # Seagate Technology Holdings (Ireland)
}

# ── Parsing: iShares CSV ──────────────────────────────────────────────────────


def parse_ishares_csv(path: Path) -> tuple[list[dict], str]:
    """Parse an iShares holdings CSV (e.g. EXXT_holdings.csv).

    Returns (rows, as_of_date) where rows have keys:
        ticker, name, weight   (weight is a fraction, e.g. 0.0843 for 8.43%)

    The file has two header lines before the column-name row:
        Line 0: 'Fund Holdings as of,"DD/Mon/YYYY"'
        Line 1: empty
        Line 2: column names
    """
    raw = path.read_text(encoding="utf-8-sig")
    lines = raw.splitlines()

    # Extract as-of date from first line
    as_of = _date.today().isoformat()
    if lines:
        m = re.search(r'"?(\d{2}/\w+/\d{4})"?', lines[0])
        if m:
            as_of = _parse_date_flexible(m.group(1))

    df = pd.read_csv(path, encoding="utf-8-sig", skiprows=2)
    df.columns = [c.strip() for c in df.columns]

    # Keep only equity rows with positive weight
    df = df[df["Asset Class"].str.strip().str.lower() == "equity"].copy()
    df["_weight"] = pd.to_numeric(df["Weight (%)"], errors="coerce")
    df = df[df["_weight"] > 0].dropna(subset=["_weight", "Ticker"])

    rows = [
        {
            "ticker": str(r["Ticker"]).strip(),
            "name": str(r["Name"]).strip(),
            "weight": float(r["_weight"]) / 100.0,
            "isin": None,
        }
        for _, r in df.iterrows()
    ]
    return rows, as_of


# ── Parsing: DWS / Xtrackers XLSX ────────────────────────────────────────────


def parse_dws_xlsx(path: Path) -> tuple[list[dict], str]:
    """Parse a DWS Xtrackers constituent XLSX (Constituent_{ISIN}.xlsx).

    Returns (rows, as_of_date) where rows have keys:
        isin, name, weight   (weight is already a fraction, e.g. 0.04148)

    File structure:
        Row 0: disclaimer text
        Row 1: empty
        Row 2: actual column headers (Name, ISIN, Country, …, Weighting)
        Row 3+: data
    """
    xl = pd.ExcelFile(path)
    sheet_name = xl.sheet_names[0]
    as_of = sheet_name  # sheet name is "YYYY-MM-DD"

    df = pd.read_excel(path, sheet_name=sheet_name, skiprows=2, header=0)
    # The real header is in row 0 of the loaded df; promote it
    df.columns = [str(v).strip() if pd.notna(v) else f"_col{i}" for i, v in enumerate(df.iloc[0])]
    df = df.iloc[1:].reset_index(drop=True)

    # Keep equity rows with positive weight
    sec_col = _find_col(df.columns, "type of security", "type")
    weight_col = _find_col(df.columns, "weighting", "weight")
    isin_col = _find_col(df.columns, "isin")
    name_col = _find_col(df.columns, "name")

    if sec_col:
        df = df[df[sec_col].astype(str).str.strip().str.lower() == "equities"].copy()

    df[weight_col] = pd.to_numeric(df[weight_col], errors="coerce")
    df = df[df[weight_col] > 0].dropna(subset=[weight_col, isin_col])

    rows = [
        {
            "isin": str(r[isin_col]).strip(),
            "name": str(r[name_col]).strip(),
            "weight": float(r[weight_col]),
            "ticker": None,
        }
        for _, r in df.iterrows()
    ]
    return rows, as_of


# ── Parsing: Vanguard XLSX ────────────────────────────────────────────────────


def parse_vanguard_xlsx(path: Path) -> tuple[list[dict], str]:
    """Parse a Vanguard holdings XLSX.

    Returns (rows, as_of_date) where rows have keys:
        ticker, name, weight, region   (weight is a fraction)

    File structure:
        Row 0: download date
        Row 1: empty
        Row 2: "Holdings details"
        Row 3: fund name
        Row 4: "As at DD Mon YYYY"
        Row 5: column headers  (Ticker, Holding name, % of market value, …)
        Row 6+: data
    """
    xl = pd.ExcelFile(path)
    sheet_name = xl.sheet_names[0]

    # Read raw rows to extract as-of date from row 4 (0-indexed)
    raw = pd.read_excel(path, sheet_name=sheet_name, header=None, nrows=6)
    as_of = _date.today().isoformat()
    for _, row in raw.iterrows():
        for val in row:
            if pd.notna(val) and re.search(r"As at", str(val), re.IGNORECASE):
                m = re.search(r"As at\s+(\d+\s+\w+\s+\d{4})", str(val), re.IGNORECASE)
                if m:
                    as_of = _parse_date_flexible(m.group(1))
                break

    # Read with headers at row 5 (skiprows=5)
    df = pd.read_excel(path, sheet_name=sheet_name, skiprows=5, header=0)
    # Actual column names are in row 0 of loaded df
    df.columns = [str(v).strip() if pd.notna(v) else f"_col{i}" for i, v in enumerate(df.iloc[0])]
    df = df.iloc[1:].reset_index(drop=True)

    ticker_col = _find_col(df.columns, "ticker")
    name_col = _find_col(df.columns, "holding name", "name")
    weight_col = _find_col(df.columns, "% of market value", "weight")
    region_col = _find_col(df.columns, "region")

    # Parse weight — strip "%" and convert
    def _parse_weight(v: object) -> float | None:
        s = str(v).strip().replace("%", "")
        try:
            f = float(s)
            return f / 100.0
        except ValueError:
            return None

    df["_weight"] = df[weight_col].apply(_parse_weight)
    df = df[df["_weight"] > 0].dropna(subset=["_weight", ticker_col, name_col])
    # Drop footer rows (NaN ticker after real data)
    df = df[
        df[ticker_col].apply(lambda x: bool(str(x).strip()) and str(x).strip().lower() != "nan")
    ]

    rows = [
        {
            "ticker": str(r[ticker_col]).strip(),
            "name": str(r[name_col]).strip(),
            "weight": float(r["_weight"]),
            "region": str(r[region_col]).strip() if region_col else None,
            "isin": None,
        }
        for _, r in df.iterrows()
    ]
    return rows, as_of


# ── ISIN resolution via yfinance ──────────────────────────────────────────────

_isin_cache: dict[str, str | None] = {}


def resolve_isins(rows: list[dict], *, verbose: bool = False) -> list[dict]:
    """Try to resolve isin=None rows using yfinance.

    Modifies rows in place (adds 'isin' where found). Returns the same list.
    Rows that can't be resolved keep isin=None.
    """
    try:
        import yfinance as yf  # type: ignore[import]
    except ImportError:
        warnings.warn("yfinance not installed; ISIN resolution skipped", stacklevel=2)
        return rows

    unresolved = [r for r in rows if not r.get("isin")]
    if not unresolved:
        return rows

    if verbose:
        print(f"  Resolving ISINs for {len(unresolved)} tickers via yfinance...")

    import time

    for r in unresolved:
        ticker = r.get("ticker")
        region = r.get("region")
        if not ticker:
            continue

        # For European regions, try exchange suffix first to avoid 404s
        candidates: list[str] = []
        if region and region in _REGION_TO_SUFFIX:
            candidates.append(ticker + _REGION_TO_SUFFIX[region])
        candidates.append(ticker)  # base ticker as fallback

        isin: str | None = None
        for t in candidates:
            if t in _isin_cache:
                isin = _isin_cache[t]
                if isin:
                    break
                continue
            try:
                raw = yf.Ticker(t).isin or None
                isin = _validate_isin(raw)
                time.sleep(0.1)  # avoid rate limiting
            except Exception:
                isin = None
            _isin_cache[t] = isin
            if isin:
                break

        # Fall back to supplement table when yfinance returns '-' or nothing
        if not isin and ticker in _NASDAQ100_ISIN_SUPPLEMENT:
            isin = _NASDAQ100_ISIN_SUPPLEMENT[ticker]

        r["isin"] = isin or None
        if verbose:
            status = isin if isin else "(unresolved)"
            print(f"    {ticker} → {status}")

    return rows


# ── Cache file writing ────────────────────────────────────────────────────────


def write_cache_json(
    cache_dir: Path,
    etf_isin: str,
    rows: list[dict],
    as_of: str,
    source: str,
) -> Path:
    """Write a ConstituentResult-compatible JSON cache file.

    Path: cache_dir/{etf_isin}.json  (matches CsvConstituentProvider._cache_path)
    """
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Validate ISINs: discard '-' and any non-conforming strings
    clean_rows = [{**r, "isin": _validate_isin(r.get("isin"))} for r in rows]

    total_weight = sum(r["weight"] for r in clean_rows)
    isin_weight = sum(r["weight"] for r in clean_rows if r.get("isin"))
    # Store as fraction (0-1), matching portfolio_sim.ConstituentResult.coverage_pct convention.
    coverage_pct = (isin_weight / total_weight) if total_weight > 0 else 0.0

    data = {
        "etf_isin": etf_isin,
        "as_of": as_of,
        "source": source,
        "coverage_pct": round(coverage_pct, 4),
        "constituents": [
            {
                "isin": r.get("isin"),
                "ticker": r.get("ticker"),
                "name": r.get("name", ""),
                "weight": r["weight"],
            }
            for r in clean_rows
        ],
    }

    path = cache_dir / f"{etf_isin}.json"
    path.write_text(json.dumps(data, indent=2))
    return path


# ── Helpers ───────────────────────────────────────────────────────────────────

_MONTH_MAP = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


def _parse_date_flexible(s: str) -> str:
    """Parse date strings like '04/Jun/2026', '30 Apr 2026', '2026-06-07'."""
    s = s.strip()
    # ISO format
    if re.match(r"\d{4}-\d{2}-\d{2}", s):
        return s[:10]
    # DD/Mon/YYYY or DD-Mon-YYYY
    m = re.match(r"(\d{1,2})[/ -](\w{3,9})[/ -](\d{4})", s)
    if m:
        day, mon_str, year = int(m.group(1)), m.group(2).lower()[:3], int(m.group(3))
        month = _MONTH_MAP.get(mon_str)
        if month:
            return _date(year, month, day).isoformat()
    # DD Mon YYYY (long month name)
    m = re.match(r"(\d{1,2})\s+(\w+)\s+(\d{4})", s)
    if m:
        day, mon_str, year = int(m.group(1)), m.group(2).lower()[:3], int(m.group(3))
        month = _MONTH_MAP.get(mon_str)
        if month:
            return _date(year, month, day).isoformat()
    return _date.today().isoformat()


def _find_col(columns: list[str] | object, *candidates: str) -> str | None:
    cols = list(columns)
    for cand in candidates:
        for col in cols:
            if cand.lower() in str(col).lower():
                return col
    return None


# ── Main ──────────────────────────────────────────────────────────────────────


def main(
    source_dir: Path,
    cache_dir: Path,
    urls_path: Path,
    *,
    resolve: bool = True,
    verbose: bool = True,
    only_isins: list[str] | None = None,
) -> None:
    """Parse all configured ETF files and write cache + URL sentinel entries."""
    _WARN = (
        "\n⚠  WARNING: ETF constituent data sourced from manually downloaded files.\n"
        "   Re-run scripts/import_etf_holdings.py after downloading updated\n"
        "   holdings files to refresh the cache.\n"
    )
    print(_WARN)

    # Load existing URL map and extend it
    url_map: dict[str, str] = {}
    if urls_path.exists():
        url_map = json.loads(urls_path.read_text())

    parsers = {
        "ishares_csv": parse_ishares_csv,
        "dws_xlsx": parse_dws_xlsx,
        "vanguard_xlsx": parse_vanguard_xlsx,
    }

    for etf_isin, cfg in _ETF_CONFIGS.items():
        if only_isins and etf_isin not in only_isins:
            continue

        src_path = source_dir / cfg["file"]
        if not src_path.exists():
            print(f"  [SKIP] {cfg['name']}: source file not found at {src_path}")
            continue

        if verbose:
            print(f"  Parsing {cfg['name']} ({etf_isin})...")

        parser = parsers[cfg["format"]]
        rows, as_of = parser(src_path)

        # Vanguard has 500 European tickers — rate-limited and low portfolio impact (~1%).
        # Skip ISIN resolution for Vanguard unless explicitly requested.
        needs_resolve = resolve and cfg["format"] in ("ishares_csv", "vanguard_xlsx")
        if needs_resolve and etf_isin == "IE00B945VV12" and only_isins is None:
            print(
                "    (skipping ISIN resolution for Vanguard —"
                " 500 EU tickers, ~1% portfolio;"
                " use --etf IE00B945VV12 to resolve)"
            )
            needs_resolve = False
        if needs_resolve:
            rows = resolve_isins(rows, verbose=verbose)

        cache_path = write_cache_json(cache_dir, etf_isin, rows, as_of, _SOURCE_TAG)

        isin_count = sum(1 for r in rows if r.get("isin"))
        total_weight = sum(r["weight"] for r in rows)
        isin_weight = sum(r["weight"] for r in rows if r.get("isin"))
        coverage_display = isin_weight / total_weight * 100 if total_weight else 0

        print(
            f"    → {len(rows)} rows, {isin_count} ISIN-resolved, "
            f"coverage {coverage_display:.1f}%, as_of={as_of}"
        )
        print(f"    → cache: {cache_path}")

        url_map[etf_isin] = _SENTINEL_URL

    urls_path.write_text(json.dumps(url_map, indent=2))
    print(f"\n  URL map written to {urls_path}")
    print("  Done.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", default="data/private/etf_composition_data_user_provided")
    parser.add_argument("--cache-dir", default="data/private/etf_constituents_cache")
    parser.add_argument("--urls-path", default="data/private/etf_download_urls.json")
    parser.add_argument("--no-resolve", action="store_true", help="Skip yfinance ISIN resolution")
    parser.add_argument(
        "--etf",
        metavar="ISIN",
        action="append",
        dest="etf_isins",
        help="Process only this ETF ISIN (repeatable)",
    )
    args = parser.parse_args()

    main(
        source_dir=Path(args.source_dir),
        cache_dir=Path(args.cache_dir),
        urls_path=Path(args.urls_path),
        resolve=not args.no_resolve,
        verbose=True,
        only_isins=args.etf_isins,
    )
