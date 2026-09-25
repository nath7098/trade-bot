from datetime import datetime

import pandas as pd
import pytest

from tradebot.backtest import run_backtest
from tradebot.domain import Signal
from tradebot.execution import PRESETS
from tradebot.risk import SizingConfig
from tradebot.strategy import BuyAndHold, Strategy, StrategyContext

from ..data.helpers import daily_frame

# 5 % de cash gardé : absorbe un écart entre la clôture (calcul) et l'ouverture (exécution).
SIZING = SizingConfig(cash_buffer=0.05, min_trade_pct=0, min_order_value=0)


class Scripted(Strategy):
    """Émet des poids cibles prédéfinis à certaines barres (par numéro)."""

    name = "scripted"

    def __init__(self, plan: dict[int, float], symbol: str = "SPY") -> None:
        self.plan = plan
        self.symbol = symbol
        self.i = -1

    def on_bar(self, ctx: StrategyContext) -> list[Signal]:
        self.i += 1
        if self.i in self.plan:
            return [Signal(self.symbol, ctx.timestamp, self.plan[self.i])]
        return []


def test_signal_executes_at_next_bar_open() -> None:
    df = daily_frame("2024-01-01", "2024-02-29")
    result = run_backtest(Scripted({0: 1.0}), {"SPY": df}, 1_000, PRESETS["zero"], SIZING)

    (fill,) = result.fills
    assert fill.timestamp == df.index[1]  # pas à la barre du signal
    assert fill.price == pytest.approx(df["open"].iloc[1])
    # Quantité calculée à la clôture de la barre 0.
    assert fill.quantity == pytest.approx(0.95 * 1_000 / df["close"].iloc[0])


def test_strategy_never_sees_the_future() -> None:
    df = daily_frame("2024-01-01", "2024-03-31")
    seen: list[tuple[datetime, pd.Timestamp, int]] = []

    class Spy(Strategy):
        def on_bar(self, ctx: StrategyContext) -> list[Signal]:
            hist = ctx.history("SPY", 20)
            seen.append((ctx.timestamp, hist.index[-1], len(hist)))
            return []

    run_backtest(Spy(), {"SPY": df}, 1_000, PRESETS["zero"])
    assert len(seen) == len(df)
    for i, (now, last_visible, length) in enumerate(seen):
        assert last_visible == now  # la barre la plus récente visible est la barre courante
        assert length == min(i + 1, 20)


def test_buy_and_hold_without_costs_tracks_the_price() -> None:
    df = daily_frame("2023-01-01", "2023-12-31")
    result = run_backtest(BuyAndHold(("SPY",)), {"SPY": df}, 1_000, PRESETS["zero"], SIZING)

    qty = 0.95 * 1_000 / df["close"].iloc[0]
    cash_left = 1_000 - qty * df["open"].iloc[1]
    expected = cash_left + qty * df["close"].iloc[-1]
    assert result.final_equity == pytest.approx(expected)
    assert len(result.equity) == len(df)
    assert len(result.fills) == 1


def test_costs_reduce_performance() -> None:
    df = daily_frame("2023-01-01", "2023-12-31")
    # Alterne 100 % investi / 0 % chaque jour : beaucoup d'allers-retours.
    plan = {i: float(i % 2 == 0) for i in range(len(df))}
    free = run_backtest(Scripted(plan), {"SPY": df}, 100, PRESETS["zero"])
    ibkr = run_backtest(Scripted(plan), {"SPY": df}, 100, PRESETS["ibkr_fixed"])

    assert ibkr.portfolio.fees_paid > 0
    assert ibkr.final_equity < free.final_equity
    # Avec 100 $ de capital, chaque ordre coûte ~1 % (plafond) : les frais sont massifs.
    assert ibkr.portfolio.fees_paid / len(ibkr.fills) == pytest.approx(
        0.01 * sum(f.notional for f in ibkr.fills) / len(ibkr.fills), rel=1e-6
    )


def test_gap_up_without_cash_buffer_is_rejected() -> None:
    df = daily_frame("2024-01-01", "2024-01-31")
    df.iloc[1, df.columns.get_loc("open")] = df["close"].iloc[0] * 1.03
    df.iloc[1, df.columns.get_loc("high")] = df.iloc[1][["open", "close", "high"]].max()
    no_buffer = SizingConfig(cash_buffer=0, min_trade_pct=0, min_order_value=0)
    result = run_backtest(Scripted({0: 1.0}), {"SPY": df}, 1_000, PRESETS["zero"], no_buffer)
    assert result.fills == []
    assert "cash insuffisant" in result.rejected[0].reason


def test_equity_accounting_identity() -> None:
    data = {"SPY": daily_frame("2023-01-01", "2023-06-30", seed=1)}
    data["QQQ"] = daily_frame("2023-01-01", "2023-06-30", first_close=300, seed=2)
    result = run_backtest(BuyAndHold(("SPY", "QQQ")), data, 10_000, PRESETS["ibkr_tiered"])

    pf = result.portfolio
    last = {s: float(df["close"].iloc[-1]) for s, df in data.items()}
    expected = pf.initial_cash + pf.realized_pnl + pf.unrealized_pnl(last) - pf.fees_paid
    assert result.final_equity == pytest.approx(expected)
    assert set(pf.positions) == {"SPY", "QQQ"}
    assert len(result.trades()) == 2


def test_symbols_with_different_histories() -> None:
    long = daily_frame("2023-01-01", "2023-06-30")
    short = daily_frame("2023-04-01", "2023-06-30", seed=3)
    result = run_backtest(
        BuyAndHold(("SPY", "NEW")), {"SPY": long, "NEW": short}, 1_000, PRESETS["zero"]
    )
    bought = {f.symbol: f.timestamp for f in result.fills}
    assert bought["SPY"] == long.index[1]
    assert bought["NEW"] == short.index[1]  # acheté dès que ses données existent


def test_duplicate_dates_are_refused() -> None:
    df = daily_frame("2023-01-01", "2023-01-31")
    with pytest.raises(ValueError, match="double"):
        run_backtest(BuyAndHold(("SPY",)), {"SPY": pd.concat([df, df])}, 1_000, PRESETS["zero"])
