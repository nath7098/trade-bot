from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from tradebot.backtest import compute_metrics, run_backtest
from tradebot.backtest.optimize import (
    BacktestSetup,
    expand_grid,
    optimize,
    robust_scores,
    split_train,
)
from tradebot.cli import main
from tradebot.config import Timeframe
from tradebot.data import ParquetBarStore
from tradebot.domain import Signal
from tradebot.execution import PRESETS
from tradebot.risk import SizingConfig
from tradebot.strategy import STRATEGIES, Strategy, StrategyContext, TrendFollowing

from ..data.helpers import daily_frame

SPLIT = datetime(2022, 1, 1, tzinfo=UTC)
SETUP = BacktestSetup(1_000, PRESETS["alpaca"], SizingConfig())


def test_expand_grid() -> None:
    assert expand_grid({}) == [{}]
    combos = expand_grid({"a": [1, 2], "b": ["x", "y", "z"]})
    assert len(combos) == 6
    assert {"a": 2, "b": "z"} in combos


def test_robust_score_prefers_a_plateau_to_an_isolated_peak() -> None:
    grid = {"p": [1, 2, 3, 4, 5, 6, 7]}
    # Pic isolé à p=2 (3.0), plateau correct autour de p=6.
    table = pd.DataFrame({"p": grid["p"], "score": [0.0, 3.0, 0.0, 0.2, 1.5, 1.6, 1.4]})
    table["robust_score"] = robust_scores(table, grid)
    best = table.sort_values(["robust_score", "score"], ascending=False).iloc[0]
    assert best["p"] == 6  # au milieu du plateau
    assert table.loc[1, "robust_score"] == pytest.approx(0.0)  # le pic isolé est pénalisé
    # Le bord (p=7) a un voisin hors grille, compté comme le pire score.
    assert table.loc[6, "robust_score"] < table.loc[5, "robust_score"]


def test_robust_score_in_two_dimensions() -> None:
    grid = {"a": [1, 2, 3], "b": [10, 20, 30]}
    table = pd.DataFrame(expand_grid(grid))
    table["score"] = 1.0
    table.loc[(table["a"] == 2) & (table["b"] == 20), "score"] = 5.0
    robust = robust_scores(table, grid)
    assert robust.max() == pytest.approx(1.0)  # un seul bon point ne suffit pas


def test_split_train_excludes_test_period() -> None:
    data = {"SPY": daily_frame("2020-01-01", "2023-12-31")}
    train = split_train(data, SPLIT)
    assert train["SPY"].index.max() < pd.Timestamp(SPLIT)
    with pytest.raises(ValueError, match="aucune donnée"):
        split_train(data, datetime(2019, 1, 1, tzinfo=UTC))


def test_trade_start_uses_prior_history_only_for_warmup() -> None:
    df = daily_frame("2020-01-01", "2023-12-31")
    seen: list[int] = []

    class Probe(Strategy):
        def on_bar(self, ctx: StrategyContext) -> list[Signal]:
            seen.append(len(ctx.history("SPY", 300)))
            return [Signal("SPY", ctx.timestamp, 1.0)] if len(seen) == 1 else []

    result = run_backtest(Probe(), {"SPY": df}, 1_000, PRESETS["zero"], trade_start=SPLIT)
    assert result.equity.index[0] >= pd.Timestamp(SPLIT)
    assert seen[0] == 300  # l'historique d'avant la coupure est visible dès le 1er appel
    assert result.fills[0].timestamp > pd.Timestamp(SPLIT)
    assert compute_metrics(result).start >= "2022-01-01"


def test_optimizer_never_sees_the_test_period_during_search() -> None:
    data = {"SPY": daily_frame("2019-01-01", "2023-12-31")}
    latest_seen: list[datetime] = []

    class Recorder(TrendFollowing):
        name = "recorder"

        def on_bar(self, ctx: StrategyContext) -> list[Signal]:
            latest_seen.append(ctx.timestamp)
            return super().on_bar(ctx)

    STRATEGIES["recorder"] = Recorder
    try:
        from tradebot.backtest.optimize import grid_search

        grid_search(
            "recorder", ("SPY",), split_train(data, SPLIT), {"lookback": [20, 50]}, SETUP, "calmar"
        )
    finally:
        del STRATEGIES["recorder"]
    assert max(latest_seen) < SPLIT


def test_optimize_end_to_end() -> None:
    data = {s: daily_frame("2018-01-01", "2023-12-31", seed=i) for i, s in enumerate(("A", "B"))}
    res = optimize("momentum", ("A", "B"), data, SPLIT, SETUP, "calmar")
    assert res.combinations == 8
    assert set(res.chosen) == {"lookback", "top_n"}
    assert res.chosen == {k: res.table[k].iloc[0] for k in res.chosen}
    assert all(type(v) is int for v in res.chosen.values())  # 126, pas 126.0
    assert res.test_metrics.start >= "2022-01-01"
    assert res.benchmark_metrics.start == res.test_metrics.start
    assert res.train.end < "2022-01-01"


def test_cli_optimize(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    store = ParquetBarStore(tmp_path / "data")
    for i, s in enumerate(("SPY", "TLT")):
        store.save(s, Timeframe.DAY, daily_frame("2018-01-01", "2023-12-31", seed=i))
    config = tmp_path / "c.yaml"
    config.write_text(
        f"data_dir: {tmp_path / 'data'}\nlog_dir: {tmp_path / 'logs'}\n"
        f"report_dir: {tmp_path / 'reports'}\nsymbols: [SPY, TLT]\n",
        encoding="utf-8",
    )
    assert main(["--config", str(config), "optimize", "--strategy", "trend"]) == 0
    out = capsys.readouterr().out
    assert "5 combinaisons" in out
    assert "Période de TEST" in out
    (report,) = (tmp_path / "reports").iterdir()
    assert (report / "grid.csv").exists()

    assert main(["--config", str(config), "optimize", "--no-report", "--split", "2021-06-01"]) == 0
    out = capsys.readouterr().out
    assert "Classement sur la période de test" in out
    for name in ("trend", "momentum", "mean_reversion", "buy_and_hold"):
        assert name in out

    assert main(["--config", str(config), "optimize", "--strategy", "buy_and_hold"]) == 2


def test_cli_backtest_with_params(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ParquetBarStore(tmp_path / "data").save(
        "SPY", Timeframe.DAY, daily_frame("2020-01-01", "2023-12-31")
    )
    config = tmp_path / "c.yaml"
    config.write_text(
        f"data_dir: {tmp_path / 'data'}\nlog_dir: {tmp_path / 'logs'}\nsymbols: [SPY]\n"
        "strategy_params: {trend: {lookback: 100}}\n",
        encoding="utf-8",
    )
    args = ["--config", str(config), "backtest", "--no-report", "--strategy", "trend"]
    assert main(args) == 0
    assert "lookback=100" in capsys.readouterr().out  # depuis la config
    assert main([*args, "--param", "lookback=60"]) == 0
    assert "lookback=60" in capsys.readouterr().out  # la CLI l'emporte
    assert main([*args, "--param", "lookback=abc"]) == 2
    assert main([*args, "--param", "oops"]) == 2
