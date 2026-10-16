"""Parameter optimisation and walk-forward analysis for a fixed rule structure.

Walk-forward: split the history into consecutive windows. In each window,
choose parameters on the in-sample part only, then trade the following
out-of-sample part with them. Stitching the out-of-sample parts gives an
equity curve made entirely of decisions that never saw their own data.
"""

from __future__ import annotations

import itertools

import numpy as np

from ..data.bars import Bars
from ..engine.backtest import Context
from ..engine.metrics import compute, fitness_value
from ..engine.spec import BacktestConfig, Strategy
from ..robustness.tests import _apply
from ..rules.library import TEMPLATES


def optimisation_axes(s: Strategy, width: float = 0.5) -> list[tuple[str, list]]:
    axes: list[tuple[str, list]] = []
    for i, sig in enumerate(s.entry):
        grid = TEMPLATES[sig.template].grid
        for k, v in sig.param_dict.items():
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                continue
            g = [x for x in grid[k] if isinstance(x, (int, float)) and abs(x - v) <= abs(v) * width + 1e-12]
            vals = sorted(set(g) | {v})
            if len(vals) > 1:
                axes.append((f"entry{i}.{k}", vals))
    for f in ("stop_atr", "target_atr", "trail_atr"):
        v = getattr(s.exits, f)
        if v is not None:
            axes.append((f"exit.{f}", sorted({round(v * m, 4) for m in (0.5, 0.75, 1.0, 1.25, 1.5)})))
    if s.exits.max_bars is not None:
        v = s.exits.max_bars
        axes.append(("exit.max_bars", sorted({max(1, round(v * m)) for m in (0.5, 0.75, 1.0, 1.25, 1.5)})))
    return axes


def _variants(s: Strategy, axes, max_variants: int, rng: np.random.Generator):
    names = [a[0] for a in axes]
    combos = list(itertools.product(*(a[1] for a in axes))) if axes else [()]
    if len(combos) > max_variants:
        keep = rng.choice(len(combos), max_variants, replace=False)
        combos = [combos[i] for i in sorted(keep)]
    out = []
    for c in combos:
        v = _apply(s, names, c) if axes else s
        if v is not None:
            out.append((dict(zip(names, c)), v))
    return out


def optimise(ctx: Context, s: Strategy, start: int, end: int, fitness: str, axes=None, max_variants: int = 300, min_trades: int = 10, seed: int = 0):
    """Best variant on bars [start, end) by fitness. Returns (params, strategy, metrics, n_tested)."""
    rng = np.random.default_rng(seed)
    axes = optimisation_axes(s) if axes is None else axes
    best = None
    tested = 0
    for params, v in _variants(s, axes, max_variants, rng):
        run = ctx.run(v, start, end)
        m = ctx.segment_metrics(run, start, end)
        tested += 1
        if m["trades"] < min_trades:
            continue
        f = fitness_value(m, fitness)
        if best is None or f > best[0]:
            best = (f, params, v, m)
    if best is None:
        return None, s, None, tested
    return best[1], best[2], best[3], tested


def walk_forward(
    bars: Bars,
    s: Strategy,
    config: BacktestConfig | None = None,
    windows: int = 5,
    is_fraction: float = 0.7,
    anchored: bool = False,
    fitness: str = "profit_factor",
    max_variants: int = 200,
    min_trades: int = 10,
    seed: int = 0,
) -> dict:
    ctx = Context(bars, config)
    n = len(bars)
    # each window = IS part + OOS part; OOS parts tile the tail of the data
    oos_len = int(n * (1 - is_fraction) / (windows * (1 - is_fraction) + is_fraction) * 1.0)
    is_len = int(oos_len * is_fraction / (1 - is_fraction))
    if oos_len < 20 or is_len < 50:
        raise ValueError("not enough bars for the requested walk-forward windows")
    axes = optimisation_axes(s)
    rows = []
    oos_pnl: list[np.ndarray] = []
    oos_eq: list[np.ndarray] = []
    oos_mkt: list[np.ndarray] = []
    oos_times: list[np.ndarray] = []
    offset = 0.0
    first_oos = n - windows * oos_len
    for w in range(windows):
        oos_start = first_oos + w * oos_len
        oos_end = n if w == windows - 1 else oos_start + oos_len
        is_start = 0 if anchored else max(0, oos_start - is_len)
        params, best, is_m, tested = optimise(ctx, s, is_start, oos_start, fitness, axes, max_variants, min_trades, seed + w)
        run = ctx.run(best, oos_start, oos_end)
        m = ctx.segment_metrics(run, oos_start, oos_end)
        rows.append({
            "window": w + 1,
            "is_start": str(bars.datetime_index()[is_start]),
            "oos_start": str(bars.datetime_index()[oos_start]),
            "oos_end": str(bars.datetime_index()[oos_end - 1]),
            "params": params,
            "variants_tested": tested,
            "is_fitness": None if is_m is None else is_m.get(fitness),
            "is_net_profit": None if is_m is None else is_m["net_profit"],
            "oos_trades": m["trades"],
            "oos_net_profit": m["net_profit"],
            "oos_fitness": m.get(fitness),
            "optimised": params is not None,
        })
        oos_pnl.append(run.pnl)
        oos_eq.append(run.equity + offset)
        offset += run.equity[-1] if len(run.equity) else 0.0
        oos_mkt.append(run.in_market)
        oos_times.append(bars.time[oos_start:oos_end])
    pnl = np.concatenate(oos_pnl) if oos_pnl else np.array([])
    eq = np.concatenate(oos_eq)
    times = np.concatenate(oos_times)
    held = np.ones(len(pnl))  # bar counts are not needed for the stitched summary
    stitched = compute(pnl, eq, np.concatenate(oos_mkt), held, times, ctx.config.initial_capital)
    is_np = [r["is_net_profit"] for r in rows if r["is_net_profit"] is not None]
    # walk-forward efficiency: OOS profit per bar relative to IS profit per bar
    is_rate = (sum(is_np) / (len(is_np) * is_len)) if is_np else 0.0
    oos_rate = stitched["net_profit"] / max(1, len(eq))
    wfe = oos_rate / is_rate if is_rate > 0 else 0.0
    prof_windows = sum(r["oos_net_profit"] > 0 for r in rows)
    verdict = "pass" if (stitched["net_profit"] > 0 and wfe >= 0.5 and prof_windows >= windows * 0.6) else ("warn" if stitched["net_profit"] > 0 else "fail")
    step = max(1, len(eq) // 1000)
    return {
        "test": "walk_forward",
        "windows": rows,
        "anchored": anchored,
        "is_fraction": is_fraction,
        "fitness": fitness,
        "stitched_oos": stitched,
        "walk_forward_efficiency": wfe,
        "profitable_windows": prof_windows,
        "equity": {"t": (times[::step] // 1_000_000_000).tolist(), "v": np.round(eq[::step], 2).tolist()},
        "verdict": verdict,
        "rule": "pass if stitched OOS is profitable, efficiency >= 0.5 and >= 60% of windows profitable",
    }
