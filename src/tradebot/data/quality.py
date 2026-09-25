"""Contrôles qualité des barres : on signale, on ne corrige jamais silencieusement."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

import pandas as pd

from tradebot.config import Timeframe
from tradebot.data.calendar import EXCHANGE_TZ, nyse
from tradebot.data.frame import COLUMNS

# Variation journalière au-delà de laquelle on alerte (souvent : split mal ajusté).
DEFAULT_MAX_ABS_RETURN = 0.25


class Severity(StrEnum):
    ERROR = "error"  # données inutilisables en l'état
    WARNING = "warning"  # à examiner, pas forcément faux


@dataclass(frozen=True)
class Issue:
    severity: Severity
    code: str
    message: str


@dataclass
class QualityReport:
    symbol: str
    rows: int
    issues: list[Issue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(i.severity is Severity.ERROR for i in self.issues)

    def add(self, severity: Severity, code: str, message: str) -> None:
        self.issues.append(Issue(severity, code, message))


def _sample(index: pd.Index, n: int = 5) -> str:
    items = [str(x) for x in index[:n]]
    return ", ".join(items) + (" ..." if len(index) > n else "")


def check_bars(
    df: pd.DataFrame,
    symbol: str,
    timeframe: Timeframe,
    *,
    max_abs_return: float = DEFAULT_MAX_ABS_RETURN,
) -> QualityReport:
    report = QualityReport(symbol, len(df))
    if df.empty:
        report.add(Severity.ERROR, "empty", "aucune barre")
        return report

    if df.index.has_duplicates:
        dup = df.index[df.index.duplicated()]
        report.add(Severity.ERROR, "duplicates", f"{len(dup)} dates en double : {_sample(dup)}")
    if not df.index.is_monotonic_increasing:
        report.add(Severity.ERROR, "unsorted", "dates non triées")

    nan_rows = df.index[df[COLUMNS].isna().any(axis=1)]
    if len(nan_rows):
        report.add(
            Severity.ERROR, "nan", f"{len(nan_rows)} barres incomplètes : {_sample(nan_rows)}"
        )

    prices = df[["open", "high", "low", "close"]]
    bad_price = df.index[(prices <= 0).any(axis=1)]
    if len(bad_price):
        report.add(Severity.ERROR, "price", f"{len(bad_price)} prix <= 0 : {_sample(bad_price)}")

    inconsistent = df.index[(df["high"] < prices.max(axis=1)) | (df["low"] > prices.min(axis=1))]
    if len(inconsistent):
        report.add(
            Severity.ERROR,
            "ohlc",
            f"{len(inconsistent)} barres OHLC incohérentes : {_sample(inconsistent)}",
        )

    zero_volume = df.index[df["volume"] <= 0]
    if len(zero_volume):
        report.add(
            Severity.WARNING,
            "volume",
            f"{len(zero_volume)} barres sans volume : {_sample(zero_volume)}",
        )

    returns = df["close"].pct_change().abs()
    jumps = df.index[returns > max_abs_return]
    if len(jumps):
        report.add(
            Severity.WARNING,
            "jump",
            f"{len(jumps)} variations > {max_abs_return:.0%} (split non ajusté ?) : "
            f"{_sample(jumps)}",
        )

    if timeframe is Timeframe.DAY:
        _check_sessions(df, report)
    return report


def _check_sessions(df: pd.DataFrame, report: QualityReport) -> None:
    """Compare les jours présents au calendrier officiel du NYSE."""
    days = pd.DatetimeIndex(pd.DatetimeIndex(df.index).tz_convert(EXCHANGE_TZ).date)
    calendar = nyse()
    first, last = days.min(), days.max()
    sessions = pd.DatetimeIndex(
        calendar.sessions_in_range(max(first, calendar.first_session), last)
    )

    missing = sessions.difference(days)
    if len(missing):
        report.add(
            Severity.WARNING,
            "missing_sessions",
            f"{len(missing)} séances manquantes : {_sample(missing.strftime('%Y-%m-%d'))}",
        )
    extra = days.difference(sessions)
    if len(extra):
        report.add(
            Severity.WARNING,
            "non_sessions",
            f"{len(extra)} barres hors séance NYSE : {_sample(extra.strftime('%Y-%m-%d'))}",
        )
