"""Broker simulé pour le backtest.

Règles d'exécution (volontairement conservatrices) :
- un ordre soumis à la clôture de la barre J est exécuté sur la barre J+1 du même symbole ;
- ordre au marché : prix d'ouverture + slippage défavorable ;
- ordre limite : exécuté à l'ouverture si elle est meilleure que la limite, sinon à la limite
  si le prix l'a touchée pendant la barre ; sinon annulé (validité : une barre) ;
- ventes traitées avant les achats (le cash libéré sert aux achats de la même barre) ;
- achat au marché plus cher que le cash disponible (écart entre la clôture où l'ordre a
  été calculé et l'ouverture où il est exécuté) : quantité réduite au cash disponible
  (`resize_buys`, comme un ordre « en montant » chez Alpaca), sinon rejet ;
- rejet si l'identifiant est déjà utilisé, si le cash reste insuffisant (pas d'effet de
  levier) ou si la vente ouvrirait une position vendeuse non autorisée.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping
from dataclasses import dataclass

from tradebot.domain import QTY_EPSILON, Bar, Fill, Order, OrderStatus, OrderType, Portfolio, Side
from tradebot.execution.costs import CostModel

log = logging.getLogger(__name__)


@dataclass
class OrderRecord:
    order: Order
    status: OrderStatus = OrderStatus.SUBMITTED
    reason: str = ""


class SimulatedBroker:
    def __init__(
        self,
        initial_cash: float,
        costs: CostModel,
        *,
        allow_short: bool = False,
        allow_fractional: bool = True,
        resize_buys: bool = True,
    ) -> None:
        self.portfolio = Portfolio(initial_cash)
        self._costs = costs
        self._allow_short = allow_short
        self._allow_fractional = allow_fractional
        self._resize_buys = resize_buys
        self.resized = 0  # nombre d'achats réduits faute de cash
        self._records: dict[str, OrderRecord] = {}
        self._pending: list[str] = []
        self.fills: list[Fill] = []
        # Coût total du slippage : écart défavorable entre le prix d'ouverture et le prix obtenu.
        self.slippage_paid = 0.0
        self.rejected: list[OrderRecord] = []

    def submit(self, order: Order) -> OrderRecord:
        if order.client_order_id in self._records:
            record = OrderRecord(order, OrderStatus.REJECTED, "identifiant déjà utilisé")
            self._reject(record)
            return record
        record = OrderRecord(order)
        self._records[order.client_order_id] = record
        self._pending.append(order.client_order_id)
        return record

    def status(self, client_order_id: str) -> OrderStatus | None:
        record = self._records.get(client_order_id)
        return record.status if record else None

    @property
    def open_orders(self) -> list[Order]:
        return [self._records[i].order for i in self._pending]

    def process_bar(self, bars: Mapping[str, Bar]) -> list[Fill]:
        """Exécute les ordres en attente sur les barres reçues. Retourne les fills."""
        ready = [self._records[i] for i in self._pending if self._records[i].order.symbol in bars]
        # Un symbole sans barre (suspendu, jour sans cotation) garde ses ordres en attente.
        self._pending = [i for i in self._pending if self._records[i].order.symbol not in bars]
        ready.sort(key=lambda r: r.order.side is Side.BUY)  # ventes d'abord

        fills = []
        for record in ready:
            fill = self._execute(record, bars[record.order.symbol])
            if fill is not None:
                fills.append(fill)
        self.fills.extend(fills)
        return fills

    def _execute(self, record: OrderRecord, bar: Bar) -> Fill | None:
        order = record.order
        price = self._fill_price(order, bar)
        if price is None:
            record.status = OrderStatus.CANCELLED
            record.reason = "limite non atteinte"
            return None

        quantity = order.quantity
        commission = self._costs.commission(quantity, price)
        held = self.portfolio.quantity(order.symbol)
        if order.side is Side.BUY and held >= -QTY_EPSILON:
            cost = quantity * price + commission
            if cost > self.portfolio.cash + 1e-9:
                affordable = self._affordable(price) if self._resize_buys else 0.0
                if affordable <= QTY_EPSILON:
                    record.reason = f"cash insuffisant ({cost:.2f} > {self.portfolio.cash:.2f})"
                    self._reject(record)
                    return None
                log.debug(f"achat {order.client_order_id} réduit : {quantity:g} -> {affordable:g}")
                quantity = affordable
                commission = self._costs.commission(quantity, price)
                record.reason = f"quantité réduite à {affordable:g} faute de cash"
                self.resized += 1
        elif order.side is Side.SELL and not self._allow_short and quantity > held + QTY_EPSILON:
            record.reason = f"vente à découvert interdite (détenu : {held:g})"
            self._reject(record)
            return None

        fill = Fill(
            order.client_order_id,
            order.symbol,
            order.side,
            quantity,
            price,
            bar.timestamp,
            commission,
        )
        self.portfolio.apply_fill(fill)
        self.slippage_paid += max(0.0, order.side.sign * (price - bar.open)) * quantity
        record.status = OrderStatus.FILLED
        return fill

    def _affordable(self, price: float) -> float:
        """Plus grande quantité achetable avec le cash disponible, frais compris."""
        cash = self.portfolio.cash
        quantity = cash / price
        for _ in range(5):  # la commission dépend de la quantité : quelques ajustements
            quantity = max(0.0, (cash - self._costs.commission(quantity, price)) / price)
        quantity *= 1 - 1e-9  # marge contre les arrondis
        return quantity if self._allow_fractional else float(math.floor(quantity))

    def _fill_price(self, order: Order, bar: Bar) -> float | None:
        if order.order_type is OrderType.MARKET:
            return self._costs.apply_slippage(order.side, bar.open)
        limit = order.limit_price
        assert limit is not None
        if order.side is Side.BUY:
            if bar.open <= limit:
                return min(self._costs.apply_slippage(Side.BUY, bar.open), limit)
            return limit if bar.low <= limit else None
        if bar.open >= limit:
            return max(self._costs.apply_slippage(Side.SELL, bar.open), limit)
        return limit if bar.high >= limit else None

    def _reject(self, record: OrderRecord) -> None:
        record.status = OrderStatus.REJECTED
        self.rejected.append(record)
        log.warning(
            f"ordre rejeté {record.order.client_order_id} : {record.reason}",
            extra={
                "event": {
                    "order_id": record.order.client_order_id,
                    "symbol": record.order.symbol,
                    "reason": record.reason,
                }
            },
        )
