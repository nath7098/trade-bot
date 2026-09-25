"""Conversion des expositions cibles (signaux) en ordres.

Version minimale : les limites de risque (taille max, perte journalière, kill-switch...)
viendront s'ajouter à l'étape « gestion du risque ».
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from tradebot.domain import Order, Portfolio, Side, Signal


class SizingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    allow_fractional: bool = True
    # Part du capital laissée en cash pour absorber l'écart entre le prix de calcul
    # (clôture) et le prix d'exécution (ouverture suivante) + les frais.
    cash_buffer: float = Field(default=0.02, ge=0, lt=1)
    # Ajustement ignoré s'il représente moins de ce pourcentage du capital (évite
    # de payer des frais pour des micro-rééquilibrages). Une clôture complète passe toujours.
    min_trade_pct: float = Field(default=0.01, ge=0, lt=1)
    # Montant minimum d'un ordre (Alpaca : 1 $ pour les fractions d'actions).
    min_order_value: float = Field(default=1.0, ge=0)


def orders_for_signals(
    signals: Sequence[Signal],
    portfolio: Portfolio,
    prices: Mapping[str, float],
    now: datetime,
    config: SizingConfig,
    id_prefix: str,
) -> list[Order]:
    """Calcule les ordres qui rapprochent le portefeuille des expositions cibles.

    `prices` : dernier prix connu de chaque symbole détenu ou visé.
    Les achats sont réduits proportionnellement s'ils dépassent le cash disponible
    (cash actuel + produit estimé des ventes - réserve) : pas d'effet de levier.
    """
    equity = portfolio.equity(prices)
    investable = equity * (1 - config.cash_buffer)

    deltas: dict[str, float] = {}
    for signal in signals:
        price = prices[signal.symbol]
        target = signal.target_weight * investable / price
        if not config.allow_fractional:
            target = float(math.trunc(target))
        deltas[signal.symbol] = target - portfolio.quantity(signal.symbol)

    sells = sum(-d * prices[s] for s, d in deltas.items() if d < 0)
    buys = sum(d * prices[s] for s, d in deltas.items() if d > 0)
    available = portfolio.cash + sells - equity * config.cash_buffer
    if buys > 0 and buys > available:
        scale = max(available, 0.0) / buys
        for symbol, delta in deltas.items():
            if delta > 0:
                scaled = delta * scale
                deltas[symbol] = scaled if config.allow_fractional else float(math.trunc(scaled))

    orders = []
    for symbol, delta in deltas.items():
        price = prices[symbol]
        held = portfolio.quantity(symbol)
        closing = held != 0 and delta == -held

        value = abs(delta) * price
        if delta == 0:
            continue
        if value < config.min_order_value and not closing:
            continue
        if value < config.min_trade_pct * equity and not closing:
            continue

        side = Side.BUY if delta > 0 else Side.SELL
        orders.append(
            Order(
                client_order_id=f"{id_prefix}-{symbol}-{now:%Y%m%dT%H%M}-{side.value}",
                symbol=symbol,
                side=side,
                quantity=abs(delta),
                created_at=now,
            )
        )
    return orders
