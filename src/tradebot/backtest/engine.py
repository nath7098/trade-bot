"""Moteur de backtest événementiel (barre par barre).

À chaque date t, dans cet ordre :
1. le broker exécute les ordres en attente sur les barres de t (prix d'ouverture) ;
2. le portefeuille est valorisé à la clôture de t ;
3. la stratégie voit les barres jusqu'à t inclus et renvoie ses signaux ;
4. les signaux deviennent des ordres, exécutés au plus tôt à t+1.
Il est donc impossible pour une stratégie d'agir au prix qu'elle vient d'observer.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from tradebot.data.frame import iter_bars, normalize
from tradebot.domain import Bar, Fill, Portfolio
from tradebot.execution import CostModel, OrderRecord, SimulatedBroker
from tradebot.risk import SizingConfig, orders_for_signals
from tradebot.strategy import Strategy

log = logging.getLogger(__name__)


@dataclass
class BacktestResult:
    strategy: str
    initial_cash: float
    equity: pd.Series  # valeur du compte à chaque clôture
    exposure: pd.Series  # part du capital investie (brute) à chaque clôture
    fills: list[Fill]
    rejected: list[OrderRecord]
    portfolio: Portfolio
    slippage_paid: float = 0.0
    resized_orders: int = 0  # achats réduits faute de cash à l'exécution

    @property
    def final_equity(self) -> float:
        return float(self.equity.iloc[-1]) if len(self.equity) else self.initial_cash

    @property
    def total_return(self) -> float:
        return self.final_equity / self.initial_cash - 1

    def trades(self) -> pd.DataFrame:
        """Journal des exécutions."""
        return pd.DataFrame(
            [
                {
                    "timestamp": f.timestamp,
                    "order_id": f.order_id,
                    "symbol": f.symbol,
                    "side": f.side.value,
                    "quantity": f.quantity,
                    "price": f.price,
                    "commission": f.commission,
                }
                for f in self.fills
            ]
        )


class _Context:
    """Vue de la stratégie sur les données : uniquement le passé et le présent."""

    def __init__(self, data: Mapping[str, pd.DataFrame]) -> None:
        self._data = data
        self._cursor: dict[str, int] = {}  # position de la dernière barre vue
        self.timestamp: datetime = datetime.min
        self.bars: dict[str, Bar] = {}

    def advance(self, timestamp: datetime, bars: dict[str, Bar]) -> None:
        self.timestamp = timestamp
        self.bars = bars
        for symbol in bars:
            self._cursor[symbol] = self._cursor.get(symbol, -1) + 1

    def history(self, symbol: str, lookback: int) -> pd.DataFrame:
        end = self._cursor.get(symbol, -1) + 1
        return self._data[symbol].iloc[max(0, end - lookback) : end]


def run_backtest(
    strategy: Strategy,
    data: Mapping[str, pd.DataFrame],
    initial_cash: float,
    costs: CostModel,
    sizing: SizingConfig | None = None,
    *,
    allow_short: bool = False,
    trade_start: datetime | None = None,
) -> BacktestResult:
    """Rejoue `strategy` sur `data` (symbole -> barres au format standard).

    `trade_start` : les barres antérieures servent uniquement d'historique (échauffement
    des indicateurs) ; la stratégie n'est appelée et le capital n'est suivi qu'à partir
    de cette date.
    """
    sizing = sizing or SizingConfig()
    frames = {s: normalize(df) for s, df in data.items()}
    for symbol, df in frames.items():
        if df.index.has_duplicates:
            raise ValueError(f"{symbol} : dates en double, lancer `tradebot data check`")
    bars_by_time: dict[pd.Timestamp, dict[str, Bar]] = {}
    for symbol, df in frames.items():
        for ts, bar in zip(df.index, iter_bars(df, symbol), strict=True):
            bars_by_time.setdefault(ts, {})[symbol] = bar

    broker = SimulatedBroker(
        initial_cash, costs, allow_short=allow_short, allow_fractional=sizing.allow_fractional
    )
    ctx = _Context(frames)
    last_close: dict[str, float] = {}
    equity: dict[pd.Timestamp, float] = {}
    exposure: dict[pd.Timestamp, float] = {}

    start = pd.Timestamp(trade_start) if trade_start is not None else None
    for ts in sorted(bars_by_time):
        bars = bars_by_time[ts]
        now = ts.to_pydatetime()
        if start is not None and ts < start:
            ctx.advance(now, bars)
            continue
        broker.process_bar(bars)
        last_close.update({s: b.close for s, b in bars.items()})
        equity[ts] = broker.portfolio.equity(last_close)
        exposure[ts] = broker.portfolio.exposure(last_close) / equity[ts]

        ctx.advance(now, bars)
        signals = strategy.on_bar(ctx)
        for signal in signals:
            if signal.symbol not in last_close:
                raise ValueError(f"signal sur {signal.symbol} sans barre connue à {now}")
        orders = orders_for_signals(
            signals, broker.portfolio, last_close, now, sizing, strategy.name
        )
        for order in orders:
            broker.submit(order)

    if not equity:
        raise ValueError("aucune barre dans la période de trading demandée")
    if broker.open_orders:
        log.debug(f"{len(broker.open_orders)} ordre(s) non exécuté(s) en fin de backtest")

    series = pd.Series(equity, dtype="float64", name="equity")
    series.index.name = "timestamp"
    return BacktestResult(
        strategy.name,
        initial_cash,
        series,
        pd.Series(exposure, dtype="float64", name="exposure"),
        broker.fills,
        broker.rejected,
        broker.portfolio,
        broker.slippage_paid,
        broker.resized,
    )
