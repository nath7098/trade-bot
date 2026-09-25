"""Source de données historiques Alpaca (API REST « Market Data v2 »).

Lecture seule : ce module ne peut passer aucun ordre.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import httpx
import pandas as pd

from tradebot.config import Timeframe
from tradebot.data.frame import INDEX_NAME, empty_frame, normalize
from tradebot.data.source import DataSourceError

log = logging.getLogger(__name__)

DATA_URL = "https://data.alpaca.markets"
Feed = Literal["sip", "iex"]

_TIMEFRAMES = {Timeframe.DAY: "1Day", Timeframe.HOUR: "1Hour"}
_RETRY_STATUSES = {429, 500, 502, 503, 504}
# L'offre gratuite n'autorise pas les 15 dernières minutes du flux SIP.
_SIP_DELAY = timedelta(minutes=16)


class AlpacaDataSource:
    def __init__(
        self,
        api_key: str,
        api_secret: str,
        *,
        feed: Feed = "sip",
        client: httpx.Client | None = None,
        max_retries: int = 4,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if not api_key or not api_secret:
            raise DataSourceError("clés Alpaca manquantes (TRADEBOT_ALPACA_API_KEY/SECRET)")
        self._client = client or httpx.Client(base_url=DATA_URL, timeout=30.0)
        self._headers = {"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": api_secret}
        self._feed = feed
        self._max_retries = max_retries
        self._sleep = sleep
        self._now = now

    def fetch_bars(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> pd.DataFrame:
        if self._feed == "sip":
            end = min(end, self._now() - _SIP_DELAY)
        if start >= end:
            return empty_frame()

        params: dict[str, str] = {
            "timeframe": _TIMEFRAMES[timeframe],
            "start": _iso(start),
            "end": _iso(end),
            "adjustment": "all",  # prix ajustés des splits et dividendes
            "feed": self._feed,
            "limit": "10000",
            "sort": "asc",
        }
        rows: list[dict[str, Any]] = []
        while True:
            payload = self._get(f"/v2/stocks/{symbol}/bars", params)
            rows.extend(payload.get("bars") or [])
            token = payload.get("next_page_token")
            if not token:
                break
            params["page_token"] = token

        log.info(
            "barres Alpaca récupérées",
            extra={"event": {"symbol": symbol, "timeframe": timeframe.value, "rows": len(rows)}},
        )
        return _to_frame(rows)

    def _get(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        for attempt in range(self._max_retries + 1):
            try:
                response = self._client.get(path, params=params, headers=self._headers)
            except httpx.TransportError as exc:
                error = f"erreur réseau : {exc}"
            else:
                if response.status_code == 200:
                    data: dict[str, Any] = response.json()
                    return data
                if response.status_code in (401, 403):
                    raise DataSourceError(
                        f"accès refusé par Alpaca ({response.status_code}) : {response.text}. "
                        "Vérifier les clés, ou essayer data_feed: iex."
                    )
                if response.status_code not in _RETRY_STATUSES:
                    raise DataSourceError(
                        f"réponse Alpaca inattendue ({response.status_code}) : {response.text}"
                    )
                error = f"HTTP {response.status_code}"

            if attempt == self._max_retries:
                raise DataSourceError(f"échec après {attempt + 1} tentatives : {error}")
            delay = 2.0**attempt
            log.warning(f"Alpaca : {error}, nouvel essai dans {delay:.0f}s")
            self._sleep(delay)
        raise AssertionError("inatteignable")


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError(f"date sans fuseau horaire : {value!r}")
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _to_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return empty_frame()
    raw = pd.DataFrame(rows)
    df = pd.DataFrame(
        {
            "open": raw["o"],
            "high": raw["h"],
            "low": raw["l"],
            "close": raw["c"],
            "volume": raw["v"],
        }
    )
    df.index = pd.DatetimeIndex(pd.to_datetime(raw["t"], utc=True), name=INDEX_NAME)
    return normalize(df)
