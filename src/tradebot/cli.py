"""Point d'entrée en ligne de commande : `tradebot ...`."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from tradebot import __version__
from tradebot.config import ConfigError, load_config, load_secrets


def _config_show(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    secrets = load_secrets()
    print(json.dumps(config.model_dump(mode="json"), indent=2, ensure_ascii=False))
    # On n'affiche que la présence des secrets, jamais leur valeur.
    for name, value in secrets:
        print(f"{name}: {'défini' if value is not None else 'non défini'}")
    return 0


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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result: int = args.func(args)
    except ConfigError as exc:
        print(f"Erreur de configuration : {exc}", file=sys.stderr)
        return 2
    return result


if __name__ == "__main__":
    sys.exit(main())
