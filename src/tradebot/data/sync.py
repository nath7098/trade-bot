"""Mise à jour incrémentale du stockage local depuis une source de données."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from tradebot.config import Timeframe
from tradebot.data.quality import QualityReport, check_bars
from tradebot.data.source import HistoricalDataSource
from tradebot.data.store import ParquetBarStore

log = logging.getLogger(__name__)

# Écart relatif toléré entre la barre déjà stockée et la même barre re-téléchargée.
_ADJUSTMENT_TOLERANCE = 1e-6


@dataclass(frozen=True)
class SyncResult:
    symbol: str
    rows_before: int
    rows_after: int
    full_refresh: bool
    report: QualityReport


def sync_symbol(
    source: HistoricalDataSource,
    store: ParquetBarStore,
    symbol: str,
    timeframe: Timeframe,
    history_start: datetime,
    end: datetime,
) -> SyncResult:
    """Télécharge ce qui manque pour `symbol` et met à jour le fichier local.

    Les prix étant ajustés (splits, dividendes), un nouvel événement modifie
    rétroactivement tout l'historique. On re-télécharge donc la dernière barre connue :
    si son prix a changé, on recharge tout l'historique au lieu d'ajouter des barres
    incohérentes avec les anciennes.
    """
    existing = store.load(symbol, timeframe)
    full_refresh = existing.empty

    if not full_refresh:
        last = existing.index[-1]
        new = source.fetch_bars(symbol, timeframe, last.to_pydatetime(), end)
        if not new.empty:
            if last not in new.index or not _same_close(existing, new, last):
                log.warning(
                    "historique ajusté modifié (split/dividende ?) : rechargement complet",
                    extra={"event": {"symbol": symbol}},
                )
                full_refresh = True
            else:
                store.append(symbol, timeframe, new)

    if full_refresh:
        store.save(symbol, timeframe, source.fetch_bars(symbol, timeframe, history_start, end))

    final = store.load(symbol, timeframe)
    report = check_bars(final, symbol, timeframe)
    for issue in report.issues:
        log.warning(
            f"{symbol} [{issue.severity}] {issue.code} : {issue.message}",
            extra={"event": {"symbol": symbol, "code": issue.code, "severity": issue.severity}},
        )
    return SyncResult(symbol, len(existing), len(final), full_refresh, report)


def _same_close(old: pd.DataFrame, new: pd.DataFrame, ts: pd.Timestamp) -> bool:
    a, b = float(old["close"].loc[ts]), float(new["close"].loc[ts])
    return abs(a - b) <= _ADJUSTMENT_TOLERANCE * max(abs(a), abs(b))
