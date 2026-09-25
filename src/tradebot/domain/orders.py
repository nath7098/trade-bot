"""Ordres et exécutions (fills)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from tradebot.domain.common import (
    require_non_negative,
    require_positive,
    require_symbol,
    require_utc_aware,
)


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"

    @property
    def sign(self) -> int:
        """+1 pour un achat, -1 pour une vente."""
        return 1 if self is Side.BUY else -1


class OrderType(StrEnum):
    MARKET = "market"
    LIMIT = "limit"


class OrderStatus(StrEnum):
    NEW = "new"  # créé localement, pas encore envoyé
    SUBMITTED = "submitted"  # accepté par le broker
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"

    @property
    def is_terminal(self) -> bool:
        return self in {OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED}


@dataclass(frozen=True, slots=True)
class Order:
    """Demande d'achat ou de vente.

    `client_order_id` est choisi par nous et unique : c'est lui qui permet au broker
    (et à nous) de détecter un ordre envoyé deux fois après une coupure.
    """

    client_order_id: str
    symbol: str
    side: Side
    quantity: float
    created_at: datetime
    order_type: OrderType = OrderType.MARKET
    limit_price: float | None = None

    def __post_init__(self) -> None:
        if not self.client_order_id.strip():
            raise ValueError("client_order_id vide")
        require_symbol(self.symbol)
        require_positive(self.quantity, "quantity")
        require_utc_aware(self.created_at, "created_at")
        if self.order_type is OrderType.LIMIT:
            if self.limit_price is None:
                raise ValueError("un ordre LIMIT exige un limit_price")
            require_positive(self.limit_price, "limit_price")
        elif self.limit_price is not None:
            raise ValueError("un ordre MARKET ne doit pas avoir de limit_price")


@dataclass(frozen=True, slots=True)
class Fill:
    """Exécution (totale ou partielle) d'un ordre.

    `commission` regroupe tous les frais facturés pour cette exécution. Le slippage,
    lui, est déjà inclus dans `price` (prix réellement obtenu).
    """

    order_id: str
    symbol: str
    side: Side
    quantity: float
    price: float
    timestamp: datetime
    commission: float = 0.0

    def __post_init__(self) -> None:
        require_symbol(self.symbol)
        require_positive(self.quantity, "quantity")
        require_positive(self.price, "price")
        require_non_negative(self.commission, "commission")
        require_utc_aware(self.timestamp, "timestamp")

    @property
    def signed_quantity(self) -> float:
        return self.side.sign * self.quantity

    @property
    def notional(self) -> float:
        """Montant échangé, hors frais."""
        return self.quantity * self.price
