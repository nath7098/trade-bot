"""Interface des stratégies.

Une stratégie ne connaît ni le broker, ni le cash, ni la façon dont les ordres sont passés :
à chaque barre, elle regarde le passé et renvoie l'exposition qu'elle souhaite (`Signal`).
Le même code tourne en backtest, en paper et (plus tard) en réel.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from datetime import datetime
from typing import Protocol

import pandas as pd

from tradebot.domain import Bar, Signal


class StrategyContext(Protocol):
    """Ce que la stratégie peut voir à l'instant présent — et rien du futur."""

    @property
    def timestamp(self) -> datetime:
        """Début de la barre courante (UTC)."""
        ...

    @property
    def bars(self) -> Mapping[str, Bar]:
        """Barres terminées à cet instant, par symbole (un symbole sans cotation est absent)."""
        ...

    def history(self, symbol: str, lookback: int) -> pd.DataFrame:
        """Les `lookback` dernières barres de `symbol`, barre courante incluse
        (format `tradebot.data.frame`). Peut en contenir moins en début d'historique."""
        ...


class Strategy(ABC):
    """Classe de base. Une instance neuve est créée pour chaque backtest."""

    name: str = "strategy"

    @abstractmethod
    def on_bar(self, ctx: StrategyContext) -> list[Signal]:
        """Appelée à la clôture de chaque barre. Les signaux seront exécutés
        au plus tôt à la barre suivante."""
