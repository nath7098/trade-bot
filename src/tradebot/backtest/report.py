"""Rapports de backtest : tableau comparatif, exports CSV/JSON, graphique."""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # rendu fichier, sans interface graphique
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.axes import Axes
from matplotlib.ticker import FuncFormatter, PercentFormatter

from tradebot.backtest.engine import BacktestResult
from tradebot.backtest.metrics import Metrics, drawdown

# Palette catégorielle validée (daltonisme, contraste) : stratégie puis référence.
SERIES_COLORS = ["#2a78d6", "#eb6834"]
SURFACE = "#fcfcfb"
TEXT_PRIMARY = "#0b0b0b"
TEXT_SECONDARY = "#52514e"
GRID = "#e4e3df"


def _pct(v: float) -> str:
    return "n/d" if not math.isfinite(v) else f"{v:+.2%}"


def _num(v: float) -> str:
    return "n/d" if not math.isfinite(v) else f"{v:,.2f}"


def _money(v: float) -> str:
    return f"{v:,.2f}"


ROWS: list[tuple[str, str, Callable[[float], str]]] = [
    ("Capital final", "final_equity", _money),
    ("Rendement total", "total_return", _pct),
    ("Rendement annualisé (CAGR)", "cagr", _pct),
    ("Volatilité annualisée", "volatility", lambda v: _pct(v).lstrip("+")),
    ("Sharpe", "sharpe", _num),
    ("Sortino", "sortino", _num),
    ("Drawdown max", "max_drawdown", _pct),
    ("Plus long drawdown (jours)", "max_drawdown_days", lambda v: f"{v:.0f}"),
    ("Calmar", "calmar", _num),
    ("Exposition moyenne", "avg_exposure", lambda v: f"{v:.0%}"),
    ("Exécutions", "fills", lambda v: f"{v:.0f}"),
    ("Ordres rejetés", "rejected", lambda v: f"{v:.0f}"),
    ("Rotation annuelle", "turnover", lambda v: "n/d" if not math.isfinite(v) else f"{v:.1f}x"),
    ("Commissions", "commissions", _money),
    ("Slippage", "slippage", _money),
    ("Coûts totaux", "total_costs", _money),
    ("Coûts / an (% capital)", "cost_drag", lambda v: _pct(v).lstrip("+")),
]


def format_table(metrics: Mapping[str, Metrics]) -> str:
    """Tableau texte : une colonne par stratégie."""
    names = list(metrics)
    label_w = max(len(r[0]) for r in ROWS)
    cells = {n: [fmt(float(getattr(metrics[n], attr))) for _, attr, fmt in ROWS] for n in names}
    widths = {n: max(len(n), *(len(c) for c in cells[n])) for n in names}
    header = " " * label_w + "  " + "  ".join(n.rjust(widths[n]) for n in names)
    lines = [header, "-" * len(header)]
    for i, (label, _, _) in enumerate(ROWS):
        lines.append(
            label.ljust(label_w) + "  " + "  ".join(cells[n][i].rjust(widths[n]) for n in names)
        )
    return "\n".join(lines)


def save_report(
    out_dir: Path,
    results: Mapping[str, BacktestResult],
    metrics: Mapping[str, Metrics],
    notes: list[str],
) -> None:
    """Écrit dans `out_dir` : metrics.json, equity.csv, trades_<nom>.csv, rejected_<nom>.csv,
    equity.png. Le premier élément de `results` est la stratégie, les suivants les références."""
    out_dir.mkdir(parents=True, exist_ok=True)

    payload = {"metrics": {n: m.as_dict() for n, m in metrics.items()}, "warnings": notes}
    (out_dir / "metrics.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )

    curves = {}
    for name, result in results.items():
        curves[f"{name}_equity"] = result.equity
        curves[f"{name}_drawdown"] = drawdown(result.equity)
        curves[f"{name}_exposure"] = result.exposure
    pd.DataFrame(curves).to_csv(out_dir / "equity.csv")

    for name, result in results.items():
        result.trades().to_csv(out_dir / f"trades_{name}.csv", index=False)
        rejected = pd.DataFrame(
            [
                {
                    "order_id": r.order.client_order_id,
                    "symbol": r.order.symbol,
                    "side": r.order.side.value,
                    "quantity": r.order.quantity,
                    "created_at": r.order.created_at,
                    "reason": r.reason,
                }
                for r in result.rejected
            ]
        )
        rejected.to_csv(out_dir / f"rejected_{name}.csv", index=False)

    plot_equity(results, out_dir / "equity.png")


def plot_equity(results: Mapping[str, BacktestResult], path: Path) -> None:
    """Deux graphiques superposés, même axe du temps : capital puis drawdown."""
    fig, (ax_eq, ax_dd) = plt.subplots(
        2,
        1,
        figsize=(10, 6.5),
        sharex=True,
        gridspec_kw={"height_ratios": [2, 1], "hspace": 0.12},
        facecolor=SURFACE,
    )
    if len(results) > len(SERIES_COLORS):
        raise ValueError(f"au plus {len(SERIES_COLORS)} courbes par graphique")
    for color, (name, result) in zip(SERIES_COLORS, results.items(), strict=False):
        equity = result.equity
        ax_eq.plot(equity.index, equity.values, color=color, linewidth=1.5, label=name)
        ax_dd.plot(equity.index, drawdown(equity).values, color=color, linewidth=1.5, label=name)

    ax_eq.set_title("Valeur du compte", loc="left", color=TEXT_PRIMARY, fontsize=12)
    ax_dd.set_title(
        "Drawdown (baisse depuis le plus haut)", loc="left", color=TEXT_PRIMARY, fontsize=10
    )
    ax_eq.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax_dd.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
    # Légende sur la ligne du titre, hors de la zone des courbes.
    ax_eq.legend(
        loc="lower right",
        bbox_to_anchor=(1.0, 1.0),
        ncol=len(results),
        frameon=False,
        labelcolor=TEXT_PRIMARY,
        fontsize=9,
    )
    _label_last_values(ax_eq, [r.equity for r in results.values()])

    for ax in (ax_eq, ax_dd):
        ax.set_facecolor(SURFACE)
        ax.grid(axis="y", color=GRID, linewidth=0.8)
        ax.tick_params(colors=TEXT_SECONDARY, labelsize=9, length=0)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(GRID)
        ax.set_axisbelow(True)

    fig.savefig(path, dpi=120, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)


def _label_last_values(ax: Axes, series: list[pd.Series], min_gap_px: float = 14) -> None:
    """Étiquette la valeur finale de chaque courbe, en écartant les étiquettes trop proches."""
    fig = ax.get_figure()
    assert fig is not None
    fig.canvas.draw()  # nécessaire pour connaître les positions en pixels
    points = sorted(
        (float(ax.transData.transform((0, s.iloc[-1]))[1]), s) for s in series if len(s)
    )
    placed: list[float] = []
    for y_px, s in points:
        target = max(y_px, placed[-1] + min_gap_px) if placed else y_px
        placed.append(target)
        ax.annotate(
            f"{s.iloc[-1]:,.2f}",
            xy=(s.index[-1], s.iloc[-1]),
            xytext=(6, target - y_px),
            textcoords="offset pixels",
            color=TEXT_PRIMARY,
            fontsize=9,
            va="center",
        )
