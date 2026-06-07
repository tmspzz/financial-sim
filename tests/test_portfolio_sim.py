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
    ChainedConstituentProvider,
    ConstituentResult,
    ConstituentRow,
    CsvConstituentProvider,
    ECBProvider,
    PriceProvider,
    StaticPriceProvider,
    UnsupportedCorporateAction,
    YahooPriceProvider,
    YahooProvider,
    YahooTopHoldingsProvider,
    apply_buy,
    apply_sell_fifo,
    apply_split,
    check_unsupported_actions,
    derive_holdings_from_lots,
    fetch_current_prices,
    fill_missing_prices_from_holdings,
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
        "isin": "DE00SYNTH001",
        "wkn": "SYN001",
        "asset_name": "Synthetic Equity Alpha",
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
        "isin": "DE00SYNTH001",
        "wkn": "SYN001",
        "asset_name": "Synthetic Equity Alpha",
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
        apply_buy(lots, "DE00SYNTH001", "2023-01-15", 12.50, 100.0)
        assert len(lots) == 1
        assert lots[0] == {
            "isin": "DE00SYNTH001",
            "lot_date": "2023-01-15",
            "lot_price_eur": 12.50,
            "remaining_shares": 100.0,
        }

    def test_multiple_buys_add_multiple_lots(self):
        lots: list[dict] = []
        apply_buy(lots, "DE00SYNTH001", "2023-01-15", 12.50, 100.0)
        apply_buy(lots, "DE00SYNTH001", "2023-06-01", 14.00, 50.0)
        assert len(lots) == 2


class TestApplySellFIFO:
    def _lot(self, price: float, shares: float, date: str = "2023-01-15") -> dict:
        return {
            "isin": "DE00SYNTH001",
            "lot_date": date,
            "lot_price_eur": price,
            "remaining_shares": shares,
        }

    def test_full_sell_of_single_lot(self):
        lots = [self._lot(12.50, 100.0)]
        lots, gain, tax = apply_sell_fifo(lots, "DE00SYNTH001", 100.0, 15.50, 0.26)
        assert lots == []
        assert abs(gain - 300.0) < 0.01  # (15.50 - 12.50) * 100
        assert abs(tax - 78.0) < 0.01  # 300 * 0.26

    def test_fifo_partial_sell_reduces_oldest_lot_first(self):
        lots = [self._lot(12.50, 100.0, "2023-01-15"), self._lot(14.00, 50.0, "2023-06-01")]
        lots, gain, _ = apply_sell_fifo(lots, "DE00SYNTH001", 80.0, 15.50, 0.26)
        assert abs(lots[0]["remaining_shares"] - 20.0) < 0.01  # 100 - 80
        assert abs(lots[1]["remaining_shares"] - 50.0) < 0.01  # second lot untouched
        assert abs(gain - (15.50 - 12.50) * 80) < 0.01

    def test_sell_spanning_two_lots(self):
        lots = [self._lot(12.50, 60.0, "2023-01-15"), self._lot(14.00, 50.0, "2023-06-01")]
        lots, gain, _ = apply_sell_fifo(lots, "DE00SYNTH001", 80.0, 15.50, 0.26)
        assert len(lots) == 1
        assert abs(lots[0]["remaining_shares"] - 30.0) < 0.01  # 50 - 20
        expected = (15.50 - 12.50) * 60 + (15.50 - 14.00) * 20
        assert abs(gain - expected) < 0.01

    def test_sell_more_than_available_raises(self):
        lots = [self._lot(12.50, 50.0)]
        with pytest.raises(ValueError, match="Cannot sell"):
            apply_sell_fifo(lots, "DE00SYNTH001", 100.0, 15.50, 0.26)

    def test_sell_at_loss_produces_zero_tax(self):
        lots = [self._lot(15.00, 100.0)]
        lots, gain, tax = apply_sell_fifo(lots, "DE00SYNTH001", 100.0, 12.00, 0.26)
        assert gain == -300.0
        assert tax == 0.0

    def test_sell_only_affects_matching_isin(self):
        lots = [
            {
                "isin": "DE00SYNTH001",
                "lot_date": "2023-01-15",
                "lot_price_eur": 12.50,
                "remaining_shares": 100.0,
            },
            {
                "isin": "US00SYNTH003",
                "lot_date": "2023-01-15",
                "lot_price_eur": 130.00,
                "remaining_shares": 10.0,
            },
        ]
        lots, _, _ = apply_sell_fifo(lots, "DE00SYNTH001", 100.0, 15.50, 0.26)
        assert len(lots) == 1
        assert lots[0]["isin"] == "US00SYNTH003"
        assert lots[0]["remaining_shares"] == 10.0


class TestApplySplit:
    def _lot(self) -> dict:
        return {
            "isin": "DE00SYNTH001",
            "lot_date": "2023-01-15",
            "lot_price_eur": 14.00,
            "remaining_shares": 100.0,
        }

    def test_forward_split_halves_lot_price_and_doubles_shares(self):
        lots = [self._lot()]
        lots = apply_split(lots, "DE00SYNTH001", 2.0)
        assert abs(lots[0]["remaining_shares"] - 200.0) < 0.01
        assert abs(lots[0]["lot_price_eur"] - 7.00) < 0.01

    def test_split_preserves_total_cost_basis(self):
        lots = [self._lot()]
        original = lots[0]["lot_price_eur"] * lots[0]["remaining_shares"]
        lots = apply_split(lots, "DE00SYNTH001", 2.0)
        new = lots[0]["lot_price_eur"] * lots[0]["remaining_shares"]
        assert abs(original - new) < 0.01

    def test_split_does_not_affect_other_securities(self):
        lots = [
            self._lot(),
            {
                "isin": "US00SYNTH003",
                "lot_date": "2023-01-15",
                "lot_price_eur": 130.00,
                "remaining_shares": 10.0,
            },
        ]
        lots = apply_split(lots, "DE00SYNTH001", 2.0)
        synthetic_gamma = next(lot for lot in lots if lot["isin"] == "US00SYNTH003")
        assert synthetic_gamma["remaining_shares"] == 10.0
        assert synthetic_gamma["lot_price_eur"] == 130.00

    def test_zero_or_negative_ratio_raises(self):
        lots = [self._lot()]
        with pytest.raises(ValueError, match="positive"):
            apply_split(lots, "DE00SYNTH001", 0.0)


class TestLotsToDataframe:
    def test_empty_lots_returns_correct_columns(self):
        df = lots_to_dataframe([])
        assert list(df.columns) == LOT_COLUMNS
        assert len(df) == 0

    def test_lots_converted_to_dataframe(self):
        lots: list[dict] = []
        apply_buy(lots, "DE00SYNTH001", "2023-01-15", 12.50, 100.0)
        df = lots_to_dataframe(lots)
        assert list(df.columns) == LOT_COLUMNS
        assert len(df) == 1


# ── Slice 6: reconciliation ────────────────────────────────────────────────────


class TestReconcileHoldings:
    def _lot_df(self, isin: str, qty: float) -> pd.DataFrame:
        return pd.DataFrame({"isin": [isin], "quantity": [qty]})

    def test_exact_match(self):
        result = reconcile_holdings(
            self._lot_df("DE00SYNTH001", 100.0), self._lot_df("DE00SYNTH001", 100.0)
        )
        assert result.loc[result["isin"] == "DE00SYNTH001", "status"].iloc[0] == "match"

    def test_mismatch_outside_tolerance(self):
        result = reconcile_holdings(
            self._lot_df("DE00SYNTH001", 100.0), self._lot_df("DE00SYNTH001", 95.0)
        )
        assert result.loc[result["isin"] == "DE00SYNTH001", "status"].iloc[0] == "mismatch"

    def test_within_tolerance_is_match(self):
        result = reconcile_holdings(
            self._lot_df("DE00SYNTH001", 100.0005),
            self._lot_df("DE00SYNTH001", 100.0),
            tolerance=0.001,
        )
        assert result.loc[result["isin"] == "DE00SYNTH001", "status"].iloc[0] == "match"

    def test_derived_only(self):
        result = reconcile_holdings(
            self._lot_df("DE00SYNTH001", 100.0),
            pd.DataFrame({"isin": [], "quantity": []}),
        )
        assert result.loc[result["isin"] == "DE00SYNTH001", "status"].iloc[0] == "derived_only"

    def test_broker_only(self):
        result = reconcile_holdings(
            pd.DataFrame({"isin": [], "quantity": []}),
            self._lot_df("DE00SYNTH001", 100.0),
        )
        assert result.loc[result["isin"] == "DE00SYNTH001", "status"].iloc[0] == "broker_only"

    def test_derive_holdings_from_lots_aggregates_per_isin(self):
        lots: list[dict] = []
        apply_buy(lots, "DE00SYNTH001", "2023-01-15", 12.50, 60.0)
        apply_buy(lots, "DE00SYNTH001", "2023-06-01", 14.00, 50.0)
        apply_buy(lots, "US00SYNTH003", "2023-01-15", 130.00, 10.0)
        df = derive_holdings_from_lots(lots)
        db_qty = df.loc[df["isin"] == "DE00SYNTH001", "quantity"].iloc[0]
        assert abs(db_qty - 110.0) < 0.01


# ── Slice 7: simulation ────────────────────────────────────────────────────────


class TestSimulatePortfolio:
    def test_buy_and_hold_produces_correct_market_value(self):
        txns = pd.DataFrame([_tx(quantity=100.0, price=12.50)])
        result = simulate_portfolio(
            txns,
            current_prices_eur={"DE00SYNTH001": 15.50},
            capital_gains_tax_rate=0.26,
            dividend_tax_rate=0.26,
            fx_provider=_eur_fx(),
            reporting_date="2023-12-31",
        )
        row = result[result["isin"] == "DE00SYNTH001"].iloc[0]
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
            current_prices_eur={"DE00SYNTH001": 15.50},
            capital_gains_tax_rate=0.26,
            dividend_tax_rate=0.26,
            fx_provider=_eur_fx(),
            reporting_date="2023-12-31",
        )
        row = result[result["isin"] == "DE00SYNTH001"].iloc[0]
        expected_gain = (15.50 - 12.50) * 80
        assert abs(row["realised_gain_ytd_eur"] - expected_gain) < 0.01
        assert abs(row["tax_paid_ytd_eur"] - expected_gain * 0.26) < 0.01

    def test_output_has_correct_columns(self):
        txns = pd.DataFrame([_tx()])
        result = simulate_portfolio(
            txns,
            current_prices_eur={"DE00SYNTH001": 15.50},
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
                current_prices_eur={"DE00SYNTH001": 15.50},
                capital_gains_tax_rate=0.26,
                dividend_tax_rate=0.26,
                fx_provider=_eur_fx(),
            )

    def test_unsupported_lot_method_raises(self):
        txns = pd.DataFrame([_tx()])
        with pytest.raises(ValueError, match="Lot method"):
            simulate_portfolio(
                txns,
                current_prices_eur={"DE00SYNTH001": 15.50},
                capital_gains_tax_rate=0.26,
                dividend_tax_rate=0.26,
                fx_provider=_eur_fx(),
                lot_method="lifo",
            )

    def test_two_securities_are_independent(self):
        txns = pd.DataFrame(
            [
                _tx(isin="DE00SYNTH001", quantity=100.0, price=12.50),
                _tx(
                    isin="US00SYNTH003",
                    asset_name="Synthetic Equity Gamma",
                    quantity=10.0,
                    price=130.00,
                ),
            ]
        )
        result = simulate_portfolio(
            txns,
            current_prices_eur={"DE00SYNTH001": 15.50, "US00SYNTH003": 180.00},
            capital_gains_tax_rate=0.26,
            dividend_tax_rate=0.26,
            fx_provider=_eur_fx(),
        )
        assert len(result) == 2
        synthetic_gamma = result[result["isin"] == "US00SYNTH003"].iloc[0]
        assert abs(synthetic_gamma["market_value_eur"] - 1800.0) < 0.01
        assert abs(synthetic_gamma["unrealised_gain_eur"] - 500.0) < 0.01


# ── Slice 8: partial results / unsupported corporate actions ───────────────────


class TestUnsupportedActions:
    def test_check_returns_affected_isins(self):
        txns = pd.DataFrame([_tx(transaction_type="merger")])
        assert "DE00SYNTH001" in check_unsupported_actions(txns)

    def test_check_returns_empty_for_clean_data(self):
        txns = pd.DataFrame([_tx(transaction_type="buy")])
        assert check_unsupported_actions(txns) == []

    def test_partial_simulation_excludes_affected_security(self):
        txns = pd.DataFrame(
            [
                _tx(isin="DE00SYNTH001", transaction_type="buy", quantity=100.0, price=12.50),
                _tx(
                    isin="US00SYNTH003",
                    asset_name="Synthetic Equity Gamma",
                    transaction_type="merger",
                    quantity=0.0,
                    price=0.0,
                    amount=0.0,
                ),
            ]
        )
        result, excluded = simulate_portfolio_partial(
            txns,
            current_prices_eur={"DE00SYNTH001": 15.50, "US00SYNTH003": 175.0},
            capital_gains_tax_rate=0.26,
            dividend_tax_rate=0.26,
            fx_provider=_eur_fx(),
        )
        assert "US00SYNTH003" in excluded
        assert not (result["isin"] == "US00SYNTH003").any()
        assert (result["isin"] == "DE00SYNTH001").any()

    def test_clean_data_partial_simulation_returns_empty_excluded(self):
        txns = pd.DataFrame([_tx()])
        result, excluded = simulate_portfolio_partial(
            txns,
            current_prices_eur={"DE00SYNTH001": 15.50},
            capital_gains_tax_rate=0.26,
            dividend_tax_rate=0.26,
            fx_provider=_eur_fx(),
        )
        assert excluded == []
        assert len(result) == 1


# ── Price provider tests ───────────────────────────────────────────────────────


class TestStaticPriceProvider:
    def test_returns_configured_price(self):
        p = StaticPriceProvider({"US00SYNTH003": 221.36})
        assert p.price_eur("US00SYNTH003", "2026-06-06") == pytest.approx(221.36)

    def test_missing_isin_raises_key_error(self):
        p = StaticPriceProvider({})
        with pytest.raises(KeyError):
            p.price_eur("US00SYNTH003", "2026-06-06")

    def test_multiple_isins(self):
        prices = {"US00SYNTH003": 221.36, "NL00SYNTH005": 1417.40}
        p = StaticPriceProvider(prices)
        assert p.price_eur("NL00SYNTH005", "2026-06-06") == pytest.approx(1417.40)

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
        provider = YahooPriceProvider({"DE00SYNTH008": "SYNT.DE"}, fx_provider=fx)
        resp = MagicMock()
        resp.json.return_value = self._make_yahoo_response(199.43, currency="EUR")
        with patch("requests.get", return_value=resp):
            price = provider.price_eur("DE00SYNTH008", "2026-06-06")
        assert price == pytest.approx(199.43)

    def test_usd_ticker_converted_to_eur(self):
        """USD-quoted ticker should be converted to EUR via fx_provider."""
        mock_fx = MagicMock(spec=PriceProvider)
        mock_fx.convert = MagicMock(return_value=200.0)

        fx_prov = MagicMock()
        fx_prov.convert = MagicMock(return_value=200.0)

        provider = YahooPriceProvider({"US00SYNTH003": "SYNG"}, fx_provider=fx_prov)
        resp = MagicMock()
        resp.json.return_value = self._make_yahoo_response(220.0, currency="USD")
        with patch("requests.get", return_value=resp):
            price = provider.price_eur("US00SYNTH003", "2026-06-06")
        fx_prov.convert.assert_called_once_with(220.0, "USD", "EUR", "2026-06-06")
        assert price == pytest.approx(200.0)

    def test_missing_isin_raises_key_error(self):
        provider = YahooPriceProvider({}, fx_provider=_eur_fx())
        with pytest.raises(KeyError, match="No ticker mapping"):
            provider.price_eur("US00SYNTH003", "2026-06-06")


class TestFetchCurrentPrices:
    def test_returns_prices_for_known_isins(self):
        provider = StaticPriceProvider({"US00SYNTH003": 221.36, "NL00SYNTH005": 1417.40})
        result = fetch_current_prices(["US00SYNTH003", "NL00SYNTH005"], provider, "2026-06-06")
        assert result == {
            "US00SYNTH003": pytest.approx(221.36),
            "NL00SYNTH005": pytest.approx(1417.40),
        }

    def test_skips_unknown_isins_silently(self):
        provider = StaticPriceProvider({"US00SYNTH003": 221.36})
        result = fetch_current_prices(["US00SYNTH003", "UNKNOWN_ISIN"], provider, "2026-06-06")
        assert "US00SYNTH003" in result
        assert "UNKNOWN_ISIN" not in result

    def test_empty_isin_list_returns_empty_dict(self):
        provider = StaticPriceProvider({})
        result = fetch_current_prices([], provider, "2026-06-06")
        assert result == {}


class TestMakePriceProvider:
    def test_static_factory(self):
        p = make_price_provider("static", prices={"US00SYNTH003": 221.36})
        assert isinstance(p, StaticPriceProvider)
        assert p.price_eur("US00SYNTH003", "2026-06-06") == pytest.approx(221.36)

    def test_yahoo_factory(self):
        p = make_price_provider("yahoo", isin_to_ticker={"US00SYNTH003": "SYNG"})
        assert isinstance(p, YahooPriceProvider)

    def test_unknown_name_raises(self):
        with pytest.raises(ValueError, match="Unknown price provider"):
            make_price_provider("bloomberg")


# ── Slice 6: Lot initialization from holdings ─────────────────────────────────


def _hld_row(**overrides) -> dict:
    """Minimal holdings row with cost_basis_eur (as produced by pdf_parser)."""
    row = {
        "date": "2026-06-06",
        "isin": "US00SYNTH004",
        "wkn": "A2N4XJ",
        "asset_name": "Synthetic Equity Delta",
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
        assert row["isin"] == "US00SYNTH004"
        assert row["lot_date"] == "2026-06-06"
        assert row["lot_price_eur"] == pytest.approx(89.20)
        assert row["remaining_shares"] == pytest.approx(34.0)

    def test_output_has_exactly_lot_columns(self):
        df = pd.DataFrame([_hld_row()])
        lots = initialize_lots_from_holdings(df)
        assert list(lots.columns) == LOT_COLUMNS

    def test_zero_quantity_row_excluded(self):
        rows = [_hld_row(quantity=34.0), _hld_row(isin="DE00SYNTH001", quantity=0.0)]
        df = pd.DataFrame(rows)
        lots = initialize_lots_from_holdings(df)
        assert len(lots) == 1
        assert lots.iloc[0]["isin"] == "US00SYNTH004"

    def test_nan_cost_basis_row_excluded(self):
        import math

        rows = [_hld_row(quantity=34.0), _hld_row(isin="DE00SYNTH001", cost_basis_eur=float("nan"))]
        df = pd.DataFrame(rows)
        lots = initialize_lots_from_holdings(df)
        assert len(lots) == 1
        assert not math.isnan(lots.iloc[0]["lot_price_eur"])

    def test_multiple_holdings_produce_multiple_lots(self):
        rows = [
            _hld_row(isin="US00SYNTH004", quantity=34.0, cost_basis_eur=89.20),
            _hld_row(isin="IE00SYNTH002", quantity=10.0, cost_basis_eur=55.10),
            _hld_row(isin="DE00SYNTH001", quantity=100.0, cost_basis_eur=12.50),
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

_SYND = "US00SYNTH004"
_SYN_ALPHA = "DE00SYNTH001"


def _initial_lots() -> pd.DataFrame:
    """Two snapshot lots: SYND @ 89.20 EUR/share × 34, SYN_ALPHA @ 12.50 × 100."""
    return pd.DataFrame(
        {
            "isin": [_SYND, _SYN_ALPHA],
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
        prices = {_SYND: 130.0, _SYN_ALPHA: 15.0}
        result = simulate_from_snapshot(
            initial_lots=lots,
            new_transactions=_empty_txns(),
            current_prices_eur=prices,
            capital_gains_tax_rate=0.26375,
            dividend_tax_rate=0.26375,
            reporting_date="2026-06-06",
        )
        synthetic_delta = result[result["isin"] == _SYND].iloc[0]
        # 34 × 130 = 4420; cost = 34 × 89.20 = 3032.80; gain = 1387.20
        assert synthetic_delta["market_value_eur"] == pytest.approx(4420.0, abs=0.01)
        assert synthetic_delta["unrealised_gain_eur"] == pytest.approx(1387.20, abs=0.01)

    def test_new_buy_adds_second_lot(self):
        lots = _initial_lots()
        new_tx = pd.DataFrame(
            [
                _tx(
                    isin=_SYND,
                    transaction_type="buy",
                    date="2026-03-01",
                    quantity=10.0,
                    price=110.0,
                    currency="EUR",
                    amount=1100.0,
                )
            ]
        )
        prices = {_SYND: 130.0, _SYN_ALPHA: 15.0}
        result = simulate_from_snapshot(
            initial_lots=lots,
            new_transactions=new_tx,
            current_prices_eur=prices,
            capital_gains_tax_rate=0.26375,
            dividend_tax_rate=0.26375,
            reporting_date="2026-06-06",
        )
        synthetic_delta = result[result["isin"] == _SYND].iloc[0]
        # (34 + 10) × 130 = 5720; cost = 34×89.20 + 10×110 = 3032.80 + 1100 = 4132.80
        assert synthetic_delta["market_value_eur"] == pytest.approx(5720.0, abs=0.01)
        assert synthetic_delta["unrealised_gain_eur"] == pytest.approx(1587.20, abs=0.01)

    def test_new_sell_reduces_lots_and_realises_gain(self):
        lots = _initial_lots()
        new_tx = pd.DataFrame(
            [
                _tx(
                    isin=_SYN_ALPHA,
                    transaction_type="sell",
                    date="2026-03-01",
                    quantity=50.0,
                    price=15.0,
                    currency="EUR",
                    amount=750.0,
                )
            ]
        )
        prices = {_SYND: 130.0, _SYN_ALPHA: 15.0}
        result = simulate_from_snapshot(
            initial_lots=lots,
            new_transactions=new_tx,
            current_prices_eur=prices,
            capital_gains_tax_rate=0.25,
            dividend_tax_rate=0.25,
            reporting_date="2026-06-06",
        )
        dbk = result[result["isin"] == _SYN_ALPHA].iloc[0]
        # Sold 50 @ 15 from lot @ 12.50 → gain = 50 × (15 - 12.50) = 125
        assert dbk["realised_gain_ytd_eur"] == pytest.approx(125.0, abs=0.01)
        assert dbk["tax_paid_ytd_eur"] == pytest.approx(31.25, abs=0.01)
        # Remaining: 50 shares × 15 = 750
        assert dbk["market_value_eur"] == pytest.approx(750.0, abs=0.01)

    def test_accepts_list_of_dicts_as_initial_lots(self):
        lots_list = _initial_lots().to_dict(orient="records")
        prices = {_SYND: 130.0, _SYN_ALPHA: 15.0}
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
        prices = {_SYND: 130.0}
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
        prices = {_SYND: 130.0}  # SYN_ALPHA missing
        result = simulate_from_snapshot(
            initial_lots=lots,
            new_transactions=_empty_txns(),
            current_prices_eur=prices,
            capital_gains_tax_rate=0.26375,
            dividend_tax_rate=0.26375,
            reporting_date="2026-06-06",
        )
        dbk = result[result["isin"] == _SYN_ALPHA]
        assert len(dbk) == 0  # ISINs absent from prices and with no realised gain are omitted


# ── fill_missing_prices_from_holdings ─────────────────────────────────────────


def _hld_df(rows: list[dict]) -> pd.DataFrame:
    """Build a minimal holdings DataFrame for fill_missing_prices tests."""
    defaults = {
        "date": "2026-06-06",
        "wkn": "SYN000",
        "asset_name": "Synthetic",
        "currency": "EUR",
        "jurisdiction": "DE",
        "cost_basis_eur": 100.0,
    }
    return pd.DataFrame([{**defaults, **r} for r in rows])


class TestFillMissingPricesFromHoldings:
    def test_missing_isin_gets_implied_price(self):
        hld = _hld_df(
            [{"isin": "DE00SYNTH001", "quantity": 10.0, "price": 50.0, "market_value": 500.0}]
        )
        result = fill_missing_prices_from_holdings({}, hld)
        assert result["DE00SYNTH001"] == pytest.approx(50.0)

    def test_existing_price_not_overwritten(self):
        hld = _hld_df(
            [{"isin": "DE00SYNTH001", "quantity": 10.0, "price": 50.0, "market_value": 500.0}]
        )
        result = fill_missing_prices_from_holdings({"DE00SYNTH001": 99.0}, hld)
        assert result["DE00SYNTH001"] == pytest.approx(99.0)

    def test_zero_quantity_row_skipped(self):
        hld = _hld_df(
            [{"isin": "DE00SYNTH001", "quantity": 0.0, "price": 0.0, "market_value": 0.0}]
        )
        result = fill_missing_prices_from_holdings({}, hld)
        assert "DE00SYNTH001" not in result

    def test_mixed_known_and_unknown(self):
        hld = _hld_df(
            [
                {"isin": "DE00SYNTH001", "quantity": 20.0, "price": 10.0, "market_value": 200.0},
                {"isin": "US00SYNTH002", "quantity": 5.0, "price": 40.0, "market_value": 200.0},
            ]
        )
        prices = {"DE00SYNTH001": 12.0}
        result = fill_missing_prices_from_holdings(prices, hld)
        assert result["DE00SYNTH001"] == pytest.approx(12.0)  # live price kept
        assert result["US00SYNTH002"] == pytest.approx(40.0)  # broker price filled

    def test_returns_new_dict_not_mutated(self):
        hld = _hld_df(
            [{"isin": "DE00SYNTH001", "quantity": 10.0, "price": 50.0, "market_value": 500.0}]
        )
        original = {}
        result = fill_missing_prices_from_holdings(original, hld)
        assert original == {}
        assert "DE00SYNTH001" in result


# ── Slice 1: ETF constituent providers ────────────────────────────────────────

# Synthetic iShares-style CSV (metadata rows + column headers + data rows).
_ISHARES_CSV = """\
"iShares Core MSCI Test UCITS ETF USD (Acc)"
"Fund Holdings as of","31/Dec/2025"
"Reporting Currency","EUR"
"Net Assets of Fund (EUR)","1,000,000,000"
""
"Name","ISIN","Asset Class","Market Value","Weight (%)","Shares","Price","Location"
"ASML HOLDING NV","NL0010273215","Equity","52,000,000","5.20","130000","400.00","Netherlands"
"APPLE INC","US0378331005","Equity","48,000,000","4.80","237000","202.35","United States"
"CASH AND/OR DERIVATIVES","","Cash","5,000,000","0.50","","","N/A"
"""

# Yahoo topHoldings JSON response (top 2 only, ~55% coverage).
_YAHOO_TOP_HOLDINGS = {
    "quoteSummary": {
        "result": [
            {
                "topHoldings": {
                    "asOfDate": {"raw": 1751241600, "fmt": "2025-06-30"},
                    "holdingsPercent": {"raw": 0.55},
                    "holdings": [
                        {
                            "symbol": "ASML",
                            "holdingName": "ASML Holding NV",
                            "holdingPercent": {"raw": 0.0520},
                        },
                        {
                            "symbol": "AAPL",
                            "holdingName": "Apple Inc",
                            "holdingPercent": {"raw": 0.0480},
                        },
                    ],
                }
            }
        ],
        "error": None,
    }
}


class TestCsvConstituentProvider:
    def _make_response(self, text: str) -> MagicMock:
        resp = MagicMock()
        resp.text = text
        resp.raise_for_status = MagicMock()
        return resp

    def test_parses_ishares_csv(self, tmp_path):
        provider = CsvConstituentProvider(
            url_map={"IE00TEST0001": "https://example.com/holdings.csv"},
            cache_dir=tmp_path,
        )
        with patch("portfolio_sim.requests.get", return_value=self._make_response(_ISHARES_CSV)):
            result = provider.get_constituents("IE00TEST0001")

        assert result.etf_isin == "IE00TEST0001"
        assert result.source == "csv"
        isins = [c.isin for c in result.constituents]
        assert "NL0010273215" in isins
        assert "US0378331005" in isins

    def test_weights_parsed_correctly(self, tmp_path):
        provider = CsvConstituentProvider(
            url_map={"IE00TEST0001": "https://example.com/holdings.csv"},
            cache_dir=tmp_path,
        )
        with patch("portfolio_sim.requests.get", return_value=self._make_response(_ISHARES_CSV)):
            result = provider.get_constituents("IE00TEST0001")

        asml = next(c for c in result.constituents if c.isin == "NL0010273215")
        assert asml.weight == pytest.approx(0.0520, abs=1e-4)

    def test_rows_without_isin_excluded_from_constituents(self, tmp_path):
        provider = CsvConstituentProvider(
            url_map={"IE00TEST0001": "https://example.com/holdings.csv"},
            cache_dir=tmp_path,
        )
        with patch("portfolio_sim.requests.get", return_value=self._make_response(_ISHARES_CSV)):
            result = provider.get_constituents("IE00TEST0001")

        assert all(c.isin for c in result.constituents)

    def test_coverage_pct_excludes_no_isin_rows(self, tmp_path):
        provider = CsvConstituentProvider(
            url_map={"IE00TEST0001": "https://example.com/holdings.csv"},
            cache_dir=tmp_path,
        )
        with patch("portfolio_sim.requests.get", return_value=self._make_response(_ISHARES_CSV)):
            result = provider.get_constituents("IE00TEST0001")

        # Total weight = 5.20 + 4.80 + 0.50 = 10.50; ISIN-covered = 10.00
        assert result.coverage_pct == pytest.approx(10.00 / 10.50, abs=1e-4)

    def test_as_of_parsed_from_csv(self, tmp_path):
        provider = CsvConstituentProvider(
            url_map={"IE00TEST0001": "https://example.com/holdings.csv"},
            cache_dir=tmp_path,
        )
        with patch("portfolio_sim.requests.get", return_value=self._make_response(_ISHARES_CSV)):
            result = provider.get_constituents("IE00TEST0001")

        assert result.as_of == "2025-12-31"

    def test_result_cached_to_disk(self, tmp_path):
        provider = CsvConstituentProvider(
            url_map={"IE00TEST0001": "https://example.com/holdings.csv"},
            cache_dir=tmp_path,
        )
        with patch(
            "portfolio_sim.requests.get", return_value=self._make_response(_ISHARES_CSV)
        ) as mock_get:
            provider.get_constituents("IE00TEST0001")
            provider.get_constituents("IE00TEST0001")  # second call

        # HTTP should only be fetched once; second call reads from disk cache
        mock_get.assert_called_once()

    def test_unknown_isin_raises_key_error(self, tmp_path):
        provider = CsvConstituentProvider(url_map={}, cache_dir=tmp_path)
        with pytest.raises(KeyError):
            provider.get_constituents("IE00UNKNOWN0")

    def test_staleness_flag_when_over_90_days(self, tmp_path):
        provider = CsvConstituentProvider(
            url_map={"IE00TEST0001": "https://example.com/holdings.csv"},
            cache_dir=tmp_path,
        )
        with patch("portfolio_sim.requests.get", return_value=self._make_response(_ISHARES_CSV)):
            result = provider.get_constituents("IE00TEST0001")

        # holdings as_of = 2025-12-31; snapshot 2026-06-07 = 158 days later → stale
        assert result.is_stale(snapshot_date="2026-06-07") is True

    def test_no_staleness_flag_within_90_days(self, tmp_path):
        provider = CsvConstituentProvider(
            url_map={"IE00TEST0001": "https://example.com/holdings.csv"},
            cache_dir=tmp_path,
        )
        with patch("portfolio_sim.requests.get", return_value=self._make_response(_ISHARES_CSV)):
            result = provider.get_constituents("IE00TEST0001")

        # 2026-01-15 is only 15 days after 2025-12-31 → not stale
        assert result.is_stale(snapshot_date="2026-01-15") is False


class TestYahooTopHoldingsProvider:
    def _make_response(self, payload: dict) -> MagicMock:
        resp = MagicMock()
        resp.json = MagicMock(return_value=payload)
        resp.raise_for_status = MagicMock()
        return resp

    def test_returns_top_holdings(self):
        provider = YahooTopHoldingsProvider(isin_to_ticker={"IE00TEST0001": "IWDA.AS"})
        with patch(
            "portfolio_sim.requests.get", return_value=self._make_response(_YAHOO_TOP_HOLDINGS)
        ):
            result = provider.get_constituents("IE00TEST0001")

        assert result.etf_isin == "IE00TEST0001"
        assert result.source == "yahoo_top_holdings"
        assert len(result.constituents) == 2

    def test_weights_from_holdingPercent(self):
        provider = YahooTopHoldingsProvider(isin_to_ticker={"IE00TEST0001": "IWDA.AS"})
        with patch(
            "portfolio_sim.requests.get", return_value=self._make_response(_YAHOO_TOP_HOLDINGS)
        ):
            result = provider.get_constituents("IE00TEST0001")

        names = {c.name: c.weight for c in result.constituents}
        assert names["ASML Holding NV"] == pytest.approx(0.0520, abs=1e-4)

    def test_coverage_pct_from_holdingsPercent(self):
        provider = YahooTopHoldingsProvider(isin_to_ticker={"IE00TEST0001": "IWDA.AS"})
        with patch(
            "portfolio_sim.requests.get", return_value=self._make_response(_YAHOO_TOP_HOLDINGS)
        ):
            result = provider.get_constituents("IE00TEST0001")

        assert result.coverage_pct == pytest.approx(0.55, abs=1e-4)

    def test_isin_none_when_no_reverse_map(self):
        provider = YahooTopHoldingsProvider(isin_to_ticker={"IE00TEST0001": "IWDA.AS"})
        with patch(
            "portfolio_sim.requests.get", return_value=self._make_response(_YAHOO_TOP_HOLDINGS)
        ):
            result = provider.get_constituents("IE00TEST0001")

        assert all(c.isin is None for c in result.constituents)

    def test_isin_resolved_via_reverse_ticker_map(self):
        reverse = {"ASML": "NL0010273215"}
        provider = YahooTopHoldingsProvider(
            isin_to_ticker={"IE00TEST0001": "IWDA.AS"},
            reverse_ticker_map=reverse,
        )
        with patch(
            "portfolio_sim.requests.get", return_value=self._make_response(_YAHOO_TOP_HOLDINGS)
        ):
            result = provider.get_constituents("IE00TEST0001")

        asml = next(c for c in result.constituents if c.name == "ASML Holding NV")
        assert asml.isin == "NL0010273215"

    def test_unknown_isin_raises_key_error(self):
        provider = YahooTopHoldingsProvider(isin_to_ticker={})
        with pytest.raises(KeyError):
            provider.get_constituents("IE00UNKNOWN0")


class TestChainedConstituentProvider:
    def test_returns_first_provider_result(self, tmp_path):
        good = CsvConstituentProvider(
            url_map={"IE00TEST0001": "https://example.com/holdings.csv"},
            cache_dir=tmp_path,
        )
        fallback = YahooTopHoldingsProvider(isin_to_ticker={"IE00TEST0001": "IWDA.AS"})
        chained = ChainedConstituentProvider([good, fallback])

        with patch("portfolio_sim.requests.get") as mock_get:

            def side_effect(url, **kwargs):
                resp = MagicMock()
                resp.raise_for_status = MagicMock()
                resp.text = _ISHARES_CSV
                return resp

            mock_get.side_effect = side_effect
            result = chained.get_constituents("IE00TEST0001")

        assert result.source == "csv"

    def test_falls_through_to_second_on_key_error(self):
        no_url = CsvConstituentProvider(url_map={})
        fallback = YahooTopHoldingsProvider(isin_to_ticker={"IE00TEST0001": "IWDA.AS"})
        chained = ChainedConstituentProvider([no_url, fallback])

        with patch("portfolio_sim.requests.get") as mock_get:
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json = MagicMock(return_value=_YAHOO_TOP_HOLDINGS)
            mock_get.return_value = resp
            result = chained.get_constituents("IE00TEST0001")

        assert result.source == "yahoo_top_holdings"

    def test_raises_key_error_when_all_fail(self):
        chained = ChainedConstituentProvider(
            [
                CsvConstituentProvider(url_map={}),
                YahooTopHoldingsProvider(isin_to_ticker={}),
            ]
        )
        with pytest.raises(KeyError):
            chained.get_constituents("IE00UNKNOWN0")


# ── Slice 2: Security metadata provider ───────────────────────────────────────

# Synthetic Yahoo quoteSummary response for a stock (ASML-like).
_YAHOO_STOCK_SUMMARY = {
    "quoteSummary": {
        "result": [
            {
                "assetProfile": {
                    "sector": "Technology",
                    "industry": "Semiconductor Equipment & Materials",
                    "country": "Netherlands",
                },
                "defaultKeyStatistics": {
                    "beta": {"raw": 1.15},
                },
                "summaryDetail": {
                    "marketCap": {"raw": 250_000_000_000},  # ~€250B
                },
                "price": {
                    "quoteType": {"longValue": "EQUITY"},
                },
            }
        ],
        "error": None,
    }
}

# Synthetic Yahoo response for an accumulating ETF (IWDA-like).
_YAHOO_ETF_SUMMARY = {
    "quoteSummary": {
        "result": [
            {
                "assetProfile": {
                    "sector": None,
                    "industry": None,
                    "country": "Ireland",
                },
                "defaultKeyStatistics": {
                    "beta": {"raw": 0.98},
                },
                "summaryDetail": {
                    "marketCap": {"raw": 84_000_000_000},
                },
                "price": {
                    "quoteType": {"longValue": "ETF"},
                },
            }
        ],
        "error": None,
    }
}


class TestYahooFinanceMetadataProvider:
    def _make_response(self, payload: dict) -> MagicMock:
        resp = MagicMock()
        resp.json = MagicMock(return_value=payload)
        resp.raise_for_status = MagicMock()
        return resp

    def test_imports(self):
        from portfolio_sim import SecurityMetadata, YahooFinanceMetadataProvider  # noqa: F401

    def test_returns_sector_country_industry(self, tmp_path):
        from portfolio_sim import YahooFinanceMetadataProvider

        provider = YahooFinanceMetadataProvider(
            isin_to_ticker={"NL0010273215": "ASML.AS"},
            cache_path=tmp_path / "meta.json",
        )
        with patch(
            "portfolio_sim.requests.get", return_value=self._make_response(_YAHOO_STOCK_SUMMARY)
        ):
            meta = provider.get_metadata("NL0010273215")

        assert meta.sector == "Technology"
        assert meta.country == "Netherlands"
        assert meta.industry == "Semiconductor Equipment & Materials"

    def test_beta_returned(self, tmp_path):
        from portfolio_sim import YahooFinanceMetadataProvider

        provider = YahooFinanceMetadataProvider(
            isin_to_ticker={"NL0010273215": "ASML.AS"},
            cache_path=tmp_path / "meta.json",
        )
        with patch(
            "portfolio_sim.requests.get", return_value=self._make_response(_YAHOO_STOCK_SUMMARY)
        ):
            meta = provider.get_metadata("NL0010273215")

        assert meta.beta == pytest.approx(1.15, abs=1e-4)

    def test_market_cap_tier_large(self, tmp_path):
        from portfolio_sim import YahooFinanceMetadataProvider

        provider = YahooFinanceMetadataProvider(
            isin_to_ticker={"NL0010273215": "ASML.AS"},
            cache_path=tmp_path / "meta.json",
        )
        with patch(
            "portfolio_sim.requests.get", return_value=self._make_response(_YAHOO_STOCK_SUMMARY)
        ):
            meta = provider.get_metadata("NL0010273215")

        assert meta.market_cap_tier == "Large"  # >€10B

    def test_etf_domicile_from_isin_prefix(self, tmp_path):
        from portfolio_sim import YahooFinanceMetadataProvider

        provider = YahooFinanceMetadataProvider(
            isin_to_ticker={"IE00B4L5Y983": "IWDA.AS"},
            cache_path=tmp_path / "meta.json",
        )
        with patch(
            "portfolio_sim.requests.get", return_value=self._make_response(_YAHOO_ETF_SUMMARY)
        ):
            meta = provider.get_metadata("IE00B4L5Y983")

        assert meta.etf_domicile == "Ireland"

    def test_etf_structure_from_override_map(self, tmp_path):
        from portfolio_sim import YahooFinanceMetadataProvider

        provider = YahooFinanceMetadataProvider(
            isin_to_ticker={"IE00B4L5Y983": "IWDA.AS"},
            cache_path=tmp_path / "meta.json",
            etf_structure_overrides={"IE00B4L5Y983": "accumulating"},
        )
        with patch(
            "portfolio_sim.requests.get", return_value=self._make_response(_YAHOO_ETF_SUMMARY)
        ):
            meta = provider.get_metadata("IE00B4L5Y983")

        assert meta.etf_structure == "accumulating"

    def test_etf_structure_heuristic_fallback(self, tmp_path):
        from portfolio_sim import YahooFinanceMetadataProvider, _YahooTickerCache

        # No override; ticker name contains "(Acc)" → heuristic picks it up.
        # Use a fresh ticker cache so a previous test's cached payload doesn't
        # interfere with the longName heuristic.
        summary = {
            "quoteSummary": {
                "result": [
                    {
                        "assetProfile": {"sector": None, "industry": None, "country": "Ireland"},
                        "defaultKeyStatistics": {"beta": {"raw": 0.98}},
                        "summaryDetail": {"marketCap": {"raw": 84_000_000_000}},
                        "price": {
                            "quoteType": {"longValue": "ETF"},
                            "longName": "iShares Core MSCI World UCITS ETF USD (Acc)",
                        },
                    }
                ],
                "error": None,
            }
        }
        provider = YahooFinanceMetadataProvider(
            isin_to_ticker={"IE00B4L5Y983": "IWDA.AS"},
            cache_path=tmp_path / "meta.json",
            ticker_cache=_YahooTickerCache(),  # isolated from module-level cache
        )
        with patch("portfolio_sim.requests.get", return_value=self._make_response(summary)):
            meta = provider.get_metadata("IE00B4L5Y983")

        assert meta.etf_structure == "accumulating"

    def test_result_cached_to_disk(self, tmp_path):
        from portfolio_sim import YahooFinanceMetadataProvider, _YahooTickerCache

        cache = tmp_path / "meta.json"
        provider = YahooFinanceMetadataProvider(
            isin_to_ticker={"NL0010273215": "ASML.AS"},
            cache_path=cache,
            ticker_cache=_YahooTickerCache(),  # isolated so HTTP call always fires on first fetch
        )
        with patch(
            "portfolio_sim.requests.get", return_value=self._make_response(_YAHOO_STOCK_SUMMARY)
        ) as mock_get:
            provider.get_metadata("NL0010273215")
            provider.get_metadata("NL0010273215")  # second call reads from disk cache

        mock_get.assert_called_once()

    def test_ticker_fetched_once_per_session(self, tmp_path):
        """_YahooTickerCache: same ticker shared across two provider instances."""
        from portfolio_sim import YahooFinanceMetadataProvider, _YahooTickerCache

        cache = _YahooTickerCache()
        p1 = YahooFinanceMetadataProvider(
            isin_to_ticker={"NL0010273215": "ASML.AS"},
            cache_path=tmp_path / "meta.json",
            ticker_cache=cache,
        )
        p2 = YahooFinanceMetadataProvider(
            isin_to_ticker={"NL0010273215": "ASML.AS"},
            cache_path=tmp_path / "meta2.json",
            ticker_cache=cache,
        )
        with patch(
            "portfolio_sim.requests.get", return_value=self._make_response(_YAHOO_STOCK_SUMMARY)
        ) as mock_get:
            p1.get_metadata("NL0010273215")
            p2.get_metadata("NL0010273215")

        # Both providers share the cache → only one HTTP call total
        mock_get.assert_called_once()

    def test_unknown_isin_raises_key_error(self, tmp_path):
        from portfolio_sim import YahooFinanceMetadataProvider

        provider = YahooFinanceMetadataProvider(
            isin_to_ticker={},
            cache_path=tmp_path / "meta.json",
        )
        with pytest.raises(KeyError):
            provider.get_metadata("XX00UNKNOWN0")


# ── Slice 3: Look-through aggregation ─────────────────────────────────────────


def _meta(
    isin,
    sector="Technology",
    country="Netherlands",
    industry="Semiconductors",
    market_cap_tier="Large",
    beta=1.1,
    etf_structure="unknown",
    etf_domicile=None,
):
    from portfolio_sim import SecurityMetadata

    return SecurityMetadata(
        isin=isin,
        ticker=None,
        sector=sector,
        country=country,
        industry=industry,
        market_cap_eur=50_000_000_000,
        market_cap_tier=market_cap_tier,
        beta=beta,
        etf_structure=etf_structure,
        etf_domicile=etf_domicile or isin[:2],
    )


def _make_stub_metadata_provider(metas: list):
    from portfolio_sim import YahooFinanceMetadataProvider

    provider = MagicMock(spec=YahooFinanceMetadataProvider)
    lookup = {m.isin: m for m in metas}
    provider.get_metadata.side_effect = lambda isin: lookup[isin]
    return provider


def _make_stub_constituent_provider(results: list):
    from portfolio_sim import ETFConstituentProvider

    provider = MagicMock(spec=ETFConstituentProvider)
    lookup = {r.etf_isin: r for r in results}

    def _get(isin):
        if isin not in lookup:
            raise KeyError(isin)
        return lookup[isin]

    provider.get_constituents.side_effect = _get
    return provider


def _holdings_df(rows: list[dict]) -> pd.DataFrame:
    defaults = {
        "date": "2025-12-31",
        "wkn": "",
        "asset_name": "Test",
        "currency": "EUR",
        "jurisdiction": "NL",
    }
    out = []
    for r in rows:
        row = {**defaults, **r}
        row.setdefault("market_value", row["quantity"] * row["price"])
        out.append(row)
    return pd.DataFrame(out)


class TestAggregatePortfolioComposition:
    def test_imports(self):
        from portfolio_sim import CompositionResult, aggregate_portfolio_composition  # noqa: F401

    def test_direct_holding_appears_with_full_weight(self):
        from portfolio_sim import aggregate_portfolio_composition

        hld = _holdings_df(
            [
                {"isin": "NL0010273215", "quantity": 10, "price": 400.0},  # ASML €4000
                {"isin": "US0378331005", "quantity": 5, "price": 200.0},  # Apple €1000
            ]
        )
        meta_provider = _make_stub_metadata_provider(
            [
                _meta("NL0010273215"),
                _meta("US0378331005"),
            ]
        )
        const_provider = _make_stub_constituent_provider([])  # no ETFs

        result = aggregate_portfolio_composition(hld, const_provider, meta_provider)
        df = result.securities

        asml = df[df["isin"] == "NL0010273215"].iloc[0]
        assert asml["total_weight_pct"] == pytest.approx(4000 / 5000 * 100, abs=1e-4)
        assert asml["direct_weight_pct"] == pytest.approx(4000 / 5000 * 100, abs=1e-4)
        assert asml["etf_weight_pct"] == pytest.approx(0.0, abs=1e-6)

    def test_etf_constituents_expand_into_look_through_rows(self):
        from portfolio_sim import aggregate_portfolio_composition

        # Portfolio: €10000 ASML direct + €20000 ETF (ETF is 10% ASML, 90% covered)
        hld = _holdings_df(
            [
                {"isin": "NL0010273215", "quantity": 25, "price": 400.0},  # €10000 direct
                {"isin": "IE00ETF00001", "quantity": 100, "price": 200.0},  # €20000 ETF
            ]
        )
        etf_result = ConstituentResult(
            etf_isin="IE00ETF00001",
            constituents=[
                ConstituentRow(isin="NL0010273215", ticker=None, name="ASML", weight=0.10),
                ConstituentRow(isin="US0378331005", ticker=None, name="Apple", weight=0.80),
            ],
            coverage_pct=0.90,
            as_of="2025-12-31",
            source="csv",
        )
        meta_provider = _make_stub_metadata_provider(
            [
                _meta("NL0010273215"),
                _meta("US0378331005"),
                _meta("IE00ETF00001", etf_structure="accumulating"),
            ]
        )
        const_provider = _make_stub_constituent_provider([etf_result])

        result = aggregate_portfolio_composition(hld, const_provider, meta_provider)
        df = result.securities

        total_portfolio = 10000 + 20000  # €30000
        asml = df[df["isin"] == "NL0010273215"].iloc[0]
        # direct: €10000; via ETF: €20000 * 10% = €2000; total: €12000
        assert asml["direct_weight_pct"] == pytest.approx(10000 / total_portfolio * 100, abs=1e-4)
        assert asml["etf_weight_pct"] == pytest.approx(2000 / total_portfolio * 100, abs=1e-4)
        assert asml["total_weight_pct"] == pytest.approx(12000 / total_portfolio * 100, abs=1e-4)

    def test_unresolved_residual_row_for_etf(self):
        from portfolio_sim import aggregate_portfolio_composition

        # ETF coverage 90% → 10% unresolved
        hld = _holdings_df(
            [
                {"isin": "IE00ETF00001", "quantity": 100, "price": 100.0},  # €10000
            ]
        )
        etf_result = ConstituentResult(
            etf_isin="IE00ETF00001",
            constituents=[
                ConstituentRow(isin="NL0010273215", ticker=None, name="ASML", weight=0.90),
            ],
            coverage_pct=0.90,
            as_of="2025-12-31",
            source="csv",
        )
        meta_provider = _make_stub_metadata_provider(
            [
                _meta("NL0010273215"),
                _meta("IE00ETF00001"),
            ]
        )
        const_provider = _make_stub_constituent_provider([etf_result])

        result = aggregate_portfolio_composition(hld, const_provider, meta_provider)
        df = result.securities

        unresolved = df[df["isin"] == "_UNRESOLVED_"]
        assert not unresolved.empty
        # unresolved weight = €10000 * 10% = €1000 → 10% of portfolio
        assert unresolved.iloc[0]["total_weight_pct"] == pytest.approx(10.0, abs=1e-4)

    def test_weights_sum_to_100(self):
        from portfolio_sim import aggregate_portfolio_composition

        hld = _holdings_df(
            [
                {"isin": "NL0010273215", "quantity": 10, "price": 400.0},
                {"isin": "IE00ETF00001", "quantity": 50, "price": 200.0},
            ]
        )
        etf_result = ConstituentResult(
            etf_isin="IE00ETF00001",
            constituents=[
                ConstituentRow(isin="US0378331005", ticker=None, name="Apple", weight=0.80),
            ],
            coverage_pct=0.80,
            as_of="2025-12-31",
            source="csv",
        )
        meta_provider = _make_stub_metadata_provider(
            [
                _meta("NL0010273215"),
                _meta("US0378331005"),
                _meta("IE00ETF00001"),
            ]
        )
        const_provider = _make_stub_constituent_provider([etf_result])

        result = aggregate_portfolio_composition(hld, const_provider, meta_provider)
        total = result.securities["total_weight_pct"].sum()
        assert total == pytest.approx(100.0, abs=1e-3)

    def test_etf_coverage_summary_populated(self):
        from portfolio_sim import aggregate_portfolio_composition

        hld = _holdings_df(
            [
                {"isin": "IE00ETF00001", "quantity": 100, "price": 100.0},
            ]
        )
        etf_result = ConstituentResult(
            etf_isin="IE00ETF00001",
            constituents=[
                ConstituentRow(isin="NL0010273215", ticker=None, name="ASML", weight=0.75),
            ],
            coverage_pct=0.75,
            as_of="2025-12-31",
            source="csv",
        )
        meta_provider = _make_stub_metadata_provider(
            [
                _meta("NL0010273215"),
                _meta("IE00ETF00001"),
            ]
        )
        const_provider = _make_stub_constituent_provider([etf_result])

        result = aggregate_portfolio_composition(hld, const_provider, meta_provider)
        cov = result.etf_coverage

        assert "IE00ETF00001" in cov["etf_isin"].values
        row = cov[cov["etf_isin"] == "IE00ETF00001"].iloc[0]
        assert row["coverage_pct"] == pytest.approx(0.75, abs=1e-4)

    def test_metadata_attached_to_security_rows(self):
        from portfolio_sim import aggregate_portfolio_composition

        hld = _holdings_df(
            [
                {"isin": "NL0010273215", "quantity": 10, "price": 400.0},
            ]
        )
        meta_provider = _make_stub_metadata_provider(
            [
                _meta("NL0010273215", sector="Technology", country="Netherlands"),
            ]
        )
        const_provider = _make_stub_constituent_provider([])

        result = aggregate_portfolio_composition(hld, const_provider, meta_provider)
        row = result.securities[result.securities["isin"] == "NL0010273215"].iloc[0]
        assert row["sector"] == "Technology"
        assert row["country"] == "Netherlands"


# ── Slice 4: Dimension breakdown functions ────────────────────────────────────


def _composition_df(rows: list[dict]) -> pd.DataFrame:
    """Build a minimal securities DataFrame for breakdown tests."""
    defaults = {
        "direct_weight_pct": 0.0,
        "etf_weight_pct": 0.0,
        "name": "Test",
        "sector": None,
        "industry": None,
        "country": None,
        "market_cap_tier": "Large",
        "beta": 1.0,
        "etf_structure": "unknown",
        "etf_domicile": None,
    }
    out = []
    for r in rows:
        row = {**defaults, **r}
        if "total_weight_pct" not in r:
            row["total_weight_pct"] = row["direct_weight_pct"] + row["etf_weight_pct"]
        out.append(row)
    return pd.DataFrame(out)


class TestBreakdownFunctions:
    def test_imports(self):
        from portfolio_sim import (  # noqa: F401
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

    def test_sector_groups_correctly(self):
        from portfolio_sim import breakdown_by_sector

        df = _composition_df(
            [
                {"isin": "A", "sector": "Technology", "total_weight_pct": 60.0},
                {"isin": "B", "sector": "Technology", "total_weight_pct": 20.0},
                {"isin": "C", "sector": "Financials", "total_weight_pct": 20.0},
            ]
        )
        result = breakdown_by_sector(df)
        tech = result[result["dimension_value"] == "Technology"].iloc[0]
        assert tech["weight_pct"] == pytest.approx(80.0, abs=1e-4)

    def test_sector_null_labelled_unknown(self):
        from portfolio_sim import breakdown_by_sector

        df = _composition_df(
            [
                {"isin": "A", "sector": None, "total_weight_pct": 100.0},
            ]
        )
        result = breakdown_by_sector(df)
        assert "Unknown" in result["dimension_value"].values

    def test_region_groups_country_to_continent(self):
        from portfolio_sim import breakdown_by_region

        df = _composition_df(
            [
                {"isin": "A", "country": "Netherlands", "total_weight_pct": 50.0},
                {"isin": "B", "country": "Germany", "total_weight_pct": 30.0},
                {"isin": "C", "country": "United States", "total_weight_pct": 20.0},
            ]
        )
        result = breakdown_by_region(df)
        europe = result[result["dimension_value"] == "Europe"].iloc[0]
        assert europe["weight_pct"] == pytest.approx(80.0, abs=1e-4)

    def test_market_cap_tier_groups_correctly(self):
        from portfolio_sim import breakdown_by_market_cap_tier

        df = _composition_df(
            [
                {"isin": "A", "market_cap_tier": "Large", "total_weight_pct": 70.0},
                {"isin": "B", "market_cap_tier": "Small", "total_weight_pct": 30.0},
            ]
        )
        result = breakdown_by_market_cap_tier(df)
        large = result[result["dimension_value"] == "Large"].iloc[0]
        assert large["weight_pct"] == pytest.approx(70.0, abs=1e-4)

    def test_beta_bucket_labels_include_benchmark(self):
        from portfolio_sim import breakdown_by_beta_bucket

        df = _composition_df(
            [
                {"isin": "A", "beta": 0.5, "total_weight_pct": 40.0},
                {"isin": "B", "beta": 1.0, "total_weight_pct": 60.0},
            ]
        )
        result = breakdown_by_beta_bucket(df)
        labels = result["dimension_value"].tolist()
        assert any("S&P 500" in lbl for lbl in labels)

    def test_beta_bucket_low_high_market(self):
        from portfolio_sim import breakdown_by_beta_bucket

        df = _composition_df(
            [
                {"isin": "A", "beta": 0.5, "total_weight_pct": 20.0},  # low <0.8
                {"isin": "B", "beta": 1.0, "total_weight_pct": 50.0},  # market 0.8–1.2
                {"isin": "C", "beta": 1.5, "total_weight_pct": 30.0},  # high >1.2
            ]
        )
        result = breakdown_by_beta_bucket(df)
        labels = result["dimension_value"].tolist()
        assert any("Low" in lbl for lbl in labels)
        assert any("Market" in lbl for lbl in labels)
        assert any("High" in lbl for lbl in labels)

    def test_etf_structure_breakdown(self):
        from portfolio_sim import breakdown_by_etf_structure

        df = _composition_df(
            [
                {"isin": "A", "etf_structure": "accumulating", "total_weight_pct": 60.0},
                {"isin": "B", "etf_structure": "distributing", "total_weight_pct": 40.0},
            ]
        )
        result = breakdown_by_etf_structure(df)
        acc = result[result["dimension_value"] == "accumulating"].iloc[0]
        assert acc["weight_pct"] == pytest.approx(60.0, abs=1e-4)

    def test_etf_domicile_breakdown(self):
        from portfolio_sim import breakdown_by_etf_domicile

        df = _composition_df(
            [
                {"isin": "A", "etf_domicile": "Ireland", "total_weight_pct": 70.0},
                {"isin": "B", "etf_domicile": "Luxembourg", "total_weight_pct": 30.0},
            ]
        )
        result = breakdown_by_etf_domicile(df)
        ie = result[result["dimension_value"] == "Ireland"].iloc[0]
        assert ie["weight_pct"] == pytest.approx(70.0, abs=1e-4)

    def test_currency_breakdown(self):
        from portfolio_sim import breakdown_by_currency

        # breakdown_by_currency takes holdings_df (not securities_df)
        hld = pd.DataFrame(
            [
                {"isin": "A", "currency": "EUR", "market_value": 6000.0},
                {"isin": "B", "currency": "USD", "market_value": 4000.0},
            ]
        )
        result = breakdown_by_currency(hld)
        eur = result[result["dimension_value"] == "EUR"].iloc[0]
        assert eur["weight_pct"] == pytest.approx(60.0, abs=1e-4)

    def test_asset_class_breakdown(self):
        from portfolio_sim import breakdown_by_asset_class

        # ISINs with IE prefix → ETF; others → Equity
        df = _composition_df(
            [
                {"isin": "IE00TEST0001", "total_weight_pct": 40.0},
                {"isin": "NL0010273215", "total_weight_pct": 60.0},
            ]
        )
        result = breakdown_by_asset_class(df)
        equity = result[result["dimension_value"] == "Equity"].iloc[0]
        assert equity["weight_pct"] == pytest.approx(60.0, abs=1e-4)

    def test_breakdown_result_has_required_columns(self):
        from portfolio_sim import breakdown_by_sector

        df = _composition_df([{"isin": "A", "sector": "Technology", "total_weight_pct": 100.0}])
        result = breakdown_by_sector(df)
        assert "dimension_value" in result.columns
        assert "weight_pct" in result.columns


# ── Slice 5: portfolio_composition script smoke test ──────────────────────────


class TestPortfolioCompositionScript:
    def test_script_runs_with_synthetic_holdings(self, tmp_path):
        """Smoke test: script accepts a holdings CSV and writes output files."""
        import subprocess
        import sys

        # Write a minimal synthetic holdings CSV
        holdings_csv = tmp_path / "holdings.csv"
        holdings_csv.write_text(
            "date,isin,wkn,asset_name,quantity,price,currency,market_value,jurisdiction\n"
            "2025-12-31,NL0010273215,,ASML Holding NV,10,400.0,EUR,4000.0,NL\n"
            "2025-12-31,US0378331005,,Apple Inc,5,200.0,EUR,1000.0,US\n"
        )
        # Write a minimal ticker map
        ticker_map = tmp_path / "ticker_map.json"
        ticker_map.write_text('{"NL0010273215": "ASML.AS", "US0378331005": "AAPL"}')

        output_dir = tmp_path / "out"
        output_dir.mkdir()

        script = Path(__file__).parent.parent / "scripts" / "portfolio_composition.py"
        result = subprocess.run(
            [
                sys.executable,
                str(script),
                "--holdings",
                str(holdings_csv),
                "--ticker-map",
                str(ticker_map),
                "--output-dir",
                str(output_dir),
                "--no-fetch",
            ],
            capture_output=True,
            text=True,
            timeout=60,
            env={
                **__import__("os").environ,
                "PYTHONPATH": str(Path(__file__).parent.parent / "src"),
            },
        )
        assert result.returncode == 0, f"Script failed:\n{result.stderr}"
        # Verify output files were written
        output_files = list(output_dir.glob("*.csv"))
        assert len(output_files) >= 5, f"Expected at least 5 output files, got {output_files}"
