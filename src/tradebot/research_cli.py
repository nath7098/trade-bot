"""Commandes de recherche : `tradebot strategies`, `backtest`, `optimize`."""

from __future__ import annotations

import argparse
import math
import sys
from datetime import UTC, date, datetime, time
from typing import Any

import pandas as pd

from tradebot.backtest import compute_metrics, warnings_for
from tradebot.backtest.optimize import BacktestSetup, OptimizationResult, optimize
from tradebot.backtest.report import format_table, save_report
from tradebot.config import AppConfig, load_config
from tradebot.data import ParquetBarStore
from tradebot.logging_setup import setup_logging
from tradebot.strategy import STRATEGIES, BuyAndHold


class UsageError(Exception):
    """Erreur d'utilisation de la ligne de commande (message affiché tel quel)."""


def parse_params(items: list[str] | None) -> dict[str, str]:
    """["lookback=150", "top_n=2"] -> {"lookback": "150", "top_n": "2"}."""
    params = {}
    for item in items or []:
        key, sep, value = item.partition("=")
        if not sep or not key:
            raise UsageError(f"paramètre invalide : {item!r} (format attendu : nom=valeur)")
        params[key.strip()] = value.strip()
    return params


def _utc(day: str | date | None) -> datetime | None:
    if day is None:
        return None
    value = date.fromisoformat(day) if isinstance(day, str) else day
    return datetime.combine(value, time(), tzinfo=UTC)


def _load(
    args: argparse.Namespace, config: AppConfig
) -> tuple[tuple[str, ...], dict[str, pd.DataFrame]]:
    symbols = tuple(s.upper() for s in args.symbols) if args.symbols else config.symbols
    store = ParquetBarStore(config.data_dir)
    start, end = _utc(getattr(args, "start", None)), _utc(getattr(args, "end", None))
    data = {s: store.load(s, config.timeframe, start, end) for s in symbols}
    empty = [s for s, df in data.items() if df.empty]
    if empty:
        raise UsageError(f"pas de données pour {', '.join(empty)} : lancer `tradebot data fetch`")
    return symbols, data


def _setup(config: AppConfig) -> BacktestSetup:
    return BacktestSetup(config.initial_capital, config.costs, config.sizing, config.allow_short)


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d-%H%M%S")


def strategies_cmd(args: argparse.Namespace) -> int:
    for name, cls in STRATEGIES.items():
        doc = (sys.modules[cls.__module__].__doc__ or "").strip()
        print(f"{name}: {doc.splitlines()[0] if doc else ''}")
        for field, info in cls.Params.model_fields.items():
            grid = cls.grid.get(field)
            extra = f", grille {grid}" if grid else ""
            print(f"    {field} = {info.default!r}  ({info.description or ''}{extra})")
    return 0


def backtest_cmd(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    setup_logging(config.log_dir, config.log_level)
    if args.strategy not in STRATEGIES:
        raise UsageError(f"stratégie inconnue : {args.strategy} (choix : {', '.join(STRATEGIES)})")
    symbols, data = _load(args, config)
    params: dict[str, Any] = {
        **config.strategy_params.get(args.strategy, {}),
        **parse_params(args.param),
    }
    setup = _setup(config)

    # La stratégie est toujours comparée à l'achat-conservation des mêmes symboles,
    # avec les mêmes frais.
    results = {args.strategy: setup.run(args.strategy, symbols, params, data)}
    if args.strategy != BuyAndHold.name:
        results[BuyAndHold.name] = setup.run(BuyAndHold.name, symbols, {}, data)
    metrics = {name: compute_metrics(r) for name, r in results.items()}
    notes = warnings_for(metrics[args.strategy])

    m = metrics[args.strategy]
    shown = ", ".join(f"{k}={v}" for k, v in params.items()) or "défauts"
    print(f"Stratégie : {args.strategy} ({shown}) sur {', '.join(symbols)}")
    print(
        f"Période   : {m.start} -> {m.end} ({m.years:.1f} ans), capital initial "
        f"{config.initial_capital:,.2f}\n"
    )
    print(format_table(metrics))
    for note in notes:
        print(f"! {note}")

    if not args.no_report:
        out_dir = config.report_dir / f"{_stamp()}_{args.strategy}"
        save_report(out_dir, results, metrics, notes)
        print(f"\nRapport : {out_dir}/ (equity.png, metrics.json, equity.csv, trades_*.csv)")
    return 0


def _fmt(value: float) -> str:
    return "n/d" if not math.isfinite(value) else f"{value:.2f}"


def _print_optimization(res: OptimizationResult, top: int = 5) -> None:
    print("\nMeilleures combinaisons (apprentissage, triées par robustesse) :")
    shown = res.table.head(top).copy()
    for col in ("score", "robust_score", "sharpe"):
        shown[col] = shown[col].map(_fmt)
    for col in ("cagr", "max_drawdown"):
        shown[col] = shown[col].map(lambda v: "n/d" if not math.isfinite(v) else f"{v:+.1%}")
    print(shown.rename(columns={"score": res.objective, "robust_score": "robuste"}).to_string())

    chosen = ", ".join(f"{k}={v}" for k, v in res.chosen.items()) or "aucun paramètre"
    print(f"\nRéglage retenu : {chosen}")
    print(
        f"\nPériode de TEST (jamais vue par l'optimiseur) : {res.test_metrics.start} -> "
        f"{res.test_metrics.end}\n"
    )
    print(
        format_table(
            {
                f"{res.strategy} (test)": res.test_metrics,
                "buy_and_hold (test)": res.benchmark_metrics,
            }
        )
    )
    train_score = float(getattr(res.train, res.objective))
    test_score = float(getattr(res.test_metrics, res.objective))
    print(
        f"\n{res.objective} : apprentissage {_fmt(train_score)} -> test {_fmt(test_score)} "
        f"(buy_and_hold sur le test : {_fmt(float(getattr(res.benchmark_metrics, res.objective)))})"
    )


def optimize_cmd(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    setup_logging(config.log_dir, config.log_level)
    candidates = [n for n in STRATEGIES if n != BuyAndHold.name]
    names = candidates if args.strategy == "all" else [args.strategy]
    if any(n not in candidates for n in names):
        raise UsageError(f"stratégie à optimiser : {', '.join(candidates)} ou all")
    split = _utc(args.split or config.optimization.split_date)
    assert split is not None
    objective = args.objective or config.optimization.objective
    symbols, data = _load(args, config)
    setup = _setup(config)
    stamp = _stamp()

    summary = []
    for name in names:
        combos = math.prod(len(v) for v in STRATEGIES[name].grid.values())
        print(f"\n=== {name} : {combos} combinaisons, apprentissage avant {split.date()} ===")
        res = optimize(name, symbols, data, split, setup, objective)
        _print_optimization(res)

        notes = warnings_for(res.test_metrics)
        for note in notes:
            print(f"! {note}")
        if not args.no_report:
            out_dir = config.report_dir / f"{stamp}_optimize_{name}"
            save_report(
                out_dir,
                {f"{name}_test": res.test, "buy_and_hold_test": res.benchmark},
                {f"{name}_test": res.test_metrics, "buy_and_hold_test": res.benchmark_metrics},
                notes,
            )
            res.table.to_csv(out_dir / "grid.csv", index=False)
            print(f"Rapport : {out_dir}/")
        summary.append(
            {
                "stratégie": name,
                "réglage": ", ".join(f"{k}={v}" for k, v in res.chosen.items()),
                f"{objective} appr.": float(getattr(res.train, objective)),
                f"{objective} test": float(getattr(res.test_metrics, objective)),
                "CAGR test": res.test_metrics.cagr,
                "DD max test": res.test_metrics.max_drawdown,
                "combinaisons": res.combinations,
            }
        )
        benchmark = res.benchmark_metrics

    if len(summary) > 1:
        summary.append(
            {
                "stratégie": "buy_and_hold",
                "réglage": "-",
                f"{objective} appr.": math.nan,
                f"{objective} test": float(getattr(benchmark, objective)),
                "CAGR test": benchmark.cagr,
                "DD max test": benchmark.max_drawdown,
                "combinaisons": 0,
            }
        )
        table = pd.DataFrame(summary).sort_values(f"{objective} test", ascending=False)
        for col in (f"{objective} appr.", f"{objective} test"):
            table[col] = table[col].map(_fmt)
        for col in ("CAGR test", "DD max test"):
            table[col] = table[col].map(lambda v: "n/d" if not math.isfinite(v) else f"{v:+.1%}")
        print("\n=== Classement sur la période de test ===")
        print(table.to_string(index=False))

    print(
        "\nRappel : la période de test n'est fiable que si on ne l'utilise qu'une fois. "
        "Relancer l'optimisation\njusqu'à ce que le test « soit bon » revient à optimiser "
        "sur le test : le résultat ne vaut plus rien."
    )
    return 0


def register(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    strategies = sub.add_parser("strategies", help="lister les stratégies et leurs paramètres")
    strategies.set_defaults(func=strategies_cmd)

    backtest = sub.add_parser("backtest", help="rejouer une stratégie sur les données locales")
    backtest.set_defaults(func=backtest_cmd)
    backtest.add_argument("--strategy", default=BuyAndHold.name)
    backtest.add_argument(
        "--param", action="append", metavar="NOM=VALEUR", help="paramètre (répétable)"
    )
    backtest.add_argument("--start", help="date de début AAAA-MM-JJ")
    backtest.add_argument("--end", help="date de fin AAAA-MM-JJ")

    opt = sub.add_parser("optimize", help="optimiser sur l'apprentissage, valider sur le test")
    opt.set_defaults(func=optimize_cmd)
    opt.add_argument("--strategy", default="all", help="nom de la stratégie, ou all")
    opt.add_argument("--split", help="date de coupure apprentissage/test (AAAA-MM-JJ)")
    opt.add_argument("--objective", choices=["calmar", "sharpe", "sortino", "cagr"])
    opt.add_argument("--start", help="début de l'historique utilisé")
    opt.add_argument("--end", help="fin de l'historique utilisé")

    for parser in (backtest, opt):
        parser.add_argument("--no-report", action="store_true", help="ne pas écrire de rapport")
        parser.add_argument("symbols", nargs="*", help="symboles (défaut : ceux de la config)")
