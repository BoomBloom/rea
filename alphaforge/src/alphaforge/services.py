"""Application workflows shared by the CLI and the web API.

Adapters (cli.py, app/server.py) parse their inputs, call these functions and
format the outputs; the workflows themselves live here once.
"""

from __future__ import annotations

import math
import time

import numpy as np

from .data.bars import Bars
from .engine.backtest import BacktestResult, Context, backtest
from .engine.metrics import bars_per_year
from .engine.spec import BacktestConfig, Strategy
from .optimize.walkforward import walk_forward
from .robustness.tests import run_suite
from .search.generator import GenerationReport, Generator, GeneratorConfig
from .search.stats import deflated_sharpe


def _clean(o):
    """Make floats JSON-safe (no NaN/inf)."""
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return f if math.isfinite(f) else None
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def bar_returns(res: BacktestResult, capital: float) -> np.ndarray:
    acct = capital + np.r_[0.0, res.run.equity]
    return np.diff(acct) / acct[:-1]


def selection_adjustment(res: BacktestResult, report: GenerationReport, capital: float) -> dict:
    """Deflated Sharpe on the in-sample segment, using all strategies tried."""
    split = res.split
    rets = bar_returns(res, capital)[:split]
    bpy = bars_per_year(res.bars.time[:split])
    trial = np.asarray(report.is_sharpes, dtype=np.float64) / math.sqrt(bpy) if report.is_sharpes else None
    return deflated_sharpe(rets, report.evaluated, trial)


def run_generation(bars: Bars, gen_cfg: GeneratorConfig, bt_cfg: BacktestConfig, progress=None, cancelled=None) -> dict:
    gen = Generator(bars, gen_cfg, bt_cfg)
    rep = gen.run(progress=progress, cancelled=cancelled)
    results = []
    for i, r in enumerate(rep.results):
        d = r.to_dict(include_curve=True, max_points=300)
        d["rank"] = i + 1
        d["selection"] = selection_adjustment(r, rep, bt_cfg.initial_capital)
        results.append(d)
    return _clean({
        "kind": "generation",
        "created": time.time(),
        "evaluated": rep.evaluated,
        "rejected_min_trades": rep.rejected_min_trades,
        "elapsed_s": rep.elapsed_s,
        "generations_run": rep.generations_run,
        "best_history": rep.best_history,
        "generator": gen_cfg.to_dict(),
        "backtest": bt_cfg.to_dict(),
        "results": results,
        "warning": (
            f"{rep.evaluated} strategies were evaluated. The best in-sample results are inflated by "
            "selection; judge them by out-of-sample, robustness tests and the deflated Sharpe ratio."
        ),
    })


def run_backtest(bars: Bars, strategy: Strategy, bt_cfg: BacktestConfig, max_trades: int = 5000) -> dict:
    res = backtest(bars, strategy, bt_cfg)
    d = res.to_dict(include_curve=True, max_points=2000)
    tf = res.trades_frame().tail(max_trades)
    tf["entry_time"] = tf["entry_time"].astype(str)
    tf["exit_time"] = tf["exit_time"].astype(str)
    d["trades"] = tf.to_dict(orient="records")
    d["split_index"] = res.split
    d["bars"] = len(bars)
    return _clean(d)


def run_robustness(bars: Bars, strategy: Strategy, bt_cfg: BacktestConfig, fitness: str = "profit_factor", quick: bool = False, seed: int = 0) -> dict:
    ctx = Context(bars, bt_cfg)
    return _clean(run_suite(ctx, strategy, fitness=fitness, quick=quick, seed=seed))


def run_walk_forward(bars: Bars, strategy: Strategy, bt_cfg: BacktestConfig, **kw) -> dict:
    return _clean(walk_forward(bars, strategy, bt_cfg, **kw))
