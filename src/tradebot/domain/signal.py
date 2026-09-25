"""Signal émis par une stratégie."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from tradebot.domain.common import require_symbol, require_utc_aware


@dataclass(frozen=True, slots=True)
class Signal:
    """Exposition souhaitée par la stratégie sur un symbole.

    La stratégie exprime une **cible** (fraction du capital), pas un ordre :
    `target_weight = 0.5` signifie « je veux 50 % du capital investi sur ce symbole »,
    `0` signifie « aucune position », une valeur négative signifie une position vendeuse.
    C'est le risk manager qui décide si, et combien, acheter ou vendre pour s'en approcher.
    Raisonner en cible rend le système idempotent : répéter le même signal ne
    duplique pas les ordres.
    """

    symbol: str
    timestamp: datetime
    target_weight: float
    reason: str = ""

    def __post_init__(self) -> None:
        require_symbol(self.symbol)
        require_utc_aware(self.timestamp, "timestamp")
        if not math.isfinite(self.target_weight) or not -1.0 <= self.target_weight <= 1.0:
            raise ValueError(f"target_weight doit être dans [-1, 1] : {self.target_weight!r}")
