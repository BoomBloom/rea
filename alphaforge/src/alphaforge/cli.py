"""Command-line interface. Run ``alphaforge --help``."""

from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from pathlib import Path

from . import __version__, services
from .data.bars import InstrumentSpec
from .data.loader import DataError, read_ohlcv
from .data.synthetic import make_bars
from .engine.metrics import FITNESS
from .engine.spec import BacktestConfig, CostModel, Strategy
from .export import TARGETS, export
from .search.generator import GeneratorConfig


def _data_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("data", help="OHLCV CSV/TXT file")
    p.add_argument("--symbol", default="DATA")
    p.add_argument("--point-value", type=float, default=1.0, help="currency per 1.0 price move per unit")
    p.add_argument("--tick-size", type=float, default=0.01)
    p.add_argument("--timezone", default=None, help="timezone of naive timestamps, e.g. America/New_York")
    p.add_argument("--commission", type=float, default=0.0, help="per unit per side")
    p.add_argument("--slippage", type=float, default=1.0, help="ticks per side (default 1)")
    p.add_argument("--capital", type=float, default=100_000.0)
    p.add_argument("--oos", type=float, default=0.3, help="out-of-sample fraction (last part of the data)")


def _load(a):
    bars, report = read_ohlcv(a.data, InstrumentSpec(a.symbol, a.point_value, a.tick_size), a.timezone)
    for w in report.warnings + report.fixes:
        print(f"note: {w}", file=sys.stderr)
    cfg = BacktestConfig(CostModel(a.commission, a.slippage), a.capital, a.oos)
    return bars, cfg


def _strategy(path: str) -> Strategy:
    d = json.loads(Path(path).read_text())
    if "strategy" in d:
        d = d["strategy"]
    return Strategy.from_dict(d)


def _print_metrics(m: dict, title: str) -> None:
    keys = ["trades", "net_profit", "profit_factor", "win_rate", "avg_trade", "max_drawdown", "sharpe", "return_dd"]
    print(f"{title:>14}: " + "  ".join(f"{k}={m[k]:.3g}" if isinstance(m[k], float) else f"{k}={m[k]}" for k in keys))


def _out(obj, path: str | None) -> None:
    text = json.dumps(obj, indent=2)
    if path:
        Path(path).write_text(text)
        print(f"wrote {path}")
    else:
        print(text)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="alphaforge", description="Strategy generation, backtesting, robustness testing and code export.")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="start the local web app")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--open", action="store_true", help="open the browser")

    s = sub.add_parser("validate", help="check a data file")
    s.add_argument("data")
    s.add_argument("--timezone", default=None)

    s = sub.add_parser("demo-data", help="write synthetic OHLCV data (no real edge) to a CSV")
    s.add_argument("out")
    s.add_argument("--bars", type=int, default=2500)
    s.add_argument("--seed", type=int, default=7)
    s.add_argument("--mean-reversion", type=float, default=0.0)

    s = sub.add_parser("generate", help="search for strategies with the genetic generator")
    _data_args(s)
    s.add_argument("--config", help="JSON file with generator settings")
    s.add_argument("--direction", choices=["long", "short", "both"])
    s.add_argument("--fitness", choices=sorted(FITNESS))
    s.add_argument("--population", type=int)
    s.add_argument("--generations", type=int)
    s.add_argument("--max-signals", type=int)
    s.add_argument("--min-trades-is", type=int)
    s.add_argument("--min-trades-oos", type=int)
    s.add_argument("--quantity", type=float)
    s.add_argument("--seed", type=int)
    s.add_argument("--top", type=int, default=10, help="results to print")
    s.add_argument("-o", "--out", help="write the full run as JSON")

    for name, help_ in (("backtest", "backtest one strategy"), ("robustness", "run the robustness suite"), ("walkforward", "walk-forward analysis")):
        s = sub.add_parser(name, help=help_)
        _data_args(s)
        s.add_argument("strategy", help="strategy JSON (or a result entry containing 'strategy')")
        s.add_argument("-o", "--out")
        if name != "backtest":
            s.add_argument("--fitness", choices=sorted(FITNESS), default="profit_factor")
        if name == "robustness":
            s.add_argument("--quick", action="store_true")
        if name == "walkforward":
            s.add_argument("--windows", type=int, default=5)
            s.add_argument("--anchored", action="store_true")

    s = sub.add_parser("export", help="generate platform code for a strategy")
    s.add_argument("strategy")
    s.add_argument("--target", choices=sorted(TARGETS), required=True)
    s.add_argument("--tick-size", type=float, default=0.01)
    s.add_argument("--point-value", type=float, default=1.0)
    s.add_argument("--commission", type=float, default=0.0)
    s.add_argument("--slippage", type=float, default=1.0)
    s.add_argument("-o", "--out")

    a = ap.parse_args(argv)
    try:
        return _dispatch(a)
    except (DataError, ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def _dispatch(a) -> int:
    if a.cmd == "serve":
        import uvicorn

        from .app.server import create_app

        url = f"http://{a.host}:{a.port}/"
        print(f"AlphaForge {__version__} at {url}  (Ctrl+C to stop)")
        if a.open:
            webbrowser.open(url)
        uvicorn.run(create_app(), host=a.host, port=a.port, log_level="warning")
        return 0
    if a.cmd == "validate":
        _, rep = read_ohlcv(a.data, timezone=a.timezone)
        print(json.dumps(rep.to_dict(), indent=2))
        return 0
    if a.cmd == "demo-data":
        b = make_bars(a.bars, seed=a.seed, mean_reversion=a.mean_reversion)
        b.to_frame().to_csv(a.out, index_label="datetime")
        print(f"wrote {len(b)} synthetic bars to {a.out}")
        return 0
    if a.cmd == "export":
        st = _strategy(a.strategy)
        code = export(st, a.target, BacktestConfig(CostModel(a.commission, a.slippage)), InstrumentSpec("EXPORT", a.point_value, a.tick_size))
        if a.out:
            Path(a.out).write_text(code)
            print(f"wrote {a.out}")
        else:
            print(code)
        return 0

    bars, cfg = _load(a)
    if a.cmd == "generate":
        g = json.loads(Path(a.config).read_text()) if a.config else {}
        for key in ("direction", "fitness", "population", "generations", "min_trades_is", "min_trades_oos", "quantity", "seed"):
            v = getattr(a, key)
            if v is not None:
                g[key] = v
        if a.max_signals is not None:
            g["max_entry_signals"] = a.max_signals
        gcfg = GeneratorConfig.from_dict(g)

        def progress(p):
            print(f"\rgeneration {p['generation']}/{p['generations']}  evaluated {p['evaluated']}  best {p['best_fitness']:.4g}", end="", file=sys.stderr)

        run = services.run_generation(bars, gcfg, cfg, progress)
        print(file=sys.stderr)
        print(f"evaluated {run['evaluated']} strategies in {run['elapsed_s']:.1f}s; {len(run['results'])} passed filters")
        print(run["warning"])
        for r in run["results"][: a.top]:
            print(f"\n#{r['rank']} {r['description']}")
            _print_metrics(r["metrics"]["in_sample"], "in-sample")
            _print_metrics(r["metrics"]["out_of_sample"], "out-of-sample")
            print(f"{'deflated SR':>14}: probability true Sharpe > 0 after {r['selection']['n_trials']} trials = {r['selection']['dsr']:.2f}")
        if a.out:
            _out(run, a.out)
        return 0
    st = _strategy(a.strategy)
    if a.cmd == "backtest":
        d = services.run_backtest(bars, st, cfg)
        print(d["description"])
        for seg, m in d["metrics"].items():
            _print_metrics(m, seg)
        if a.out:
            _out(d, a.out)
        return 0
    if a.cmd == "robustness":
        d = services.run_robustness(bars, st, cfg, a.fitness, a.quick)
        for t in d["tests"]:
            print(f"{t['test']:>20}: {t['verdict'].upper():5}  {t.get('rule', t.get('reason', ''))}")
        print(f"score: {d['score']}")
        if a.out:
            _out(d, a.out)
        return 0
    if a.cmd == "walkforward":
        d = services.run_walk_forward(bars, st, cfg, windows=a.windows, anchored=a.anchored, fitness=a.fitness)
        for w in d["windows"]:
            print(f"window {w['window']}: OOS {w['oos_start'][:10]}..{w['oos_end'][:10]} trades={w['oos_trades']} net={w['oos_net_profit']:.2f} params={w['params']}")
        print(f"stitched OOS net profit {d['stitched_oos']['net_profit']:.2f}, efficiency {d['walk_forward_efficiency']:.2f}, verdict {d['verdict']}")
        if a.out:
            _out(d, a.out)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
