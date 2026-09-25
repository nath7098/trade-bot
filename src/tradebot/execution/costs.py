"""Modèle de coûts de transaction : commissions + slippage.

Les valeurs par défaut sont volontairement prudentes. Mieux vaut un backtest un peu
pessimiste qu'une stratégie « rentable » uniquement parce que les frais sont sous-estimés.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from tradebot.domain import Side


class CostModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    # Commission = clamp(par action * quantité + % du montant, minimum, maximum % du montant)
    commission_per_share: float = Field(default=0.0, ge=0)
    commission_pct: float = Field(default=0.0, ge=0)
    commission_min: float = Field(default=0.0, ge=0)
    commission_max_pct: float = Field(default=1.0, ge=0)
    # Écart défavorable entre le prix de référence et le prix obtenu (spread + impact),
    # en points de base (1 bp = 0,01 %).
    slippage_bps: float = Field(default=5.0, ge=0)

    def commission(self, quantity: float, price: float) -> float:
        notional = quantity * price
        fee = quantity * self.commission_per_share + notional * self.commission_pct
        fee = max(fee, self.commission_min)
        return min(fee, notional * self.commission_max_pct)

    def apply_slippage(self, side: Side, price: float) -> float:
        """Prix d'exécution d'un ordre au marché : toujours au désavantage du trader."""
        return price * (1 + side.sign * self.slippage_bps / 10_000)


# Profils indicatifs (tarifs à revérifier chez le broker au moment de l'utilisation).
PRESETS: dict[str, CostModel] = {
    # Sans commission ; le coût réel est dans le spread.
    "alpaca": CostModel(slippage_bps=5.0),
    # IBKR Pro « fixed » actions US : 0,005 $/action, min 1 $, max 1 % du montant.
    "ibkr_fixed": CostModel(
        commission_per_share=0.005, commission_min=1.0, commission_max_pct=0.01, slippage_bps=5.0
    ),
    # IBKR Pro « tiered » (petit volume) : ~0,0035 $/action + frais de place, min 0,35 $.
    "ibkr_tiered": CostModel(
        commission_per_share=0.0035, commission_min=0.35, commission_max_pct=0.01, slippage_bps=5.0
    ),
    "zero": CostModel(slippage_bps=0.0),
}
