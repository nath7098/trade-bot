from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from tradebot.config import Timeframe
from tradebot.data import ParquetBarStore, empty_frame, iter_bars, normalize

from .helpers import daily_frame

D = Timeframe.DAY


class TestFrame:
    def test_normalize_rejects_missing_columns(self) -> None:
        df = daily_frame("2024-01-02", "2024-01-05").drop(columns="volume")
        with pytest.raises(ValueError, match="volume"):
            normalize(df)

    def test_normalize_rejects_naive_index(self) -> None:
        df = daily_frame("2024-01-02", "2024-01-05")
        df.index = df.index.tz_localize(None)
        with pytest.raises(ValueError, match="fuseau"):
            normalize(df)

    def test_normalize_converts_to_utc_and_sorts(self) -> None:
        df = daily_frame("2024-01-02", "2024-01-05")
        shuffled = df.iloc[::-1].tz_convert("America/New_York")
        out = normalize(shuffled)
        assert str(out.index.tz) == "UTC"
        assert out.index.is_monotonic_increasing

    def test_iter_bars(self) -> None:
        df = daily_frame("2024-01-02", "2024-01-05")
        bars = list(iter_bars(df, "SPY"))
        assert len(bars) == len(df)
        assert bars[0].timestamp == datetime(2024, 1, 2, 5, tzinfo=UTC)
        assert bars[-1].close == pytest.approx(df["close"].iloc[-1])


class TestStore:
    def test_missing_file_gives_empty_frame(self, tmp_path: Path) -> None:
        store = ParquetBarStore(tmp_path)
        assert store.load("SPY", D).empty
        assert store.last_timestamp("SPY", D) is None

    def test_roundtrip_and_filter(self, tmp_path: Path) -> None:
        store = ParquetBarStore(tmp_path)
        df = daily_frame("2024-01-02", "2024-01-31")
        store.save("SPY", D, df)
        pd.testing.assert_frame_equal(store.load("SPY", D), df, check_freq=False)

        start = datetime(2024, 1, 10, tzinfo=UTC)
        end = datetime(2024, 1, 20, tzinfo=UTC)
        part = store.load("SPY", D, start, end)
        assert part.index.min() >= pd.Timestamp(start)
        assert part.index.max() <= pd.Timestamp(end)
        assert store.symbols(D) == ["SPY"]
        assert not list(tmp_path.rglob("*.tmp"))  # écriture atomique : pas de reste

    def test_append_overwrites_duplicates_with_new_values(self, tmp_path: Path) -> None:
        store = ParquetBarStore(tmp_path)
        full = daily_frame("2024-01-02", "2024-01-31")
        store.save("SPY", D, full.iloc[:10])
        update = full.iloc[9:].copy()
        update.iloc[0, update.columns.get_loc("volume")] = 42.0
        merged = store.append("SPY", D, update)
        assert len(merged) == len(full)
        assert not merged.index.has_duplicates
        assert merged["volume"].iloc[9] == 42.0

    def test_empty_frame_is_normalized(self) -> None:
        assert normalize(empty_frame()).empty
