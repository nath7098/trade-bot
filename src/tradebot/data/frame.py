"""Format standard des barres en DataFrame, et conversion vers les objets du domaine.

Toutes les briques `data` échangent des DataFrames au même format :
- index `timestamp` : DatetimeIndex en UTC, trié, sans doublon (début de la barre) ;
- colonnes `open, high, low, close, volume` en float.
"""

from __future__ import annotations

from collections.abc import Iterator

import pandas as pd

from tradebot.domain import Bar

COLUMNS = ["open", "high", "low", "close", "volume"]
INDEX_NAME = "timestamp"


def empty_frame() -> pd.DataFrame:
    index = pd.DatetimeIndex([], tz="UTC", name=INDEX_NAME)
    return pd.DataFrame({c: pd.Series(dtype="float64") for c in COLUMNS}, index=index)


def normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Met un DataFrame au format standard (colonnes, types, index UTC trié).

    Ne corrige pas les données : les anomalies sont signalées par `quality.check_bars`.
    """
    missing = [c for c in COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"colonnes manquantes : {missing}")
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("l'index doit être un DatetimeIndex")
    if df.index.tz is None:
        raise ValueError("l'index doit avoir un fuseau horaire")
    out = df[COLUMNS].astype("float64")
    out.index = df.index.tz_convert("UTC").rename(INDEX_NAME)
    return out.sort_index()


def iter_bars(df: pd.DataFrame, symbol: str) -> Iterator[Bar]:
    """Convertit un DataFrame standard en objets `Bar` (validés un par un)."""
    values = df[COLUMNS].to_numpy(dtype="float64")
    for ts, (open_, high, low, close, volume) in zip(
        pd.DatetimeIndex(df.index), values, strict=True
    ):
        yield Bar(
            symbol=symbol,
            timestamp=ts.to_pydatetime(),
            open=float(open_),
            high=float(high),
            low=float(low),
            close=float(close),
            volume=float(volume),
        )
