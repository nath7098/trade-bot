from datetime import UTC, datetime

import pytest

from tradebot.domain import Fill, Portfolio, Side, Signal
from tradebot.risk import SizingConfig, orders_for_signals

NOW = datetime(2024, 1, 2, 21, tzinfo=UTC)
NO_BUFFER = SizingConfig(cash_buffer=0, min_trade_pct=0, min_order_value=0)


def sized(
    signals: list[Signal], pf: Portfolio, prices: dict[str, float], config: SizingConfig
) -> list[tuple[str, Side, float]]:
    orders = orders_for_signals(signals, pf, prices, NOW, config, "test")
    return [(o.symbol, o.side, o.quantity) for o in orders]


def test_target_weight_to_fractional_quantity() -> None:
    pf = Portfolio(100)
    result = sized([Signal("SPY", NOW, 1.0)], pf, {"SPY": 400.0}, NO_BUFFER)
    assert result == [("SPY", Side.BUY, pytest.approx(0.25))]


def test_cash_buffer_is_kept() -> None:
    pf = Portfolio(1_000)
    config = SizingConfig(cash_buffer=0.02, min_trade_pct=0)
    ((_, _, qty),) = sized([Signal("SPY", NOW, 1.0)], pf, {"SPY": 100.0}, config)
    assert qty == pytest.approx(9.8)


def test_whole_shares_only() -> None:
    pf = Portfolio(100)
    config = SizingConfig(allow_fractional=False, cash_buffer=0, min_trade_pct=0)
    # 100 $ ne permet pas d'acheter une action à 400 $ : aucun ordre.
    assert sized([Signal("SPY", NOW, 1.0)], pf, {"SPY": 400.0}, config) == []
    assert sized([Signal("SPY", NOW, 1.0)], pf, {"SPY": 30.0}, config) == [("SPY", Side.BUY, 3.0)]


def test_reduce_and_close_positions() -> None:
    pf = Portfolio(1_000)
    pf.apply_fill(Fill("f", "SPY", Side.BUY, 5, 100.0, NOW))
    prices = {"SPY": 100.0}
    assert sized([Signal("SPY", NOW, 0.25)], pf, prices, NO_BUFFER) == [("SPY", Side.SELL, 2.5)]
    assert sized([Signal("SPY", NOW, 0.0)], pf, prices, NO_BUFFER) == [("SPY", Side.SELL, 5.0)]


def test_small_adjustments_are_skipped_but_closing_is_not() -> None:
    pf = Portfolio(1_000)
    pf.apply_fill(Fill("f", "SPY", Side.BUY, 0.05, 100.0, NOW))  # 5 $ détenus
    config = SizingConfig(cash_buffer=0, min_trade_pct=0.01, min_order_value=10)
    prices = {"SPY": 100.0}
    # Passer de 5 $ à 9 $ : < 1 % du capital et < 10 $ -> ignoré.
    assert sized([Signal("SPY", NOW, 0.009)], pf, prices, config) == []
    # Mais une clôture passe toujours, même minuscule.
    assert sized([Signal("SPY", NOW, 0.0)], pf, prices, config) == [
        ("SPY", Side.SELL, pytest.approx(0.05))
    ]


def test_order_ids_are_deterministic() -> None:
    pf = Portfolio(1_000)
    signals = [Signal("SPY", NOW, 0.5)]
    first = orders_for_signals(signals, pf, {"SPY": 100.0}, NOW, NO_BUFFER, "strat")
    again = orders_for_signals(signals, pf, {"SPY": 100.0}, NOW, NO_BUFFER, "strat")
    # Même décision au même instant -> même identifiant -> doublon détectable.
    assert first[0].client_order_id == again[0].client_order_id == "strat-SPY-20240102T2100-buy"


def test_buys_are_scaled_down_to_available_cash() -> None:
    # 3 positions ont monté : elles occupent 90 % du capital ; viser 25 % d'un 4e actif
    # dépasserait le cash disponible -> l'achat est réduit au lieu d'être rejeté.
    pf = Portfolio(100)
    for symbol in ("A", "B", "C"):
        pf.apply_fill(Fill(f"f{symbol}", symbol, Side.BUY, 1, 25.0, NOW))
    prices = {"A": 30.0, "B": 30.0, "C": 30.0, "D": 10.0}  # equity = 25 + 90 = 115
    config = SizingConfig(cash_buffer=0.02, min_trade_pct=0, min_order_value=0)
    ((symbol, side, qty),) = sized([Signal("D", NOW, 0.25)], pf, prices, config)
    assert (symbol, side) == ("D", Side.BUY)
    assert qty * 10.0 == pytest.approx(25 - 0.02 * 115)  # cash - réserve


def test_sell_proceeds_fund_buys_in_same_rebalance() -> None:
    pf = Portfolio(100)
    pf.apply_fill(Fill("f", "A", Side.BUY, 9.8, 10.0, NOW))  # 98 % investi
    prices = {"A": 10.0, "B": 10.0}
    signals = [Signal("A", NOW, 0.0), Signal("B", NOW, 1.0)]
    result = sized(signals, pf, prices, NO_BUFFER)
    assert ("A", Side.SELL, pytest.approx(9.8)) in result
    assert ("B", Side.BUY, pytest.approx(10.0)) in result  # non réduit : la vente finance
