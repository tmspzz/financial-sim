"""Tests for scripts/import_etf_holdings.py parsing functions."""

import io
import json
from pathlib import Path

import pandas as pd
import pytest

# ── Helpers to build synthetic source files ───────────────────────────────────


def _make_ishares_csv(rows: list[dict]) -> str:
    """Build a minimal iShares CSV string (2-line header, then data rows)."""
    lines = ['Fund Holdings as of,"04/Jun/2026"', ""]
    header = (
        "Ticker,Name,Sector,Asset Class,Market Value,Weight (%),"
        "Notional Value,Shares,Price,Location,Exchange,Market Currency"
    )
    lines.append(header)
    for r in rows:
        lines.append(
            f'"{r["Ticker"]}","{r["Name"]}","{r["Sector"]}","{r["AssetClass"]}",'
            f'"{r["MarketValue"]}","{r["Weight"]}",'
            f'"0","0","0","{r.get("Location", "US")}","NASDAQ","USD"'
        )
    return "\n".join(lines)


def _make_dws_xlsx(rows: list[dict], sheet_name: str = "2026-06-07") -> bytes:
    """Build a minimal DWS constituent XLSX in memory."""
    disclaimer = (
        "Although information in this document has been obtained from sources "
        "believed to be reliable, DWS does not guarantee its accuracy."
    )
    header_row = {
        "Unnamed: 0": None,
        "Unnamed: 1": "Name",
        "Unnamed: 2": "ISIN",
        "Unnamed: 3": "Country",
        "Unnamed: 4": "Currency",
        "Unnamed: 5": "Exchange",
        "Unnamed: 6": "Type of Security",
        "Unnamed: 7": "Rating",
        "Unnamed: 8": "Primary Listing",
        "Unnamed: 9": "Industry Classification",
        "Unnamed: 10": "Weighting",
    }
    data_rows = [
        {
            "Unnamed: 0": i + 1,
            "Unnamed: 1": r["Name"],
            "Unnamed: 2": r["ISIN"],
            "Unnamed: 3": r.get("Country", "Japan"),
            "Unnamed: 4": r.get("Currency", "JPY"),
            "Unnamed: 5": r.get("Exchange", "-"),
            "Unnamed: 6": r.get("TypeOfSecurity", "Equities"),
            "Unnamed: 7": "-",
            "Unnamed: 8": "-",
            "Unnamed: 9": r.get("Sector", "Financials"),
            "Unnamed: 10": r["Weighting"],
        }
        for i, r in enumerate(rows)
    ]
    df_to_write = pd.DataFrame(
        [{"Unnamed: 0": disclaimer, **{k: None for k in list(header_row.keys())[1:]}}]
        + [{"Unnamed: 0": None, **{k: None for k in list(header_row.keys())[1:]}}]
        + [header_row]
        + data_rows
    )
    buf = io.BytesIO()
    df_to_write.to_excel(buf, sheet_name=sheet_name, index=False)
    return buf.getvalue()


def _make_vanguard_xlsx(rows: list[dict], as_of: str = "30 Apr 2026") -> bytes:
    """Build a minimal Vanguard holdings XLSX in memory."""
    meta_rows = [
        {
            "c0": "This file was downloaded on 07 Jun 2026",
            "c1": None,
            "c2": None,
            "c3": None,
            "c4": None,
            "c5": None,
            "c6": None,
        },
        {k: None for k in ["c0", "c1", "c2", "c3", "c4", "c5", "c6"]},
        {
            "c0": "Holdings details",
            "c1": None,
            "c2": None,
            "c3": None,
            "c4": None,
            "c5": None,
            "c6": None,
        },
        {
            "c0": "Vanguard FTSE Developed Europe UCITS ETF (EUR) Distributing",
            "c1": None,
            "c2": None,
            "c3": None,
            "c4": None,
            "c5": None,
            "c6": None,
        },
        {
            "c0": f"As at {as_of}",
            "c1": None,
            "c2": None,
            "c3": None,
            "c4": None,
            "c5": None,
            "c6": None,
        },
        {
            "c0": "Ticker",
            "c1": "Holding name",
            "c2": "% of market value",
            "c3": "Sector",
            "c4": "Region",
            "c5": "Market value",
            "c6": "Shares",
        },
    ]
    data_rows = [
        {
            "c0": r["Ticker"],
            "c1": r["Name"],
            "c2": r["Weight"],
            "c3": r.get("Sector", "Technology"),
            "c4": r.get("Region", "NL"),
            "c5": f"€{r.get('MarketValue', '0')}",
            "c6": r.get("Shares", 0),
        }
        for r in rows
    ]
    all_rows = meta_rows + data_rows
    df = pd.DataFrame([{f"Unnamed: {i}": row[f"c{i}"] for i in range(7)} for row in all_rows])
    buf = io.BytesIO()
    df.to_excel(buf, sheet_name="Holdings details", index=False)
    return buf.getvalue()


# ── Imports (will fail until script is written) ────────────────────────────────


@pytest.fixture(autouse=True)
def _import_script(monkeypatch):
    """Make the scripts/ directory importable."""
    import sys

    scripts_dir = str(Path(__file__).parent.parent / "scripts")
    if scripts_dir not in sys.path:
        monkeypatch.syspath_prepend(scripts_dir)


def _import_module():
    import importlib

    return importlib.import_module("import_etf_holdings")


# ── iShares CSV parsing ────────────────────────────────────────────────────────


class TestParseIsharesCSV:
    def test_returns_equity_rows_only(self, tmp_path):
        m = _import_module()
        csv_text = _make_ishares_csv(
            [
                {
                    "Ticker": "NVDA",
                    "Name": "NVIDIA CORP",
                    "Sector": "IT",
                    "AssetClass": "Equity",
                    "MarketValue": "500000",
                    "Weight": "8.43",
                },
                {
                    "Ticker": "CASH",
                    "Name": "USD CASH",
                    "Sector": "-",
                    "AssetClass": "MoneyMarket",
                    "MarketValue": "1000",
                    "Weight": "0.02",
                },
            ]
        )
        path = tmp_path / "holdings.csv"
        path.write_text(csv_text)
        rows, as_of = m.parse_ishares_csv(path)
        assert len(rows) == 1
        assert rows[0]["ticker"] == "NVDA"

    def test_weight_converted_to_fraction(self, tmp_path):
        m = _import_module()
        csv_text = _make_ishares_csv(
            [
                {
                    "Ticker": "AAPL",
                    "Name": "APPLE INC",
                    "Sector": "IT",
                    "AssetClass": "Equity",
                    "MarketValue": "100",
                    "Weight": "7.25",
                },
            ]
        )
        path = tmp_path / "holdings.csv"
        path.write_text(csv_text)
        rows, _ = m.parse_ishares_csv(path)
        assert abs(rows[0]["weight"] - 0.0725) < 1e-6

    def test_as_of_date_parsed(self, tmp_path):
        m = _import_module()
        csv_text = _make_ishares_csv(
            [
                {
                    "Ticker": "MSFT",
                    "Name": "MSFT",
                    "Sector": "IT",
                    "AssetClass": "Equity",
                    "MarketValue": "100",
                    "Weight": "5.0",
                },
            ]
        )
        path = tmp_path / "holdings.csv"
        path.write_text(csv_text)
        _, as_of = m.parse_ishares_csv(path)
        assert as_of == "2026-06-04"

    def test_skips_zero_weight_rows(self, tmp_path):
        m = _import_module()
        csv_text = _make_ishares_csv(
            [
                {
                    "Ticker": "NVDA",
                    "Name": "NVIDIA CORP",
                    "Sector": "IT",
                    "AssetClass": "Equity",
                    "MarketValue": "500",
                    "Weight": "5.0",
                },
                {
                    "Ticker": "NQM6",
                    "Name": "NASDAQ FUTURE",
                    "Sector": "-",
                    "AssetClass": "Equity",
                    "MarketValue": "0",
                    "Weight": "0.0",
                },
            ]
        )
        path = tmp_path / "holdings.csv"
        path.write_text(csv_text)
        rows, _ = m.parse_ishares_csv(path)
        assert all(r["weight"] > 0 for r in rows)


# ── DWS XLSX parsing ───────────────────────────────────────────────────────────


class TestParseDwsXlsx:
    def test_returns_rows_with_isin_and_weight(self, tmp_path):
        m = _import_module()
        xlsx = _make_dws_xlsx(
            [
                {"Name": "MITSUBISHI UFJ", "ISIN": "JP3902900004", "Weighting": 0.041478},
                {"Name": "TOYOTA MOTOR", "ISIN": "JP3633400001", "Weighting": 0.032966},
            ]
        )
        path = tmp_path / "fund.xlsx"
        path.write_bytes(xlsx)
        rows, as_of = m.parse_dws_xlsx(path)
        assert len(rows) == 2
        assert rows[0]["isin"] == "JP3902900004"
        assert abs(rows[0]["weight"] - 0.041478) < 1e-8

    def test_weight_already_fraction(self, tmp_path):
        m = _import_module()
        xlsx = _make_dws_xlsx([{"Name": "TSMC", "ISIN": "TW0002330008", "Weighting": 0.14745}])
        path = tmp_path / "fund.xlsx"
        path.write_bytes(xlsx)
        rows, _ = m.parse_dws_xlsx(path)
        assert abs(rows[0]["weight"] - 0.14745) < 1e-8

    def test_as_of_from_sheet_name(self, tmp_path):
        m = _import_module()
        xlsx = _make_dws_xlsx(
            [{"Name": "X", "ISIN": "JP0000000001", "Weighting": 0.01}], sheet_name="2026-06-07"
        )
        path = tmp_path / "fund.xlsx"
        path.write_bytes(xlsx)
        _, as_of = m.parse_dws_xlsx(path)
        assert as_of == "2026-06-07"

    def test_filters_non_equity_rows(self, tmp_path):
        m = _import_module()
        xlsx = _make_dws_xlsx(
            [
                {
                    "Name": "TOYOTA",
                    "ISIN": "JP3633400001",
                    "Weighting": 0.03,
                    "TypeOfSecurity": "Equities",
                },
                {
                    "Name": "JGB",
                    "ISIN": "JP1300011E31",
                    "Weighting": 0.02,
                    "TypeOfSecurity": "Bonds",
                },
            ]
        )
        path = tmp_path / "fund.xlsx"
        path.write_bytes(xlsx)
        rows, _ = m.parse_dws_xlsx(path)
        assert len(rows) == 1
        assert rows[0]["name"] == "TOYOTA"


# ── Vanguard XLSX parsing ──────────────────────────────────────────────────────


class TestParseVanguardXlsx:
    def test_returns_rows_with_ticker_and_weight(self, tmp_path):
        m = _import_module()
        xlsx = _make_vanguard_xlsx(
            [
                {"Ticker": "ASML", "Name": "ASML Holding NV", "Weight": "3.8514%", "Region": "NL"},
                {
                    "Ticker": "HSBA",
                    "Name": "HSBC Holdings PLC",
                    "Weight": "2.1793%",
                    "Region": "GB",
                },
            ]
        )
        path = tmp_path / "vanguard.xlsx"
        path.write_bytes(xlsx)
        rows, as_of = m.parse_vanguard_xlsx(path)
        assert len(rows) == 2
        assert rows[0]["ticker"] == "ASML"
        assert abs(rows[0]["weight"] - 0.038514) < 1e-6

    def test_as_of_date_parsed(self, tmp_path):
        m = _import_module()
        xlsx = _make_vanguard_xlsx(
            [{"Ticker": "ASML", "Name": "ASML", "Weight": "1.0%", "Region": "NL"}]
        )
        path = tmp_path / "vanguard.xlsx"
        path.write_bytes(xlsx)
        _, as_of = m.parse_vanguard_xlsx(path)
        assert as_of == "2026-04-30"

    def test_skips_zero_weight_and_footer_rows(self, tmp_path):
        m = _import_module()
        xlsx = _make_vanguard_xlsx(
            [
                {"Ticker": "ASML", "Name": "ASML", "Weight": "3.0%", "Region": "NL"},
                {"Ticker": "DLN", "Name": "Derwent", "Weight": "0.00%", "Region": "GB"},
            ]
        )
        path = tmp_path / "vanguard.xlsx"
        path.write_bytes(xlsx)
        rows, _ = m.parse_vanguard_xlsx(path)
        assert len(rows) == 1
        assert rows[0]["ticker"] == "ASML"

    def test_region_preserved_in_rows(self, tmp_path):
        m = _import_module()
        xlsx = _make_vanguard_xlsx(
            [
                {"Ticker": "ASML", "Name": "ASML", "Weight": "3.0%", "Region": "NL"},
            ]
        )
        path = tmp_path / "vanguard.xlsx"
        path.write_bytes(xlsx)
        rows, _ = m.parse_vanguard_xlsx(path)
        assert rows[0]["region"] == "NL"


# ── Cache file writing ─────────────────────────────────────────────────────────


class TestBuildAndWriteCache:
    def test_cache_file_written_to_correct_path(self, tmp_path):
        m = _import_module()
        rows = [
            {"isin": "JP3902900004", "ticker": None, "name": "MITSUBISHI UFJ", "weight": 0.041478}
        ]
        m.write_cache_json(tmp_path, "LU0274209740", rows, "2026-06-07", "user_provided_file")
        cache_file = tmp_path / "LU0274209740.json"
        assert cache_file.exists()

    def test_cache_json_structure(self, tmp_path):
        m = _import_module()
        rows = [
            {"isin": "JP3902900004", "ticker": None, "name": "MITSUBISHI UFJ", "weight": 0.041478},
            {"isin": "JP3571400005", "ticker": None, "name": "TOKYO ELECTRON", "weight": 0.034959},
        ]
        m.write_cache_json(tmp_path, "LU0274209740", rows, "2026-06-07", "user_provided_file")
        data = json.loads((tmp_path / "LU0274209740.json").read_text())
        assert data["etf_isin"] == "LU0274209740"
        assert data["as_of"] == "2026-06-07"
        assert data["source"] == "user_provided_file"
        assert len(data["constituents"]) == 2
        assert data["constituents"][0]["isin"] == "JP3902900004"
        assert abs(data["constituents"][0]["weight"] - 0.041478) < 1e-8
        # coverage_pct should reflect fraction of weight with resolved ISINs
        assert data["coverage_pct"] > 0

    def test_coverage_pct_is_isin_resolved_weight(self, tmp_path):
        m = _import_module()
        rows = [
            {"isin": "JP3902900004", "ticker": "8306.T", "name": "MUFG", "weight": 0.04},
            {"isin": None, "ticker": "UNKNOWN", "name": "UNRESOLVED CO", "weight": 0.01},
        ]
        m.write_cache_json(tmp_path, "LU0274209740", rows, "2026-06-07", "user_provided_file")
        data = json.loads((tmp_path / "LU0274209740.json").read_text())
        # coverage_pct is a FRACTION (0-1), matching portfolio_sim.ConstituentResult convention.
        # 0.04 / (0.04 + 0.01) = 0.80
        assert abs(data["coverage_pct"] - 0.80) < 0.001

    def test_coverage_pct_treats_dash_isin_as_unresolved(self, tmp_path):
        """ISIN='-' (yfinance failure) must NOT count toward coverage."""
        m = _import_module()
        rows = [
            {"isin": "JP3902900004", "ticker": "8306.T", "name": "MUFG", "weight": 0.04},
            {"isin": "-", "ticker": "NVDA", "name": "NVIDIA CORP", "weight": 0.08},
        ]
        m.write_cache_json(tmp_path, "LU0274209740", rows, "2026-06-07", "user_provided_file")
        data = json.loads((tmp_path / "LU0274209740.json").read_text())
        # coverage_pct is a fraction: only MUFG (0.04) counted; NVDA '-' is invalid
        # 0.04 / 0.12 ≈ 0.333
        assert abs(data["coverage_pct"] - (0.04 / 0.12)) < 0.001
        # The stored ISIN for NVDA must be null, not '-'
        nvda_row = next(c for c in data["constituents"] if c["ticker"] == "NVDA")
        assert nvda_row["isin"] is None


# ── ISIN validation ────────────────────────────────────────────────────────────


class TestValidateIsin:
    def test_valid_isin_passes_through(self):
        m = _import_module()
        assert m._validate_isin("US67066G1040") == "US67066G1040"

    def test_dash_returns_none(self):
        m = _import_module()
        assert m._validate_isin("-") is None

    def test_none_returns_none(self):
        m = _import_module()
        assert m._validate_isin(None) is None

    def test_wrong_format_returns_none(self):
        m = _import_module()
        assert m._validate_isin("not_an_isin") is None

    def test_too_short_returns_none(self):
        m = _import_module()
        assert m._validate_isin("US1234") is None


# ── ISIN supplement for yfinance failures ─────────────────────────────────────


class TestIsInSupplement:
    def test_supplement_covers_major_nasdaq100_tickers(self):
        m = _import_module()
        for ticker in ("NVDA", "MSFT", "AMZN", "TSLA", "CSCO", "INTC"):
            assert ticker in m._NASDAQ100_ISIN_SUPPLEMENT, f"{ticker} missing from supplement"

    def test_supplement_isins_are_valid_format(self):
        m = _import_module()
        for ticker, isin in m._NASDAQ100_ISIN_SUPPLEMENT.items():
            assert m._validate_isin(isin) == isin, f"{ticker}: {isin!r} is not a valid ISIN"

    def test_resolve_isins_uses_supplement_when_yfinance_returns_dash(self, monkeypatch):
        """When yfinance returns '-', resolve_isins should fall back to supplement."""
        import sys

        scripts_dir = str(Path(__file__).parent.parent / "scripts")
        if scripts_dir not in sys.path:
            monkeypatch.syspath_prepend(scripts_dir)
        m = _import_module()

        # Patch yfinance to return '-' for every ticker
        import types

        fake_yf = types.ModuleType("yfinance")

        class _FakeTicker:
            def __init__(self, t):
                pass

            @property
            def isin(self):
                return "-"

        fake_yf.Ticker = _FakeTicker
        monkeypatch.setitem(sys.modules, "yfinance", fake_yf)

        rows = [{"ticker": "NVDA", "name": "NVIDIA CORP", "weight": 0.0843, "isin": None}]
        # Clear cache so the patched yfinance is actually called
        m._isin_cache.clear()
        result = m.resolve_isins(rows)
        assert result[0]["isin"] == "US67066G1040"

    def test_resolve_isins_validates_yfinance_result(self, monkeypatch):
        """A syntactically valid-looking but wrong ISIN from yfinance should pass through."""
        import sys

        scripts_dir = str(Path(__file__).parent.parent / "scripts")
        if scripts_dir not in sys.path:
            monkeypatch.syspath_prepend(scripts_dir)
        m = _import_module()

        import types

        fake_yf = types.ModuleType("yfinance")

        class _FakeTicker:
            def __init__(self, t):
                self._t = t

            @property
            def isin(self):
                return "JP3902900004"  # valid format, returned for any ticker

        fake_yf.Ticker = _FakeTicker
        monkeypatch.setitem(sys.modules, "yfinance", fake_yf)

        rows = [{"ticker": "UNKNWN", "name": "UNKNOWN CO", "weight": 0.01, "isin": None}]
        m._isin_cache.clear()
        result = m.resolve_isins(rows)
        # yfinance returned a valid-format ISIN — should be kept as-is
        assert result[0]["isin"] == "JP3902900004"
