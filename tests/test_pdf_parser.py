"""
Tests for the Deutsche Bank PDF parser (src/pdf_parser.py).

Unit tests use hardcoded text fixtures (no PDF file needed).
Integration tests run only when the private PDF is present.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from pdf_parser import (
    _derive_split_ratios,
    _has_isin,
    _is_tx_start_line,
    _jurisdiction_from_isin,
    _parse_date,
    _parse_german_number,
    _parse_isin_line,
    _parse_tx_block,
)

# Integration test: real PDF (gitignored)
REAL_PDF = Path("data/private/report.pdf")


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
        assert _jurisdiction_from_isin("US0258161092") == "US"

    def test_de(self):
        assert _jurisdiction_from_isin("DE000A0F5UF5") == "DE"

    def test_ie(self):
        assert _jurisdiction_from_isin("IE00BTJRMP35") == "IE"

    def test_nl(self):
        assert _jurisdiction_from_isin("NL0010273215") == "NL"

    def test_lu(self):
        assert _jurisdiction_from_isin("LU0274209740") == "LU"


# ── Line classifier tests ──────────────────────────────────────────────────────


class TestIsTxStartLine:
    def test_kauf(self):
        assert _is_tx_start_line(
            "05.06.2026 000000000000 Kauf 27 X(IE)-MSCIEM.MKTS1CDLFUNDS A12GVR EUR 78,18400 -2.117,87"  # noqa: E501
        )

    def test_verkauf(self):
        assert _is_tx_start_line(
            "05.06.2026 000000000000 Verkauf -25 ADVANCEDMICRODEVICESINC.RG.SH. 863186 EUR 415,20000 8.448,72"  # noqa: E501
        )

    def test_dividend(self):
        assert _is_tx_start_line(
            "01.06.2026 000000000000 Divid./Ausschütt. 20 VISAINC.REG.SHARESCLASSADL-,0001 A0NC7B USD 6,81"  # noqa: E501
        )

    def test_kapitaltransaktion(self):
        assert _is_tx_start_line(
            "10.06.2024 000000000000 Kapitaltransaktion 342 NVIDIACORP.REGISTEREDSHARES 918422 USD 0,00000 0,00"  # noqa: E501
        )

    def test_continuation_line_is_not_start(self):
        assert not _is_tx_start_line("DL-,01")

    def test_isin_line_is_not_start(self):
        assert not _is_tx_start_line("09.06.2026 000000000000EUR US0079031078 EUR")

    def test_header_is_not_start(self):
        assert not _is_tx_start_line("Umsätze vom 01.01.2024 bis 06.06.2026")


class TestHasISIN:
    def test_eur_isin_line(self):
        assert _has_isin("09.06.2026 000000000000EUR US0079031078 EUR")

    def test_usd_isin_line_with_fx(self):
        assert _has_isin("01.06.2026 000000000000USD US92826C8394 1,16980 EUR")

    def test_kapitaltransaktion_isin_line(self):
        assert _has_isin("10.06.2024 US67066G1040 EUR")

    def test_primary_line_has_no_isin(self):
        # WKN is 6 chars, not 12 — should not match
        assert not _has_isin(
            "05.06.2026 000000000000 Kauf 27 X(IE)-MSCIEM.MKTS1CDLFUNDS A12GVR EUR 78,18400 -2.117,87"  # noqa: E501
        )


# ── ISIN line parser tests ─────────────────────────────────────────────────────


class TestParseISINLine:
    def test_eur_no_fx(self):
        result = _parse_isin_line("09.06.2026 000000000000EUR US0079031078 EUR")
        assert result["isin"] == "US0079031078"
        assert result["fx_rate"] is None

    def test_usd_with_fx(self):
        result = _parse_isin_line("01.06.2026 000000000000USD US92826C8394 1,16980 EUR")
        assert result["isin"] == "US92826C8394"
        assert result["fx_rate"] == pytest.approx(1.1698)

    def test_kapitaltransaktion_no_depot(self):
        result = _parse_isin_line("10.06.2024 US67066G1040 EUR")
        assert result["isin"] == "US67066G1040"
        assert result["fx_rate"] is None

    def test_nl_isin_no_fx(self):
        result = _parse_isin_line("05.05.2026 000000000000EUR NL0010273215 EUR")
        assert result["isin"] == "NL0010273215"
        assert result["fx_rate"] is None


# ── Transaction block parser tests ────────────────────────────────────────────


class TestParseTxBlock:
    def test_buy_no_wrap(self):
        block = [
            "05.06.2026 000000000000 Kauf 27 X(IE)-MSCIEM.MKTS1CDLFUNDS A12GVR EUR 78,18400 -2.117,87",  # noqa: E501
            "09.06.2026 000000000000EUR IE00BTJRMP35 EUR",
        ]
        tx = _parse_tx_block(block)
        assert tx is not None
        assert tx["transaction_type"] == "buy"
        assert tx["quantity"] == pytest.approx(27.0)
        assert tx["wkn"] == "A12GVR"
        assert tx["currency"] == "EUR"
        assert tx["price"] == pytest.approx(78.184)
        assert tx["amount"] == pytest.approx(2117.87)
        assert tx["isin"] == "IE00BTJRMP35"
        assert tx["date"] == "2026-06-05"
        assert tx["jurisdiction"] == "IE"
        assert tx["fees"] == 0.0
        assert tx["tax_withheld"] == 0.0

    def test_sell_with_name_wrap(self):
        block = [
            "05.06.2026 000000000000 Verkauf -25 ADVANCEDMICRODEVICESINC.RG.SH. 863186 EUR 415,20000 8.448,72",  # noqa: E501
            "DL-,01",
            "09.06.2026 000000000000EUR US0079031078 EUR",
        ]
        tx = _parse_tx_block(block)
        assert tx is not None
        assert tx["transaction_type"] == "sell"
        assert tx["quantity"] == pytest.approx(25.0)  # abs value
        assert tx["wkn"] == "863186"
        assert tx["price"] == pytest.approx(415.2)
        assert tx["amount"] == pytest.approx(8448.72)
        assert tx["isin"] == "US0079031078"
        assert "ADVANCEDMICRODEVICESINC" in tx["asset_name"]
        assert "DL-,01" in tx["asset_name"]

    def test_dividend_usd_with_fx(self):
        block = [
            "01.06.2026 000000000000 Divid./Ausschütt. 20 VISAINC.REG.SHARESCLASSADL-,0001 A0NC7B USD 6,81",  # noqa: E501
            "01.06.2026 000000000000USD US92826C8394 1,16980 EUR",
        ]
        tx = _parse_tx_block(block)
        assert tx is not None
        assert tx["transaction_type"] == "dividend"
        assert tx["quantity"] == pytest.approx(0.0)  # canonical: qty=0 for dividends
        assert tx["currency"] == "USD"
        assert tx["amount"] == pytest.approx(6.81)
        assert tx["price"] == pytest.approx(0.0)
        assert tx["isin"] == "US92826C8394"
        assert tx["jurisdiction"] == "US"

    def test_dividend_eur_with_name_wrap(self):
        block = [
            "05.05.2026 000000000000 Divid./Ausschütt. 22 ASMLHOLDINGN.V.AANDELENOPNAAM A1J4U4 EUR 44,23",  # noqa: E501
            "EO-,09",
            "05.05.2026 000000000000EUR NL0010273215 EUR",
        ]
        tx = _parse_tx_block(block)
        assert tx is not None
        assert tx["transaction_type"] == "dividend"
        assert tx["currency"] == "EUR"
        assert tx["amount"] == pytest.approx(44.23)
        assert tx["isin"] == "NL0010273215"
        assert "ASML" in tx["asset_name"]

    def test_kapitaltransaktion_raw_new_shares(self):
        """Kapitaltransaktion stores raw new_shares; ratio is derived later."""
        block = [
            "10.06.2024 000000000000 Kapitaltransaktion 342 NVIDIACORP.REGISTEREDSHARES 918422 USD 0,00000 0,00",  # noqa: E501
            "DL-,001",
            "10.06.2024 US67066G1040 EUR",
        ]
        tx = _parse_tx_block(block)
        assert tx is not None
        assert tx["transaction_type"] == "split"
        assert tx["isin"] == "US67066G1040"
        # Raw new_shares stored; ratio derivation is done by _derive_split_ratios
        assert tx["_new_shares"] == pytest.approx(342.0)

    def test_buy_large_amount(self):
        """Kauf with large EUR amount (iShares)."""
        primary = (
            "06.02.2026 000000000000 Kauf 235 ISHARE.NASDAQ-100UCITSETFDE"
            " A0F5UF EUR 203,20000 -47.758,90"
        )
        block = [primary, "INHABER-ANT.", "10.02.2026 000000000000EUR DE000A0F5UF5 EUR"]
        tx = _parse_tx_block(block)
        assert tx is not None
        assert tx["transaction_type"] == "buy"
        assert tx["quantity"] == pytest.approx(235.0)
        assert tx["price"] == pytest.approx(203.2)
        assert tx["amount"] == pytest.approx(47758.9)
        assert tx["isin"] == "DE000A0F5UF5"
        assert tx["jurisdiction"] == "DE"


# ── Split ratio derivation tests ──────────────────────────────────────────────


class TestDeriveSplitRatios:
    def test_nvidia_10_for_1(self):
        """Simulate the Nvidia 10-for-1 split: 38 existing + 342 new = ratio 10."""
        raw_txns = [
            # Buy 20 shares
            {
                "date": "2024-01-02",
                "isin": "US67066G1040",
                "transaction_type": "buy",
                "quantity": 20.0,
                "_new_shares": None,
            },
            # Buy 10 more
            {
                "date": "2024-02-21",
                "isin": "US67066G1040",
                "transaction_type": "buy",
                "quantity": 10.0,
                "_new_shares": None,
            },
            # Buy 8 more (total: 38)
            {
                "date": "2024-05-23",
                "isin": "US67066G1040",
                "transaction_type": "buy",
                "quantity": 8.0,
                "_new_shares": None,
            },
            # 10-for-1 split: new_shares = 342 = 38 * 9
            {
                "date": "2024-06-10",
                "isin": "US67066G1040",
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


@pytest.mark.skipif(not REAL_PDF.exists(), reason="Private PDF fixture not present")
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

    def test_nvidia_split_ratio_is_ten(self, parsed):
        """Nvidia 10-for-1 split (2024-06-10) must have ratio=10 after derivation."""
        tx_df, _ = parsed
        nvidia_splits = tx_df[
            (tx_df["isin"] == "US67066G1040") & (tx_df["transaction_type"] == "split")
        ]
        assert len(nvidia_splits) == 1, "Expected exactly one Nvidia split"
        assert nvidia_splits.iloc[0]["quantity"] == pytest.approx(10.0)

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
