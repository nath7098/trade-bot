from datetime import UTC, datetime

import pytest

from tradebot.domain import Fill, Portfolio, Position, Side

T0 = datetime(2024, 1, 2, tzinfo=UTC)
_counter = 0


def fill(side: Side, qty: float, price: float, symbol: str = "SPY", fee: float = 0.0) -> Fill:
    global _counter
    _counter += 1
    return Fill(f"o{_counter}", symbol, side, qty, price, T0, commission=fee)


BUY, SELL = Side.BUY, Side.SELL


class TestPosition:
    def test_open_and_add_uses_weighted_average(self) -> None:
        pos = Position("SPY")
        pos.apply(fill(BUY, 2, 100))
        pos.apply(fill(BUY, 1, 130))
        assert pos.quantity == 3
        assert pos.avg_price == pytest.approx(110)
        assert pos.realized_pnl == 0

    def test_partial_close_realizes_pnl_and_keeps_avg(self) -> None:
        pos = Position("SPY")
        pos.apply(fill(BUY, 4, 100))
        realized = pos.apply(fill(SELL, 1, 110))
        assert realized == pytest.approx(10)
        assert pos.quantity == 3
        assert pos.avg_price == pytest.approx(100)

    def test_full_close_resets(self) -> None:
        pos = Position("SPY")
        pos.apply(fill(BUY, 2, 100))
        pos.apply(fill(SELL, 2, 90))
        assert pos.is_flat
        assert pos.avg_price == 0
        assert pos.realized_pnl == pytest.approx(-20)

    def test_short_position_pnl(self) -> None:
        pos = Position("SPY")
        pos.apply(fill(SELL, 2, 100))
        assert pos.quantity == -2
        assert pos.unrealized_pnl(90) == pytest.approx(20)
        realized = pos.apply(fill(BUY, 2, 95))
        assert realized == pytest.approx(10)
        assert pos.is_flat

    def test_flip_from_long_to_short(self) -> None:
        pos = Position("SPY")
        pos.apply(fill(BUY, 2, 100))
        realized = pos.apply(fill(SELL, 5, 110))
        assert realized == pytest.approx(20)  # seules les 2 actions détenues sont clôturées
        assert pos.quantity == -3
        assert pos.avg_price == pytest.approx(110)

    def test_fractional_close_leaves_no_dust(self) -> None:
        pos = Position("SPY")
        for _ in range(10):
            pos.apply(fill(BUY, 0.1, 100))
        pos.apply(fill(SELL, 1.0, 100))
        assert pos.is_flat
        assert pos.quantity == 0.0

    def test_wrong_symbol_rejected(self) -> None:
        with pytest.raises(ValueError):
            Position("SPY").apply(fill(BUY, 1, 100, symbol="QQQ"))


class TestPortfolio:
    def test_buy_reduces_cash_including_fees(self) -> None:
        pf = Portfolio(1_000)
        pf.apply_fill(fill(BUY, 2, 100, fee=1.0))
        assert pf.cash == pytest.approx(799)
        assert pf.fees_paid == pytest.approx(1)
        assert pf.quantity("SPY") == 2
        assert pf.equity({"SPY": 100}) == pytest.approx(999)  # seul le frais est perdu

    def test_round_trip_accounting(self) -> None:
        pf = Portfolio(1_000)
        pf.apply_fill(fill(BUY, 2, 100, fee=1.0))
        pf.apply_fill(fill(SELL, 2, 110, fee=1.0))
        assert pf.positions == {}
        assert pf.quantity("SPY") == 0
        assert pf.realized_pnl == pytest.approx(20)
        assert pf.fees_paid == pytest.approx(2)
        assert pf.cash == pytest.approx(1_018)
        assert pf.equity({}) == pytest.approx(1_018)

    def test_equity_identity_with_multiple_symbols(self) -> None:
        pf = Portfolio(10_000)
        pf.apply_fill(fill(BUY, 10, 100, fee=1))
        pf.apply_fill(fill(BUY, 5, 200, "QQQ", fee=1))
        pf.apply_fill(fill(SELL, 4, 120, fee=1))
        pf.apply_fill(fill(SELL, 5, 210, "QQQ", fee=1))  # QQQ clôturé
        pf.apply_fill(fill(SELL, 3, 50, "IWM", fee=1))  # position vendeuse
        prices = {"SPY": 90.0, "IWM": 55.0}

        expected = pf.initial_cash + pf.realized_pnl + pf.unrealized_pnl(prices) - pf.fees_paid
        assert pf.equity(prices) == pytest.approx(expected)
        assert pf.realized_pnl == pytest.approx(4 * 20 + 5 * 10)
        assert pf.unrealized_pnl(prices) == pytest.approx(6 * -10 + -3 * 5)
        assert pf.exposure(prices) == pytest.approx(6 * 90 + 3 * 55)

    def test_missing_price_is_explicit_error(self) -> None:
        pf = Portfolio(1_000)
        pf.apply_fill(fill(BUY, 1, 100))
        with pytest.raises(KeyError, match="SPY"):
            pf.equity({})

    def test_initial_cash_must_be_positive(self) -> None:
        with pytest.raises(ValueError):
            Portfolio(0)
