"""Retour à la moyenne à court terme (inspiré du « RSI(2) » de L. Connors).

On achète après quelques jours de forte baisse (RSI court très bas), uniquement si la
tendance de fond est haussière (prix au-dessus de sa moyenne longue), et on revend au
rebond (RSI qui remonte). Positions de quelques jours : plus de trades, donc plus
sensible aux frais que les deux autres stratégies.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import Field, model_validator

from tradebot.domain import Signal
from tradebot.strategy.base import Strategy, StrategyContext, StrategyParams
from tradebot.strategy.indicators import rsi, sma


class MeanReversionParams(StrategyParams):
    rsi_period: int = Field(default=2, ge=2, description="période du RSI (barres)")
    entry: float = Field(default=10.0, gt=0, lt=100, description="achat si RSI < entry")
    exit: float = Field(default=70.0, gt=0, lt=100, description="vente si RSI > exit")
    trend_lookback: int = Field(default=200, ge=0, description="filtre de tendance (0 = aucun)")

    @model_validator(mode="after")
    def _entry_below_exit(self) -> MeanReversionParams:
        if self.entry >= self.exit:
            raise ValueError("entry doit être inférieur à exit")
        return self


class MeanReversion(Strategy):
    name = "mean_reversion"
    Params = MeanReversionParams
    grid: ClassVar = {"rsi_period": [2, 3, 5], "entry": [5.0, 10.0, 20.0], "exit": [50.0, 70.0]}

    def __init__(self, symbols: tuple[str, ...] = (), params: StrategyParams | None = None) -> None:
        super().__init__(symbols, params)
        assert isinstance(self.params, MeanReversionParams)
        self.p = self.params
        self._invested: dict[str, bool] = {}

    def on_bar(self, ctx: StrategyContext) -> list[Signal]:
        weight = 1.0 / len(self.symbols)
        need = max(self.p.trend_lookback, self.p.rsi_period + 1)
        signals = []
        for symbol in self.symbols:
            if symbol not in ctx.bars:
                continue
            close = ctx.history(symbol, need)["close"].to_numpy()
            if len(close) < need:
                continue
            value = rsi(close, self.p.rsi_period)
            uptrend = self.p.trend_lookback == 0 or float(close[-1]) > sma(
                close, self.p.trend_lookback
            )
            invested = self._invested.get(symbol, False)
            if not invested and value < self.p.entry and uptrend:
                self._invested[symbol] = True
                signals.append(Signal(symbol, ctx.timestamp, weight, f"RSI {value:.0f} bas"))
            elif invested and value > self.p.exit:
                self._invested[symbol] = False
                signals.append(Signal(symbol, ctx.timestamp, 0.0, f"RSI {value:.0f} rebond"))
        return signals
