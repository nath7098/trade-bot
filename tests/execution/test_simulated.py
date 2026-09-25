from datetime import UTC, datetime, timedelta

import pytest

from tradebot.domain import Bar, Order, OrderStatus, OrderType, Side
from tradebot.execution import PRESETS, CostModel, SimulatedBroker

T0 = datetime(2024, 1, 2, 5, tzinfo=UTC)
T1 = T0 + timedelta(days=1)
FREE = PRESETS["zero"]


def bar(
    symbol: str = "SPY",
    open_: float = 100.0,
    high: float | None = None,
    low: float | None = None,
    close: float = 102.0,
    ts: datetime = T1,
) -> Bar:
    high = high if high is not None else max(open_, close) * 1.05
    low = low if low is not None else min(open_, close) * 0.95
    return Bar(symbol, ts, open_, high, low, close, 1e6)


def order(
    oid: str,
    side: Side,
    qty: float,
    symbol: str = "SPY",
    limit: float | None = None,
) -> Order:
    kind = OrderType.LIMIT if limit is not None else OrderType.MARKET
    return Order(oid, symbol, side, qty, T0, kind, limit)


def test_market_order_fills_at_next_open_with_slippage_and_fees() -> None:
    costs = CostModel(commission_min=1.0, slippage_bps=10)
    broker = SimulatedBroker(1_000, costs)
    broker.submit(order("o1", Side.BUY, 2))
    assert broker.status("o1") is OrderStatus.SUBMITTED

    (fill,) = broker.process_bar({"SPY": bar(open_=100)})
    assert fill.price == pytest.approx(100.1)
    assert fill.timestamp == T1
    assert fill.commission == pytest.approx(1.0)
    assert broker.status("o1") is OrderStatus.FILLED
    assert broker.portfolio.cash == pytest.approx(1_000 - 200.2 - 1.0)


def test_insufficient_cash_is_rejected() -> None:
    broker = SimulatedBroker(100, FREE)
    broker.submit(order("o1", Side.BUY, 2))
    assert broker.process_bar({"SPY": bar(open_=60)}) == []
    assert broker.status("o1") is OrderStatus.REJECTED
    assert "cash insuffisant" in broker.rejected[0].reason
    assert broker.portfolio.cash == 100


def test_sells_are_processed_before_buys() -> None:
    broker = SimulatedBroker(100, FREE)
    broker.submit(order("buy-spy", Side.BUY, 1))
    broker.process_bar({"SPY": bar(open_=90)})
    # Plus assez de cash pour QQQ... sauf si la vente de SPY passe d'abord.
    broker.submit(order("buy-qqq", Side.BUY, 1, symbol="QQQ"))
    broker.submit(order("sell-spy", Side.SELL, 1))
    fills = broker.process_bar({"SPY": bar(open_=90), "QQQ": bar("QQQ", open_=95)})
    assert [f.order_id for f in fills] == ["sell-spy", "buy-qqq"]


def test_short_selling_forbidden_by_default() -> None:
    broker = SimulatedBroker(1_000, FREE)
    broker.submit(order("o1", Side.SELL, 1))
    broker.process_bar({"SPY": bar()})
    assert broker.status("o1") is OrderStatus.REJECTED
    assert "découvert" in broker.rejected[0].reason


def test_short_selling_when_allowed() -> None:
    broker = SimulatedBroker(1_000, FREE, allow_short=True)
    broker.submit(order("o1", Side.SELL, 1))
    broker.process_bar({"SPY": bar(open_=100)})
    assert broker.portfolio.quantity("SPY") == -1
    assert broker.portfolio.cash == pytest.approx(1_100)


def test_duplicate_order_id_is_rejected() -> None:
    broker = SimulatedBroker(1_000, FREE)
    broker.submit(order("o1", Side.BUY, 1))
    record = broker.submit(order("o1", Side.BUY, 1))
    assert record.status is OrderStatus.REJECTED
    assert len(broker.process_bar({"SPY": bar()})) == 1  # un seul achat


def test_order_waits_for_a_bar_of_its_symbol() -> None:
    broker = SimulatedBroker(1_000, FREE)
    broker.submit(order("o1", Side.BUY, 1, symbol="QQQ"))
    assert broker.process_bar({"SPY": bar()}) == []
    assert [o.client_order_id for o in broker.open_orders] == ["o1"]
    assert len(broker.process_bar({"QQQ": bar("QQQ")})) == 1
    assert broker.open_orders == []


@pytest.mark.parametrize(
    ("side", "limit", "expected"),
    [
        (Side.BUY, 101.0, 100.0),  # ouverture meilleure que la limite
        (Side.BUY, 97.0, 97.0),  # limite touchée pendant la barre
        (Side.BUY, 94.0, None),  # jamais atteinte -> annulé
        (Side.SELL, 99.0, 100.0),
        (Side.SELL, 104.0, 104.0),
        (Side.SELL, 106.0, None),
    ],
)
def test_limit_orders(side: Side, limit: float, expected: float | None) -> None:
    broker = SimulatedBroker(1_000, FREE, allow_short=True)
    broker.submit(order("o1", side, 1, limit=limit))
    fills = broker.process_bar({"SPY": bar(open_=100, high=105, low=95)})
    if expected is None:
        assert fills == []
        assert broker.status("o1") is OrderStatus.CANCELLED
    else:
        assert fills[0].price == pytest.approx(expected)
