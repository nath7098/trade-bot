import pandas as pd

from tradebot.config import Timeframe
from tradebot.data import Severity, check_bars, empty_frame

from .helpers import daily_frame

D = Timeframe.DAY


def codes(df: pd.DataFrame) -> dict[str, Severity]:
    return {i.code: i.severity for i in check_bars(df, "SPY", D).issues}


def test_clean_data_has_no_issue() -> None:
    report = check_bars(daily_frame("2023-01-01", "2023-12-31"), "SPY", D)
    assert report.ok
    assert report.issues == []


def test_empty_is_error() -> None:
    assert codes(empty_frame()) == {"empty": Severity.ERROR}


def test_missing_session_is_detected() -> None:
    df = daily_frame("2024-01-02", "2024-01-31")
    assert codes(df.drop(df.index[5])) == {"missing_sessions": Severity.WARNING}


def test_bar_on_holiday_is_detected() -> None:
    df = daily_frame("2024-12-20", "2024-12-31")
    christmas = pd.Timestamp("2024-12-25", tz="America/New_York").tz_convert("UTC")
    extra = df.iloc[[0]].copy()
    extra.index = pd.DatetimeIndex([christmas])
    assert codes(pd.concat([df, extra]).sort_index()) == {"non_sessions": Severity.WARNING}


def test_duplicates_are_errors() -> None:
    df = daily_frame("2024-01-02", "2024-01-31")
    result = codes(pd.concat([df, df.iloc[[3]]]).sort_index())
    assert result["duplicates"] is Severity.ERROR


def test_ohlc_inconsistency_and_bad_prices() -> None:
    df = daily_frame("2024-01-02", "2024-01-31")
    df.iloc[2, df.columns.get_loc("high")] = df["low"].iloc[2] * 0.5
    df.iloc[4, df.columns.get_loc("close")] = 0.0
    result = codes(df)
    assert result["ohlc"] is Severity.ERROR
    assert result["price"] is Severity.ERROR


def test_nan_is_error() -> None:
    df = daily_frame("2024-01-02", "2024-01-31")
    df.iloc[3, df.columns.get_loc("open")] = float("nan")
    assert codes(df)["nan"] is Severity.ERROR


def test_unadjusted_split_is_flagged() -> None:
    df = daily_frame("2024-01-02", "2024-01-31")
    df.iloc[10:, :4] = df.iloc[10:, :4] / 4  # split 4:1 non ajusté
    result = codes(df)
    assert result == {"jump": Severity.WARNING}


def test_zero_volume_is_warning() -> None:
    df = daily_frame("2024-01-02", "2024-01-31")
    df.iloc[1, df.columns.get_loc("volume")] = 0.0
    assert codes(df) == {"volume": Severity.WARNING}


def test_hourly_data_skips_session_check() -> None:
    df = daily_frame("2024-01-02", "2024-01-31").drop(
        daily_frame("2024-01-02", "2024-01-31").index[5]
    )
    assert check_bars(df, "SPY", Timeframe.HOUR).issues == []
