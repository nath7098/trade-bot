# tradebot

Infrastructure de trading automatisé en Python, construite étape par étape :
données de marché → stratégies → backtest (frais, slippage, hors-échantillon) → gestion du risque
→ paper trading → (plus tard, sur décision explicite) trading réel.

**Aucun ordre réel n'est possible** : le mode `live` est verrouillé dans le code.

## Installation

Prérequis : [uv](https://docs.astral.sh/uv/).

```bash
uv sync
cp .env.example .env   # puis y mettre les clés PAPER (jamais commité)
```

## Utilisation

```bash
uv run tradebot --version
uv run tradebot config show
```

## Développement

```bash
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run mypy src
```

## Structure

```
config/default.yaml     paramètres non sensibles
src/tradebot/config/    chargement/validation de la config et des secrets
src/tradebot/domain/    types purs : Bar, Signal, Order, Fill, Position, Portfolio
src/tradebot/logging_setup.py  logs console + JSON (logs/tradebot.jsonl)
src/tradebot/cli.py     commandes `tradebot`
tests/                  tests automatisés
```

## Roadmap

0. Squelette (config, logs, CLI, CI) ✅
1. Types du domaine (barres, ordres, positions, portefeuille) ✅
2. Données historiques (Alpaca) + cache Parquet + contrôles qualité
3. Backtester event-driven (frais, slippage, exécution à la barre suivante)
4. Métriques et rapports
5. Stratégie de référence
6. Gestion du risque
7. Validation robuste (walk-forward, sensibilité)
8. Paper trading Alpaca
9. Monitoring et alertes
10. Adapter Interactive Brokers (paper)
11. Live — uniquement après décision explicite
