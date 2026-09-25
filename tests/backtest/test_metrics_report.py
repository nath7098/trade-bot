import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tradebot.backtest import BacktestResult, compute_metrics, drawdown, run_backtest, warnings_for
from tradebot.backtest.report import format_table, save_report
from tradebot.cli import main
from tradebot.config import Timeframe
from tradebot.data import ParquetBarStore
from tradebot.domain import Portfolio
from tradebot.execution import PRESETS, CostModel
from tradebot.strategy import BuyAndHold

from ..data.helpers import daily_frame


def synthetic_result(values: list[float], start: str = "2020-01-01") -> BacktestResult:
    index = pd.date_range(start, periods=len(values), freq="D", tz="UTC")
    equity = pd.Series(values, index=index, dtype="float64")
    return BacktestResult(
        strategy="test",
        initial_cash=values[0],
        equity=equity,
        exposure=pd.Series(1.0, index=index),
        fills=[],
        rejected=[],
        portfolio=Portfolio(values[0]),
    )


def test_drawdown_series() -> None:
    dd = drawdown(pd.Series([100.0, 120.0, 90.0, 130.0]))
    assert list(dd) == pytest.approx([0.0, 0.0, -0.25, 0.0])


def test_known_values() -> None:
    # Capital qui double en exactement 2 ans (731 jours calendaires, 2020 bissextile).
    values = list(np.linspace(100, 200, 732))
    m = compute_metrics(synthetic_result(values))
    assert m.years == pytest.approx(731 / 365.25)
    assert m.total_return == pytest.approx(1.0)
    assert m.cagr == pytest.approx(2 ** (365.25 / 731) - 1)
    assert m.max_drawdown == 0
    assert m.max_drawdown_days == 0
    assert m.sharpe > 0
    assert math.isnan(m.calmar)  # pas de drawdown : ratio non défini, pas infini


def test_drawdown_duration_and_depth() -> None:
    # Sommet à 120 au jour 1, creux à 60 (-50 %), retour au sommet au jour 11.
    values = [100.0, 120.0, *np.linspace(110, 60, 5), *np.linspace(70, 110, 4), 120.0, 125.0]
    m = compute_metrics(synthetic_result(values))
    assert m.max_drawdown == pytest.approx(-0.5)
    assert m.max_drawdown_days == 9  # du jour 1 au jour 10 (dernier jour sous l'eau)


def test_flat_equity_gives_nan_ratios() -> None:
    m = compute_metrics(synthetic_result([100.0] * 300))
    assert m.volatility == 0
    assert math.isnan(m.sharpe)
    assert math.isnan(m.sortino)


def test_costs_are_measured() -> None:
    df = daily_frame("2023-01-01", "2023-12-31")
    costs = CostModel(commission_min=1.0, slippage_bps=10)
    result = run_backtest(BuyAndHold(("SPY",)), {"SPY": df}, 1_000, costs)
    m = compute_metrics(result)
    (fill,) = result.fills
    assert m.commissions == pytest.approx(1.0)
    assert m.slippage == pytest.approx(fill.quantity * df["open"].iloc[1] * 0.001)
    assert m.total_costs == pytest.approx(m.commissions + m.slippage)
    assert m.avg_exposure == pytest.approx(0.97, abs=0.03)  # investi dès le 2e jour


def test_warnings() -> None:
    m = compute_metrics(synthetic_result(list(np.linspace(100, 110, 200))))
    notes = warnings_for(m)
    assert any("période courte" in n for n in notes)


def test_table_and_report_files(tmp_path: Path) -> None:
    data = {"SPY": daily_frame("2021-01-01", "2023-12-31")}
    results = {
        "buy_and_hold": run_backtest(BuyAndHold(("SPY",)), data, 100, PRESETS["ibkr_fixed"]),
        "sans_frais": run_backtest(BuyAndHold(("SPY",)), data, 100, PRESETS["zero"]),
    }
    metrics = {n: compute_metrics(r) for n, r in results.items()}

    table = format_table(metrics)
    assert "Sharpe" in table and "sans_frais" in table

    save_report(tmp_path, results, metrics, ["note"])
    files = {p.name for p in tmp_path.iterdir()}
    assert {"metrics.json", "equity.csv", "equity.png", "trades_buy_and_hold.csv"} <= files
    payload = json.loads((tmp_path / "metrics.json").read_text(encoding="utf-8"))
    assert payload["warnings"] == ["note"]
    # ~98 $ investis : le minimum de 1 $ est plafonné à 1 % du montant.
    (fill,) = results["buy_and_hold"].fills
    assert payload["metrics"]["buy_and_hold"]["commissions"] == pytest.approx(0.01 * fill.notional)
    equity = pd.read_csv(tmp_path / "equity.csv", index_col=0)
    assert "sans_frais_drawdown" in equity.columns
    assert (tmp_path / "equity.png").stat().st_size > 10_000


def test_cli_backtest(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ParquetBarStore(tmp_path / "data").save(
        "SPY", Timeframe.DAY, daily_frame("2021-01-01", "2023-12-31")
    )
    config = tmp_path / "c.yaml"
    config.write_text(
        f"data_dir: {tmp_path / 'data'}\nlog_dir: {tmp_path / 'logs'}\n"
        f"report_dir: {tmp_path / 'reports'}\ncosts: ibkr_fixed\nsymbols: [SPY]\n",
        encoding="utf-8",
    )
    assert main(["--config", str(config), "backtest"]) == 0
    out = capsys.readouterr().out
    assert "buy_and_hold (défauts) sur SPY" in out
    assert "Rendement annualisé (CAGR)" in out
    (report,) = (tmp_path / "reports").iterdir()
    assert (report / "equity.png").exists()

    assert main(["--config", str(config), "backtest", "--no-report"]) == 0
    assert len(list((tmp_path / "reports").iterdir())) == 1

    assert main(["--config", str(config), "backtest", "--strategy", "nope"]) == 2
    assert main(["--config", str(config), "backtest", "QQQ"]) == 2  # pas de données
