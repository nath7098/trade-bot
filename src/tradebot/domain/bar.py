"""Barre de prix (OHLCV) sur un intervalle de temps."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from tradebot.domain.common import (
    require_non_negative,
    require_positive,
    require_symbol,
    require_utc_aware,
)


@dataclass(frozen=True, slots=True)
class Bar:
    """Résumé des cotations d'un symbole sur un intervalle.

    `timestamp` est le **début** de l'intervalle, en UTC. Les prix de la barre ne sont
    connus qu'à la fin de l'intervalle : une décision prise sur cette barre ne peut être
    exécutée qu'à la barre suivante.
    """

    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    def __post_init__(self) -> None:
        require_symbol(self.symbol)
        require_utc_aware(self.timestamp, "timestamp")
        for name in ("open", "high", "low", "close"):
            require_positive(getattr(self, name), name)
        require_non_negative(self.volume, "volume")
        if self.high < max(self.open, self.close, self.low):
            raise ValueError(f"high incohérent pour {self.symbol} @ {self.timestamp}")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError(f"low incohérent pour {self.symbol} @ {self.timestamp}")
