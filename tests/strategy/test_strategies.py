import numpy as np
import pytest
from pydantic import ValidationError

from tradebot.backtest import run_backtest
from tradebot.execution import PRESETS
from tradebot.risk import SizingConfig
from tradebot.strategy import STRATEGIES, build_strategy
from tradebot.strategy.indicators import rsi, sma, total_return

from ..data.helpers import daily_frame, frame_from_closes

FREE = PRESETS["zero"]
SIZING = SizingConfig(min_trade_pct=0)


class TestIndicators:
    def test_sma_and_return(self) -> None:
        close = np.array([1.0, 2.0, 3.0, 4.0])
        assert sma(close, 2) == pytest.approx(3.5)
        assert total_return(close, 3) == pytest.approx(3.0)
        with pytest.raises(ValueError):
            sma(close, 5)

    def test_rsi_extremes_and_known_value(self) -> None:
        assert rsi(np.array([1.0, 2.0, 3.0]), 2) == 100.0
        assert rsi(np.array([3.0, 2.0, 1.0]), 2) == pytest.approx(0.0)
        # Hausses 2 et baisse 1 -> gain moyen 1, perte moyenne 0,5 -> RSI 66,7
        assert rsi(np.array([10.0, 12.0, 11.0]), 2) == pytest.approx(100 - 100 / 3)
        assert rsi(np.array([5.0, 5.0, 5.0]), 2) == 50.0


def test_registry_and_param_validation() -> None:
    assert set(STRATEGIES) == {"buy_and_hold", "trend", "momentum", "mean_reversion"}
    strategy = build_strategy("trend", ("SPY",), {"lookback": "150"})  # conversion depuis la CLI
    assert strategy.params.lookback == 150  # type: ignore[attr-defined]
    with pytest.raises(ValidationError):
        build_strategy("trend", ("SPY",), {"lookback": 1})
    with pytest.raises(ValidationError):
        build_strategy("trend", ("SPY",), {"unknown": 1})
    with pytest.raises(ValidationError):
        build_strategy("mean_reversion", ("SPY",), {"entry": 80, "exit": 70})
    with pytest.raises(ValueError, match="inconnue"):
        build_strategy("nope", ("SPY",))


def test_every_grid_value_is_a_valid_parameter() -> None:
    for name, cls in STRATEGIES.items():
        for field, values in cls.grid.items():
            for value in values:
                build_strategy(name, ("SPY",), {field: value})


class TestTrend:
    def test_enters_above_average_and_exits_below(self) -> None:
        # 30 jours de hausse, 30 de baisse.
        closes = [100 + i for i in range(30)] + [129 - 2 * i for i in range(30)]
        df = frame_from_closes(closes)
        strategy = build_strategy("trend", ("SPY",), {"lookback": 10})
        result = run_backtest(strategy, {"SPY": df}, 1_000, FREE, SIZING)

        buy, sell = result.fills
        assert buy.side.value == "buy"
        assert (
            buy.timestamp == df.index[10]
        )  # signal à la 10e barre (échauffement), exécution à la 11e
        assert sell.side.value == "sell"
        assert result.portfolio.positions == {}

    def test_no_signal_repeated_while_regime_unchanged(self) -> None:
        df = frame_from_closes([100 + i for i in range(60)])
        strategy = build_strategy("trend", ("SPY",), {"lookback": 10})
        result = run_backtest(strategy, {"SPY": df}, 1_000, FREE, SIZING)
        assert len(result.fills) == 1


class TestMomentum:
    def test_holds_the_best_performer_and_goes_to_cash_when_all_fall(self) -> None:
        n = 120
        up_fast = frame_from_closes(np.linspace(100, 200, n))
        up_slow = frame_from_closes(np.linspace(100, 110, n))
        strategy = build_strategy("momentum", ("A", "B"), {"lookback": 20, "top_n": 1})
        result = run_backtest(strategy, {"A": up_fast, "B": up_slow}, 1_000, FREE, SIZING)
        assert {f.symbol for f in result.fills} == {"A"}
        assert set(result.portfolio.positions) == {"A"}

        down = frame_from_closes(np.linspace(200, 100, n))
        down2 = frame_from_closes(np.linspace(150, 120, n))
        result = run_backtest(
            build_strategy("momentum", ("A", "B"), {"lookback": 20}),
            {"A": down, "B": down2},
            1_000,
            FREE,
            SIZING,
        )
        assert result.fills == []  # filtre absolu : tout baisse -> cash

    def test_rebalances_at_most_once_a_month(self) -> None:
        data = {s: daily_frame("2020-01-01", "2021-12-31", seed=i) for i, s in enumerate("ABC")}
        strategy = build_strategy("momentum", ("A", "B", "C"), {"lookback": 21, "absolute": False})
        result = run_backtest(strategy, data, 1_000, FREE, SIZING)
        months = {(f.timestamp.year, f.timestamp.month) for f in result.fills}
        # 24 mois au plus ; chaque rééquilibrage = au plus une vente + un achat.
        assert len(result.fills) <= 2 * 24
        assert len(months) <= 24


class TestMeanReversion:
    def test_buys_the_dip_and_sells_the_rebound(self) -> None:
        closes = [100.0 + i * 2 for i in range(30)]  # nette tendance haussière
        closes += [closes[-1] - 3, closes[-1] - 6]  # deux baisses -> RSI(2) = 0
        closes += [closes[-1] + 4, closes[-1] + 8, closes[-1] + 9]  # rebond
        df = frame_from_closes(closes)
        strategy = build_strategy(
            "mean_reversion", ("SPY",), {"rsi_period": 2, "trend_lookback": 20}
        )
        result = run_backtest(strategy, {"SPY": df}, 1_000, FREE, SIZING)
        buy, sell = result.fills
        assert buy.timestamp == df.index[32]  # signal après la 2e baisse (barre 31)
        assert sell.timestamp > buy.timestamp

    def test_trend_filter_blocks_entries_in_downtrend(self) -> None:
        closes = [200.0 - i for i in range(40)]  # baisse continue : RSI bas en permanence
        df = frame_from_closes(closes)
        with_filter = build_strategy("mean_reversion", ("SPY",), {"trend_lookback": 20})
        without = build_strategy("mean_reversion", ("SPY",), {"trend_lookback": 0})
        assert run_backtest(with_filter, {"SPY": df}, 1_000, FREE, SIZING).fills == []
        assert run_backtest(without, {"SPY": df}, 1_000, FREE, SIZING).fills != []
