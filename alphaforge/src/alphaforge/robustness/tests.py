"""Robustness tests for a single strategy.

Each test returns a JSON-serialisable dict with the inputs it used, summary
statistics, a ``verdict`` ("pass" / "warn" / "fail") and the rule behind the
verdict. Thresholds are our own documented defaults (docs/robustness.md), not
claims about any other product. A pass is evidence against overfitting, never
proof of future profitability.

All tests are seeded and therefore reproducible.
"""

from __future__ import annotations

import itertools
import math

import numpy as np

from ..data.bars import Bars
from ..engine.backtest import Context, backtest
from ..engine.metrics import FITNESS, fitness_value
from ..engine.spec import ExitSpec, Strategy
from ..rules import indicators as ind
from ..rules.library import TEMPLATES, Signal


def _pct(a, q):
    return float(np.percentile(a, q)) if len(a) else 0.0


def _summary(values: np.ndarray) -> dict:
    v = np.asarray(values, dtype=np.float64)
    if not len(v):
        return {}
    return {
        "mean": float(v.mean()),
        "p5": _pct(v, 5),
        "p25": _pct(v, 25),
        "median": _pct(v, 50),
        "p75": _pct(v, 75),
        "p95": _pct(v, 95),
    }


def _max_dd(pnl_path: np.ndarray) -> float:
    eq = np.cumsum(pnl_path)
    peak = np.maximum.accumulate(np.r_[0.0, eq])[1:]
    return float((peak - eq).max()) if len(eq) else 0.0


# --------------------------------------------------------------- trade-level Monte Carlo
def monte_carlo_trades(pnl: np.ndarray, runs: int = 1000, seed: int = 0, method: str = "resample") -> dict:
    """Reshuffle (permute order) or resample (bootstrap with replacement) trade P&L.

    Reshuffling keeps total profit and only changes the drawdown path;
    resampling also varies the total. Reports drawdown and profit distributions.
    """
    pnl = np.asarray(pnl, dtype=np.float64)
    rng = np.random.default_rng(seed)
    n = len(pnl)
    if n < 5:
        return {"test": "monte_carlo", "method": method, "verdict": "fail", "reason": "fewer than 5 trades"}
    dds = np.empty(runs)
    nets = np.empty(runs)
    for i in range(runs):
        path = rng.permutation(pnl) if method == "reshuffle" else rng.choice(pnl, n, replace=True)
        dds[i] = _max_dd(path)
        nets[i] = path.sum()
    hist_dd = _max_dd(pnl)
    prob_loss = float((nets <= 0).mean())
    verdict = "pass" if prob_loss < 0.05 else ("warn" if prob_loss < 0.2 else "fail")
    return {
        "test": "monte_carlo",
        "method": method,
        "runs": runs,
        "historical_max_drawdown": hist_dd,
        "max_drawdown": _summary(dds),
        "net_profit": _summary(nets),
        "prob_net_loss": prob_loss,
        "verdict": verdict,
        "rule": "pass if < 5% of resampled paths lose money, warn if < 20%",
    }


# --------------------------------------------------------------- price noise
def add_noise(bars: Bars, rng: np.random.Generator, atr_fraction: float = 0.2, prob: float = 0.5, atr_len: int = 14) -> Bars:
    """Perturb each of O/H/L/C with probability ``prob`` by U(-f, f) * ATR, then
    restore OHLC consistency (high = max, low = min of the four prices)."""
    a = ind.atr(bars.high, bars.low, bars.close, atr_len)
    a = np.where(np.isnan(a), np.nanmean(a), a)
    n = len(bars)
    out = []
    for arr in (bars.open, bars.high, bars.low, bars.close):
        mask = rng.random(n) < prob
        delta = rng.uniform(-atr_fraction, atr_fraction, n) * a
        out.append(arr + np.where(mask, delta, 0.0))
    o, h, lo, c = out
    h2 = np.maximum.reduce([o, h, lo, c])
    l2 = np.minimum.reduce([o, h, lo, c])
    return bars.with_prices(o, h2, l2, c)


def noise_test(ctx: Context, s: Strategy, runs: int = 200, atr_fraction: float = 0.2, prob: float = 0.5, fitness: str = "profit_factor", seed: int = 0) -> dict:
    """Re-trade the strategy on noise-perturbed copies of the data. Signals are
    recomputed on each noisy series, so the test checks dependence on exact prices."""
    rng = np.random.default_rng(seed)
    base = backtest(ctx.bars, s, ctx=ctx).metrics_all
    vals, nets = [], []
    for _ in range(runs):
        nb = add_noise(ctx.bars, rng, atr_fraction, prob, s.exits.atr_len)
        m = backtest(nb, s, ctx.config).metrics_all
        vals.append(m.get(fitness, 0.0))
        nets.append(m["net_profit"])
    vals, nets = np.array(vals), np.array(nets)
    frac_profitable = float((nets > 0).mean())
    base_v = base.get(fitness, 0.0)
    # how much of the original metric survives at the median
    retention = float(np.median(vals) / base_v) if base_v not in (0.0,) and FITNESS[fitness][1] else float("nan")
    verdict = "pass" if frac_profitable >= 0.8 else ("warn" if frac_profitable >= 0.6 else "fail")
    return {
        "test": "noise",
        "runs": runs,
        "atr_fraction": atr_fraction,
        "probability": prob,
        "fitness": fitness,
        "original": base_v,
        "distribution": _summary(vals),
        "median_retention": retention,
        "fraction_profitable": frac_profitable,
        "verdict": verdict,
        "rule": "pass if >= 80% of noisy series are profitable, warn if >= 60%",
    }


# --------------------------------------------------------------- vs random entries
def vs_random(ctx: Context, s: Strategy, runs: int = 300, fitness: str = "profit_factor", seed: int = 0) -> dict:
    """Compare with random entries that fire as often as the real entry signal,
    using the same direction and exits. Reports the strategy's percentile and a
    one-sided p-value (fraction of random runs at least as good)."""
    rng = np.random.default_rng(seed)
    real_entry = ctx.entry_array(s)
    rate = float(real_entry.mean())
    real = fitness_value(backtest(ctx.bars, s, ctx=ctx).metrics_all, fitness)
    vals = np.empty(runs)
    n = len(ctx.bars)
    for i in range(runs):
        ent = rng.random(n) < rate
        run = ctx.run(s, entry=ent)
        vals[i] = fitness_value(ctx.segment_metrics(run, 0, n), fitness)
    p = float(((vals >= real).sum() + 1) / (runs + 1))
    best_random = float(vals.max())
    verdict = "pass" if p <= 0.05 else ("warn" if p <= 0.2 else "fail")
    sign = 1 if FITNESS[fitness][1] else -1
    return {
        "test": "vs_random",
        "runs": runs,
        "fitness": fitness,
        "entry_rate": rate,
        "strategy": sign * real,
        "random": {k: sign * v for k, v in _summary(vals).items()},
        "best_random": sign * best_random,
        "beats_best_random": bool(real > best_random),
        "p_value": p,
        "verdict": verdict,
        "rule": "pass if p <= 0.05, warn if p <= 0.20",
    }


# --------------------------------------------------------------- Monte Carlo permutation
def permute_bars(bars: Bars, rng: np.random.Generator) -> Bars:
    """Permute bar-to-bar log changes, keeping each bar's internal shape.

    Each bar is described relative to the previous close (gap = log(open/prev
    close)) and to its own open (log high/open, log low/open, log close/open).
    Shuffling those tuples destroys serial structure but keeps the return
    distribution, volatility and intrabar shapes."""
    o, h, lo, c = (np.log(x) for x in (bars.open, bars.high, bars.low, bars.close))
    gap = o[1:] - c[:-1]
    rh, rl, rc = h[1:] - o[1:], lo[1:] - o[1:], c[1:] - o[1:]
    perm = rng.permutation(len(gap))
    gap, rh, rl, rc = gap[perm], rh[perm], rl[perm], rc[perm]
    no, nh, nl, nc = (np.empty_like(o) for _ in range(4))
    no[0], nh[0], nl[0], nc[0] = o[0], h[0], lo[0], c[0]
    nc[1:] = c[0] + np.cumsum(gap + rc)
    no[1:] = np.r_[c[0], nc[1:-1]] + gap
    nh[1:] = no[1:] + rh
    nl[1:] = no[1:] + rl
    return bars.with_prices(np.exp(no), np.exp(nh), np.exp(nl), np.exp(nc))


def permutation_test(ctx: Context, s: Strategy, runs: int = 200, fitness: str = "profit_factor", seed: int = 0) -> dict:
    """Monte Carlo permutation test of the *fixed* rules.

    p = (k + 1) / (runs + 1), k = permutations scoring at least the real data.
    Limitation: this tests the final rules, not the search that found them. A
    selection-aware test would re-run the whole generation on each permutation
    (Masters, 2018); use the deflated Sharpe ratio for search-level correction.
    """
    rng = np.random.default_rng(seed)
    real = fitness_value(backtest(ctx.bars, s, ctx=ctx).metrics_all, fitness)
    vals = np.empty(runs)
    for i in range(runs):
        pb = permute_bars(ctx.bars, rng)
        vals[i] = fitness_value(backtest(pb, s, ctx.config).metrics_all, fitness)
    p = float(((vals >= real).sum() + 1) / (runs + 1))
    sign = 1 if FITNESS[fitness][1] else -1
    return {
        "test": "permutation",
        "runs": runs,
        "fitness": fitness,
        "strategy": sign * real,
        "permuted": {k: sign * v for k, v in _summary(vals).items()},
        "p_value": p,
        "verdict": "pass" if p <= 0.05 else ("warn" if p <= 0.2 else "fail"),
        "rule": "pass if p <= 0.05, warn if p <= 0.20 (fixed rules; see limitation)",
    }


# --------------------------------------------------------------- delayed entries
def delay_test(ctx: Context, s: Strategy, delays: tuple[int, ...] = (1, 2), fitness: str = "profit_factor") -> dict:
    base_entry = ctx.entry_array(s)
    n = len(ctx.bars)
    real_m = ctx.segment_metrics(ctx.run(s), 0, n)
    rows = [{"delay": 0, "net_profit": real_m["net_profit"], fitness: real_m.get(fitness, 0.0), "trades": real_m["trades"]}]
    for d in delays:
        ent = np.zeros(n, np.bool_)
        ent[d:] = base_entry[:-d]
        m = ctx.segment_metrics(ctx.run(s, entry=ent), 0, n)
        rows.append({"delay": d, "net_profit": m["net_profit"], fitness: m.get(fitness, 0.0), "trades": m["trades"]})
    ok = all(r["net_profit"] > 0 for r in rows[1:])
    some = any(r["net_profit"] > 0 for r in rows[1:])
    return {
        "test": "delay",
        "fitness": fitness,
        "rows": rows,
        "verdict": "pass" if ok else ("warn" if some else "fail"),
        "rule": "pass if every delayed variant is still profitable",
    }


# --------------------------------------------------------------- variance (win-rate degradation)
def variance_test(pnl: np.ndarray, win_rate_drop: float = 0.05, horizon: int | None = None, runs: int = 1000, seed: int = 0) -> dict:
    """Simulate the next ``horizon`` trades assuming the win rate is
    ``win_rate_drop`` lower than in the backtest. Wins and losses are drawn
    from the historical win and loss distributions."""
    pnl = np.asarray(pnl, dtype=np.float64)
    wins, losses = pnl[pnl > 0], pnl[pnl <= 0]
    if len(wins) < 3 or len(losses) < 3:
        return {"test": "variance", "verdict": "fail", "reason": "need at least 3 wins and 3 losses"}
    rng = np.random.default_rng(seed)
    wr = max(0.0, len(wins) / len(pnl) - win_rate_drop)
    horizon = horizon or len(pnl)
    nets, dds = np.empty(runs), np.empty(runs)
    for i in range(runs):
        is_win = rng.random(horizon) < wr
        path = np.where(is_win, rng.choice(wins, horizon), rng.choice(losses, horizon))
        nets[i] = path.sum()
        dds[i] = _max_dd(path)
    prob_loss = float((nets <= 0).mean())
    return {
        "test": "variance",
        "win_rate_used": wr,
        "horizon": horizon,
        "runs": runs,
        "net_profit": _summary(nets),
        "max_drawdown": _summary(dds),
        "prob_net_loss": prob_loss,
        "verdict": "pass" if prob_loss < 0.1 else ("warn" if prob_loss < 0.3 else "fail"),
        "rule": "pass if < 10% of degraded paths lose money, warn if < 30%",
    }


# --------------------------------------------------------------- parameter stability
def _numeric_neighbours(v, grid: list, span: float = 0.2) -> list:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return [v]
    if isinstance(v, int):
        lo, hi = math.floor(v * (1 - span)), math.ceil(v * (1 + span))
        vals = sorted({max(1, x) for x in (lo, v - 1, v, v + 1, hi)})
        return vals
    return sorted({round(v * f, 4) for f in (1 - span, 1 - span / 2, 1.0, 1 + span / 2, 1 + span)})


def parameter_stability(ctx: Context, s: Strategy, fitness: str = "profit_factor", span: float = 0.2, max_variants: int = 400, seed: int = 0) -> dict:
    """Evaluate the strategy with every numeric parameter moved to nearby values
    (about ±span). A robust strategy sits on a plateau: neighbours perform
    similarly and the original is not an isolated spike."""
    rng = np.random.default_rng(seed)
    axes: list[tuple[str, list]] = []
    for i, sig in enumerate(s.entry):
        grid = TEMPLATES[sig.template].grid
        for k, v in sig.param_dict.items():
            nb = _numeric_neighbours(v, grid[k], span)
            if len(nb) > 1:
                axes.append((f"entry{i}.{k}", nb))
    for f in ("stop_atr", "target_atr", "trail_atr", "max_bars"):
        v = getattr(s.exits, f)
        if v is not None:
            axes.append((f"exit.{f}", _numeric_neighbours(v, [], span)))
    if not axes:
        return {"test": "parameter_stability", "verdict": "warn", "reason": "strategy has no numeric parameters"}
    combos = list(itertools.product(*(a[1] for a in axes)))
    if len(combos) > max_variants:
        idx = rng.choice(len(combos), max_variants, replace=False)
        combos = [combos[i] for i in idx]
    n = len(ctx.bars)
    vals, nets = [], []
    for combo in combos:
        variant = _apply(s, [a[0] for a in axes], combo)
        if variant is None:
            continue
        m = ctx.segment_metrics(ctx.run(variant), 0, n)
        vals.append(fitness_value(m, fitness))
        nets.append(m["net_profit"])
    vals, nets = np.array(vals), np.array(nets)
    real = fitness_value(ctx.segment_metrics(ctx.run(s), 0, n), fitness)
    med, p25 = float(np.median(vals)), _pct(vals, 25)
    frac_prof = float((nets > 0).mean())
    sign = 1 if FITNESS[fitness][1] else -1
    spike = real > 0 and med > 0 and real > 2.0 * med
    verdict = "pass" if (frac_prof >= 0.7 and not spike and _pct(nets, 25) > 0) else ("warn" if frac_prof >= 0.5 else "fail")
    return {
        "test": "parameter_stability",
        "fitness": fitness,
        "span": span,
        "variants": int(len(vals)),
        "axes": {a[0]: a[1] for a in axes},
        "strategy": sign * real,
        "neighbours": {k: sign * v for k, v in _summary(vals).items()},
        "fraction_profitable": frac_prof,
        "is_spike": bool(spike),
        "verdict": verdict,
        "rule": "pass if >= 70% of neighbours profitable, 25th percentile net profit > 0 and the original is not > 2x the neighbour median",
        "neighbour_p25": sign * p25,
    }


def _apply(s: Strategy, names: list[str], values) -> Strategy | None:
    entry = [dict(sig.param_dict) for sig in s.entry]
    ex = dict(s.exits.__dict__)
    for name, v in zip(names, values):
        head, key = name.split(".", 1)
        if head == "exit":
            ex[key] = v
        else:
            entry[int(head[5:])][key] = v
    try:
        sigs = []
        for sig, p in zip(s.entry, entry):
            t = TEMPLATES[sig.template]
            if not t.valid(**p):
                return None
            sigs.append(Signal.of(sig.template, **p))
            sigs[-1].expr()  # validate (e.g. lengths >= 1)
        return Strategy(s.direction, tuple(sigs), ExitSpec(**ex), s.quantity)
    except ValueError:
        return None


# --------------------------------------------------------------- other markets
def other_markets(s: Strategy, markets: dict[str, Bars], config, fitness: str = "profit_factor") -> dict:
    rows = []
    for name, b in markets.items():
        m = backtest(b, s, config).metrics_all
        rows.append({"market": name, "trades": m["trades"], "net_profit": m["net_profit"], fitness: m.get(fitness, 0.0)})
    prof = sum(r["net_profit"] > 0 for r in rows)
    frac = prof / len(rows) if rows else 0.0
    return {
        "test": "other_markets",
        "rows": rows,
        "fraction_profitable": frac,
        "verdict": "pass" if frac >= 0.6 else ("warn" if frac >= 0.4 else "fail"),
        "rule": "pass if profitable on >= 60% of the other markets",
    }


# --------------------------------------------------------------- suite
def run_suite(ctx: Context, s: Strategy, fitness: str = "profit_factor", quick: bool = False, seed: int = 0) -> dict:
    runs = 100 if quick else 300
    res = backtest(ctx.bars, s, ctx=ctx)
    pnl = res.run.pnl
    oos_ok = res.metrics_oos["trades"] > 0 and res.metrics_oos["net_profit"] > 0
    tests = [
        {
            "test": "out_of_sample",
            "in_sample": {k: res.metrics_is[k] for k in ("trades", "net_profit", "profit_factor", "sharpe", "max_drawdown")},
            "out_of_sample": {k: res.metrics_oos[k] for k in ("trades", "net_profit", "profit_factor", "sharpe", "max_drawdown")},
            "verdict": "pass" if oos_ok and res.metrics_oos["profit_factor"] >= 1.1 else ("warn" if oos_ok else "fail"),
            "rule": "pass if out-of-sample is profitable with profit factor >= 1.1",
        },
        monte_carlo_trades(pnl, 1000, seed, "resample"),
        noise_test(ctx, s, runs // 2, fitness=fitness, seed=seed),
        vs_random(ctx, s, runs, fitness=fitness, seed=seed),
        permutation_test(ctx, s, runs // 2, fitness=fitness, seed=seed),
        delay_test(ctx, s, fitness=fitness),
        variance_test(pnl, seed=seed),
        parameter_stability(ctx, s, fitness=fitness, max_variants=150 if quick else 400, seed=seed),
    ]
    score = {"pass": 0, "warn": 0, "fail": 0}
    for t in tests:
        score[t["verdict"]] += 1
    return {"tests": tests, "score": score}
