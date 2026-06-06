from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from portfolio_sim import (
    ALL_TRANSACTION_TYPES,
    HOLDINGS_COLUMNS,
    LOT_COLUMNS,
    SIMULATION_OUTPUT_COLUMNS,
    TRANSACTION_COLUMNS,
    ECBProvider,
    PriceProvider,
    StaticPriceProvider,
    UnsupportedCorporateAction,
    YahooPriceProvider,
    YahooProvider,
    apply_buy,
    apply_sell_fifo,
    apply_split,
    check_unsupported_actions,
    derive_holdings_from_lots,
    fetch_current_prices,
    initialize_lots_from_holdings,
    lots_to_dataframe,
    make_fx_provider,
    make_price_provider,
    reconcile_holdings,
    simulate_from_snapshot,
    simulate_portfolio,
    simulate_portfolio_partial,
    validate_holdings,
    validate_transactions,
)

FIXTURES = Path(__file__).parent / "fixtures"

# ── helpers ────────────────────────────────────────────────────────────────────


def _tx(**overrides) -> dict:
    row = {
        "date": "2023-01-15",
        "isin": "DE0005140008",
        "wkn": "514000",
        "asset_name": "Deutsche Bank AG",
        "transaction_type": "buy",
        "quantity": 100.0,
        "price": 12.50,
        "currency": "EUR",
        "amount": 1250.0,
        "fees": 9.90,
        "tax_withheld": 0.0,
        "jurisdiction": "DE",
    }
    row.update(overrides)
    return row


def _eur_fx() -> MagicMock:
    """FX provider that passes amounts through unchanged (all EUR)."""
    provider = MagicMock()
    provider.convert.side_effect = lambda amount, fc, tc, date: amount
    return provider


# ── Slice 1: schema column constants ──────────────────────────────────────────


class TestSchemaConstants:
    def test_transaction_columns_include_jurisdiction(self):
        assert "jurisdiction" in TRANSACTION_COLUMNS

    def test_holdings_columns_include_jurisdiction(self):
        assert "jurisdiction" in HOLDINGS_COLUMNS

    def test_lot_columns_are_defined(self):
        assert LOT_COLUMNS == ["isin", "lot_date", "lot_price_eur", "remaining_shares"]

    def test_simulation_output_columns_are_defined(self):
        assert SIMULATION_OUTPUT_COLUMNS == [
            "isin",
            "reporting_date",
            "market_value_eur",
            "unrealised_gain_eur",
            "realised_gain_ytd_eur",
            "tax_paid_ytd_eur",
        ]


# ── Slice 1: transaction validation ───────────────────────────────────────────


class TestValidateTransactions:
    def test_valid_row_has_no_errors(self):
        df = pd.DataFrame([_tx()])
        assert validate_transactions(df) == []

    def test_missing_required_column_is_flagged(self):
        df = pd.DataFrame([_tx()]).drop(columns=["asset_name"])
        errors = validate_transactions(df)
        assert any("asset_name" in e for e in errors)

    def test_missing_both_isin_and_wkn_is_flagged(self):
        df = pd.DataFrame([_tx(isin=None, wkn=None)])
        errors = validate_transactions(df)
        assert any("isin" in e and "wkn" in e for e in errors)

    def test_isin_only_is_accepted(self):
        df = pd.DataFrame([_tx(wkn=None)])
        assert validate_transactions(df) == []

    def test_wkn_only_is_accepted(self):
        df = pd.DataFrame([_tx(isin=None)])
        assert validate_transactions(df) == []

    def test_missing_asset_name_is_flagged(self):
        df = pd.DataFrame([_tx(asset_name=None)])
        errors = validate_transactions(df)
        assert any("asset_name" in e for e in errors)

    def test_unknown_transaction_type_is_flagged(self):
        df = pd.DataFrame([_tx(transaction_type="unknown_type")])
        errors = validate_transactions(df)
        assert any("unknown_type" in e for e in errors)

    def test_all_known_transaction_types_are_accepted(self):
        rows = [_tx(transaction_type=t) for t in ALL_TRANSACTION_TYPES]
        df = pd.DataFrame(rows)
        assert validate_transactions(df) == []


# ── Slice 1: holdings validation ──────────────────────────────────────────────


def _holding(**overrides) -> dict:
    row = {
        "date": "2023-12-31",
        "isin": "DE0005140008",
        "wkn": "514000",
        "asset_name": "Deutsche Bank AG",
        "quantity": 100.0,
        "price": 15.50,
        "currency": "EUR",
        "market_value": 1550.0,
        "jurisdiction": "DE",
    }
    row.update(overrides)
    return row


class TestValidateHoldings:
    def test_valid_row_has_no_errors(self):
        df = pd.DataFrame([_holding()])
        assert validate_holdings(df) == []

    def test_missing_both_isin_and_wkn_is_flagged(self):
        df = pd.DataFrame([_holding(isin=None, wkn=None)])
        errors = validate_holdings(df)
        assert any("isin" in e and "wkn" in e for e in errors)

    def test_missing_asset_name_is_flagged(self):
        df = pd.DataFrame([_holding(asset_name=None)])
        errors = validate_holdings(df)
        assert any("asset_name" in e for e in errors)

    def test_missing_required_column_is_flagged(self):
        df = pd.DataFrame([_holding()]).drop(columns=["quantity"])
        errors = validate_holdings(df)
        assert any("quantity" in e for e in errors)


# ── Slice 2: fixture loading ───────────────────────────────────────────────────


class TestFixtureLoading:
    def test_transactions_fixture_loads_and_validates(self):
        df = pd.read_csv(FIXTURES / "transactions_simple.csv")
        errors = validate_transactions(df)
        assert errors == [], f"Fixture errors: {errors}"

    def test_holdings_fixture_loads_and_validates(self):
        df = pd.read_csv(FIXTURES / "holdings_simple.csv")
        errors = validate_holdings(df)
        assert errors == [], f"Fixture errors: {errors}"

    def test_split_fixture_loads_and_validates(self):
        df = pd.read_csv(FIXTURES / "transactions_with_split.csv")
        errors = validate_transactions(df)
        assert errors == [], f"Fixture errors: {errors}"


# ── Slice 4: FX providers ──────────────────────────────────────────────────────


class TestFXFactory:
    def test_make_ecb_provider(self):
        assert isinstance(make_fx_provider("ecb"), ECBProvider)

    def test_make_yahoo_provider(self):
        assert isinstance(make_fx_provider("yahoo"), YahooProvider)

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown FX provider"):
            make_fx_provider("bloomberg")


class TestFXConvert:
    def test_same_currency_returns_amount_unchanged(self):
        p = ECBProvider()
        assert p.convert(100.0, "EUR", "EUR", "2023-01-15") == 100.0

    def test_ecb_usd_to_eur_inverts_ecb_rate(self):
        # ECB reports USD per 1 EUR = 1.0765 → USD->EUR = 1/1.0765
        mock_resp = MagicMock()
        mock_resp.text = (
            "KEY,FREQ,CURRENCY,CURRENCY_DENOM,EXR_TYPE,EXR_SUFFIX,TIME_PERIOD,OBS_VALUE\n"
            "EXR.D.USD.EUR.SP00.A,D,USD,EUR,SP00,A,2023-01-15,1.0765\n"
        )
        mock_resp.raise_for_status = MagicMock()
        with patch("requests.get", return_value=mock_resp):
            rate = ECBProvider().rate("USD", "EUR", "2023-01-15")
        assert abs(rate - 1 / 1.0765) < 0.001

    def test_ecb_eur_to_usd_returns_ecb_rate(self):
        mock_resp = MagicMock()
        mock_resp.text = (
            "KEY,FREQ,CURRENCY,CURRENCY_DENOM,EXR_TYPE,EXR_SUFFIX,TIME_PERIOD,OBS_VALUE\n"
            "EXR.D.USD.EUR.SP00.A,D,USD,EUR,SP00,A,2023-01-15,1.0765\n"
        )
        mock_resp.raise_for_status = MagicMock()
        with patch("requests.get", return_value=mock_resp):
            rate = ECBProvider().rate("EUR", "USD", "2023-01-15")
        assert abs(rate - 1.0765) < 0.001

    def test_ecb_no_data_raises(self):
        mock_resp = MagicMock()
        mock_resp.text = (
            "KEY,FREQ,CURRENCY,CURRENCY_DENOM,EXR_TYPE,EXR_SUFFIX,TIME_PERIOD,OBS_VALUE\n"
        )
        mock_resp.raise_for_status = MagicMock()
        with (
            patch("requests.get", return_value=mock_resp),
            pytest.raises(ValueError, match="No ECB rate"),
        ):
            ECBProvider().rate("USD", "EUR", "2023-01-15")


# ── Slice 5: lot engine ────────────────────────────────────────────────────────


class TestApplyBuy:
    def test_buy_adds_lot(self):
        lots: list[dict] = []
        apply_buy(lots, "DE0005140008", "2023-01-15", 12.50, 100.0)
        assert len(lots) == 1
        assert lots[0] == {
            "isin": "DE0005140008",
            "lot_date": "2023-01-15",
            "lot_price_eur": 12.50,
            "remaining_shares": 100.0,
        }

    def test_multiple_buys_add_multiple_lots(self):
        lots: list[dict] = []
        apply_buy(lots, "DE0005140008", "2023-01-15", 12.50, 100.0)
        apply_buy(lots, "DE0005140008", "2023-06-01", 14.00, 50.0)
        assert len(lots) == 2


class TestApplySellFIFO:
    def _lot(self, price: float, shares: float, date: str = "2023-01-15") -> dict:
        return {
            "isin": "DE0005140008",
            "lot_date": date,
            "lot_price_eur": price,
            "remaining_shares": shares,
        }

    def test_full_sell_of_single_lot(self):
        lots = [self._lot(12.50, 100.0)]
        lots, gain, tax = apply_sell_fifo(lots, "DE0005140008", 100.0, 15.50, 0.26)
        assert lots == []
        assert abs(gain - 300.0) < 0.01  # (15.50 - 12.50) * 100
        assert abs(tax - 78.0) < 0.01  # 300 * 0.26

    def test_fifo_partial_sell_reduces_oldest_lot_first(self):
        lots = [self._lot(12.50, 100.0, "2023-01-15"), self._lot(14.00, 50.0, "2023-06-01")]
        lots, gain, _ = apply_sell_fifo(lots, "DE0005140008", 80.0, 15.50, 0.26)
        assert abs(lots[0]["remaining_shares"] - 20.0) < 0.01  # 100 - 80
        assert abs(lots[1]["remaining_shares"] - 50.0) < 0.01  # second lot untouched
        assert abs(gain - (15.50 - 12.50) * 80) < 0.01

    def test_sell_spanning_two_lots(self):
        lots = [self._lot(12.50, 60.0, "2023-01-15"), self._lot(14.00, 50.0, "2023-06-01")]
        lots, gain, _ = apply_sell_fifo(lots, "DE0005140008", 80.0, 15.50, 0.26)
        assert len(lots) == 1
        assert abs(lots[0]["remaining_shares"] - 30.0) < 0.01  # 50 - 20
        expected = (15.50 - 12.50) * 60 + (15.50 - 14.00) * 20
        assert abs(gain - expected) < 0.01

    def test_sell_more_than_available_raises(self):
        lots = [self._lot(12.50, 50.0)]
        with pytest.raises(ValueError, match="Cannot sell"):
            apply_sell_fifo(lots, "DE0005140008", 100.0, 15.50, 0.26)

    def test_sell_at_loss_produces_zero_tax(self):
        lots = [self._lot(15.00, 100.0)]
        lots, gain, tax = apply_sell_fifo(lots, "DE0005140008", 100.0, 12.00, 0.26)
        assert gain == -300.0
        assert tax == 0.0

    def test_sell_only_affects_matching_isin(self):
        lots = [
            {
                "isin": "DE0005140008",
                "lot_date": "2023-01-15",
                "lot_price_eur": 12.50,
                "remaining_shares": 100.0,
            },
            {
                "isin": "US0378331005",
                "lot_date": "2023-01-15",
                "lot_price_eur": 130.00,
                "remaining_shares": 10.0,
            },
        ]
        lots, _, _ = apply_sell_fifo(lots, "DE0005140008", 100.0, 15.50, 0.26)
        assert len(lots) == 1
        assert lots[0]["isin"] == "US0378331005"
        assert lots[0]["remaining_shares"] == 10.0


class TestApplySplit:
    def _lot(self) -> dict:
        return {
            "isin": "DE0005140008",
            "lot_date": "2023-01-15",
            "lot_price_eur": 14.00,
            "remaining_shares": 100.0,
        }

    def test_forward_split_halves_lot_price_and_doubles_shares(self):
        lots = [self._lot()]
        lots = apply_split(lots, "DE0005140008", 2.0)
        assert abs(lots[0]["remaining_shares"] - 200.0) < 0.01
        assert abs(lots[0]["lot_price_eur"] - 7.00) < 0.01

    def test_split_preserves_total_cost_basis(self):
        lots = [self._lot()]
        original = lots[0]["lot_price_eur"] * lots[0]["remaining_shares"]
        lots = apply_split(lots, "DE0005140008", 2.0)
        new = lots[0]["lot_price_eur"] * lots[0]["remaining_shares"]
        assert abs(original - new) < 0.01

    def test_split_does_not_affect_other_securities(self):
        lots = [
            self._lot(),
            {
                "isin": "US0378331005",
                "lot_date": "2023-01-15",
                "lot_price_eur": 130.00,
                "remaining_shares": 10.0,
            },
        ]
        lots = apply_split(lots, "DE0005140008", 2.0)
        aapl = next(lot for lot in lots if lot["isin"] == "US0378331005")
        assert aapl["remaining_shares"] == 10.0
        assert aapl["lot_price_eur"] == 130.00

    def test_zero_or_negative_ratio_raises(self):
        lots = [self._lot()]
        with pytest.raises(ValueError, match="positive"):
            apply_split(lots, "DE0005140008", 0.0)


class TestLotsToDataframe:
    def test_empty_lots_returns_correct_columns(self):
        df = lots_to_dataframe([])
        assert list(df.columns) == LOT_COLUMNS
        assert len(df) == 0

    def test_lots_converted_to_dataframe(self):
        lots: list[dict] = []
        apply_buy(lots, "DE0005140008", "2023-01-15", 12.50, 100.0)
        df = lots_to_dataframe(lots)
        assert list(df.columns) == LOT_COLUMNS
        assert len(df) == 1


# ── Slice 6: reconciliation ────────────────────────────────────────────────────


class TestReconcileHoldings:
    def _lot_df(self, isin: str, qty: float) -> pd.DataFrame:
        return pd.DataFrame({"isin": [isin], "quantity": [qty]})

    def test_exact_match(self):
        result = reconcile_holdings(
            self._lot_df("DE0005140008", 100.0), self._lot_df("DE0005140008", 100.0)
        )
        assert result.loc[result["isin"] == "DE0005140008", "status"].iloc[0] == "match"

    def test_mismatch_outside_tolerance(self):
        result = reconcile_holdings(
            self._lot_df("DE0005140008", 100.0), self._lot_df("DE0005140008", 95.0)
        )
        assert result.loc[result["isin"] == "DE0005140008", "status"].iloc[0] == "mismatch"

    def test_within_tolerance_is_match(self):
        result = reconcile_holdings(
            self._lot_df("DE0005140008", 100.0005),
            self._lot_df("DE0005140008", 100.0),
            tolerance=0.001,
        )
        assert result.loc[result["isin"] == "DE0005140008", "status"].iloc[0] == "match"

    def test_derived_only(self):
        result = reconcile_holdings(
            self._lot_df("DE0005140008", 100.0),
            pd.DataFrame({"isin": [], "quantity": []}),
        )
        assert result.loc[result["isin"] == "DE0005140008", "status"].iloc[0] == "derived_only"

    def test_broker_only(self):
        result = reconcile_holdings(
            pd.DataFrame({"isin": [], "quantity": []}),
            self._lot_df("DE0005140008", 100.0),
        )
        assert result.loc[result["isin"] == "DE0005140008", "status"].iloc[0] == "broker_only"

    def test_derive_holdings_from_lots_aggregates_per_isin(self):
        lots: list[dict] = []
        apply_buy(lots, "DE0005140008", "2023-01-15", 12.50, 60.0)
        apply_buy(lots, "DE0005140008", "2023-06-01", 14.00, 50.0)
        apply_buy(lots, "US0378331005", "2023-01-15", 130.00, 10.0)
        df = derive_holdings_from_lots(lots)
        db_qty = df.loc[df["isin"] == "DE0005140008", "quantity"].iloc[0]
        assert abs(db_qty - 110.0) < 0.01


# ── Slice 7: simulation ────────────────────────────────────────────────────────


class TestSimulatePortfolio:
    def test_buy_and_hold_produces_correct_market_value(self):
        txns = pd.DataFrame([_tx(quantity=100.0, price=12.50)])
        result = simulate_portfolio(
            txns,
            current_prices_eur={"DE0005140008": 15.50},
            capital_gains_tax_rate=0.26,
            dividend_tax_rate=0.26,
            fx_provider=_eur_fx(),
            reporting_date="2023-12-31",
        )
        row = result[result["isin"] == "DE0005140008"].iloc[0]
        assert abs(row["market_value_eur"] - 1550.0) < 0.01
        assert abs(row["unrealised_gain_eur"] - 300.0) < 0.01
        assert row["realised_gain_ytd_eur"] == 0.0
        assert row["tax_paid_ytd_eur"] == 0.0

    def test_sell_records_realised_gain_and_tax(self):
        txns = pd.DataFrame(
            [
                _tx(date="2023-01-15", transaction_type="buy", quantity=100.0, price=12.50),
                _tx(date="2023-09-15", transaction_type="sell", quantity=80.0, price=15.50),
            ]
        )
        result = simulate_portfolio(
            txns,
            current_prices_eur={"DE0005140008": 15.50},
            capital_gains_tax_rate=0.26,
            dividend_tax_rate=0.26,
            fx_provider=_eur_fx(),
            reporting_date="2023-12-31",
        )
        row = result[result["isin"] == "DE0005140008"].iloc[0]
        expected_gain = (15.50 - 12.50) * 80
        assert abs(row["realised_gain_ytd_eur"] - expected_gain) < 0.01
        assert abs(row["tax_paid_ytd_eur"] - expected_gain * 0.26) < 0.01

    def test_output_has_correct_columns(self):
        txns = pd.DataFrame([_tx()])
        result = simulate_portfolio(
            txns,
            current_prices_eur={"DE0005140008": 15.50},
            capital_gains_tax_rate=0.26,
            dividend_tax_rate=0.26,
            fx_provider=_eur_fx(),
        )
        assert list(result.columns) == SIMULATION_OUTPUT_COLUMNS

    def test_unsupported_action_raises(self):
        txns = pd.DataFrame([_tx(transaction_type="merger")])
        with pytest.raises(UnsupportedCorporateAction):
            simulate_portfolio(
                txns,
                current_prices_eur={"DE0005140008": 15.50},
                capital_gains_tax_rate=0.26,
                dividend_tax_rate=0.26,
                fx_provider=_eur_fx(),
            )

    def test_unsupported_lot_method_raises(self):
        txns = pd.DataFrame([_tx()])
        with pytest.raises(ValueError, match="Lot method"):
            simulate_portfolio(
                txns,
                current_prices_eur={"DE0005140008": 15.50},
                capital_gains_tax_rate=0.26,
                dividend_tax_rate=0.26,
                fx_provider=_eur_fx(),
                lot_method="lifo",
            )

    def test_two_securities_are_independent(self):
        txns = pd.DataFrame(
            [
                _tx(isin="DE0005140008", quantity=100.0, price=12.50),
                _tx(isin="US0378331005", asset_name="Apple Inc", quantity=10.0, price=130.00),
            ]
        )
        result = simulate_portfolio(
            txns,
            current_prices_eur={"DE0005140008": 15.50, "US0378331005": 180.00},
            capital_gains_tax_rate=0.26,
            dividend_tax_rate=0.26,
            fx_provider=_eur_fx(),
        )
        assert len(result) == 2
        aapl = result[result["isin"] == "US0378331005"].iloc[0]
        assert abs(aapl["market_value_eur"] - 1800.0) < 0.01
        assert abs(aapl["unrealised_gain_eur"] - 500.0) < 0.01


# ── Slice 8: partial results / unsupported corporate actions ───────────────────


class TestUnsupportedActions:
    def test_check_returns_affected_isins(self):
        txns = pd.DataFrame([_tx(transaction_type="merger")])
        assert "DE0005140008" in check_unsupported_actions(txns)

    def test_check_returns_empty_for_clean_data(self):
        txns = pd.DataFrame([_tx(transaction_type="buy")])
        assert check_unsupported_actions(txns) == []

    def test_partial_simulation_excludes_affected_security(self):
        txns = pd.DataFrame(
            [
                _tx(isin="DE0005140008", transaction_type="buy", quantity=100.0, price=12.50),
                _tx(
                    isin="US0378331005",
                    asset_name="Apple Inc",
                    transaction_type="merger",
                    quantity=0.0,
                    price=0.0,
                    amount=0.0,
                ),
            ]
        )
        result, excluded = simulate_portfolio_partial(
            txns,
            current_prices_eur={"DE0005140008": 15.50, "US0378331005": 175.0},
            capital_gains_tax_rate=0.26,
            dividend_tax_rate=0.26,
            fx_provider=_eur_fx(),
        )
        assert "US0378331005" in excluded
        assert not (result["isin"] == "US0378331005").any()
        assert (result["isin"] == "DE0005140008").any()

    def test_clean_data_partial_simulation_returns_empty_excluded(self):
        txns = pd.DataFrame([_tx()])
        result, excluded = simulate_portfolio_partial(
            txns,
            current_prices_eur={"DE0005140008": 15.50},
            capital_gains_tax_rate=0.26,
            dividend_tax_rate=0.26,
            fx_provider=_eur_fx(),
        )
        assert excluded == []
        assert len(result) == 1


# ── Price provider tests ───────────────────────────────────────────────────────


class TestStaticPriceProvider:
    def test_returns_configured_price(self):
        p = StaticPriceProvider({"US0378331005": 221.36})
        assert p.price_eur("US0378331005", "2026-06-06") == pytest.approx(221.36)

    def test_missing_isin_raises_key_error(self):
        p = StaticPriceProvider({})
        with pytest.raises(KeyError):
            p.price_eur("US0378331005", "2026-06-06")

    def test_multiple_isins(self):
        prices = {"US0378331005": 221.36, "NL0010273215": 1417.40}
        p = StaticPriceProvider(prices)
        assert p.price_eur("NL0010273215", "2026-06-06") == pytest.approx(1417.40)

    def test_is_price_provider(self):
        from portfolio_sim import PriceProvider

        assert isinstance(StaticPriceProvider({}), PriceProvider)


class TestYahooPriceProvider:
    def _make_yahoo_response(
        self, close: float, currency: str = "USD", date: str = "2026-06-06"
    ) -> dict:
        """Build a minimal Yahoo Finance chart API response.

        Timestamps are anchored to noon UTC on the given date so they fall
        within the target_ts window regardless of when the test runs.
        """
        from datetime import datetime, timedelta

        # Use noon UTC two days and one day before `date` so both timestamps
        # fall below target_ts (midnight of `date`) regardless of timezone.
        dt = datetime.strptime(date, "%Y-%m-%d")
        ts1 = int((dt - timedelta(days=2)).replace(hour=12).timestamp())
        ts2 = int((dt - timedelta(days=1)).replace(hour=12).timestamp())
        return {
            "chart": {
                "result": [
                    {
                        "meta": {"currency": currency},
                        "timestamp": [ts1, ts2],
                        "indicators": {"quote": [{"close": [close - 1.0, close]}]},
                    }
                ]
            }
        }

    def test_eur_ticker_no_fx_conversion(self):
        """EUR-quoted ticker should be returned as-is (no FX conversion needed)."""
        fx = _eur_fx()
        provider = YahooPriceProvider({"DE000A0F5UF5": "EXXT.DE"}, fx_provider=fx)
        resp = MagicMock()
        resp.json.return_value = self._make_yahoo_response(199.43, currency="EUR")
        with patch("requests.get", return_value=resp):
            price = provider.price_eur("DE000A0F5UF5", "2026-06-06")
        assert price == pytest.approx(199.43)

    def test_usd_ticker_converted_to_eur(self):
        """USD-quoted ticker should be converted to EUR via fx_provider."""
        mock_fx = MagicMock(spec=PriceProvider)
        mock_fx.convert = MagicMock(return_value=200.0)

        fx_prov = MagicMock()
        fx_prov.convert = MagicMock(return_value=200.0)

        provider = YahooPriceProvider({"US0378331005": "AAPL"}, fx_provider=fx_prov)
        resp = MagicMock()
        resp.json.return_value = self._make_yahoo_response(220.0, currency="USD")
        with patch("requests.get", return_value=resp):
            price = provider.price_eur("US0378331005", "2026-06-06")
        fx_prov.convert.assert_called_once_with(220.0, "USD", "EUR", "2026-06-06")
        assert price == pytest.approx(200.0)

    def test_missing_isin_raises_key_error(self):
        provider = YahooPriceProvider({}, fx_provider=_eur_fx())
        with pytest.raises(KeyError, match="No ticker mapping"):
            provider.price_eur("US0378331005", "2026-06-06")


class TestFetchCurrentPrices:
    def test_returns_prices_for_known_isins(self):
        provider = StaticPriceProvider({"US0378331005": 221.36, "NL0010273215": 1417.40})
        result = fetch_current_prices(["US0378331005", "NL0010273215"], provider, "2026-06-06")
        assert result == {
            "US0378331005": pytest.approx(221.36),
            "NL0010273215": pytest.approx(1417.40),
        }

    def test_skips_unknown_isins_silently(self):
        provider = StaticPriceProvider({"US0378331005": 221.36})
        result = fetch_current_prices(["US0378331005", "UNKNOWN_ISIN"], provider, "2026-06-06")
        assert "US0378331005" in result
        assert "UNKNOWN_ISIN" not in result

    def test_empty_isin_list_returns_empty_dict(self):
        provider = StaticPriceProvider({})
        result = fetch_current_prices([], provider, "2026-06-06")
        assert result == {}


class TestMakePriceProvider:
    def test_static_factory(self):
        p = make_price_provider("static", prices={"US0378331005": 221.36})
        assert isinstance(p, StaticPriceProvider)
        assert p.price_eur("US0378331005", "2026-06-06") == pytest.approx(221.36)

    def test_yahoo_factory(self):
        p = make_price_provider("yahoo", isin_to_ticker={"US0378331005": "AAPL"})
        assert isinstance(p, YahooPriceProvider)

    def test_unknown_name_raises(self):
        with pytest.raises(ValueError, match="Unknown price provider"):
            make_price_provider("bloomberg")


# ── Slice 6: Lot initialization from holdings ─────────────────────────────────


def _hld_row(**overrides) -> dict:
    """Minimal holdings row with cost_basis_eur (as produced by pdf_parser)."""
    row = {
        "date": "2026-06-06",
        "isin": "US67066G1040",
        "wkn": "A2N4XJ",
        "asset_name": "NVIDIA Corp.",
        "quantity": 34.0,
        "price": 130.50,
        "currency": "USD",
        "market_value": 4437.00,
        "jurisdiction": "US",
        "cost_basis_eur": 89.20,
    }
    row.update(overrides)
    return row


class TestInitializeLotsFromHoldings:
    def test_single_row_maps_to_lot(self):
        df = pd.DataFrame([_hld_row()])
        lots = initialize_lots_from_holdings(df)
        assert len(lots) == 1
        row = lots.iloc[0]
        assert row["isin"] == "US67066G1040"
        assert row["lot_date"] == "2026-06-06"
        assert row["lot_price_eur"] == pytest.approx(89.20)
        assert row["remaining_shares"] == pytest.approx(34.0)

    def test_output_has_exactly_lot_columns(self):
        df = pd.DataFrame([_hld_row()])
        lots = initialize_lots_from_holdings(df)
        assert list(lots.columns) == LOT_COLUMNS

    def test_zero_quantity_row_excluded(self):
        rows = [_hld_row(quantity=34.0), _hld_row(isin="DE0005140008", quantity=0.0)]
        df = pd.DataFrame(rows)
        lots = initialize_lots_from_holdings(df)
        assert len(lots) == 1
        assert lots.iloc[0]["isin"] == "US67066G1040"

    def test_nan_cost_basis_row_excluded(self):
        import math

        rows = [_hld_row(quantity=34.0), _hld_row(isin="DE0005140008", cost_basis_eur=float("nan"))]
        df = pd.DataFrame(rows)
        lots = initialize_lots_from_holdings(df)
        assert len(lots) == 1
        assert not math.isnan(lots.iloc[0]["lot_price_eur"])

    def test_multiple_holdings_produce_multiple_lots(self):
        rows = [
            _hld_row(isin="US67066G1040", quantity=34.0, cost_basis_eur=89.20),
            _hld_row(isin="IE00B4L5Y983", quantity=10.0, cost_basis_eur=55.10),
            _hld_row(isin="DE0005140008", quantity=100.0, cost_basis_eur=12.50),
        ]
        df = pd.DataFrame(rows)
        lots = initialize_lots_from_holdings(df)
        assert len(lots) == 3

    def test_missing_cost_basis_column_raises(self):
        df = pd.DataFrame([_hld_row()]).drop(columns=["cost_basis_eur"])
        with pytest.raises(KeyError, match="cost_basis_eur"):
            initialize_lots_from_holdings(df)

    def test_empty_dataframe_returns_empty_lots(self):
        df = pd.DataFrame(
            columns=[
                "date",
                "isin",
                "wkn",
                "asset_name",
                "quantity",
                "price",
                "currency",
                "market_value",
                "jurisdiction",
                "cost_basis_eur",
            ]
        )
        lots = initialize_lots_from_holdings(df)
        assert len(lots) == 0
        assert list(lots.columns) == LOT_COLUMNS


# ── Slice 7: simulate_from_snapshot ───────────────────────────────────────────

_NVDA = "US67066G1040"
_DBK = "DE0005140008"


def _initial_lots() -> pd.DataFrame:
    """Two snapshot lots: NVDA @ 89.20 EUR/share × 34, DBK @ 12.50 × 100."""
    return pd.DataFrame(
        {
            "isin": [_NVDA, _DBK],
            "lot_date": ["2026-01-01", "2026-01-01"],
            "lot_price_eur": [89.20, 12.50],
            "remaining_shares": [34.0, 100.0],
        }
    )


def _empty_txns() -> pd.DataFrame:
    return pd.DataFrame(columns=TRANSACTION_COLUMNS)


class TestSimulateFromSnapshot:
    def test_no_new_transactions_computes_unrealised_gain(self):
        lots = _initial_lots()
        prices = {_NVDA: 130.0, _DBK: 15.0}
        result = simulate_from_snapshot(
            initial_lots=lots,
            new_transactions=_empty_txns(),
            current_prices_eur=prices,
            capital_gains_tax_rate=0.26375,
            dividend_tax_rate=0.26375,
            reporting_date="2026-06-06",
        )
        nvda = result[result["isin"] == _NVDA].iloc[0]
        # 34 × 130 = 4420; cost = 34 × 89.20 = 3032.80; gain = 1387.20
        assert nvda["market_value_eur"] == pytest.approx(4420.0, abs=0.01)
        assert nvda["unrealised_gain_eur"] == pytest.approx(1387.20, abs=0.01)

    def test_new_buy_adds_second_lot(self):
        lots = _initial_lots()
        new_tx = pd.DataFrame(
            [
                _tx(
                    isin=_NVDA,
                    transaction_type="buy",
                    date="2026-03-01",
                    quantity=10.0,
                    price=110.0,
                    currency="EUR",
                    amount=1100.0,
                )
            ]
        )
        prices = {_NVDA: 130.0, _DBK: 15.0}
        result = simulate_from_snapshot(
            initial_lots=lots,
            new_transactions=new_tx,
            current_prices_eur=prices,
            capital_gains_tax_rate=0.26375,
            dividend_tax_rate=0.26375,
            reporting_date="2026-06-06",
        )
        nvda = result[result["isin"] == _NVDA].iloc[0]
        # (34 + 10) × 130 = 5720; cost = 34×89.20 + 10×110 = 3032.80 + 1100 = 4132.80
        assert nvda["market_value_eur"] == pytest.approx(5720.0, abs=0.01)
        assert nvda["unrealised_gain_eur"] == pytest.approx(1587.20, abs=0.01)

    def test_new_sell_reduces_lots_and_realises_gain(self):
        lots = _initial_lots()
        new_tx = pd.DataFrame(
            [
                _tx(
                    isin=_DBK,
                    transaction_type="sell",
                    date="2026-03-01",
                    quantity=50.0,
                    price=15.0,
                    currency="EUR",
                    amount=750.0,
                )
            ]
        )
        prices = {_NVDA: 130.0, _DBK: 15.0}
        result = simulate_from_snapshot(
            initial_lots=lots,
            new_transactions=new_tx,
            current_prices_eur=prices,
            capital_gains_tax_rate=0.25,
            dividend_tax_rate=0.25,
            reporting_date="2026-06-06",
        )
        dbk = result[result["isin"] == _DBK].iloc[0]
        # Sold 50 @ 15 from lot @ 12.50 → gain = 50 × (15 - 12.50) = 125
        assert dbk["realised_gain_ytd_eur"] == pytest.approx(125.0, abs=0.01)
        assert dbk["tax_paid_ytd_eur"] == pytest.approx(31.25, abs=0.01)
        # Remaining: 50 shares × 15 = 750
        assert dbk["market_value_eur"] == pytest.approx(750.0, abs=0.01)

    def test_accepts_list_of_dicts_as_initial_lots(self):
        lots_list = _initial_lots().to_dict(orient="records")
        prices = {_NVDA: 130.0, _DBK: 15.0}
        result = simulate_from_snapshot(
            initial_lots=lots_list,
            new_transactions=_empty_txns(),
            current_prices_eur=prices,
            capital_gains_tax_rate=0.26375,
            dividend_tax_rate=0.26375,
            reporting_date="2026-06-06",
        )
        assert len(result) == 2

    def test_output_has_simulation_output_columns(self):
        lots = _initial_lots()
        prices = {_NVDA: 130.0}
        result = simulate_from_snapshot(
            initial_lots=lots,
            new_transactions=_empty_txns(),
            current_prices_eur=prices,
            capital_gains_tax_rate=0.26375,
            dividend_tax_rate=0.26375,
        )
        assert list(result.columns) == SIMULATION_OUTPUT_COLUMNS

    def test_isin_absent_from_prices_gives_zero_market_value(self):
        lots = _initial_lots()
        prices = {_NVDA: 130.0}  # DBK missing
        result = simulate_from_snapshot(
            initial_lots=lots,
            new_transactions=_empty_txns(),
            current_prices_eur=prices,
            capital_gains_tax_rate=0.26375,
            dividend_tax_rate=0.26375,
            reporting_date="2026-06-06",
        )
        dbk = result[result["isin"] == _DBK]
        assert len(dbk) == 0  # ISINs absent from prices and with no realised gain are omitted
