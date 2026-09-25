"""Point d'entrée en ligne de commande : `tradebot ...`."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, time
from pathlib import Path

from pydantic import ValidationError

from tradebot import __version__, research_cli
from tradebot.config import AppConfig, ConfigError, load_config, load_secrets
from tradebot.data import DataSourceError, ParquetBarStore, check_bars, sync_symbol
from tradebot.data.calendar import last_completed_bar
from tradebot.logging_setup import setup_logging


def _config_show(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    secrets = load_secrets()
    print(json.dumps(config.model_dump(mode="json"), indent=2, ensure_ascii=False))
    # On n'affiche que la présence des secrets, jamais leur valeur.
    for name, value in secrets:
        print(f"{name}: {'défini' if value is not None else 'non défini'}")
    return 0


def _symbols(args: argparse.Namespace, config: AppConfig) -> list[str]:
    return [s.upper() for s in args.symbols] if args.symbols else list(config.symbols)


def _data_fetch(args: argparse.Namespace) -> int:
    from tradebot.data.alpaca import AlpacaDataSource

    config = load_config(args.config)
    setup_logging(config.log_dir, config.log_level)
    secrets = load_secrets()
    source = AlpacaDataSource(
        secrets.alpaca_api_key.get_secret_value() if secrets.alpaca_api_key else "",
        secrets.alpaca_api_secret.get_secret_value() if secrets.alpaca_api_secret else "",
        feed=config.data_feed,
    )
    store = ParquetBarStore(config.data_dir)
    start = datetime.combine(config.history_start, time(), tzinfo=UTC)
    # On ne télécharge que des barres terminées (jamais la séance en cours).
    end = last_completed_bar(config.timeframe, datetime.now(UTC))
    status = 0
    for symbol in _symbols(args, config):
        result = sync_symbol(source, store, symbol, config.timeframe, start, end)
        mode = "complet" if result.full_refresh else "incrémental"
        print(
            f"{symbol}: {result.rows_before} -> {result.rows_after} barres ({mode}), "
            f"{len(result.report.issues)} alerte(s)"
        )
        if not result.report.ok:
            status = 1
    return status


def _data_check(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    store = ParquetBarStore(config.data_dir)
    status = 0
    for symbol in _symbols(args, config):
        df = store.load(symbol, config.timeframe)
        report = check_bars(df, symbol, config.timeframe)
        span = f"{df.index[0].date()} -> {df.index[-1].date()}" if len(df) else "vide"
        print(f"{symbol}: {report.rows} barres ({span}) - {'OK' if report.ok else 'ERREURS'}")
        for issue in report.issues:
            print(f"  [{issue.severity}] {issue.code}: {issue.message}")
        if not report.ok:
            status = 1
    return status


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tradebot")
    parser.add_argument("--version", action="version", version=f"tradebot {__version__}")
    parser.add_argument(
        "--config", type=Path, default=Path("config/default.yaml"), help="fichier YAML"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    config_parser = sub.add_parser("config", help="inspecter la configuration")
    config_sub = config_parser.add_subparsers(dest="config_command", required=True)
    show = config_sub.add_parser("show", help="afficher la configuration effective")
    show.set_defaults(func=_config_show)

    data_parser = sub.add_parser("data", help="données de marché historiques")
    data_sub = data_parser.add_subparsers(dest="data_command", required=True)
    fetch = data_sub.add_parser("fetch", help="télécharger / mettre à jour depuis Alpaca")
    fetch.set_defaults(func=_data_fetch)
    check = data_sub.add_parser("check", help="contrôler la qualité des données locales")
    check.set_defaults(func=_data_check)

    for p in (fetch, check):
        p.add_argument("symbols", nargs="*", help="symboles (défaut : ceux de la config)")

    research_cli.register(sub)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result: int = args.func(args)
    except ConfigError as exc:
        print(f"Erreur de configuration : {exc}", file=sys.stderr)
        return 2
    except DataSourceError as exc:
        print(f"Erreur de données : {exc}", file=sys.stderr)
        return 3
    except research_cli.UsageError as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 2
    except ValidationError as exc:
        print(f"Paramètres invalides : {exc}", file=sys.stderr)
        return 2
    return result


if __name__ == "__main__":
    sys.exit(main())
