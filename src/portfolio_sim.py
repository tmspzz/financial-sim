"""
portfolio_sim.py — multi-security portfolio transaction simulation.

Implements schema validation, FX conversion, a FIFO lot engine, holdings
reconciliation, and portfolio-level simulation. All portfolio logic lives
here so that src/tax_risk_sim.py and src/inputs.py (single-position model)
remain unchanged.

Notebook 06 and scripts/normalize_portfolio_inputs.py are the primary
consumers. Do not import from tax_risk_sim.py or inputs.py.
"""

from __future__ import annotations

import contextlib
import csv
import io
import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date as _date
from pathlib import Path
from typing import Literal

import pandas as pd
import requests

# ── Column name constants ──────────────────────────────────────────────────────

TRANSACTION_COLUMNS: list[str] = [
    "date",
    "isin",
    "wkn",
    "asset_name",
    "transaction_type",
    "quantity",
    "price",
    "currency",
    "amount",
    "fees",
    "tax_withheld",
    "jurisdiction",
]

HOLDINGS_COLUMNS: list[str] = [
    "date",
    "isin",
    "wkn",
    "asset_name",
    "quantity",
    "price",
    "currency",
    "market_value",
    "jurisdiction",
]

LOT_COLUMNS: list[str] = [
    "isin",
    "lot_date",
    "lot_price_eur",
    "remaining_shares",
]

SIMULATION_OUTPUT_COLUMNS: list[str] = [
    "isin",
    "reporting_date",
    "market_value_eur",
    "unrealised_gain_eur",
    "realised_gain_ytd_eur",
    "tax_paid_ytd_eur",
]

SUPPORTED_TRANSACTION_TYPES: frozenset[str] = frozenset(
    {
        "buy",
        "sell",
        "fee",
        "dividend",
        "tax_withheld",
        "split",
        "transfer_in",
        "transfer_out",
    }
)

UNSUPPORTED_TRANSACTION_TYPES: frozenset[str] = frozenset(
    {
        "merger",
        "spin_off",
        "option",
    }
)

ALL_TRANSACTION_TYPES: frozenset[str] = SUPPORTED_TRANSACTION_TYPES | UNSUPPORTED_TRANSACTION_TYPES


# ── Validation ─────────────────────────────────────────────────────────────────


def validate_transactions(df: pd.DataFrame) -> list[str]:
    """
    Validate a transactions DataFrame against the canonical schema.

    Returns a list of human-readable error strings. An empty list means valid.

    Required: all TRANSACTION_COLUMNS present; each row has at least one of
    isin or wkn; asset_name is non-empty; transaction_type is a known value.
    """
    errors: list[str] = []

    missing_cols = [c for c in TRANSACTION_COLUMNS if c not in df.columns]
    if missing_cols:
        errors.append(f"Missing required columns: {missing_cols}")
        return errors  # cannot validate structure without columns

    missing_id = df[
        (df["isin"].isna() | (df["isin"] == "")) & (df["wkn"].isna() | (df["wkn"] == ""))
    ]
    if not missing_id.empty:
        errors.append(
            f"{len(missing_id)} rows missing both isin and wkn: rows {missing_id.index.tolist()}"
        )

    missing_name = df[df["asset_name"].isna() | (df["asset_name"] == "")]
    if not missing_name.empty:
        errors.append(
            f"{len(missing_name)} rows missing asset_name: rows {missing_name.index.tolist()}"
        )

    unknown = df[~df["transaction_type"].isin(ALL_TRANSACTION_TYPES)]
    if not unknown.empty:
        errors.append(f"Unknown transaction types: {unknown['transaction_type'].unique().tolist()}")

    return errors


def validate_holdings(df: pd.DataFrame) -> list[str]:
    """
    Validate a holdings DataFrame against the canonical schema.

    Returns a list of human-readable error strings. An empty list means valid.
    """
    errors: list[str] = []

    missing_cols = [c for c in HOLDINGS_COLUMNS if c not in df.columns]
    if missing_cols:
        errors.append(f"Missing required columns: {missing_cols}")
        return errors

    missing_id = df[
        (df["isin"].isna() | (df["isin"] == "")) & (df["wkn"].isna() | (df["wkn"] == ""))
    ]
    if not missing_id.empty:
        errors.append(f"{len(missing_id)} rows missing both isin and wkn")

    missing_name = df[df["asset_name"].isna() | (df["asset_name"] == "")]
    if not missing_name.empty:
        errors.append(f"{len(missing_name)} rows missing asset_name")

    return errors


# ── FX providers ───────────────────────────────────────────────────────────────


class FXProvider(ABC):
    """Abstract interface for FX rate providers."""

    @abstractmethod
    def rate(self, from_currency: str, to_currency: str, date: str) -> float:
        """
        Return the exchange rate from_currency → to_currency for the given date.

        date must be an ISO 8601 string (YYYY-MM-DD). If the market was closed
        on the requested date the provider should return the most recent
        available prior rate.
        """

    def convert(
        self,
        amount: float,
        from_currency: str,
        to_currency: str,
        date: str,
    ) -> float:
        """Convert amount from from_currency to to_currency on the given date."""
        if from_currency == to_currency:
            return amount
        return amount * self.rate(from_currency, to_currency, date)


class ECBProvider(FXProvider):
    """
    Fetches exchange rates from the ECB Statistical Data Warehouse.

    All ECB rates are expressed as units of non-EUR currency per 1 EUR.
    Example: OBS_VALUE = 1.0765 for USD means 1 EUR = 1.0765 USD.

    Uses a 7-day lookback window to handle weekends and market holidays.
    Returns the most recent available rate within that window.
    """

    _BASE = "https://data-api.ecb.europa.eu/service/data/EXR"

    def rate(self, from_currency: str, to_currency: str, date: str) -> float:
        if from_currency == to_currency:
            return 1.0

        if from_currency == "EUR":
            # EUR → X: ECB rate is X per EUR
            return self._ecb_rate(to_currency, date)
        elif to_currency == "EUR":
            # X → EUR: 1 / ECB rate
            return 1.0 / self._ecb_rate(from_currency, date)
        else:
            # Cross rate via EUR
            return self.rate(from_currency, "EUR", date) * self.rate("EUR", to_currency, date)

    def _ecb_rate(self, currency: str, date: str) -> float:
        """
        Return ECB rate: units of currency per 1 EUR on the given date.
        Uses a 7-day lookback window so weekends and holidays are handled.
        """
        from datetime import date as date_type
        from datetime import timedelta

        dt = date_type.fromisoformat(date)
        start = (dt - timedelta(days=7)).isoformat()

        url = (
            f"{self._BASE}/D.{currency}.EUR.SP00.A"
            f"?startPeriod={start}&endPeriod={date}&format=csvdata"
        )
        response = requests.get(url, timeout=10)
        response.raise_for_status()

        reader = csv.DictReader(io.StringIO(response.text))
        rows = [r for r in reader if r.get("OBS_VALUE", "").strip()]
        if not rows:
            raise ValueError(f"No ECB rate found for {currency} on or before {date}")

        # Take the most recent row (last in date-ascending response)
        obs = rows[-1]["OBS_VALUE"].strip()
        return float(obs)


class YahooProvider(FXProvider):
    """
    Fetches historical FX rates from Yahoo Finance.

    Uses the {FROM}{TO}=X ticker convention with a 5-day lookback.
    Returns the most recent close on or before the requested date.
    """

    def rate(self, from_currency: str, to_currency: str, date: str) -> float:
        from datetime import datetime, timedelta

        if from_currency == to_currency:
            return 1.0

        ticker = f"{from_currency}{to_currency}=X"
        dt = datetime.strptime(date, "%Y-%m-%d")
        period1 = int((dt - timedelta(days=5)).timestamp())
        period2 = int((dt + timedelta(days=1)).timestamp())

        url = (
            f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
            f"?interval=1d&period1={period1}&period2={period2}"
        )
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()

        data = resp.json()
        result = data["chart"]["result"][0]
        timestamps = result["timestamp"]
        closes = result["indicators"]["quote"][0]["close"]

        target_ts = int(dt.timestamp())
        pairs = [
            (ts, c)
            for ts, c in zip(timestamps, closes, strict=False)
            if c is not None and ts <= target_ts
        ]
        if not pairs:
            raise ValueError(f"No Yahoo rate found for {ticker} on or before {date}")

        _, rate = max(pairs, key=lambda p: p[0])
        return rate


def make_fx_provider(name: str = "ecb") -> FXProvider:
    """Return a FXProvider by name. Accepts 'ecb' or 'yahoo'."""
    if name == "ecb":
        return ECBProvider()
    if name == "yahoo":
        return YahooProvider()
    raise ValueError(f"Unknown FX provider: {name!r}. Use 'ecb' or 'yahoo'.")


# ── Price providers ────────────────────────────────────────────────────────────


class PriceProvider(ABC):
    """
    Abstract interface for security price providers.

    All implementations return prices in EUR so they can be fed directly
    into simulate_portfolio() as current_prices_eur.
    """

    @abstractmethod
    def price_eur(self, isin: str, date: str) -> float:
        """
        Return the closing price in EUR on or before the given date.

        date: ISO 8601 string (YYYY-MM-DD).
        Raises KeyError if the ISIN is not known to this provider.
        Raises ValueError if no price is available on or before the date.
        """


class StaticPriceProvider(PriceProvider):
    """
    Fixed-price provider for demos, backtests, and offline testing.

    Prices are constant regardless of the requested date — suitable when
    you already have a snapshot of end-of-period prices (e.g. from a
    broker holdings report).
    """

    def __init__(self, prices: dict[str, float]) -> None:
        """
        prices: mapping of ISIN → price in EUR.
        """
        self._prices = dict(prices)

    def price_eur(self, isin: str, date: str) -> float:
        if isin not in self._prices:
            raise KeyError(f"No price configured for ISIN {isin!r}")
        return self._prices[isin]


class YahooPriceProvider(PriceProvider):
    """
    Fetches historical security prices from Yahoo Finance.

    Requires a user-supplied ISIN → Yahoo ticker mapping because Yahoo
    uses ticker symbols, not ISINs.  For EUR-listed tickers (e.g. "SYNT.DE")
    the price is returned directly in EUR. For non-EUR tickers (e.g. "SYNG"
    quoted in USD) the fx_provider converts to EUR using the same date.

    Uses a 7-day lookback window to handle weekends and holidays.
    """

    def __init__(
        self,
        isin_to_ticker: dict[str, str],
        fx_provider: FXProvider | None = None,
    ) -> None:
        """
        isin_to_ticker: mapping of ISIN → Yahoo Finance ticker symbol.
            EUR-listed examples : "SYNT.DE", "SYNE.AS", "SYNX.DE"
            USD-listed examples : "SYNG", "SYNM", "SYND"
        fx_provider: used to convert non-EUR prices to EUR.
            Defaults to ECBProvider.
        """
        self._map = dict(isin_to_ticker)
        self._fx = fx_provider if fx_provider is not None else ECBProvider()

    def price_eur(self, isin: str, date: str) -> float:
        ticker = self._map.get(isin)
        if not ticker:
            raise KeyError(f"No ticker mapping for ISIN {isin!r}")
        price, currency = self._fetch(ticker, date)
        return self._fx.convert(price, currency, "EUR", date)

    def _fetch(self, ticker: str, date: str) -> tuple[float, str]:
        """Return (price, currency) for the ticker on or before date."""
        from datetime import datetime, timedelta

        dt = datetime.strptime(date, "%Y-%m-%d")
        period1 = int((dt - timedelta(days=7)).timestamp())
        period2 = int((dt + timedelta(days=1)).timestamp())

        url = (
            f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
            f"?interval=1d&period1={period1}&period2={period2}"
        )
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()

        data = resp.json()
        result = data["chart"]["result"][0]
        currency: str = result["meta"]["currency"]
        timestamps: list[int] = result["timestamp"]
        closes: list[float | None] = result["indicators"]["quote"][0]["close"]

        target_ts = int(dt.timestamp())
        pairs = [
            (ts, c)
            for ts, c in zip(timestamps, closes, strict=False)
            if c is not None and ts <= target_ts
        ]
        if not pairs:
            raise ValueError(f"No Yahoo price found for {ticker!r} on or before {date}")

        _, price = max(pairs, key=lambda p: p[0])
        return price, currency


def make_price_provider(name: str, **kwargs: object) -> PriceProvider:
    """
    Return a PriceProvider by name.

    Supported names:
        "static"  — StaticPriceProvider; pass prices=dict[str, float]
        "yahoo"   — YahooPriceProvider; pass isin_to_ticker=dict[str, str]
                    and optionally fx_provider=FXProvider
    """
    if name == "static":
        return StaticPriceProvider(prices=kwargs.get("prices", {}))  # type: ignore[arg-type]
    if name == "yahoo":
        return YahooPriceProvider(
            isin_to_ticker=kwargs.get("isin_to_ticker", {}),  # type: ignore[arg-type]
            fx_provider=kwargs.get("fx_provider"),  # type: ignore[arg-type]
        )
    raise ValueError(f"Unknown price provider: {name!r}. Use 'static' or 'yahoo'.")


# ── ETF constituent providers ──────────────────────────────────────────────────


@dataclass
class ConstituentRow:
    isin: str | None
    ticker: str | None
    name: str
    weight: float  # fraction of ETF total value, 0.0–1.0


@dataclass
class ConstituentResult:
    etf_isin: str
    constituents: list[ConstituentRow]
    coverage_pct: float  # fraction of ETF weight that has resolvable ISINs
    as_of: str  # ISO date YYYY-MM-DD
    source: str  # "csv" | "yahoo_top_holdings"

    def is_stale(self, snapshot_date: str) -> bool:
        """Return True if constituent data is more than 90 days older than snapshot_date."""
        delta = _date.fromisoformat(snapshot_date) - _date.fromisoformat(self.as_of)
        return delta.days > 90


class ETFConstituentProvider(ABC):
    @abstractmethod
    def get_constituents(self, isin: str) -> ConstituentResult:
        """Return constituent breakdown for the given ETF ISIN.

        Raises KeyError if this provider does not know the ISIN.
        """


# Month abbreviation map for iShares-style dates like "31/Dec/2025"
_MONTH_ABBR = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}


def _parse_ishares_date(raw: str) -> str:
    """Parse iShares-style date strings to ISO format.

    Handles "31/Dec/2025", "2025-12-31", and "30-Jun-2025".
    """
    raw = raw.strip().strip('"')
    # Try ISO first
    try:
        return _date.fromisoformat(raw).isoformat()
    except ValueError:
        pass
    # Try DD/Mon/YYYY or DD-Mon-YYYY (e.g. "31/Dec/2025", "30-Jun-2025")
    m = re.match(r"(\d{1,2})[/-]([A-Za-z]{3})[/-](\d{4})", raw)
    if m:
        day, mon_str, year = int(m.group(1)), m.group(2).capitalize(), int(m.group(3))
        month = _MONTH_ABBR.get(mon_str)
        if month:
            return _date(year, month, day).isoformat()
    # Try DD/MM/YYYY or DD-MM-YYYY (e.g. "31/03/2026" from justETF)
    m = re.match(r"(\d{1,2})[/-](\d{2})[/-](\d{4})", raw)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return _date(year, month, day).isoformat()
    raise ValueError(f"Cannot parse date: {raw!r}")


class CsvConstituentProvider(ETFConstituentProvider):
    """Downloads and parses ETF holdings CSVs (iShares, Amundi, Xtrackers, etc.).

    url_map: ISIN → direct CSV download URL (user-maintained, e.g. from
        data/private/etf_download_urls.json).
    cache_dir: if given, parsed results are cached as JSON files under
        cache_dir/<ISIN>.json so repeated runs skip the HTTP download.
    """

    def __init__(
        self,
        url_map: dict[str, str] | None = None,
        cache_dir: Path | None = None,
    ) -> None:
        self._url_map: dict[str, str] = dict(url_map or {})
        self._cache_dir = cache_dir

    def get_constituents(self, isin: str) -> ConstituentResult:
        if isin not in self._url_map:
            raise KeyError(f"No CSV URL configured for ISIN {isin!r}")

        if self._cache_dir is not None:
            cached = self._load_cache(isin)
            if cached is not None:
                return cached

        url = self._url_map[isin]
        resp = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        result = self._parse_csv(isin, resp.text)

        if self._cache_dir is not None:
            self._save_cache(isin, result)

        return result

    @staticmethod
    def _parse_csv(etf_isin: str, text: str) -> ConstituentResult:
        lines = text.splitlines()

        # Find the header row: first row containing both "ISIN" and "Weight"
        header_idx = None
        as_of_raw: str | None = None
        for i, line in enumerate(lines):
            upper = line.upper()
            if "ISIN" in upper and "WEIGHT" in upper:
                header_idx = i
                break
            # Look for "as of" date in metadata rows
            if "HOLDINGS AS OF" in upper or "AS OF" in upper:
                parts = [p.strip().strip('"') for p in line.split(",")]
                for part in parts:
                    if re.search(r"\d{1,2}[/-][A-Za-z]{3}[/-]\d{4}", part) or re.search(
                        r"\d{4}-\d{2}-\d{2}", part
                    ):
                        as_of_raw = part
                        break

        if header_idx is None:
            raise ValueError(f"Could not find column header row in CSV for {etf_isin!r}")

        # Parse column headers
        reader = csv.DictReader(
            lines[header_idx:],
            dialect="excel",
        )
        reader.fieldnames = [h.strip().strip('"') for h in (reader.fieldnames or [])]

        # Normalise column names to handle minor formatting differences
        def _find_col(fieldnames: list[str], *candidates: str) -> str | None:
            for c in candidates:
                for f in fieldnames:
                    if c.lower() in f.lower():
                        return f
            return None

        fn = list(reader.fieldnames)
        isin_col = _find_col(fn, "isin")
        weight_col = _find_col(fn, "weight (%)", "weight(%)", "weight")
        name_col = _find_col(fn, "name")

        if not isin_col or not weight_col or not name_col:
            raise ValueError(
                f"Required columns (Name, ISIN, Weight) not found in CSV for {etf_isin!r}. "
                f"Found: {fn}"
            )

        constituents: list[ConstituentRow] = []
        total_weight = 0.0
        isin_weight = 0.0

        for row in reader:
            raw_isin = (row.get(isin_col) or "").strip().strip('"')
            raw_weight = (row.get(weight_col) or "").strip().strip('"').replace(",", "")
            raw_name = (row.get(name_col) or "").strip().strip('"')

            if not raw_weight or not raw_name:
                continue
            try:
                w = float(raw_weight) / 100.0  # convert percentage to fraction
            except ValueError:
                continue

            total_weight += w
            if raw_isin:
                isin_weight += w
                constituents.append(
                    ConstituentRow(isin=raw_isin, ticker=None, name=raw_name, weight=w)
                )

        coverage = isin_weight / total_weight if total_weight > 0 else 0.0
        as_of = _parse_ishares_date(as_of_raw) if as_of_raw else _date.today().isoformat()

        return ConstituentResult(
            etf_isin=etf_isin,
            constituents=constituents,
            coverage_pct=coverage,
            as_of=as_of,
            source="csv",
        )

    def _cache_path(self, isin: str) -> Path:
        assert self._cache_dir is not None
        return self._cache_dir / f"{isin}.json"

    def _load_cache(self, isin: str) -> ConstituentResult | None:
        path = self._cache_path(isin)
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        return ConstituentResult(
            etf_isin=data["etf_isin"],
            constituents=[ConstituentRow(**c) for c in data["constituents"]],
            coverage_pct=data["coverage_pct"],
            as_of=data["as_of"],
            source=data["source"],
        )

    def _save_cache(self, isin: str, result: ConstituentResult) -> None:
        assert self._cache_dir is not None
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "etf_isin": result.etf_isin,
            "constituents": [
                {"isin": c.isin, "ticker": c.ticker, "name": c.name, "weight": c.weight}
                for c in result.constituents
            ],
            "coverage_pct": result.coverage_pct,
            "as_of": result.as_of,
            "source": result.source,
        }
        self._cache_path(isin).write_text(json.dumps(data, indent=2))


def _yahoo_crumb_session() -> tuple[requests.Session, str]:
    """Return a requests Session with Yahoo Finance cookies and a valid crumb.

    Yahoo's quoteSummary v10 API requires a crumb obtained from their consent
    endpoint.  The crumb is stable for the lifetime of the cookie jar, so we
    fetch it once per process and cache it on the function object.
    """
    if getattr(_yahoo_crumb_session, "_cache", None):
        return _yahoo_crumb_session._cache  # type: ignore[attr-defined]

    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    # Seed the cookie jar via the consent/check redirect.
    session.get("https://fc.yahoo.com", timeout=10)
    session.get("https://finance.yahoo.com/", timeout=10)
    crumb_resp = session.get("https://query1.finance.yahoo.com/v1/test/getcrumb", timeout=10)
    crumb = crumb_resp.text.strip()
    _yahoo_crumb_session._cache = (session, crumb)  # type: ignore[attr-defined]
    return session, crumb


def yahoo_isin_from_ticker(ticker: str) -> str | None:
    """Return the ISIN for a ticker using Yahoo Finance's search page.

    Uses the same session/crumb infrastructure as the rest of this module,
    giving a single Yahoo Finance integration point.  Returns None when Yahoo
    does not embed an ISIN in the search-page JSON (common for US-listed
    domestic stocks — use _NASDAQ100_ISIN_SUPPLEMENT in import_etf_holdings.py
    as the authoritative fallback for those).
    """
    _ISIN_RE = re.compile(r'"isin"\s*:\s*"([A-Z]{2}[A-Z0-9]{9}[0-9])"')
    try:
        session, _crumb = _yahoo_crumb_session()
        resp = session.get(
            "https://finance.yahoo.com/search/",
            params={"q": ticker, "lang": "en-US", "region": "US"},
            timeout=10,
        )
        m = _ISIN_RE.search(resp.text)
        return m.group(1) if m else None
    except Exception:  # noqa: BLE001
        return None


class YahooTopHoldingsProvider(ETFConstituentProvider):
    """Yahoo Finance topHoldings fallback.

    Returns the top ~10–15 holdings from Yahoo's quoteSummary API.
    Coverage is partial (holdingsPercent field from Yahoo).
    ISINs are None unless a reverse_ticker_map is provided.
    """

    _BASE = "https://query1.finance.yahoo.com/v10/finance/quoteSummary"

    def __init__(
        self,
        isin_to_ticker: dict[str, str],
        reverse_ticker_map: dict[str, str] | None = None,
    ) -> None:
        self._map = dict(isin_to_ticker)
        self._reverse = dict(reverse_ticker_map or {})

    def get_constituents(self, isin: str) -> ConstituentResult:
        ticker = self._map.get(isin)
        if not ticker:
            raise KeyError(f"No ticker mapping for ISIN {isin!r}")

        try:
            session, crumb = _yahoo_crumb_session()
            url = f"{self._BASE}/{ticker}?modules=topHoldings&crumb={crumb}"
            resp = session.get(url, timeout=15)
            resp.raise_for_status()
        except requests.exceptions.RequestException as exc:
            raise ValueError(f"Yahoo Finance request failed for {ticker!r}: {exc}") from exc
        data = resp.json()

        result_list = data.get("quoteSummary", {}).get("result") or []
        if not result_list:
            raise ValueError(f"No topHoldings data returned for ticker {ticker!r}")

        top = result_list[0].get("topHoldings", {})
        holdings_pct = (top.get("holdingsPercent") or {}).get("raw", 0.0)
        as_of_raw = (top.get("asOfDate") or {}).get("fmt", _date.today().isoformat())
        as_of = _parse_ishares_date(as_of_raw)

        constituents: list[ConstituentRow] = []
        for h in top.get("holdings", []):
            sym = (h.get("symbol") or "").strip()
            name = (h.get("holdingName") or "").strip()
            w = (h.get("holdingPercent") or {}).get("raw", 0.0)
            resolved_isin = self._reverse.get(sym)
            constituents.append(ConstituentRow(isin=resolved_isin, ticker=sym, name=name, weight=w))

        return ConstituentResult(
            etf_isin=isin,
            constituents=constituents,
            coverage_pct=holdings_pct,
            as_of=as_of,
            source="yahoo_top_holdings",
        )


# justETF profile page base URL
_JUSTETF_PROFILE_URL = "https://www.justetf.com/en/etf-profile.html"

_BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class JustETFConstituentProvider(ETFConstituentProvider):
    """Scrapes top-10 ETF holdings from justETF (https://www.justetf.com).

    Works by ISIN. Returns up to 10 constituents with ISINs and weights.
    Requires beautifulsoup4 (already in the project Docker image).

    cache_dir: if given, parsed results are stored as JSON so repeated runs
        skip the HTTP request.
    """

    def __init__(self, cache_dir: Path | None = None) -> None:
        self._cache_dir = cache_dir

    def get_constituents(self, isin: str) -> ConstituentResult:
        try:
            from bs4 import BeautifulSoup  # type: ignore[import]
        except ImportError as exc:
            raise KeyError(f"beautifulsoup4 required for JustETF scraping of {isin}") from exc

        if self._cache_dir is not None:
            cached = self._load_cache(isin)
            if cached is not None:
                return cached

        resp = requests.get(
            _JUSTETF_PROFILE_URL,
            params={"isin": isin},
            headers={"User-Agent": _BROWSER_UA},
            timeout=20,
        )
        if resp.status_code != 200:
            raise ValueError(f"justETF returned HTTP {resp.status_code} for {isin}")

        soup = BeautifulSoup(resp.text, "html.parser")

        constituents: list[ConstituentRow] = []
        total_weight = 0.0
        for row in soup.find_all("tr", attrs={"data-testid": "etf-holdings_top-holdings_row"}):
            name_el = row.find("a", attrs={"data-testid": "tl_etf-holdings_top-holdings_link_name"})
            pct_el = row.find(
                "span",
                attrs={"data-testid": "tl_etf-holdings_top-holdings_value_percentage"},
            )
            if not (name_el and pct_el):
                continue
            pct_match = re.search(r"([\d.]+)", pct_el.get_text(strip=True))
            if not pct_match:
                continue
            w = float(pct_match.group(1)) / 100.0
            href = name_el.get("href", "")
            holding_isin = (
                href.split("/stock-profiles/")[-1] if "/stock-profiles/" in href else None
            )
            constituents.append(
                ConstituentRow(
                    isin=holding_isin, ticker=None, name=name_el.get_text(strip=True), weight=w
                )
            )
            total_weight += w

        if not constituents:
            raise ValueError(f"No holdings found on justETF for {isin}")

        ref_el = soup.find("div", attrs={"data-testid": "tl_etf-holdings_reference-date"})
        as_of = _date.today().isoformat()
        if ref_el:
            with contextlib.suppress(ValueError):
                as_of = _parse_ishares_date(ref_el.get_text(strip=True))

        result = ConstituentResult(
            etf_isin=isin,
            constituents=constituents,
            coverage_pct=total_weight,
            as_of=as_of,
            source="justetf_top_holdings",
        )
        if self._cache_dir is not None:
            self._save_cache(isin, result)
        return result

    def _cache_path(self, isin: str) -> Path:
        assert self._cache_dir is not None
        return self._cache_dir / f"{isin}_justetf.json"

    def _load_cache(self, isin: str) -> ConstituentResult | None:
        path = self._cache_path(isin)
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        return ConstituentResult(
            etf_isin=data["etf_isin"],
            constituents=[ConstituentRow(**c) for c in data["constituents"]],
            coverage_pct=data["coverage_pct"],
            as_of=data["as_of"],
            source=data["source"],
        )

    def _save_cache(self, isin: str, result: ConstituentResult) -> None:
        assert self._cache_dir is not None
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "etf_isin": result.etf_isin,
            "constituents": [
                {"isin": c.isin, "ticker": c.ticker, "name": c.name, "weight": c.weight}
                for c in result.constituents
            ],
            "coverage_pct": result.coverage_pct,
            "as_of": result.as_of,
            "source": result.source,
        }
        self._cache_path(isin).write_text(json.dumps(data, indent=2))


class ChainedConstituentProvider(ETFConstituentProvider):
    """Try providers in order and return the first successful result.

    Raises KeyError if all providers fail for the given ISIN.
    """

    def __init__(self, providers: list[ETFConstituentProvider]) -> None:
        self._providers = list(providers)

    def get_constituents(self, isin: str) -> ConstituentResult:
        last_exc: Exception = KeyError(isin)
        for provider in self._providers:
            try:
                return provider.get_constituents(isin)
            except (KeyError, ValueError) as exc:
                last_exc = exc
        raise KeyError(isin) from last_exc


# ── Security metadata provider ─────────────────────────────────────────────────

# ISIN country prefix → human-readable domicile name
_ISIN_DOMICILE: dict[str, str] = {
    "IE": "Ireland",
    "LU": "Luxembourg",
    "DE": "Germany",
    "FR": "France",
    "NL": "Netherlands",
    "GB": "United Kingdom",
    "US": "United States",
    "CH": "Switzerland",
    "SE": "Sweden",
    "DK": "Denmark",
    "FI": "Finland",
    "NO": "Norway",
    "AT": "Austria",
    "BE": "Belgium",
    "ES": "Spain",
    "IT": "Italy",
}

# Market cap tier thresholds in EUR
_LARGE_CAP_EUR = 10_000_000_000
_MID_CAP_EUR = 2_000_000_000


@dataclass
class SecurityMetadata:
    isin: str
    ticker: str | None
    sector: str | None
    industry: str | None
    country: str | None
    market_cap_eur: float | None
    market_cap_tier: str  # "Large" | "Mid" | "Small" | "Unknown"
    beta: float | None
    etf_structure: str  # "accumulating" | "distributing" | "unknown"
    etf_domicile: str | None  # derived from ISIN prefix


class _YahooTickerCache:
    """In-memory cache of raw Yahoo quoteSummary responses, keyed by ticker.

    Shared across provider instances in the same Python session so each
    ticker is fetched at most once per run.  Metadata fields (sector, beta,
    etc.) change slowly and are safe to cache for a session.  Price data
    is NOT stored here — the price provider always fetches live.
    """

    def __init__(self) -> None:
        self._store: dict[str, dict] = {}

    def get(self, ticker: str) -> dict | None:
        return self._store.get(ticker)

    def set(self, ticker: str, data: dict) -> None:
        self._store[ticker] = data


# Module-level default cache — shared within a single Python process.
_default_ticker_cache = _YahooTickerCache()

_YAHOO_SUMMARY_BASE = "https://query1.finance.yahoo.com/v10/finance/quoteSummary"
_SUMMARY_MODULES = "assetProfile,defaultKeyStatistics,summaryDetail,price"


class YahooFinanceMetadataProvider:
    """Fetches security metadata from Yahoo Finance.

    Returns sector, industry, country, market cap tier, beta, ETF structure,
    and ETF domicile for each ISIN.  Results are persisted to a sidecar JSON
    cache file so repeated runs skip the network call.

    etf_structure_overrides: explicit ISIN → "accumulating"/"distributing" map.
        Takes precedence over the name heuristic.
    ticker_cache: optional shared _YahooTickerCache for cross-provider dedup.
        Defaults to the module-level cache.
    """

    def __init__(
        self,
        isin_to_ticker: dict[str, str],
        cache_path: Path | None = None,
        etf_structure_overrides: dict[str, str] | None = None,
        ticker_cache: _YahooTickerCache | None = None,
    ) -> None:
        self._map = dict(isin_to_ticker)
        self._cache_path = cache_path
        self._overrides = dict(etf_structure_overrides or {})
        self._ticker_cache = ticker_cache if ticker_cache is not None else _default_ticker_cache
        self._disk_cache: dict[str, dict] = self._load_disk_cache()

    def get_metadata(self, isin: str) -> SecurityMetadata:
        ticker = self._map.get(isin)
        if not ticker:
            raise KeyError(f"No ticker mapping for ISIN {isin!r}")

        if isin in self._disk_cache:
            return self._from_dict(self._disk_cache[isin])

        raw = self._ticker_cache.get(ticker)
        if raw is None:
            try:
                session, crumb = _yahoo_crumb_session()
                url = f"{_YAHOO_SUMMARY_BASE}/{ticker}?modules={_SUMMARY_MODULES}&crumb={crumb}"
                resp = session.get(url, timeout=15)
                resp.raise_for_status()
            except requests.exceptions.RequestException as exc:
                raise ValueError(f"Yahoo Finance request failed for {ticker!r}: {exc}") from exc
            data = resp.json()
            result_list = (data.get("quoteSummary") or {}).get("result") or []
            if not result_list:
                raise ValueError(f"No quoteSummary data for ticker {ticker!r}")
            raw = result_list[0]
            self._ticker_cache.set(ticker, raw)

        meta = self._extract(isin, ticker, raw)
        self._disk_cache[isin] = self._to_dict(meta)
        self._save_disk_cache()
        return meta

    def _extract(self, isin: str, ticker: str, raw: dict) -> SecurityMetadata:
        profile = raw.get("assetProfile") or {}
        stats = raw.get("defaultKeyStatistics") or {}
        summary = raw.get("summaryDetail") or {}
        price_info = raw.get("price") or {}

        sector = profile.get("sector") or None
        industry = profile.get("industry") or None
        country = profile.get("country") or None

        beta_raw = (stats.get("beta") or {}).get("raw")
        beta = float(beta_raw) if beta_raw is not None else None

        market_cap_raw = (summary.get("marketCap") or {}).get("raw")
        market_cap_eur = float(market_cap_raw) if market_cap_raw is not None else None
        market_cap_tier = _classify_market_cap(market_cap_eur)

        etf_domicile = _ISIN_DOMICILE.get(isin[:2].upper())

        etf_structure = self._resolve_etf_structure(isin, price_info)

        return SecurityMetadata(
            isin=isin,
            ticker=ticker,
            sector=sector,
            industry=industry,
            country=country,
            market_cap_eur=market_cap_eur,
            market_cap_tier=market_cap_tier,
            beta=beta,
            etf_structure=etf_structure,
            etf_domicile=etf_domicile,
        )

    def _resolve_etf_structure(self, isin: str, price_info: dict) -> str:
        if isin in self._overrides:
            return self._overrides[isin]
        long_name = (price_info.get("longName") or "").lower()
        if "(acc)" in long_name or " acc " in long_name or long_name.endswith(" acc"):
            return "accumulating"
        if "(dist)" in long_name or "(dis)" in long_name or " dist " in long_name:
            return "distributing"
        return "unknown"

    def _load_disk_cache(self) -> dict[str, dict]:
        if self._cache_path and Path(self._cache_path).exists():
            return json.loads(Path(self._cache_path).read_text())
        return {}

    def _save_disk_cache(self) -> None:
        if self._cache_path:
            Path(self._cache_path).parent.mkdir(parents=True, exist_ok=True)
            Path(self._cache_path).write_text(json.dumps(self._disk_cache, indent=2))

    @staticmethod
    def _to_dict(meta: SecurityMetadata) -> dict:
        return {
            "isin": meta.isin,
            "ticker": meta.ticker,
            "sector": meta.sector,
            "industry": meta.industry,
            "country": meta.country,
            "market_cap_eur": meta.market_cap_eur,
            "market_cap_tier": meta.market_cap_tier,
            "beta": meta.beta,
            "etf_structure": meta.etf_structure,
            "etf_domicile": meta.etf_domicile,
        }

    @staticmethod
    def _from_dict(d: dict) -> SecurityMetadata:
        return SecurityMetadata(**d)


def _classify_market_cap(market_cap_eur: float | None) -> str:
    if market_cap_eur is None:
        return "Unknown"
    if market_cap_eur >= _LARGE_CAP_EUR:
        return "Large"
    if market_cap_eur >= _MID_CAP_EUR:
        return "Mid"
    return "Small"


# ── Portfolio composition aggregation ──────────────────────────────────────────

_UNRESOLVED_ISIN = "_UNRESOLVED_"

# Columns present in CompositionResult.securities DataFrame
COMPOSITION_SECURITY_COLUMNS: list[str] = [
    "isin",
    "name",
    "direct_weight_pct",
    "etf_weight_pct",
    "total_weight_pct",
    "sector",
    "industry",
    "country",
    "market_cap_tier",
    "beta",
    "etf_structure",
    "etf_domicile",
]

# Columns present in CompositionResult.etf_coverage DataFrame
COMPOSITION_COVERAGE_COLUMNS: list[str] = [
    "etf_isin",
    "coverage_pct",
    "as_of",
    "source",
    "is_stale",
]


@dataclass
class CompositionResult:
    securities: pd.DataFrame  # COMPOSITION_SECURITY_COLUMNS schema
    etf_coverage: pd.DataFrame  # COMPOSITION_COVERAGE_COLUMNS schema
    snapshot_date: str


def aggregate_portfolio_composition(
    holdings_df: pd.DataFrame,
    constituent_provider: ETFConstituentProvider,
    metadata_provider: YahooFinanceMetadataProvider,
    snapshot_date: str | None = None,
) -> CompositionResult:
    """Aggregate portfolio holdings into a look-through composition view.

    Expands ETF holdings into their constituent securities, sums direct and
    ETF-derived weights per ISIN, and attaches metadata (sector, country, etc.).
    Rows without a resolvable ISIN contribute to the '_UNRESOLVED_' residual row.

    holdings_df must contain: isin, market_value columns (in EUR).
    snapshot_date is used for ETF constituent staleness checks.
    """
    if not snapshot_date:
        snapshot_date = _date.today().isoformat()

    total_portfolio_eur = holdings_df["market_value"].sum()
    if total_portfolio_eur == 0:
        return CompositionResult(
            securities=pd.DataFrame(columns=COMPOSITION_SECURITY_COLUMNS),
            etf_coverage=pd.DataFrame(columns=COMPOSITION_COVERAGE_COLUMNS),
            snapshot_date=snapshot_date,
        )

    # Per-ISIN accumulators: {isin: {"direct_eur": float, "etf_eur": float, "name": str}}
    buckets: dict[str, dict] = {}
    unresolved_eur = 0.0
    coverage_rows: list[dict] = []

    def _ensure(isin: str, name: str = "") -> None:
        if isin not in buckets:
            buckets[isin] = {"direct_eur": 0.0, "etf_eur": 0.0, "name": name}

    for _, row in holdings_df.iterrows():
        isin = str(row["isin"])
        mv_eur = float(row["market_value"])
        name = str(row.get("asset_name", isin))

        # Try to expand as ETF
        try:
            constituents_result = constituent_provider.get_constituents(isin)
        except (KeyError, ValueError):
            # Not an ETF or no constituent data — treat as direct holding
            _ensure(isin, name)
            buckets[isin]["direct_eur"] += mv_eur
            continue

        # Record coverage info
        coverage_rows.append(
            {
                "etf_isin": isin,
                "coverage_pct": constituents_result.coverage_pct,
                "as_of": constituents_result.as_of,
                "source": constituents_result.source,
                "is_stale": constituents_result.is_stale(snapshot_date),
            }
        )

        # Expand constituents
        for c in constituents_result.constituents:
            if c.isin:
                _ensure(c.isin, c.name)
                buckets[c.isin]["etf_eur"] += mv_eur * c.weight
                if not buckets[c.isin]["name"]:
                    buckets[c.isin]["name"] = c.name
            else:
                unresolved_eur += mv_eur * c.weight

        # Unresolved residual for this ETF
        unresolved_eur += mv_eur * (1.0 - constituents_result.coverage_pct)

    # Add global unresolved row
    if unresolved_eur > 0:
        _ensure(_UNRESOLVED_ISIN, "Unresolved / other")
        buckets[_UNRESOLVED_ISIN]["etf_eur"] += unresolved_eur

    # Build securities DataFrame
    security_rows = []
    for isin, acc in buckets.items():
        direct_pct = acc["direct_eur"] / total_portfolio_eur * 100.0
        etf_pct = acc["etf_eur"] / total_portfolio_eur * 100.0
        total_pct = direct_pct + etf_pct

        meta_kwargs: dict = {
            "sector": None,
            "industry": None,
            "country": None,
            "market_cap_tier": "Unknown",
            "beta": None,
            "etf_structure": "unknown",
            "etf_domicile": None,
        }
        if isin != _UNRESOLVED_ISIN:
            with contextlib.suppress(KeyError, ValueError):
                meta = metadata_provider.get_metadata(isin)
                meta_kwargs = {
                    "sector": meta.sector,
                    "industry": meta.industry,
                    "country": meta.country,
                    "market_cap_tier": meta.market_cap_tier,
                    "beta": meta.beta,
                    "etf_structure": meta.etf_structure,
                    "etf_domicile": meta.etf_domicile,
                }

        security_rows.append(
            {
                "isin": isin,
                "name": acc["name"],
                "direct_weight_pct": round(direct_pct, 4),
                "etf_weight_pct": round(etf_pct, 4),
                "total_weight_pct": round(total_pct, 4),
                **meta_kwargs,
            }
        )

    securities_df = (
        pd.DataFrame(security_rows, columns=COMPOSITION_SECURITY_COLUMNS)
        .sort_values("total_weight_pct", ascending=False)
        .reset_index(drop=True)
    )

    coverage_df = (
        pd.DataFrame(coverage_rows, columns=COMPOSITION_COVERAGE_COLUMNS)
        if coverage_rows
        else pd.DataFrame(columns=COMPOSITION_COVERAGE_COLUMNS)
    )

    return CompositionResult(
        securities=securities_df,
        etf_coverage=coverage_df,
        snapshot_date=snapshot_date,
    )


# ── Dimension breakdown functions ──────────────────────────────────────────────

# Country → geographic region mapping (continent-level)
_COUNTRY_TO_REGION: dict[str, str] = {
    # North America
    "United States": "North America",
    "Canada": "North America",
    "Mexico": "North America",
    # Europe
    "Netherlands": "Europe",
    "Germany": "Europe",
    "France": "Europe",
    "United Kingdom": "Europe",
    "Switzerland": "Europe",
    "Sweden": "Europe",
    "Denmark": "Europe",
    "Finland": "Europe",
    "Norway": "Europe",
    "Spain": "Europe",
    "Italy": "Europe",
    "Belgium": "Europe",
    "Austria": "Europe",
    "Ireland": "Europe",
    "Luxembourg": "Europe",
    "Portugal": "Europe",
    "Poland": "Europe",
    "Czech Republic": "Europe",
    "Hungary": "Europe",
    "Romania": "Europe",
    "Greece": "Europe",
    # Asia-Pacific
    "Japan": "Asia-Pacific",
    "China": "Asia-Pacific",
    "South Korea": "Asia-Pacific",
    "Taiwan": "Asia-Pacific",
    "India": "Asia-Pacific",
    "Australia": "Asia-Pacific",
    "New Zealand": "Asia-Pacific",
    "Hong Kong": "Asia-Pacific",
    "Singapore": "Asia-Pacific",
    "Indonesia": "Asia-Pacific",
    "Thailand": "Asia-Pacific",
    "Malaysia": "Asia-Pacific",
    "Philippines": "Asia-Pacific",
    # Emerging / Other
    "Brazil": "Other",
    "South Africa": "Other",
    "Saudi Arabia": "Other",
    "United Arab Emirates": "Other",
    "Israel": "Other",
}

# ETF ISIN prefixes that indicate fund wrappers
_ETF_ISIN_PREFIXES: frozenset[str] = frozenset({"IE", "LU", "FR", "DE00ETF"})


def _group_by_dimension(df: pd.DataFrame, col: str) -> pd.DataFrame:
    """Sum total_weight_pct by a dimension column, filling None with 'Unknown'."""
    working = df.copy()
    working[col] = working[col].fillna("Unknown").replace("", "Unknown")
    result = (
        working.groupby(col, as_index=False)["total_weight_pct"]
        .sum()
        .rename(columns={col: "dimension_value", "total_weight_pct": "weight_pct"})
        .sort_values("weight_pct", ascending=False)
        .reset_index(drop=True)
    )
    return result


def breakdown_by_sector(securities_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate total_weight_pct by sector.  None → 'Unknown'."""
    return _group_by_dimension(securities_df, "sector")


def breakdown_by_industry(securities_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate total_weight_pct by industry.  None → 'Unknown'."""
    return _group_by_dimension(securities_df, "industry")


def breakdown_by_country(securities_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate total_weight_pct by country.  None → 'Unknown'."""
    return _group_by_dimension(securities_df, "country")


def breakdown_by_region(securities_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate total_weight_pct by geographic region (continent-level)."""
    working = securities_df.copy()
    working["region"] = working["country"].map(_COUNTRY_TO_REGION).fillna("Other")
    return (
        working.groupby("region", as_index=False)["total_weight_pct"]
        .sum()
        .rename(columns={"region": "dimension_value", "total_weight_pct": "weight_pct"})
        .sort_values("weight_pct", ascending=False)
        .reset_index(drop=True)
    )


def breakdown_by_currency(holdings_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate holdings market_value by currency, expressed as portfolio weight %.

    Takes the raw holdings DataFrame (not the securities DataFrame) since currency
    is a property of the holding itself, not the underlying security.
    """
    total = holdings_df["market_value"].sum()
    if total == 0:
        return pd.DataFrame(columns=["dimension_value", "weight_pct"])
    result = (
        holdings_df.groupby("currency", as_index=False)["market_value"]
        .sum()
        .rename(columns={"currency": "dimension_value", "market_value": "weight_pct"})
    )
    result["weight_pct"] = result["weight_pct"] / total * 100.0
    return result.sort_values("weight_pct", ascending=False).reset_index(drop=True)


def _classify_asset_class(isin: str) -> str:
    """Heuristic: ISINs starting with known ETF country prefixes are 'ETF'; else 'Equity'."""
    prefix2 = isin[:2].upper()
    if isin == _UNRESOLVED_ISIN:
        return "Unresolved"
    if prefix2 in {"IE", "LU"} or isin.startswith("DE000ETF"):
        return "ETF"
    return "Equity"


def breakdown_by_asset_class(securities_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate total_weight_pct by asset class (Equity / ETF / Unresolved)."""
    working = securities_df.copy()
    working["asset_class"] = working["isin"].apply(_classify_asset_class)
    return (
        working.groupby("asset_class", as_index=False)["total_weight_pct"]
        .sum()
        .rename(columns={"asset_class": "dimension_value", "total_weight_pct": "weight_pct"})
        .sort_values("weight_pct", ascending=False)
        .reset_index(drop=True)
    )


def breakdown_by_market_cap_tier(securities_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate total_weight_pct by market cap tier (Large / Mid / Small / Unknown)."""
    return _group_by_dimension(securities_df, "market_cap_tier")


# Beta bucket boundaries
_BETA_LOW = 0.8
_BETA_HIGH = 1.2
_BETA_LOW_LABEL = f"Low beta (<{_BETA_LOW}, vs S&P 500 (yfinance))"
_BETA_MARKET_LABEL = f"Market beta ({_BETA_LOW}–{_BETA_HIGH}, vs S&P 500 (yfinance))"
_BETA_HIGH_LABEL = f"High beta (>{_BETA_HIGH}, vs S&P 500 (yfinance))"
_BETA_UNKNOWN_LABEL = "Unknown beta"


def _beta_bucket(beta: float | None) -> str:
    if beta is None:
        return _BETA_UNKNOWN_LABEL
    if beta < _BETA_LOW:
        return _BETA_LOW_LABEL
    if beta <= _BETA_HIGH:
        return _BETA_MARKET_LABEL
    return _BETA_HIGH_LABEL


def breakdown_by_beta_bucket(securities_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate total_weight_pct by beta bucket vs S&P 500 (yfinance).

    Buckets: Low (<0.8), Market (0.8–1.2), High (>1.2), Unknown.
    All bucket labels include 'vs S&P 500 (yfinance)' as a reminder of the
    benchmark used.
    """
    working = securities_df.copy()
    working["beta_bucket"] = working["beta"].apply(_beta_bucket)
    return (
        working.groupby("beta_bucket", as_index=False)["total_weight_pct"]
        .sum()
        .rename(columns={"beta_bucket": "dimension_value", "total_weight_pct": "weight_pct"})
        .sort_values("weight_pct", ascending=False)
        .reset_index(drop=True)
    )


def breakdown_by_etf_structure(securities_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate total_weight_pct by ETF structure (accumulating / distributing / unknown)."""
    return _group_by_dimension(securities_df, "etf_structure")


def breakdown_by_etf_domicile(securities_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate total_weight_pct by ETF domicile (Ireland / Luxembourg / etc.)."""
    return _group_by_dimension(securities_df, "etf_domicile")


def fetch_current_prices(
    isins: list[str],
    provider: PriceProvider,
    date: str,
) -> dict[str, float]:
    """
    Fetch current prices in EUR for a list of ISINs using the given provider.

    ISINs that raise KeyError or ValueError from the provider are silently
    skipped — the caller should check for missing entries if needed.

    Returns dict[isin, price_eur].
    """
    prices: dict[str, float] = {}
    for isin in isins:
        with contextlib.suppress(KeyError, ValueError):
            prices[isin] = provider.price_eur(isin, date)
    return prices


# ── Lot engine ─────────────────────────────────────────────────────────────────


def apply_buy(
    lots: list[dict],
    isin: str,
    lot_date: str,
    lot_price_eur: float,
    shares: float,
) -> list[dict]:
    """
    Add a new lot for a buy transaction. Mutates and returns lots.

    lot_price_eur is the per-share acquisition cost in EUR (FX-converted
    before calling this function).
    """
    lots.append(
        {
            "isin": isin,
            "lot_date": lot_date,
            "lot_price_eur": lot_price_eur,
            "remaining_shares": shares,
        }
    )
    return lots


def apply_sell_fifo(
    lots: list[dict],
    isin: str,
    shares_to_sell: float,
    price_eur: float,
    tax_rate: float,
) -> tuple[list[dict], float, float]:
    """
    Consume lots in FIFO order for a sell transaction.

    price_eur is the per-share sale price in EUR.
    tax_rate is applied only to positive (gain) portions.

    Returns:
        (updated_lots, realised_gain_eur, tax_due_eur)

    Raises:
        ValueError if shares_to_sell exceeds available shares for this isin.
    """
    available = sum(lot["remaining_shares"] for lot in lots if lot["isin"] == isin)
    if shares_to_sell > available + 1e-9:
        raise ValueError(
            f"Cannot sell {shares_to_sell} shares of {isin}: only {available:.4f} available."
        )

    remaining_to_sell = shares_to_sell
    realised_gain = 0.0
    updated: list[dict] = []

    for lot in lots:
        if lot["isin"] != isin or remaining_to_sell <= 1e-9:
            updated.append(lot)
            continue

        consume = min(lot["remaining_shares"], remaining_to_sell)
        realised_gain += (price_eur - lot["lot_price_eur"]) * consume
        remaining_to_sell -= consume

        leftover = lot["remaining_shares"] - consume
        if leftover > 1e-9:
            updated_lot = dict(lot)
            updated_lot["remaining_shares"] = leftover
            updated.append(updated_lot)
        # Fully consumed lots are dropped

    tax_due = max(realised_gain, 0.0) * tax_rate
    return updated, realised_gain, tax_due


def apply_split(
    lots: list[dict],
    isin: str,
    ratio: float,
) -> list[dict]:
    """
    Apply a forward or reverse split to all open lots for the given security.

    ratio > 1: forward split (e.g. 2.0 for 2-for-1 — doubles shares, halves price)
    ratio < 1: reverse split (e.g. 0.5 for 1-for-2 — halves shares, doubles price)

    Total cost basis is preserved: lot_price_eur / ratio, remaining_shares * ratio.

    Fractional shares resulting from a reverse split are retained at full
    precision in v1. The caller is responsible for treating any fractional
    remainder as a cash distribution.

    Raises:
        ValueError if ratio is zero or negative.
    """
    if ratio <= 0:
        raise ValueError(f"Split ratio must be positive, got {ratio!r}.")

    updated: list[dict] = []
    for lot in lots:
        if lot["isin"] != isin:
            updated.append(lot)
            continue
        updated_lot = dict(lot)
        updated_lot["remaining_shares"] = lot["remaining_shares"] * ratio
        updated_lot["lot_price_eur"] = lot["lot_price_eur"] / ratio
        updated.append(updated_lot)

    return updated


def lots_to_dataframe(lots: list[dict]) -> pd.DataFrame:
    """Convert the lot ledger list to a DataFrame with LOT_COLUMNS schema."""
    if not lots:
        return pd.DataFrame(columns=LOT_COLUMNS)
    return pd.DataFrame(lots)[LOT_COLUMNS]


def fill_missing_prices_from_holdings(
    prices_eur: dict[str, float],
    hld_df: pd.DataFrame,
) -> dict[str, float]:
    """Return a copy of prices_eur with broker-implied prices added for missing ISINs.

    For each ISIN in hld_df absent from prices_eur, the implied price is
    market_value / quantity (the broker's reported current price). Positions with
    zero quantity are skipped. Existing prices are never overwritten — live prices
    always take precedence over broker-reported prices.
    """
    result = dict(prices_eur)
    for _, row in hld_df.iterrows():
        isin = row["isin"]
        if isin in result:
            continue
        qty = float(row["quantity"])
        if qty == 0.0:
            continue
        result[isin] = float(row["market_value"]) / qty
    return result


def initialize_lots_from_holdings(hld_df: pd.DataFrame) -> pd.DataFrame:
    """
    Seed the lot ledger from a holdings DataFrame that includes cost_basis_eur.

    This is the fast path for starting a simulation from a broker statement
    snapshot rather than replaying the full transaction history.  Each holding
    row becomes one lot entry; rows with zero quantity or a missing cost basis
    are dropped (they carry no cost information useful for gain/loss tracking).

    Parameters
    ----------
    hld_df : pd.DataFrame
        Holdings DataFrame, typically produced by ``parse_db_pdf``.  Must
        contain columns: ``date``, ``isin``, ``quantity``, ``cost_basis_eur``.

    Returns
    -------
    pd.DataFrame
        Lot ledger with LOT_COLUMNS: ``isin``, ``lot_date``,
        ``lot_price_eur``, ``remaining_shares``.

    Raises
    ------
    KeyError
        If ``cost_basis_eur`` is not present in *hld_df*.
    """
    # Validate presence of required column (raises KeyError on miss)
    _ = hld_df["cost_basis_eur"]

    if hld_df.empty:
        return pd.DataFrame(columns=LOT_COLUMNS)

    df = hld_df[["date", "isin", "quantity", "cost_basis_eur"]].copy()
    df = df[df["quantity"] > 0]
    df = df[df["cost_basis_eur"].notna()]

    lots = pd.DataFrame(
        {
            "isin": df["isin"].values,
            "lot_date": df["date"].values,
            "lot_price_eur": df["cost_basis_eur"].values,
            "remaining_shares": df["quantity"].values,
        }
    )
    return lots.reset_index(drop=True)


# ── Reconciliation ─────────────────────────────────────────────────────────────


def derive_holdings_from_lots(lots: list[dict]) -> pd.DataFrame:
    """
    Aggregate the lot ledger to a per-security holdings summary.

    Returns a DataFrame with columns: isin, quantity.
    """
    if not lots:
        return pd.DataFrame(columns=["isin", "quantity"])
    df = pd.DataFrame(lots)
    return (
        df.groupby("isin", as_index=False)["remaining_shares"]
        .sum()
        .rename(columns={"remaining_shares": "quantity"})
    )


def reconcile_holdings(
    lot_holdings: pd.DataFrame,
    broker_holdings: pd.DataFrame,
    tolerance: float = 0.001,
) -> pd.DataFrame:
    """
    Compare transaction-derived holdings against a broker snapshot.

    Both DataFrames must have columns: isin, quantity.

    Returns a DataFrame with columns:
        isin, derived_quantity, broker_quantity, difference, status

    status values:
        'match'        — difference ≤ tolerance
        'mismatch'     — difference > tolerance
        'derived_only' — security exists in derived holdings but not broker
        'broker_only'  — security exists in broker snapshot but not derived
    """
    derived = lot_holdings[["isin", "quantity"]].rename(columns={"quantity": "derived_quantity"})
    broker = broker_holdings[["isin", "quantity"]].rename(columns={"quantity": "broker_quantity"})
    merged = derived.merge(broker, on="isin", how="outer")
    merged["derived_quantity"] = merged["derived_quantity"].fillna(0.0)
    merged["broker_quantity"] = merged["broker_quantity"].fillna(0.0)
    merged["difference"] = merged["derived_quantity"] - merged["broker_quantity"]

    def _status(row: pd.Series) -> str:
        if row["derived_quantity"] == 0 and row["broker_quantity"] != 0:
            return "broker_only"
        if row["broker_quantity"] == 0 and row["derived_quantity"] != 0:
            return "derived_only"
        if abs(row["difference"]) <= tolerance:
            return "match"
        return "mismatch"

    merged["status"] = merged.apply(_status, axis=1)
    return merged


# ── Unsupported corporate actions ──────────────────────────────────────────────


class UnsupportedCorporateAction(Exception):
    """
    Raised when transactions contain types that the simulation cannot model.

    Unsupported types: merger, spin_off, option.

    Use simulate_portfolio_partial() to obtain results that exclude the
    affected securities and return the excluded ISINs as a warning list.
    """


def check_unsupported_actions(transactions: pd.DataFrame) -> list[str]:
    """
    Return a sorted list of ISINs affected by unsupported corporate actions.

    An empty list means all transactions are supported.
    """
    mask = transactions["transaction_type"].isin(UNSUPPORTED_TRANSACTION_TYPES)
    return sorted(transactions.loc[mask, "isin"].dropna().unique().tolist())


# ── Simulation ─────────────────────────────────────────────────────────────────


def simulate_portfolio(
    transactions: pd.DataFrame,
    current_prices_eur: dict[str, float],
    capital_gains_tax_rate: float,
    dividend_tax_rate: float,
    fx_provider: FXProvider | None = None,
    lot_method: Literal["fifo"] = "fifo",
    reporting_date: str | None = None,
) -> pd.DataFrame:
    """
    Replay transactions in chronological order, maintain a FIFO lot ledger,
    and produce a portfolio simulation output in SIMULATION_OUTPUT_COLUMNS.

    current_prices_eur: map of isin → current price in EUR.
    capital_gains_tax_rate: flat rate applied to realised capital gains.
    dividend_tax_rate: flat rate applied to dividend income.
    fx_provider: if None, defaults to ECBProvider.
    lot_method: only 'fifo' is supported in v1.
    reporting_date: ISO date string for the output row; defaults to the
        latest transaction date.

    Raises:
        UnsupportedCorporateAction if any transaction type is unsupported.
            Use simulate_portfolio_partial() instead.
        ValueError if lot_method is not 'fifo'.

    Known limitations (v1):
        - Flat tax rates only; Sparer-Pauschbetrag and solidarity surcharge
          are not modelled.
        - Fractional shares from reverse splits are retained at full precision;
          no cash distribution is generated.
    """
    if lot_method != "fifo":
        raise ValueError(f"Lot method {lot_method!r} is not supported in v1. Use 'fifo'.")

    if fx_provider is None:
        fx_provider = ECBProvider()

    unsupported = check_unsupported_actions(transactions)
    if unsupported:
        raise UnsupportedCorporateAction(
            f"Unsupported corporate actions for: {unsupported}. "
            "Call simulate_portfolio_partial() to exclude them."
        )

    lots: list[dict] = []
    realised_gain: dict[str, float] = {}
    tax_paid: dict[str, float] = {}

    txns = transactions.sort_values("date").reset_index(drop=True)

    for _, row in txns.iterrows():
        isin = row["isin"]
        tx_type = row["transaction_type"]
        currency = str(row["currency"])
        date = str(row["date"])

        realised_gain.setdefault(isin, 0.0)
        tax_paid.setdefault(isin, 0.0)

        if tx_type == "buy":
            price_eur = fx_provider.convert(float(row["price"]), currency, "EUR", date)
            apply_buy(lots, isin, date, price_eur, float(row["quantity"]))

        elif tx_type == "sell":
            price_eur = fx_provider.convert(float(row["price"]), currency, "EUR", date)
            lots, gain, tax = apply_sell_fifo(
                lots, isin, float(row["quantity"]), price_eur, capital_gains_tax_rate
            )
            realised_gain[isin] += gain
            tax_paid[isin] += tax

        elif tx_type == "split":
            # quantity field carries the split ratio (e.g. 2.0 for 2-for-1)
            lots = apply_split(lots, isin, float(row["quantity"]))

        elif tx_type == "dividend":
            amount_eur = fx_provider.convert(float(row["amount"]), currency, "EUR", date)
            dividend_tax = amount_eur * dividend_tax_rate
            realised_gain[isin] += amount_eur
            tax_paid[isin] += dividend_tax

        elif tx_type == "tax_withheld":
            # Broker-withheld tax already paid — track against this security
            withheld = fx_provider.convert(abs(float(row["tax_withheld"])), currency, "EUR", date)
            tax_paid[isin] += withheld

        # fee, transfer_in, transfer_out: no lot or P&L effect in v1

    if reporting_date is None:
        reporting_date = str(txns["date"].max())

    all_isins = sorted(set(current_prices_eur) | set(realised_gain))
    rows = []
    for isin in all_isins:
        current_price = current_prices_eur.get(isin, 0.0)
        isin_lots = [lot for lot in lots if lot["isin"] == isin]
        total_shares = sum(lot["remaining_shares"] for lot in isin_lots)
        total_cost_basis = sum(lot["lot_price_eur"] * lot["remaining_shares"] for lot in isin_lots)
        market_value = current_price * total_shares
        unrealised_gain = market_value - total_cost_basis

        rows.append(
            {
                "isin": isin,
                "reporting_date": reporting_date,
                "market_value_eur": round(market_value, 2),
                "unrealised_gain_eur": round(unrealised_gain, 2),
                "realised_gain_ytd_eur": round(realised_gain.get(isin, 0.0), 2),
                "tax_paid_ytd_eur": round(tax_paid.get(isin, 0.0), 2),
            }
        )

    return pd.DataFrame(rows, columns=SIMULATION_OUTPUT_COLUMNS)


def simulate_portfolio_partial(
    transactions: pd.DataFrame,
    current_prices_eur: dict[str, float],
    capital_gains_tax_rate: float,
    dividend_tax_rate: float,
    fx_provider: FXProvider | None = None,
    lot_method: Literal["fifo"] = "fifo",
    reporting_date: str | None = None,
) -> tuple[pd.DataFrame, list[str]]:
    """
    Like simulate_portfolio(), but excludes securities affected by unsupported
    corporate actions rather than raising UnsupportedCorporateAction.

    Returns:
        (simulation_result, excluded_isins)

    The caller must surface excluded_isins as a warning. Results do not
    include excluded securities — totals are partial and must not be
    presented as complete portfolio values.
    """
    excluded = check_unsupported_actions(transactions)

    if excluded:
        filtered_txns = transactions[~transactions["isin"].isin(excluded)].copy()
        filtered_prices = {k: v for k, v in current_prices_eur.items() if k not in excluded}
    else:
        filtered_txns = transactions
        filtered_prices = current_prices_eur

    result = simulate_portfolio(
        filtered_txns,
        filtered_prices,
        capital_gains_tax_rate,
        dividend_tax_rate,
        fx_provider=fx_provider,
        lot_method=lot_method,
        reporting_date=reporting_date,
    )

    return result, excluded


def simulate_from_snapshot(
    initial_lots: pd.DataFrame | list[dict],
    new_transactions: pd.DataFrame | list,
    current_prices_eur: dict[str, float],
    capital_gains_tax_rate: float,
    dividend_tax_rate: float,
    fx_provider: FXProvider | None = None,
    reporting_date: str | None = None,
) -> pd.DataFrame:
    """
    Simulate a portfolio starting from a pre-seeded lot ledger (snapshot mode).

    Use this when you have a broker statement with cost-basis data — seed the
    lot ledger with ``initialize_lots_from_holdings``, pass only the *new*
    transactions that occurred after the statement date, and compute current
    portfolio value and gains.

    Parameters
    ----------
    initial_lots : pd.DataFrame | list[dict]
        Starting lot ledger in LOT_COLUMNS schema.  Typically produced by
        ``initialize_lots_from_holdings``.  Both DataFrame and list-of-dicts
        are accepted.
    new_transactions : pd.DataFrame
        Transactions to replay on top of the snapshot (may be empty).
        Must conform to TRANSACTION_COLUMNS schema.  Only ``buy``, ``sell``,
        ``split``, ``dividend``, and ``tax_withheld`` have lot/P&L effects;
        other types are silently ignored, consistent with ``simulate_portfolio``.
    current_prices_eur : dict[str, float]
        Map of ISIN → current price in EUR.  ISINs absent from this dict
        *and* from any realised gain accumulation are omitted from the output.
    capital_gains_tax_rate : float
        Flat rate applied to realised capital gains (e.g. 0.26375 for Germany).
    dividend_tax_rate : float
        Flat rate applied to dividend income.
    fx_provider : FXProvider | None
        Defaults to ECBProvider if None.
    reporting_date : str | None
        ISO date for the output rows.  Defaults to the latest new transaction
        date, or today's date if new_transactions is empty.

    Returns
    -------
    pd.DataFrame
        SIMULATION_OUTPUT_COLUMNS schema — one row per ISIN that appears in
        current_prices_eur or has realised gain/income.
    """
    if fx_provider is None:
        fx_provider = ECBProvider()

    # Normalise initial_lots to a mutable list[dict]
    if isinstance(initial_lots, pd.DataFrame):
        lots: list[dict] = initial_lots[LOT_COLUMNS].to_dict(orient="records")
    else:
        lots = [dict(lot) for lot in initial_lots]

    realised_gain: dict[str, float] = {}
    tax_paid: dict[str, float] = {}

    if isinstance(new_transactions, list):
        new_transactions = pd.DataFrame(new_transactions)

    if not new_transactions.empty:
        txns = new_transactions.sort_values("date").reset_index(drop=True)
        for _, row in txns.iterrows():
            isin = row["isin"]
            tx_type = row["transaction_type"]
            currency = str(row["currency"])
            date = str(row["date"])

            realised_gain.setdefault(isin, 0.0)
            tax_paid.setdefault(isin, 0.0)

            if tx_type == "buy":
                price_eur = fx_provider.convert(float(row["price"]), currency, "EUR", date)
                apply_buy(lots, isin, date, price_eur, float(row["quantity"]))

            elif tx_type == "sell":
                price_eur = fx_provider.convert(float(row["price"]), currency, "EUR", date)
                lots, gain, tax = apply_sell_fifo(
                    lots, isin, float(row["quantity"]), price_eur, capital_gains_tax_rate
                )
                realised_gain[isin] += gain
                tax_paid[isin] += tax

            elif tx_type == "split":
                lots = apply_split(lots, isin, float(row["quantity"]))

            elif tx_type == "dividend":
                amount_eur = fx_provider.convert(float(row["amount"]), currency, "EUR", date)
                dividend_tax = amount_eur * dividend_tax_rate
                realised_gain[isin] += amount_eur
                tax_paid[isin] += dividend_tax

            elif tx_type == "tax_withheld":
                withheld = fx_provider.convert(
                    abs(float(row["tax_withheld"])), currency, "EUR", date
                )
                tax_paid[isin] += withheld

        if reporting_date is None:
            reporting_date = str(txns["date"].max())
    else:
        txns = None

    if reporting_date is None:
        from datetime import date as _date

        reporting_date = _date.today().isoformat()

    all_isins = sorted(set(current_prices_eur) | set(realised_gain))
    rows = []
    for isin in all_isins:
        current_price = current_prices_eur.get(isin, 0.0)
        isin_lots = [lot for lot in lots if lot["isin"] == isin]
        total_shares = sum(lot["remaining_shares"] for lot in isin_lots)
        total_cost_basis = sum(lot["lot_price_eur"] * lot["remaining_shares"] for lot in isin_lots)
        market_value = current_price * total_shares
        unrealised_gain = market_value - total_cost_basis

        rows.append(
            {
                "isin": isin,
                "reporting_date": reporting_date,
                "market_value_eur": round(market_value, 2),
                "unrealised_gain_eur": round(unrealised_gain, 2),
                "realised_gain_ytd_eur": round(realised_gain.get(isin, 0.0), 2),
                "tax_paid_ytd_eur": round(tax_paid.get(isin, 0.0), 2),
            }
        )

    return pd.DataFrame(rows, columns=SIMULATION_OUTPUT_COLUMNS)
