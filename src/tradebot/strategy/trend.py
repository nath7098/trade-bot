"""Suivi de tendance : investi quand le prix est au-dessus de sa moyenne mobile.

Idée : les marchés ont tendance à prolonger leurs mouvements de fond. Rester à l'écart
quand le prix passe sous sa moyenne longue vise à éviter une partie des grandes baisses,
au prix de faux signaux (achats/ventes inutiles) dans les marchés sans tendance.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import Field

from tradebot.domain import Signal
from tradebot.strategy.base import Strategy, StrategyContext, StrategyParams
from tradebot.strategy.indicators import sma


class TrendParams(StrategyParams):
    lookback: int = Field(default=200, ge=2, description="longueur de la moyenne (barres)")


class TrendFollowing(Strategy):
    name = "trend"
    Params = TrendParams
    grid: ClassVar = {"lookback": [50, 100, 150, 200, 250]}

    def __init__(self, symbols: tuple[str, ...] = (), params: StrategyParams | None = None) -> None:
        super().__init__(symbols, params)
        assert isinstance(self.params, TrendParams)
        self.lookback = self.params.lookback
        self._invested: dict[str, bool] = {}

    def on_bar(self, ctx: StrategyContext) -> list[Signal]:
        weight = 1.0 / len(self.symbols)
        signals = []
        for symbol in self.symbols:
            if symbol not in ctx.bars:
                continue
            close = ctx.history(symbol, self.lookback)["close"].to_numpy()
            if len(close) < self.lookback:
                continue  # échauffement : pas assez d'historique
            invested = float(close[-1]) > sma(close, self.lookback)
            # On n'émet que les changements de régime : pas d'ordres inutiles.
            if self._invested.get(symbol) != invested:
                self._invested[symbol] = invested
                reason = "au-dessus de la moyenne" if invested else "sous la moyenne"
                signals.append(Signal(symbol, ctx.timestamp, weight if invested else 0.0, reason))
        return signals
