"""Stratégies de trading et registre des stratégies disponibles."""

from collections.abc import Callable

from tradebot.strategy.base import Strategy, StrategyContext
from tradebot.strategy.buy_and_hold import BuyAndHold

# Nom (utilisé en CLI/config) -> fabrique prenant la liste des symboles.
STRATEGIES: dict[str, Callable[[tuple[str, ...]], Strategy]] = {
    BuyAndHold.name: BuyAndHold,
}

__all__ = ["STRATEGIES", "BuyAndHold", "Strategy", "StrategyContext"]
