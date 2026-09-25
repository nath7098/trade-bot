"""Stockage local des barres en fichiers Parquet : `<root>/<timeframe>/<SYMBOL>.parquet`."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from tradebot.config import Timeframe
from tradebot.data.frame import empty_frame, normalize


class ParquetBarStore:
    def __init__(self, root: Path) -> None:
        self._root = root

    def path(self, symbol: str, timeframe: Timeframe) -> Path:
        return self._root / timeframe.value / f"{symbol}.parquet"

    def load(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pd.DataFrame:
        path = self.path(symbol, timeframe)
        if not path.exists():
            return empty_frame()
        df = normalize(pd.read_parquet(path))
        if start is not None:
            df = df[df.index >= pd.Timestamp(start)]
        if end is not None:
            df = df[df.index <= pd.Timestamp(end)]
        return df

    def last_timestamp(self, symbol: str, timeframe: Timeframe) -> pd.Timestamp | None:
        df = self.load(symbol, timeframe)
        return df.index[-1] if len(df) else None

    def save(self, symbol: str, timeframe: Timeframe, df: pd.DataFrame) -> None:
        """Remplace le fichier (écriture atomique : fichier temporaire puis renommage)."""
        path = self.path(symbol, timeframe)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".parquet.tmp")
        normalize(df).to_parquet(tmp)
        tmp.replace(path)

    def append(self, symbol: str, timeframe: Timeframe, new: pd.DataFrame) -> pd.DataFrame:
        """Fusionne avec l'existant ; en cas de doublon de date, la nouvelle barre l'emporte."""
        merged = pd.concat([self.load(symbol, timeframe), normalize(new)])
        merged = merged[~merged.index.duplicated(keep="last")].sort_index()
        self.save(symbol, timeframe, merged)
        return merged

    def symbols(self, timeframe: Timeframe) -> list[str]:
        folder = self._root / timeframe.value
        return sorted(p.stem for p in folder.glob("*.parquet")) if folder.exists() else []
