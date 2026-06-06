"""
Tests for the Deutsche Bank PDF parser (src/pdf_parser.py).

Unit tests use hardcoded text fixtures (no PDF file needed).
Integration tests run only when DB_PDF_TEST_PATH points to a local private PDF.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import pytest

from pdf_parser import (
    _HLD_ISIN_LINE_QUICK_RE,
    _derive_split_ratios,
    _has_isin,
    _is_tx_start_line,
    _jurisdiction_from_isin,
    _parse_date,
    _parse_german_number,
    _parse_holdings_block,
    _parse_isin_line,
    _parse_tx_block,
)

_PDF_TEST_PATH = os.environ.get("DB_PDF_TEST_PATH")
REAL_PDF = Path(_PDF_TEST_PATH) if _PDF_TEST_PATH else None


class TestParseGermanNumber:
    def test_simple_decimal(self):
        assert _parse_german_number("6,81") == pytest.approx(6.81)

    def test_with_thousands_separator(self):
        assert _parse_german_number("8.448,72") == pytest.approx(8448.72)

    def test_negative(self):
        assert _parse_german_number("-2.117,87") == pytest.approx(-2117.87)

    def test_many_decimal_places(self):
        assert _parse_german_number("415,20000") == pytest.approx(415.2)

    def test_annotation_stripped(self):
        # "(a)" suffix appears on cost-basis numbers in the holdings section
        assert _parse_german_number("140,23518(a)") == pytest.approx(140.23518)

    def test_zero(self):
        assert _parse_german_number("0,00000") == pytest.approx(0.0)


class TestParseDate:
    def test_basic(self):
        assert _parse_date("05.06.2026") == "2026-06-05"

    def test_january(self):
        assert _parse_date("02.01.2024") == "2024-01-02"

    def test_december(self):
        assert _parse_date("27.12.2024") == "2024-12-27"


class TestJurisdictionFromISIN:
    def test_us(self):
        assert _jurisdiction_from_isin("US00SYNTH012") == "US"

    def test_de(self):
        assert _jurisdiction_from_isin("DE00SYNTH008") == "DE"

    def test_ie(self):
        assert _jurisdiction_from_isin("IE00SYNTH009") == "IE"

    def test_nl(self):
        assert _jurisdiction_from_isin("NL00SYNTH005") == "NL"

    def test_lu(self):
        assert _jurisdiction_from_isin("LU00SYNTH010") == "LU"


# ── Line classifier tests ──────────────────────────────────────────────────────


class TestIsTxStartLine:
    def test_kauf(self):
        assert _is_tx_start_line(
            "05.06.2026 000000000000 Kauf 27 SYNTHETICETFIOTA SYN009 EUR 78,18400 -2.117,87"  # noqa: E501
        )

    def test_verkauf(self):
        assert _is_tx_start_line(
            "05.06.2026 000000000000 Verkauf -25 SYNTHETICEQUITYETA.RG.SH. SYN007 EUR 415,20000 8.448,72"  # noqa: E501
        )

    def test_dividend(self):
        assert _is_tx_start_line(
            "01.06.2026 000000000000 Divid./Ausschütt. 20 SYNTHETICEQUITYZETA.REG.SHARES SYN006 USD 6,81"  # noqa: E501
        )

    def test_kapitaltransaktion(self):
        assert _is_tx_start_line(
            "10.06.2024 000000000000 Kapitaltransaktion 342 SYNTHETICEQUITYDELTA SYN004 USD 0,00000 0,00"  # noqa: E501
        )

    def test_continuation_line_is_not_start(self):
        assert not _is_tx_start_line("DL-,01")

    def test_isin_line_is_not_start(self):
        assert not _is_tx_start_line("09.06.2026 000000000000EUR US00SYNTH007 EUR")

    def test_header_is_not_start(self):
        assert not _is_tx_start_line("Umsätze vom 01.01.2024 bis 06.06.2026")


class TestHasISIN:
    def test_eur_isin_line(self):
        assert _has_isin("09.06.2026 000000000000EUR US00SYNTH007 EUR")

    def test_usd_isin_line_with_fx(self):
        assert _has_isin("01.06.2026 000000000000USD US00SYNTH006 1,16980 EUR")

    def test_kapitaltransaktion_isin_line(self):
        assert _has_isin("10.06.2024 US00SYNTH004 EUR")

    def test_primary_line_has_no_isin(self):
        # WKN is 6 chars, not 12 — should not match
        assert not _has_isin(
            "05.06.2026 000000000000 Kauf 27 SYNTHETICETFIOTA SYN009 EUR 78,18400 -2.117,87"  # noqa: E501
        )


# ── Holdings ISIN line quick regex tests ──────────────────────────────────────


class TestHldISINLineQuickRE:
    """_HLD_ISIN_LINE_QUICK_RE must match real ISIN lines and reject
    company-name tokens that happen to look like ISINs to _has_isin."""

    def test_matches_real_isin_line(self):
        # Typical holdings ISIN line: date + depot-no + ISIN + currency + ...
        line = "06.06.2026 NL0010273215 15,74 0,00"
        assert _HLD_ISIN_LINE_QUICK_RE.match(line)

    def test_matches_isin_line_minimal(self):
        line = "06.06.2026 IE00B945VV12"
        assert _HLD_ISIN_LINE_QUICK_RE.match(line)

    def test_rejects_asml_company_name_token(self):
        # "ASMLHOLDINGN" triggered _has_isin because it looks like a 12-char ISIN.
        # The primary line starts with a quantity, not a date — must NOT match.
        line = (
            "22 ASMLHOLDINGN.V.AANDELENOPNAAM EO-,09 SYN001 EUR"
            " 1.400,00000 14,20 200,00 3.159,40 22,24"
        )
        assert not _HLD_ISIN_LINE_QUICK_RE.match(line)

    def test_rejects_vanguard_company_name_token(self):
        # "UETFEODFUNDS" in Vanguard FTSE name similarly triggered a false positive.
        line = "100 VANG.FTSEDEV.EU.UETFEODFUNDS SYN002 EUR 25,00000 2,50 62,50 1.947,00 6,25"
        assert not _HLD_ISIN_LINE_QUICK_RE.match(line)

    def test_rejects_transaction_primary_line(self):
        line = "05.06.2026 000000000000 Kauf 27 SYNTHETICETFIOTA SYN009 EUR 78,18400 -2.117,87"
        assert not _HLD_ISIN_LINE_QUICK_RE.match(line)

    def test_rejects_name_continuation_line(self):
        assert not _HLD_ISIN_LINE_QUICK_RE.match("EO-,09")
        assert not _HLD_ISIN_LINE_QUICK_RE.match("DL-,001")


# ── Holdings block parser tests ───────────────────────────────────────────────


class TestParseHoldingsBlock:
    REPORT_DATE = "2026-06-06"

    def _asml_block(self):
        # Real line format (sanitised with synthetic WKN/values):
        # QTY NAME WKN COST_BASIS CCY CURRENT_PRICE GAIN_EUR MV PCT
        # ISIN line: DATE ISIN GAIN_PCT ACCRUED
        return [
            "22 ASMLHOLDINGN.V.AANDELENOPNAAM SYN001 412,34567 EUR"  # noqa: E501
            " 1.234,56789 7.654,32 27.160,50 18,55",
            "EO-,09",
            "01.03.2025 NL0010273215 43,26 0,00",
        ]

    def _vanguard_block(self):
        return [
            "60 VANG.FTSEDEV.EU.UETFEODFUNDS SYN002 35,12500 EUR 32,45000 23,45 1.947,00 8,24",
            "05.06.2026 IE00B945VV12 8,24 0,00",
        ]

    def test_asml_isin_parsed(self):
        rec = _parse_holdings_block(self._asml_block(), self.REPORT_DATE)
        assert rec is not None
        assert rec["isin"] == "NL0010273215"

    def test_asml_quantity_and_cost_basis(self):
        rec = _parse_holdings_block(self._asml_block(), self.REPORT_DATE)
        assert rec["quantity"] == pytest.approx(22.0)
        assert rec["cost_basis_eur"] == pytest.approx(412.34567)

    def test_asml_name_includes_continuation(self):
        rec = _parse_holdings_block(self._asml_block(), self.REPORT_DATE)
        assert "ASMLHOLDINGN" in rec["asset_name"]
        assert "EO-,09" in rec["asset_name"]

    def test_vanguard_isin_parsed(self):
        rec = _parse_holdings_block(self._vanguard_block(), self.REPORT_DATE)
        assert rec is not None
        assert rec["isin"] == "IE00B945VV12"

    def test_vanguard_market_value(self):
        rec = _parse_holdings_block(self._vanguard_block(), self.REPORT_DATE)
        assert rec["market_value"] == pytest.approx(1947.00)
        assert rec["quantity"] == pytest.approx(60.0)

    def test_block_too_short_returns_none(self):
        assert _parse_holdings_block(["only one line"], self.REPORT_DATE) is None

    def test_missing_isin_line_returns_none(self):
        block = [
            "22 SOMECOMPANY SYN001 EUR 100,00000 110,00000 22,00 2.420,00 10,00",
            "not an isin line at all",
        ]
        assert _parse_holdings_block(block, self.REPORT_DATE) is None


# ── ISIN line parser tests ─────────────────────────────────────────────────────


class TestParseISINLine:
    def test_eur_no_fx(self):
        result = _parse_isin_line("09.06.2026 000000000000EUR US00SYNTH007 EUR")
        assert result["isin"] == "US00SYNTH007"
        assert result["fx_rate"] is None

    def test_usd_with_fx(self):
        result = _parse_isin_line("01.06.2026 000000000000USD US00SYNTH006 1,16980 EUR")
        assert result["isin"] == "US00SYNTH006"
        assert result["fx_rate"] == pytest.approx(1.1698)

    def test_kapitaltransaktion_no_depot(self):
        result = _parse_isin_line("10.06.2024 US00SYNTH004 EUR")
        assert result["isin"] == "US00SYNTH004"
        assert result["fx_rate"] is None

    def test_nl_isin_no_fx(self):
        result = _parse_isin_line("05.05.2026 000000000000EUR NL00SYNTH005 EUR")
        assert result["isin"] == "NL00SYNTH005"
        assert result["fx_rate"] is None


# ── Transaction block parser tests ────────────────────────────────────────────


class TestParseTxBlock:
    def test_buy_no_wrap(self):
        block = [
            "05.06.2026 000000000000 Kauf 27 SYNTHETICETFIOTA SYN009 EUR 78,18400 -2.117,87",  # noqa: E501
            "09.06.2026 000000000000EUR IE00SYNTH009 EUR",
        ]
        tx = _parse_tx_block(block)
        assert tx is not None
        assert tx["transaction_type"] == "buy"
        assert tx["quantity"] == pytest.approx(27.0)
        assert tx["wkn"] == "SYN009"
        assert tx["currency"] == "EUR"
        assert tx["price"] == pytest.approx(78.184)
        assert tx["amount"] == pytest.approx(2117.87)
        assert tx["isin"] == "IE00SYNTH009"
        assert tx["date"] == "2026-06-05"
        assert tx["jurisdiction"] == "IE"
        assert tx["fees"] == 0.0
        assert tx["tax_withheld"] == 0.0

    def test_sell_with_name_wrap(self):
        block = [
            "05.06.2026 000000000000 Verkauf -25 SYNTHETICEQUITYETA.RG.SH. SYN007 EUR 415,20000 8.448,72",  # noqa: E501
            "DL-,01",
            "09.06.2026 000000000000EUR US00SYNTH007 EUR",
        ]
        tx = _parse_tx_block(block)
        assert tx is not None
        assert tx["transaction_type"] == "sell"
        assert tx["quantity"] == pytest.approx(25.0)  # abs value
        assert tx["wkn"] == "SYN007"
        assert tx["price"] == pytest.approx(415.2)
        assert tx["amount"] == pytest.approx(8448.72)
        assert tx["isin"] == "US00SYNTH007"
        assert "SYNTHETICEQUITYETA" in tx["asset_name"]
        assert "DL-,01" in tx["asset_name"]

    def test_dividend_usd_with_fx(self):
        block = [
            "01.06.2026 000000000000 Divid./Ausschütt. 20 SYNTHETICEQUITYZETA.REG.SHARES SYN006 USD 6,81",  # noqa: E501
            "01.06.2026 000000000000USD US00SYNTH006 1,16980 EUR",
        ]
        tx = _parse_tx_block(block)
        assert tx is not None
        assert tx["transaction_type"] == "dividend"
        assert tx["quantity"] == pytest.approx(0.0)  # canonical: qty=0 for dividends
        assert tx["currency"] == "USD"
        assert tx["amount"] == pytest.approx(6.81)
        assert tx["price"] == pytest.approx(0.0)
        assert tx["isin"] == "US00SYNTH006"
        assert tx["jurisdiction"] == "US"

    def test_dividend_eur_with_name_wrap(self):
        block = [
            "05.05.2026 000000000000 Divid./Ausschütt. 22 SYNTHETICEQUITYEPSILON.NAAM SYN005 EUR 44,23",  # noqa: E501
            "EO-,09",
            "05.05.2026 000000000000EUR NL00SYNTH005 EUR",
        ]
        tx = _parse_tx_block(block)
        assert tx is not None
        assert tx["transaction_type"] == "dividend"
        assert tx["currency"] == "EUR"
        assert tx["amount"] == pytest.approx(44.23)
        assert tx["isin"] == "NL00SYNTH005"
        assert "SYNTHETICEQUITYEPSILON" in tx["asset_name"]

    def test_kapitaltransaktion_raw_new_shares(self):
        """Kapitaltransaktion stores raw new_shares; ratio is derived later."""
        block = [
            "10.06.2024 000000000000 Kapitaltransaktion 342 SYNTHETICEQUITYDELTA SYN004 USD 0,00000 0,00",  # noqa: E501
            "DL-,001",
            "10.06.2024 US00SYNTH004 EUR",
        ]
        tx = _parse_tx_block(block)
        assert tx is not None
        assert tx["transaction_type"] == "split"
        assert tx["isin"] == "US00SYNTH004"
        # Raw new_shares stored; ratio derivation is done by _derive_split_ratios
        assert tx["_new_shares"] == pytest.approx(342.0)

    def test_buy_large_amount(self):
        """Kauf with large EUR amount (iShares)."""
        primary = (
            "06.02.2026 000000000000 Kauf 235 SYNTHETICETFTHETA SYN008 EUR 203,20000 -47.758,90"
        )
        block = [primary, "INHABER-ANT.", "10.02.2026 000000000000EUR DE00SYNTH008 EUR"]
        tx = _parse_tx_block(block)
        assert tx is not None
        assert tx["transaction_type"] == "buy"
        assert tx["quantity"] == pytest.approx(235.0)
        assert tx["price"] == pytest.approx(203.2)
        assert tx["amount"] == pytest.approx(47758.9)
        assert tx["isin"] == "DE00SYNTH008"
        assert tx["jurisdiction"] == "DE"


# ── Split ratio derivation tests ──────────────────────────────────────────────


class TestDeriveSplitRatios:
    def test_synthetic_10_for_1(self):
        """Simulate a 10-for-1 split: 38 existing + 342 new = ratio 10."""
        raw_txns = [
            # Buy 20 shares
            {
                "date": "2024-01-02",
                "isin": "US00SYNTH004",
                "transaction_type": "buy",
                "quantity": 20.0,
                "_new_shares": None,
            },
            # Buy 10 more
            {
                "date": "2024-02-21",
                "isin": "US00SYNTH004",
                "transaction_type": "buy",
                "quantity": 10.0,
                "_new_shares": None,
            },
            # Buy 8 more (total: 38)
            {
                "date": "2024-05-23",
                "isin": "US00SYNTH004",
                "transaction_type": "buy",
                "quantity": 8.0,
                "_new_shares": None,
            },
            # 10-for-1 split: new_shares = 342 = 38 * 9
            {
                "date": "2024-06-10",
                "isin": "US00SYNTH004",
                "transaction_type": "split",
                "quantity": 0.0,  # placeholder
                "_new_shares": 342.0,
            },
        ]
        result = _derive_split_ratios(raw_txns)
        split_row = next(r for r in result if r["transaction_type"] == "split")
        assert split_row["quantity"] == pytest.approx(10.0)

    def test_no_splits_unchanged(self):
        """Transactions without splits pass through unchanged."""
        raw_txns = [
            {
                "date": "2024-01-02",
                "isin": "US1234567890",
                "transaction_type": "buy",
                "quantity": 50.0,
                "_new_shares": None,
            },
            {
                "date": "2024-06-01",
                "isin": "US1234567890",
                "transaction_type": "sell",
                "quantity": 10.0,
                "_new_shares": None,
            },
        ]
        result = _derive_split_ratios(raw_txns)
        assert result[0]["quantity"] == pytest.approx(50.0)
        assert result[1]["quantity"] == pytest.approx(10.0)


# ── Integration tests (skipped if private PDF absent) ─────────────────────────


@pytest.mark.skipif(
    REAL_PDF is None or not REAL_PDF.exists(),
    reason="DB_PDF_TEST_PATH is not set to a private PDF fixture",
)
class TestRealPDF:
    @pytest.fixture(scope="class")
    def parsed(self):
        from pdf_parser import parse_db_pdf

        return parse_db_pdf(REAL_PDF)

    def test_returns_two_dataframes(self, parsed):
        tx_df, hld_df = parsed
        assert isinstance(tx_df, pd.DataFrame)
        assert isinstance(hld_df, pd.DataFrame)

    def test_transaction_count(self, parsed):
        tx_df, _ = parsed
        # 13 pages of transactions, ~7-10 per page → at least 50
        assert len(tx_df) >= 50

    def test_transaction_schema_valid(self, parsed):
        from portfolio_sim import validate_transactions

        tx_df, _ = parsed
        errors = validate_transactions(tx_df)
        assert errors == [], f"Validation errors: {errors}"

    def test_holdings_schema_valid(self, parsed):
        from portfolio_sim import HOLDINGS_COLUMNS, validate_holdings

        _, hld_df = parsed
        errors = validate_holdings(hld_df[HOLDINGS_COLUMNS])
        assert errors == [], f"Validation errors: {errors}"

    def test_transaction_types_are_canonical(self, parsed):
        from portfolio_sim import ALL_TRANSACTION_TYPES

        tx_df, _ = parsed
        unknown = set(tx_df["transaction_type"].unique()) - ALL_TRANSACTION_TYPES
        assert unknown == set(), f"Unknown transaction types: {unknown}"

    def test_synthetic_split_ratio_is_ten(self, parsed):
        """Synthetic 10-for-1 split row must have ratio=10 after derivation."""
        tx_df, _ = parsed
        synthetic_splits = tx_df[
            (tx_df["isin"] == "US00SYNTH004") & (tx_df["transaction_type"] == "split")
        ]
        assert len(synthetic_splits) == 1, "Expected exactly one synthetic split"
        assert synthetic_splits.iloc[0]["quantity"] == pytest.approx(10.0)

    def test_all_isins_are_twelve_chars(self, parsed):
        tx_df, hld_df = parsed
        for isin in tx_df["isin"].dropna():
            assert len(isin) == 12, f"Bad ISIN length: {isin!r}"
        for isin in hld_df["isin"].dropna():
            assert len(isin) == 12, f"Bad ISIN length: {isin!r}"

    def test_holdings_have_cost_basis(self, parsed):
        _, hld_df = parsed
        assert "cost_basis_eur" in hld_df.columns
        assert (hld_df["cost_basis_eur"] > 0).all()

    def test_buy_amounts_are_positive(self, parsed):
        tx_df, _ = parsed
        buys = tx_df[tx_df["transaction_type"] == "buy"]
        assert (buys["amount"] > 0).all()

    def test_sell_amounts_are_positive(self, parsed):
        tx_df, _ = parsed
        sells = tx_df[tx_df["transaction_type"] == "sell"]
        assert (sells["amount"] > 0).all()
