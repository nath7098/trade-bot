"""Momentum entre actifs (« dual momentum »).

Chaque début de mois, on classe les actifs selon leur performance sur `lookback` barres
et on détient les `top_n` meilleurs. Avec `absolute=True`, un actif n'est retenu que
si sa performance est positive : si tout baisse, on reste en cash.

Idée : ce qui a monté récemment tend à continuer à court/moyen terme (effet momentum,
largement documenté), et le filtre absolu évite de rester investi dans un marché baissier.
"""

from __future__ import annotations

from typing import ClassVar

import pandas as pd
from pydantic import Field

from tradebot.data.calendar import EXCHANGE_TZ
from tradebot.domain import Signal
from tradebot.strategy.base import Strategy, StrategyContext, StrategyParams
from tradebot.strategy.indicators import total_return


class MomentumParams(StrategyParams):
    lookback: int = Field(default=126, ge=5, description="fenêtre de performance (barres)")
    top_n: int = Field(default=1, ge=1, description="nombre d'actifs détenus")
    absolute: bool = Field(default=True, description="exiger une performance positive")


class DualMomentum(Strategy):
    name = "momentum"
    Params = MomentumParams
    grid: ClassVar = {"lookback": [63, 126, 189, 252], "top_n": [1, 2]}

    def __init__(self, symbols: tuple[str, ...] = (), params: StrategyParams | None = None) -> None:
        super().__init__(symbols, params)
        assert isinstance(self.params, MomentumParams)
        self.p = self.params
        self._month: tuple[int, int] | None = None
        self._targets: dict[str, float] = {}

    def on_bar(self, ctx: StrategyContext) -> list[Signal]:
        local = pd.Timestamp(ctx.timestamp).tz_convert(EXCHANGE_TZ)
        month = (local.year, local.month)
        if month == self._month:
            return []  # on ne rééquilibre qu'une fois par mois
        self._month = month

        scores: dict[str, float] = {}
        for symbol in self.symbols:
            close = ctx.history(symbol, self.p.lookback + 1)["close"].to_numpy()
            if symbol in ctx.bars and len(close) == self.p.lookback + 1:
                scores[symbol] = total_return(close, self.p.lookback)
        if not scores:
            return []

        ranked = sorted(scores, key=lambda s: scores[s], reverse=True)[: self.p.top_n]
        chosen = [s for s in ranked if scores[s] > 0 or not self.p.absolute]
        targets = {s: (1.0 / self.p.top_n if s in chosen else 0.0) for s in scores}

        signals = []
        for symbol, weight in targets.items():
            if self._targets.get(symbol, 0.0) != weight:
                reason = f"perf {scores[symbol]:+.1%} sur {self.p.lookback} barres"
                signals.append(Signal(symbol, ctx.timestamp, weight, reason))
                self._targets[symbol] = weight
        return signals
