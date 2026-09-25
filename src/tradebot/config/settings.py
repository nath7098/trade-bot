"""Chargement et validation de la configuration.

Deux sources, volontairement séparées :
- `AppConfig` : paramètres non sensibles, lus depuis un fichier YAML versionné.
- `Secrets` : clés API, lues uniquement depuis l'environnement (ou un fichier `.env`
  non versionné). Jamais écrites dans le code ni dans le YAML.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from tradebot.execution.costs import PRESETS, CostModel
from tradebot.risk.sizing import SizingConfig

DEFAULT_CONFIG_PATH = Path("config/default.yaml")


class ConfigError(Exception):
    """Configuration absente, illisible ou invalide."""


class Mode(StrEnum):
    BACKTEST = "backtest"
    PAPER = "paper"
    LIVE = "live"


class Timeframe(StrEnum):
    DAY = "1d"
    HOUR = "1h"


class AppConfig(BaseModel):
    """Paramètres de l'application (non sensibles)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: Mode = Mode.BACKTEST
    base_currency: str = "USD"
    initial_capital: float = Field(default=100.0, gt=0)
    symbols: tuple[str, ...] = Field(default=("SPY",), min_length=1)
    timeframe: Timeframe = Timeframe.DAY
    # Flux Alpaca : "sip" (toutes les bourses US) ou "iex" (une seule bourse, volumes partiels).
    data_feed: Literal["sip", "iex"] = "sip"
    # Début de l'historique téléchargé (Alpaca remonte à 2016 environ).
    history_start: date = date(2016, 1, 1)
    # Coûts de transaction : nom de profil (alpaca, ibkr_fixed, ibkr_tiered, zero)
    # ou paramètres détaillés (voir tradebot.execution.costs.CostModel).
    costs: CostModel = PRESETS["alpaca"]
    sizing: SizingConfig = SizingConfig()
    allow_short: bool = False
    data_dir: Path = Path("data")
    log_dir: Path = Path("logs")
    log_level: str = "INFO"

    @field_validator("mode")
    @classmethod
    def _live_is_locked(cls, value: Mode) -> Mode:
        # Garde-fou : aucun ordre réel tant que nous n'avons pas explicitement décidé
        # ensemble d'activer le trading réel (étape dédiée de la roadmap).
        if value is Mode.LIVE:
            raise ValueError(
                "le mode 'live' est désactivé : seuls 'backtest' et 'paper' sont permis"
            )
        return value

    @field_validator("costs", mode="before")
    @classmethod
    def _resolve_cost_preset(cls, value: Any) -> Any:
        if isinstance(value, str):
            if value not in PRESETS:
                raise ValueError(
                    f"profil de coûts inconnu : {value} (choix : {', '.join(PRESETS)})"
                )
            return PRESETS[value]
        return value

    @field_validator("symbols")
    @classmethod
    def _normalize_symbols(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        symbols = tuple(s.strip().upper() for s in value)
        if any(not s for s in symbols):
            raise ValueError("symbole vide")
        if len(set(symbols)) != len(symbols):
            raise ValueError("symboles en double")
        return symbols

    @field_validator("log_level")
    @classmethod
    def _check_log_level(cls, value: str) -> str:
        level = value.upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(f"niveau de log inconnu : {value}")
        return level


class Secrets(BaseSettings):
    """Identifiants lus depuis l'environnement (préfixe TRADEBOT_) ou `.env`."""

    model_config = SettingsConfigDict(
        env_prefix="TRADEBOT_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    alpaca_api_key: SecretStr | None = None
    alpaca_api_secret: SecretStr | None = None


def load_config(path: Path | str = DEFAULT_CONFIG_PATH) -> AppConfig:
    """Lit et valide le fichier YAML de configuration."""
    path = Path(path)
    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError as exc:
        raise ConfigError(f"fichier de configuration introuvable : {path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"YAML invalide dans {path} : {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} doit contenir un dictionnaire de paramètres")
    try:
        return AppConfig.model_validate(raw)
    except ValueError as exc:
        raise ConfigError(f"configuration invalide dans {path} :\n{exc}") from exc


def load_secrets() -> Secrets:
    return Secrets()
