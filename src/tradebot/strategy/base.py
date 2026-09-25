"""Interface des stratégies.

Une stratégie ne connaît ni le broker, ni le cash, ni la façon dont les ordres sont passés :
à chaque barre, elle regarde le passé et renvoie l'exposition qu'elle souhaite (`Signal`).
Le même code tourne en backtest, en paper et (plus tard) en réel.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from datetime import datetime
from typing import Any, ClassVar, Protocol

import pandas as pd
from pydantic import BaseModel, ConfigDict

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


class StrategyParams(BaseModel):
    """Paramètres réglables d'une stratégie (validés, convertis depuis la config/CLI)."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class Strategy(ABC):
    """Classe de base. Une instance neuve est créée pour chaque backtest.

    Chaque stratégie déclare :
    - `Params` : ses paramètres et leurs valeurs par défaut ;
    - `grid` : les valeurs essayées par l'optimiseur (peu nombreuses et espacées :
      plus on teste de combinaisons, plus le risque de surapprentissage augmente).
    """

    name: ClassVar[str] = "strategy"
    Params: ClassVar[type[StrategyParams]] = StrategyParams
    grid: ClassVar[dict[str, list[Any]]] = {}

    def __init__(self, symbols: tuple[str, ...] = (), params: StrategyParams | None = None) -> None:
        self.symbols = symbols
        self.params = params if params is not None else self.Params()

    @abstractmethod
    def on_bar(self, ctx: StrategyContext) -> list[Signal]:
        """Appelée à la clôture de chaque barre. Les signaux seront exécutés
        au plus tôt à la barre suivante."""
