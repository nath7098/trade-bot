"""Utilitaires partagés par les types du domaine."""

from __future__ import annotations

import math
from datetime import datetime

# En dessous de ce seuil, une quantité est considérée comme nulle (erreurs d'arrondi
# sur les fractions d'actions).
QTY_EPSILON = 1e-9


def require_utc_aware(value: datetime, name: str) -> None:
    """Refuse les dates sans fuseau horaire : tout le système raisonne en UTC."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} doit avoir un fuseau horaire (UTC recommandé) : {value!r}")


def require_positive(value: float, name: str) -> None:
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} doit être strictement positif : {value!r}")


def require_non_negative(value: float, name: str) -> None:
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} doit être positif ou nul : {value!r}")


def require_symbol(value: str) -> None:
    if not value or value != value.strip().upper():
        raise ValueError(f"symbole invalide (attendu : majuscules, sans espaces) : {value!r}")
