"""Interface commune des sources de données historiques."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

import pandas as pd

from tradebot.config import Timeframe


class DataSourceError(Exception):
    """Échec de récupération des données (réseau, authentification, réponse invalide)."""


class HistoricalDataSource(Protocol):
    """Toute source (Alpaca, IBKR, fichier...) expose cette méthode.

    Retourne un DataFrame au format standard (`tradebot.data.frame`), prix ajustés
    des splits et dividendes, pour les barres dont le début est dans [start, end].
    """

    def fetch_bars(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> pd.DataFrame: ...
