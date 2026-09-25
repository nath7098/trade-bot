"""Données factices pour les tests (aucun accès réseau)."""

from __future__ import annotations

import exchange_calendars as xcals
import numpy as np
import pandas as pd

from tradebot.data.frame import normalize


def daily_frame(start: str, end: str, first_close: float = 100.0, seed: int = 0) -> pd.DataFrame:
    """Barres journalières plausibles sur les séances NYSE, horodatées comme Alpaca
    (minuit heure de New York, exprimé en UTC)."""
    sessions = xcals.get_calendar("XNYS").sessions_in_range(start, end)
    rng = np.random.default_rng(seed)
    close = first_close * np.cumprod(1 + rng.normal(0, 0.01, len(sessions)))
    open_ = close * (1 + rng.normal(0, 0.003, len(sessions)))
    high = np.maximum(open_, close) * 1.005
    low = np.minimum(open_, close) * 0.995
    index = pd.DatetimeIndex(sessions).tz_localize("America/New_York").tz_convert("UTC")
    df = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": 1e6}, index=index
    )
    return normalize(df)


def frame_from_closes(closes: list[float] | np.ndarray, start: str = "2020-01-01") -> pd.DataFrame:
    """Barres journalières (séances NYSE) avec des clôtures imposées ; ouverture = clôture
    précédente, pour des tests déterministes."""
    calendar = xcals.get_calendar("XNYS")
    sessions = calendar.sessions_in_range(
        start, pd.Timestamp(start) + pd.Timedelta(days=2 * len(closes) + 10)
    )
    sessions = sessions[: len(closes)]
    close = np.asarray(closes, dtype="float64")
    open_ = np.concatenate([[close[0]], close[:-1]])
    index = pd.DatetimeIndex(sessions).tz_localize("America/New_York").tz_convert("UTC")
    df = pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close),
            "low": np.minimum(open_, close),
            "close": close,
            "volume": 1e6,
        },
        index=index,
    )
    return normalize(df)
