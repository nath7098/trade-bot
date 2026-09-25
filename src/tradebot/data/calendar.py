"""Calendrier de la bourse de New York (NYSE)."""

from __future__ import annotations

from datetime import datetime, timedelta
from functools import cache
from typing import Any

import exchange_calendars as xcals
import pandas as pd

from tradebot.config import Timeframe

EXCHANGE_TZ = "America/New_York"


@cache
def nyse() -> Any:
    return xcals.get_calendar("XNYS")


def last_completed_bar(timeframe: Timeframe, now: datetime) -> datetime:
    """Horodatage (début) de la dernière barre **terminée** à l'instant `now`.

    Sert de borne de fin aux téléchargements : une barre en cours de formation
    (séance pas encore close) ne doit jamais être stockée ni utilisée.
    """
    ts = pd.Timestamp(now).tz_convert("UTC")
    if timeframe is Timeframe.HOUR:
        return (ts.floor("h") - pd.Timedelta(hours=1)).to_pydatetime()

    calendar = nyse()
    today = ts.tz_convert(EXCHANGE_TZ).normalize().tz_localize(None)
    sessions = calendar.sessions_in_range(today - timedelta(days=10), today)
    for session in reversed(sessions):
        if calendar.session_close(session) <= ts:
            # Les barres journalières commencent à minuit, heure de New York.
            start: datetime = (
                pd.Timestamp(session).tz_localize(EXCHANGE_TZ).tz_convert("UTC").to_pydatetime()
            )
            return start
    raise ValueError(f"aucune séance terminée trouvée avant {now}")
