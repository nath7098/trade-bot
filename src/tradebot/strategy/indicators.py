"""Indicateurs techniques, calculés sur l'historique fourni (jamais au-delà).

Calculs en numpy : ils sont appelés à chaque barre de chaque backtest.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _values(close: pd.Series | np.ndarray, needed: int) -> np.ndarray:
    values = np.asarray(close, dtype="float64")
    if len(values) < needed:
        raise ValueError(f"historique insuffisant : {len(values)} < {needed}")
    return values


def sma(close: pd.Series | np.ndarray, period: int) -> float:
    """Moyenne simple des `period` dernières valeurs."""
    return float(_values(close, period)[-period:].mean())


def total_return(close: pd.Series | np.ndarray, period: int) -> float:
    """Variation sur les `period` dernières barres (besoin de period + 1 valeurs)."""
    values = _values(close, period + 1)
    return float(values[-1] / values[-period - 1] - 1)


def rsi(close: pd.Series | np.ndarray, period: int) -> float:
    """RSI (variante de Cutler : moyennes simples des hausses et des baisses).

    0 = uniquement des baisses sur la période, 100 = uniquement des hausses.
    """
    changes = np.diff(_values(close, period + 1)[-period - 1 :])
    gain = float(np.clip(changes, 0, None).mean())
    loss = float(-np.clip(changes, None, 0).mean())
    if loss == 0:
        return 100.0 if gain > 0 else 50.0
    return 100.0 - 100.0 / (1.0 + gain / loss)
