"""Positions et portefeuille : comptabilité du cash, des frais et des gains/pertes."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from tradebot.domain.common import QTY_EPSILON, require_positive
from tradebot.domain.orders import Fill


@dataclass(slots=True)
class Position:
    """Position sur un symbole.

    `quantity` est signée (> 0 acheteur, < 0 vendeur). `avg_price` est le prix moyen
    d'entrée de la position ouverte. `realized_pnl` cumule les gains/pertes des
    quantités clôturées, **hors frais** (les frais sont suivis par le portefeuille).
    """

    symbol: str
    quantity: float = 0.0
    avg_price: float = 0.0
    realized_pnl: float = 0.0

    @property
    def is_flat(self) -> bool:
        return abs(self.quantity) < QTY_EPSILON

    def apply(self, fill: Fill) -> float:
        """Met à jour la position avec une exécution. Retourne le PnL réalisé par ce fill."""
        if fill.symbol != self.symbol:
            raise ValueError(f"fill {fill.symbol} appliqué à la position {self.symbol}")

        delta = fill.signed_quantity
        realized = 0.0

        if self.is_flat or (self.quantity > 0) == (delta > 0):
            # Ouverture ou renforcement : nouveau prix moyen pondéré.
            new_qty = self.quantity + delta
            self.avg_price = (self.quantity * self.avg_price + delta * fill.price) / new_qty
            self.quantity = new_qty
        else:
            # Réduction, clôture ou retournement.
            closed = min(abs(delta), abs(self.quantity))
            direction = 1.0 if self.quantity > 0 else -1.0
            realized = closed * (fill.price - self.avg_price) * direction
            self.quantity += delta
            if self.is_flat:
                self.quantity = 0.0
                self.avg_price = 0.0
            elif (self.quantity > 0) != (direction > 0):
                # Retournement : le reliquat ouvre une position dans l'autre sens.
                self.avg_price = fill.price

        self.realized_pnl += realized
        return realized

    def market_value(self, price: float) -> float:
        return self.quantity * price

    def unrealized_pnl(self, price: float) -> float:
        return self.quantity * (price - self.avg_price)


@dataclass(slots=True)
class Portfolio:
    """Cash + positions.

    Relation vérifiée par les tests :
        equity = cash + Σ valeur de marché
               = capital initial + PnL réalisé + PnL latent - frais payés
    """

    initial_cash: float
    cash: float = field(init=False)
    positions: dict[str, Position] = field(default_factory=dict, init=False)
    fees_paid: float = field(default=0.0, init=False)
    # PnL réalisé des positions déjà clôturées (retirées de `positions`).
    _closed_realized: float = field(default=0.0, init=False, repr=False)

    def __post_init__(self) -> None:
        require_positive(self.initial_cash, "initial_cash")
        self.cash = self.initial_cash

    def apply_fill(self, fill: Fill) -> None:
        position = self.positions.setdefault(fill.symbol, Position(fill.symbol))
        position.apply(fill)
        self.cash -= fill.signed_quantity * fill.price + fill.commission
        self.fees_paid += fill.commission
        if position.is_flat:
            self._closed_realized += position.realized_pnl
            del self.positions[fill.symbol]

    def quantity(self, symbol: str) -> float:
        position = self.positions.get(symbol)
        return position.quantity if position else 0.0

    @property
    def realized_pnl(self) -> float:
        """PnL réalisé total, hors frais (positions clôturées et ouvertes)."""
        return self._closed_realized + sum(p.realized_pnl for p in self.positions.values())

    def _price(self, prices: Mapping[str, float], symbol: str) -> float:
        try:
            return prices[symbol]
        except KeyError:
            raise KeyError(f"prix manquant pour valoriser {symbol}") from None

    def market_value(self, prices: Mapping[str, float]) -> float:
        return sum(p.market_value(self._price(prices, s)) for s, p in self.positions.items())

    def unrealized_pnl(self, prices: Mapping[str, float]) -> float:
        return sum(p.unrealized_pnl(self._price(prices, s)) for s, p in self.positions.items())

    def equity(self, prices: Mapping[str, float]) -> float:
        """Valeur totale du compte (cash + positions valorisées aux prix donnés)."""
        return self.cash + self.market_value(prices)

    def exposure(self, prices: Mapping[str, float]) -> float:
        """Exposition brute (somme des valeurs absolues des positions)."""
        return sum(abs(p.market_value(self._price(prices, s))) for s, p in self.positions.items())
