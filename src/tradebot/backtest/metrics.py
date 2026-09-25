"""Mesures de performance et de risque d'un backtest.

Conventions :
- rendements calculés sur la courbe de capital (après frais et slippage) ;
- annualisation d'après la durée calendaire réelle de la période, ce qui marche
  pour toute granularité de barres ;
- taux sans risque nul par défaut (paramétrable) ;
- une valeur non calculable (ex. volatilité nulle) vaut NaN, jamais 0.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from tradebot.backtest.engine import BacktestResult

DAYS_PER_YEAR = 365.25


@dataclass(frozen=True)
class Metrics:
    start: str
    end: str
    years: float
    initial_equity: float
    final_equity: float
    total_return: float
    cagr: float  # rendement annualisé composé
    volatility: float  # écart-type annualisé des rendements
    sharpe: float  # (rendement - sans risque) / volatilité, annualisé
    sortino: float  # comme Sharpe, mais ne pénalise que la volatilité à la baisse
    max_drawdown: float  # pire baisse depuis un sommet (négatif)
    max_drawdown_days: int  # plus longue période (jours calendaires) sous un sommet
    calmar: float  # CAGR / |max drawdown|
    avg_exposure: float  # part moyenne du capital investie
    fills: int
    rejected: int
    turnover: float  # montant échangé par an / capital moyen
    commissions: float
    slippage: float
    total_costs: float
    cost_drag: float  # coûts annuels / capital moyen

    def as_dict(self) -> dict[str, float | int | str]:
        return asdict(self)


def drawdown(equity: pd.Series) -> pd.Series:
    """Baisse relative depuis le plus haut atteint (0 au sommet, négatif sinon)."""
    return equity / equity.cummax() - 1


def _longest_underwater_days(equity: pd.Series) -> int:
    index = pd.DatetimeIndex(equity.index)
    peak_time, peak = index[0], float(equity.iloc[0])
    longest = 0
    for ts, value in zip(index, equity.to_numpy(dtype="float64"), strict=True):
        if value >= peak:
            peak, peak_time = float(value), ts
        else:
            longest = max(longest, (ts - peak_time).days)
    return longest


def _ratio(numerator: float, denominator: float) -> float:
    if denominator == 0 or not math.isfinite(denominator):
        return math.nan
    return numerator / denominator


def compute_metrics(result: BacktestResult, risk_free_rate: float = 0.0) -> Metrics:
    equity = result.equity
    if len(equity) < 2:
        raise ValueError("au moins deux points de capital sont nécessaires")

    index = pd.DatetimeIndex(equity.index)
    years = (index[-1] - index[0]).days / DAYS_PER_YEAR
    returns = equity.pct_change().dropna()
    periods_per_year = len(returns) / years if years > 0 else math.nan

    total_return = float(equity.iloc[-1] / result.initial_cash - 1)
    cagr = (1 + total_return) ** (1 / years) - 1 if years > 0 and total_return > -1 else math.nan

    rf_per_period = (1 + risk_free_rate) ** (1 / periods_per_year) - 1
    excess = returns - rf_per_period
    std = float(returns.std(ddof=1))
    volatility = std * math.sqrt(periods_per_year)
    sharpe = _ratio(float(excess.mean()) * math.sqrt(periods_per_year), std)
    downside = float(np.sqrt((np.minimum(excess, 0) ** 2).mean()))
    sortino = _ratio(float(excess.mean()) * math.sqrt(periods_per_year), downside)

    max_dd = float(drawdown(equity).min())
    mean_equity = float(equity.mean())
    traded = sum(f.notional for f in result.fills)
    commissions = result.portfolio.fees_paid
    total_costs = commissions + result.slippage_paid

    return Metrics(
        start=str(index[0].date()),
        end=str(index[-1].date()),
        years=years,
        initial_equity=result.initial_cash,
        final_equity=float(equity.iloc[-1]),
        total_return=total_return,
        cagr=cagr,
        volatility=volatility,
        sharpe=sharpe,
        sortino=sortino,
        max_drawdown=max_dd,
        max_drawdown_days=_longest_underwater_days(equity),
        calmar=_ratio(cagr, abs(max_dd)),
        avg_exposure=float(result.exposure.mean()) if len(result.exposure) else math.nan,
        fills=len(result.fills),
        rejected=len(result.rejected),
        turnover=_ratio(traded / mean_equity, years),
        commissions=commissions,
        slippage=result.slippage_paid,
        total_costs=total_costs,
        cost_drag=_ratio(total_costs / mean_equity, years),
    )


def warnings_for(metrics: Metrics) -> list[str]:
    """Avertissements sur la fiabilité statistique des résultats."""
    notes = []
    if metrics.years < 3:
        notes.append(f"période courte ({metrics.years:.1f} ans) : résultats peu représentatifs")
    if 1 < metrics.fills < 30:
        notes.append(f"seulement {metrics.fills} exécutions : statistiquement peu significatif")
    if metrics.rejected:
        notes.append(f"{metrics.rejected} ordre(s) rejeté(s) : vérifier sizing et cash")
    if math.isfinite(metrics.cost_drag) and metrics.cost_drag > 0.02:
        notes.append(f"les coûts coûtent {metrics.cost_drag:.1%} du capital par an")
    return notes
