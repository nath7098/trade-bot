"""Backtest événementiel, métriques et rapports."""

from tradebot.backtest.engine import BacktestResult, run_backtest
from tradebot.backtest.metrics import Metrics, compute_metrics, drawdown, warnings_for

__all__ = [
    "BacktestResult",
    "Metrics",
    "compute_metrics",
    "drawdown",
    "run_backtest",
    "warnings_for",
]
