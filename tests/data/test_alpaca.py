from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from tradebot.config import Timeframe
from tradebot.data import DataSourceError
from tradebot.data.alpaca import DATA_URL, AlpacaDataSource

NOW = datetime(2024, 6, 1, 12, 0, tzinfo=UTC)
START = datetime(2024, 1, 1, tzinfo=UTC)
END = datetime(2024, 12, 31, tzinfo=UTC)


def bar(day: int, close: float = 100.0) -> dict[str, Any]:
    return {
        "t": f"2024-01-{day:02d}T05:00:00Z",
        "o": close,
        "h": close + 1,
        "l": close - 1,
        "c": close,
        "v": 1000,
        "n": 10,
        "vw": close,
    }


def make_source(
    handler: Callable[[httpx.Request], httpx.Response], **kwargs: Any
) -> tuple[AlpacaDataSource, list[float]]:
    sleeps: list[float] = []
    client = httpx.Client(base_url=DATA_URL, transport=httpx.MockTransport(handler))
    source = AlpacaDataSource(
        "key", "secret", client=client, sleep=sleeps.append, now=lambda: NOW, **kwargs
    )
    return source, sleeps


def test_fetch_with_pagination_and_parameters() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if "page_token" not in request.url.params:
            return httpx.Response(200, json={"bars": [bar(2), bar(3)], "next_page_token": "p2"})
        return httpx.Response(200, json={"bars": [bar(4, 105.0)], "next_page_token": None})

    source, _ = make_source(handler)
    df = source.fetch_bars("SPY", Timeframe.DAY, START, END)

    assert len(requests) == 2
    first = requests[0]
    assert first.url.path == "/v2/stocks/SPY/bars"
    assert first.headers["APCA-API-KEY-ID"] == "key"
    assert first.url.params["timeframe"] == "1Day"
    assert first.url.params["adjustment"] == "all"
    assert first.url.params["feed"] == "sip"
    # Le flux SIP gratuit exclut les 15 dernières minutes : la fin est bornée.
    assert first.url.params["end"] == "2024-06-01T11:44:00Z"
    assert requests[1].url.params["page_token"] == "p2"

    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert len(df) == 3
    assert df.index[0] == datetime(2024, 1, 2, 5, tzinfo=UTC)
    assert df["close"].iloc[-1] == 105.0


def test_iex_feed_does_not_clip_end() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"bars": [], "next_page_token": None})

    source, _ = make_source(handler, feed="iex")
    assert source.fetch_bars("SPY", Timeframe.DAY, START, END).empty
    assert seen[0].url.params["end"] == "2024-12-31T00:00:00Z"


def test_retries_then_succeeds() -> None:
    responses = iter(
        [
            httpx.Response(429),
            httpx.Response(503),
            httpx.Response(200, json={"bars": [bar(2)], "next_page_token": None}),
        ]
    )
    source, sleeps = make_source(lambda _: next(responses))
    assert len(source.fetch_bars("SPY", Timeframe.DAY, START, END)) == 1
    assert sleeps == [1.0, 2.0]


def test_gives_up_after_max_retries() -> None:
    source, sleeps = make_source(lambda _: httpx.Response(500), max_retries=2)
    with pytest.raises(DataSourceError, match="3 tentatives"):
        source.fetch_bars("SPY", Timeframe.DAY, START, END)
    assert len(sleeps) == 2


def test_network_errors_are_retried() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("coupure", request=request)
        return httpx.Response(200, json={"bars": [bar(2)]})

    source, _ = make_source(handler)
    assert len(source.fetch_bars("SPY", Timeframe.DAY, START, END)) == 1


def test_auth_error_is_not_retried() -> None:
    source, sleeps = make_source(lambda _: httpx.Response(403, text="forbidden"))
    with pytest.raises(DataSourceError, match="403"):
        source.fetch_bars("SPY", Timeframe.DAY, START, END)
    assert sleeps == []


def test_missing_keys() -> None:
    with pytest.raises(DataSourceError, match="clés"):
        AlpacaDataSource("", "")


def test_start_after_end_returns_empty_without_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("aucune requête attendue")

    source, _ = make_source(handler)
    assert source.fetch_bars("SPY", Timeframe.DAY, NOW, NOW).empty
