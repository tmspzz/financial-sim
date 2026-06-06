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
from abc import ABC, abstractmethod
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
    uses ticker symbols, not ISINs.  For EUR-listed tickers (e.g. "EXXT.DE")
    the price is returned directly in EUR. For non-EUR tickers (e.g. "AAPL"
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
            EUR-listed examples : "EXXT.DE", "ASML.AS", "AXP.DE"
            USD-listed examples : "AAPL", "MSFT", "NVDA"
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
