"""Stratégies de trading et registre des stratégies disponibles."""

from collections.abc import Mapping
from typing import Any

from tradebot.strategy.base import Strategy, StrategyContext, StrategyParams
from tradebot.strategy.buy_and_hold import BuyAndHold
from tradebot.strategy.mean_reversion import MeanReversion
from tradebot.strategy.momentum import DualMomentum
from tradebot.strategy.trend import TrendFollowing

# Nom (utilisé en CLI/config) -> classe de stratégie.
STRATEGIES: dict[str, type[Strategy]] = {
    cls.name: cls for cls in (BuyAndHold, TrendFollowing, DualMomentum, MeanReversion)
}


def build_strategy(
    name: str, symbols: tuple[str, ...], params: Mapping[str, Any] | None = None
) -> Strategy:
    """Instancie une stratégie ; les paramètres sont validés et convertis (ex. "150" -> 150)."""
    if name not in STRATEGIES:
        raise ValueError(f"stratégie inconnue : {name} (choix : {', '.join(STRATEGIES)})")
    cls = STRATEGIES[name]
    return cls(symbols, cls.Params.model_validate(dict(params or {})))


__all__ = [
    "STRATEGIES",
    "BuyAndHold",
    "DualMomentum",
    "MeanReversion",
    "Strategy",
    "StrategyContext",
    "StrategyParams",
    "TrendFollowing",
    "build_strategy",
]
