"""Achat puis conservation, à parts égales : la référence à battre."""

from __future__ import annotations

from tradebot.domain import Signal
from tradebot.strategy.base import Strategy, StrategyContext


class BuyAndHold(Strategy):
    name = "buy_and_hold"

    def __init__(self, symbols: tuple[str, ...]) -> None:
        self._weight = 1.0 / len(symbols)
        self._symbols = set(symbols)
        self._invested: set[str] = set()

    def on_bar(self, ctx: StrategyContext) -> list[Signal]:
        signals = []
        for symbol in sorted(self._symbols & ctx.bars.keys() - self._invested):
            signals.append(Signal(symbol, ctx.timestamp, self._weight, "achat initial"))
            self._invested.add(symbol)
        return signals
