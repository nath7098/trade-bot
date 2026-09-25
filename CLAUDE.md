# Conventions du projet tradebot

## Règles de sécurité (non négociables)
- Ne jamais activer le mode `live` ni écrire d'adapter broker réel sans décision explicite de l'utilisateur.
  Le verrou est dans `src/tradebot/config/settings.py` (`AppConfig._live_is_locked`).
- Aucune clé/identifiant dans le code, le YAML ou les tests : uniquement variables d'env `TRADEBOT_*` / `.env`.
- Les tests n'accèdent jamais au réseau (données factices, brokers simulés).

## Architecture
- Séparation stricte : `config`, `domain`, `data`, `strategy`, `risk`, `execution`, `backtest`, `live`.
- Les stratégies ne connaissent pas le broker ; elles émettent des signaux, le risk manager produit les ordres.
- Même code de stratégie et de risque en backtest, paper et live.
- Pas de look-ahead : un signal calculé sur la barre J s'exécute au plus tôt à la barre J+1.
- Temps en UTC en interne.

## Recherche de stratégies
- Ne jamais présenter un résultat de backtest optimisé comme une performance attendue.
- Toute optimisation se fait sur la période d'apprentissage ; la période de test ne sert qu'une fois.
- Toujours comparer à `buy_and_hold` avec les mêmes frais ; signaler le nombre de combinaisons testées.

## Style
- Python ≥ 3.11, typé (mypy strict), ruff. Code simple, pas d'abstraction prématurée.
- Messages utilisateur et docstrings en français ; identifiants en anglais.

## Commandes
- `uv run pytest` — tests
- `uv run ruff check . && uv run ruff format --check .` — lint/format
- `uv run mypy src` — typage
