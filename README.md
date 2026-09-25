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
uv run tradebot data fetch          # télécharge/met à jour les symboles de la config (Alpaca)
uv run tradebot data fetch QQQ IWM  # ou des symboles précis
uv run tradebot data check          # contrôle qualité des données locales
uv run tradebot backtest            # rejoue une stratégie (défaut : buy_and_hold)
uv run tradebot backtest --strategy buy_and_hold --start 2018-01-01 SPY QQQ
uv run tradebot backtest --no-report  # tableau seulement, sans fichiers
```

Les données sont stockées dans `data/1d/<SYMBOLE>.parquet` (prix ajustés des splits et
dividendes). Seules les barres terminées sont téléchargées ; si un nouvel ajustement
modifie l'historique, il est rechargé entièrement.

Backtest : un signal calculé à la clôture d'un jour est exécuté à l'ouverture du jour
suivant, avec frais et slippage (`costs` dans la config : `alpaca`, `ibkr_fixed`,
`ibkr_tiered`, `zero` ou paramètres détaillés).

Chaque backtest affiche un tableau comparant la stratégie à l'achat-conservation
(mêmes symboles, mêmes frais) : rendement, CAGR, volatilité, Sharpe, Sortino, drawdown
max et durée, Calmar, exposition, rotation, commissions, slippage. Un rapport est écrit
dans `reports/<date>_<stratégie>/` : `equity.png`, `metrics.json`, `equity.csv`,
`trades_*.csv`, `rejected_*.csv`.

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
src/tradebot/data/      source Alpaca, stockage Parquet, calendrier NYSE, contrôles qualité
src/tradebot/strategy/  interface Strategy + stratégies (buy_and_hold)
src/tradebot/risk/      conversion exposition cible -> ordres (limites à venir)
src/tradebot/execution/ modèle de coûts, broker simulé
src/tradebot/backtest/  moteur de backtest barre par barre, métriques, rapports
src/tradebot/logging_setup.py  logs console + JSON (logs/tradebot.jsonl)
src/tradebot/cli.py     commandes `tradebot`
tests/                  tests automatisés
```

## Roadmap

0. Squelette (config, logs, CLI, CI) ✅
1. Types du domaine (barres, ordres, positions, portefeuille) ✅
2. Données historiques (Alpaca) + cache Parquet + contrôles qualité ✅
3. Backtester event-driven (frais, slippage, exécution à la barre suivante) ✅
4. Métriques et rapports ✅
5. Stratégie de référence
6. Gestion du risque
7. Validation robuste (walk-forward, sensibilité)
8. Paper trading Alpaca
9. Monitoring et alertes
10. Adapter Interactive Brokers (paper)
11. Live — uniquement après décision explicite
