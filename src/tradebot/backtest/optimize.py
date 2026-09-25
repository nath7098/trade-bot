"""Optimisation de paramètres avec validation hors échantillon.

Protocole (pour limiter le surapprentissage) :
1. on coupe l'historique en deux à `split` : apprentissage (avant) / test (après) ;
2. on teste toutes les combinaisons de la grille **sur l'apprentissage uniquement** ;
3. on retient la combinaison la plus **robuste** : celle dont le voisinage dans la grille
   (paramètres adjacents) obtient la meilleure médiane. Un bon réglage entouré de mauvais
   est un coup de chance ; un plateau de bons réglages est plus crédible ;
4. on évalue ce réglage **une seule fois** sur la période de test, jamais vue, et on le
   compare à l'achat-conservation sur la même période.
La dégradation entre apprentissage et test mesure ce que l'optimisation a « inventé ».
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from tradebot.backtest.engine import BacktestResult, run_backtest
from tradebot.backtest.metrics import Metrics, compute_metrics
from tradebot.execution import CostModel
from tradebot.risk import SizingConfig
from tradebot.strategy import BuyAndHold, build_strategy

OBJECTIVES = ("calmar", "sharpe", "sortino", "cagr")


@dataclass(frozen=True)
class BacktestSetup:
    """Conditions communes à tous les backtests d'une optimisation."""

    initial_cash: float
    costs: CostModel
    sizing: SizingConfig
    allow_short: bool = False

    def run(
        self,
        name: str,
        symbols: tuple[str, ...],
        params: Mapping[str, Any],
        data: Mapping[str, pd.DataFrame],
        trade_start: datetime | None = None,
    ) -> BacktestResult:
        return run_backtest(
            build_strategy(name, symbols, params),
            data,
            self.initial_cash,
            self.costs,
            self.sizing,
            allow_short=self.allow_short,
            trade_start=trade_start,
        )


@dataclass
class OptimizationResult:
    strategy: str
    objective: str
    split: datetime
    table: pd.DataFrame  # une ligne par combinaison (apprentissage), triée par robustesse
    chosen: dict[str, Any]
    train: Metrics
    test: BacktestResult
    test_metrics: Metrics
    benchmark: BacktestResult
    benchmark_metrics: Metrics

    @property
    def combinations(self) -> int:
        return len(self.table)


def expand_grid(grid: Mapping[str, list[Any]]) -> list[dict[str, Any]]:
    if not grid:
        return [{}]
    keys = list(grid)
    return [dict(zip(keys, values, strict=True)) for values in itertools.product(*grid.values())]


def split_train(data: Mapping[str, pd.DataFrame], split: datetime) -> dict[str, pd.DataFrame]:
    """Données strictement antérieures à `split` (aucune barre de la période de test)."""
    cut = pd.Timestamp(split)
    train = {s: df[df.index < cut] for s, df in data.items()}
    empty = [s for s, df in train.items() if df.empty]
    if empty:
        raise ValueError(f"aucune donnée avant {cut.date()} pour {', '.join(empty)}")
    return train


def score(metrics: Metrics, objective: str) -> float:
    """Valeur de l'objectif ; un ratio non défini (NaN) compte comme le pire score."""
    if objective not in OBJECTIVES:
        raise ValueError(f"objectif inconnu : {objective} (choix : {', '.join(OBJECTIVES)})")
    value = float(getattr(metrics, objective))
    return value if math.isfinite(value) else -math.inf


def robust_scores(
    table: pd.DataFrame, grid: Mapping[str, list[Any]], column: str = "score"
) -> pd.Series:
    """Médiane du score sur chaque combinaison et ses voisines (au plus un cran d'écart
    sur chaque paramètre). Un voisin hors de la grille compte comme le pire score :
    un optimum au bord de la grille est suspect (le vrai optimum est peut-être au-delà)
    et ne doit pas être favorisé parce qu'il a moins de voisins."""
    if not grid:
        return table[column].astype("float64")
    sizes = np.array([len(v) for v in grid.values()])
    positions = np.array(
        [[grid[k].index(row[k]) for k in grid] for _, row in table.iterrows()], dtype=int
    )
    scores = table[column].to_numpy(dtype="float64")
    worst = float(np.min(scores))
    lookup = {tuple(p): v for p, v in zip(positions, scores, strict=True)}
    offsets = list(itertools.product((-1, 0, 1), repeat=len(sizes)))
    result = []
    for pos in positions:
        values = []
        for offset in offsets:
            neighbor = pos + np.array(offset)
            inside = bool(np.all((neighbor >= 0) & (neighbor < sizes)))
            values.append(lookup.get(tuple(neighbor), worst) if inside else worst)
        result.append(float(np.median(values)))
    return pd.Series(result, index=table.index, name="robust_score")


def grid_search(
    name: str,
    symbols: tuple[str, ...],
    train: Mapping[str, pd.DataFrame],
    grid: Mapping[str, list[Any]],
    setup: BacktestSetup,
    objective: str,
) -> pd.DataFrame:
    rows = []
    for params in expand_grid(grid):
        metrics = compute_metrics(setup.run(name, symbols, params, train))
        rows.append(
            {
                **params,
                "score": score(metrics, objective),
                "cagr": metrics.cagr,
                "max_drawdown": metrics.max_drawdown,
                "sharpe": metrics.sharpe,
                "fills": metrics.fills,
            }
        )
    table = pd.DataFrame(rows)
    table["robust_score"] = robust_scores(table, grid)
    return table.sort_values(["robust_score", "score"], ascending=False, ignore_index=True)


def optimize(
    name: str,
    symbols: tuple[str, ...],
    data: Mapping[str, pd.DataFrame],
    split: datetime,
    setup: BacktestSetup,
    objective: str = "calmar",
    grid: Mapping[str, list[Any]] | None = None,
) -> OptimizationResult:
    from tradebot.strategy import STRATEGIES

    grid = dict(grid if grid is not None else STRATEGIES[name].grid)
    train = split_train(data, split)
    table = grid_search(name, symbols, train, grid, setup, objective)
    # Lecture par colonne (et non par ligne) pour garder les types : 150 et non 150.0.
    chosen = {k: _plain(table[k].iloc[0]) for k in grid}

    train_metrics = compute_metrics(setup.run(name, symbols, chosen, train))
    # Période de test : l'historique d'avant `split` ne sert qu'à échauffer les indicateurs.
    test = setup.run(name, symbols, chosen, data, trade_start=split)
    benchmark = setup.run(BuyAndHold.name, symbols, {}, data, trade_start=split)
    return OptimizationResult(
        strategy=name,
        objective=objective,
        split=split,
        table=table,
        chosen=chosen,
        train=train_metrics,
        test=test,
        test_metrics=compute_metrics(test),
        benchmark=benchmark,
        benchmark_metrics=compute_metrics(benchmark),
    )


def _plain(value: Any) -> Any:
    """Convertit les scalaires numpy en types Python (pour pydantic et l'affichage)."""
    return value.item() if isinstance(value, np.generic) else value
