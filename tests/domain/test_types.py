from datetime import UTC, datetime

import pytest

from tradebot.domain import Bar, Fill, Order, OrderStatus, OrderType, Side, Signal

T0 = datetime(2024, 1, 2, tzinfo=UTC)


def make_bar(**overrides: object) -> Bar:
    fields: dict[str, object] = {
        "symbol": "SPY",
        "timestamp": T0,
        "open": 100.0,
        "high": 102.0,
        "low": 99.0,
        "close": 101.0,
        "volume": 1_000.0,
    }
    fields.update(overrides)
    return Bar(**fields)  # type: ignore[arg-type]


class TestBar:
    def test_valid_bar(self) -> None:
        bar = make_bar()
        assert bar.close == 101.0

    @pytest.mark.parametrize(
        "overrides",
        [
            {"high": 100.5},  # high < close
            {"low": 100.5},  # low > open
            {"high": 98.0},  # high < low
            {"open": 0.0},
            {"close": -1.0},
            {"close": float("nan")},
            {"volume": -1.0},
            {"symbol": "spy"},
            {"symbol": ""},
            {"timestamp": datetime(2024, 1, 2)},  # sans fuseau
        ],
    )
    def test_invalid_bar(self, overrides: dict[str, object]) -> None:
        with pytest.raises(ValueError):
            make_bar(**overrides)

    def test_bar_is_immutable(self) -> None:
        bar = make_bar()
        with pytest.raises(AttributeError):
            bar.close = 1.0  # type: ignore[misc]


class TestSignal:
    @pytest.mark.parametrize("weight", [-1.0, 0.0, 0.5, 1.0])
    def test_valid_weights(self, weight: float) -> None:
        assert Signal("SPY", T0, weight).target_weight == weight

    @pytest.mark.parametrize("weight", [1.5, -1.01, float("nan"), float("inf")])
    def test_invalid_weights(self, weight: float) -> None:
        with pytest.raises(ValueError):
            Signal("SPY", T0, weight)


class TestOrder:
    def test_market_order(self) -> None:
        order = Order("id-1", "SPY", Side.BUY, 1.5, T0)
        assert order.order_type is OrderType.MARKET
        assert order.limit_price is None

    def test_limit_order_requires_price(self) -> None:
        with pytest.raises(ValueError, match="limit_price"):
            Order("id-1", "SPY", Side.BUY, 1, T0, OrderType.LIMIT)
        order = Order("id-1", "SPY", Side.BUY, 1, T0, OrderType.LIMIT, 99.5)
        assert order.limit_price == 99.5

    def test_market_order_rejects_limit_price(self) -> None:
        with pytest.raises(ValueError):
            Order("id-1", "SPY", Side.BUY, 1, T0, OrderType.MARKET, 99.5)

    @pytest.mark.parametrize("quantity", [0.0, -1.0, float("nan")])
    def test_quantity_must_be_positive(self, quantity: float) -> None:
        # Le sens est porté par `side`, jamais par le signe de la quantité.
        with pytest.raises(ValueError):
            Order("id-1", "SPY", Side.SELL, quantity, T0)

    def test_empty_client_order_id(self) -> None:
        with pytest.raises(ValueError):
            Order("  ", "SPY", Side.BUY, 1, T0)

    def test_terminal_statuses(self) -> None:
        terminal = {s for s in OrderStatus if s.is_terminal}
        assert terminal == {OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED}


class TestFill:
    def test_signed_quantity_and_notional(self) -> None:
        buy = Fill("o1", "SPY", Side.BUY, 2, 100.0, T0, commission=0.5)
        sell = Fill("o2", "SPY", Side.SELL, 2, 100.0, T0)
        assert buy.signed_quantity == 2
        assert sell.signed_quantity == -2
        assert buy.notional == 200.0

    def test_negative_commission_rejected(self) -> None:
        with pytest.raises(ValueError):
            Fill("o1", "SPY", Side.BUY, 1, 100.0, T0, commission=-0.1)
