from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from tradebot.cli import main
from tradebot.config import Timeframe
from tradebot.data import ParquetBarStore, sync_symbol

from .helpers import daily_frame

D = Timeframe.DAY
HISTORY_START = datetime(2024, 1, 1, tzinfo=UTC)


class FakeSource:
    """Source en mémoire : renvoie les barres de `data` dans [start, end]."""

    def __init__(self, data: pd.DataFrame) -> None:
        self.data = data
        self.calls: list[tuple[datetime, datetime]] = []

    def fetch_bars(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> pd.DataFrame:
        self.calls.append((start, end))
        idx = self.data.index
        return self.data[(idx >= pd.Timestamp(start)) & (idx <= pd.Timestamp(end))]


def test_first_sync_downloads_full_history(tmp_path: Path) -> None:
    source = FakeSource(daily_frame("2024-01-01", "2024-03-31"))
    store = ParquetBarStore(tmp_path)
    end = datetime(2024, 4, 1, tzinfo=UTC)

    result = sync_symbol(source, store, "SPY", D, HISTORY_START, end)

    assert result.full_refresh
    assert result.rows_before == 0
    assert result.rows_after == len(source.data)
    assert result.report.ok
    assert source.calls == [(HISTORY_START, end)]


def test_incremental_sync_only_fetches_new_bars(tmp_path: Path) -> None:
    full = daily_frame("2024-01-01", "2024-03-31")
    store = ParquetBarStore(tmp_path)
    store.save("SPY", D, full.iloc[:40])
    source = FakeSource(full)

    result = sync_symbol(source, store, "SPY", D, HISTORY_START, datetime(2024, 4, 1, tzinfo=UTC))

    assert not result.full_refresh
    assert result.rows_before == 40
    assert result.rows_after == len(full)
    # On repart de la dernière barre connue, pas du début de l'historique.
    assert source.calls[0][0] == full.index[39].to_pydatetime()
    pd.testing.assert_frame_equal(store.load("SPY", D), full, check_freq=False)


def test_new_adjustment_triggers_full_refresh(tmp_path: Path) -> None:
    full = daily_frame("2024-01-01", "2024-03-31")
    store = ParquetBarStore(tmp_path)
    store.save("SPY", D, full.iloc[:40])
    # Un dividende/split a été versé : Alpaca renvoie tout l'historique ré-ajusté.
    adjusted = full.copy()
    adjusted[["open", "high", "low", "close"]] *= 0.98
    source = FakeSource(adjusted)

    result = sync_symbol(source, store, "SPY", D, HISTORY_START, datetime(2024, 4, 1, tzinfo=UTC))

    assert result.full_refresh
    assert len(source.calls) == 2
    pd.testing.assert_frame_equal(store.load("SPY", D), adjusted, check_freq=False)


def test_nothing_new_keeps_data(tmp_path: Path) -> None:
    full = daily_frame("2024-01-01", "2024-03-31")
    store = ParquetBarStore(tmp_path)
    store.save("SPY", D, full)
    result = sync_symbol(
        FakeSource(full.iloc[:0]), store, "SPY", D, HISTORY_START, datetime(2024, 4, 1, tzinfo=UTC)
    )
    assert not result.full_refresh
    assert result.rows_after == len(full)


def test_cli_data_check(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ParquetBarStore(tmp_path / "data").save("SPY", D, daily_frame("2024-01-01", "2024-03-31"))
    config = tmp_path / "c.yaml"
    config.write_text(f"data_dir: {tmp_path / 'data'}\nsymbols: [SPY, QQQ]\n", encoding="utf-8")

    assert main(["--config", str(config), "data", "check"]) == 1  # QQQ absent
    out = capsys.readouterr().out
    assert "SPY: 61 barres (2024-01-02 -> 2024-03-28) - OK" in out
    assert "QQQ: 0 barres (vide) - ERREURS" in out


def test_cli_data_fetch_without_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TRADEBOT_ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("TRADEBOT_ALPACA_API_SECRET", raising=False)
    config = tmp_path / "c.yaml"
    config.write_text(f"log_dir: {tmp_path / 'logs'}\n", encoding="utf-8")
    assert main(["--config", str(config), "data", "fetch"]) == 3
    assert "clés Alpaca manquantes" in capsys.readouterr().err
