"""High-level backtest API on top of the kernel."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..data.bars import Bars
from ..rules import indicators as ind
from ..rules.evaluate import Evaluator
from . import metrics as mt
from .kernel import REASONS, simulate
from .spec import BacktestConfig, Strategy


@dataclass
class RawRun:
    entry_idx: np.ndarray
    exit_idx: np.ndarray
    entry_px: np.ndarray
    exit_px: np.ndarray
    reason: np.ndarray
    pnl: np.ndarray
    mae: np.ndarray
    mfe: np.ndarray
    equity: np.ndarray  # cumulative P&L per bar over [start, end)
    in_market: np.ndarray
    start: int
    end: int


class Context:
    """Bars plus caches shared by many backtests on the same data."""

    def __init__(self, bars: Bars, config: BacktestConfig | None = None):
        self.bars = bars
        self.config = config or BacktestConfig()
        self.ev = Evaluator(bars)
        self._atr: dict[int, np.ndarray] = {}
        n = len(bars)
        self.split = int(round(n * (1.0 - self.config.oos_fraction)))
        self.split = min(max(self.split, 1), n)

    def atr(self, n: int) -> np.ndarray:
        if n not in self._atr:
            self._atr[n] = ind.atr(self.bars.high, self.bars.low, self.bars.close, n)
        return self._atr[n]

    def entry_array(self, strategy: Strategy) -> np.ndarray:
        arr = self.ev.boolean(strategy.entry[0].expr())
        for s in strategy.entry[1:]:
            arr = arr & self.ev.boolean(s.expr())
        return arr

    def exit_array(self, strategy: Strategy) -> np.ndarray:
        if strategy.exits.exit_signal is None:
            return np.zeros(len(self.bars), np.bool_)
        return self.ev.boolean(strategy.exits.exit_signal.expr())

    def run(
        self,
        strategy: Strategy,
        start: int = 0,
        end: int | None = None,
        entry: np.ndarray | None = None,
        bars: Bars | None = None,
    ) -> RawRun:
        """Simulate over bar indices [start, end). ``entry``/``bars`` override
        the evaluated entry array or price data (used by robustness tests)."""
        b = bars or self.bars
        end = len(b) if end is None else end
        e = strategy.exits
        if entry is None:
            entry = self.entry_array(strategy)
        exit_sig = self.exit_array(strategy)
        atr = self.atr(e.atr_len) if bars is None else ind.atr(b.high, b.low, b.close, e.atr_len)
        slip = self.config.costs.slippage_ticks * b.instrument.tick_size
        out = simulate(
            b.open,
            b.high,
            b.low,
            b.close,
            np.ascontiguousarray(entry, dtype=np.bool_),
            np.ascontiguousarray(exit_sig, dtype=np.bool_),
            atr,
            strategy.sign,
            float(e.stop_atr or 0.0),
            float(e.target_atr or 0.0),
            float(e.trail_atr or 0.0),
            int(e.max_bars or 0),
            bool(e.profitable_close),
            float(slip),
            float(self.config.costs.commission),
            float(strategy.quantity),
            float(b.instrument.point_value),
            int(start),
            int(end),
        )
        return RawRun(*out, start=start, end=end)

    def segment_metrics(self, run: RawRun, lo: int, hi: int) -> dict:
        """Metrics for trades whose entry bar is in [lo, hi), with the equity of that range."""
        mask = (run.entry_idx >= lo) & (run.entry_idx < hi)
        a, z = max(lo, run.start) - run.start, min(hi, run.end) - run.start
        eq = run.equity[a:z]
        eq = eq - (run.equity[a - 1] if a > 0 else 0.0)
        return mt.compute(
            run.pnl[mask],
            eq,
            run.in_market[a:z],
            (run.exit_idx - run.entry_idx + 1)[mask],
            self.bars.time[max(lo, run.start) : min(hi, run.end)],
            self.config.initial_capital,
        )


@dataclass
class BacktestResult:
    strategy: Strategy
    run: RawRun
    metrics_all: dict
    metrics_is: dict
    metrics_oos: dict
    split: int
    bars: Bars

    def trades_frame(self) -> pd.DataFrame:
        r = self.run
        t = self.bars.datetime_index()
        return pd.DataFrame(
            {
                "entry_time": t[r.entry_idx],
                "exit_time": t[r.exit_idx],
                "direction": self.strategy.direction,
                "entry_price": r.entry_px,
                "exit_price": r.exit_px,
                "bars": r.exit_idx - r.entry_idx + 1,
                "reason": [REASONS[int(x)] for x in r.reason],
                "pnl": r.pnl,
                "mae": r.mae,
                "mfe": r.mfe,
                "sample": np.where(r.entry_idx < self.split, "in", "out"),
            }
        )

    def equity_series(self) -> pd.Series:
        return pd.Series(self.run.equity, index=self.bars.datetime_index()[self.run.start : self.run.end])

    def to_dict(self, include_curve: bool = True, max_points: int = 1500) -> dict:
        d = {
            "strategy": self.strategy.to_dict(),
            "description": self.strategy.describe(),
            "metrics": {"all": self.metrics_all, "in_sample": self.metrics_is, "out_of_sample": self.metrics_oos},
            "split_time": str(self.bars.datetime_index()[self.split]) if self.split < len(self.bars) else None,
        }
        if include_curve:
            eq = self.run.equity
            step = max(1, len(eq) // max_points)
            idx = np.arange(0, len(eq), step)
            if idx[-1] != len(eq) - 1:
                idx = np.r_[idx, len(eq) - 1]
            ts = self.bars.time[self.run.start : self.run.end][idx] // 1_000_000_000
            dd = eq - np.maximum.accumulate(np.r_[0.0, eq])[1:]
            d["equity"] = {"t": ts.tolist(), "v": np.round(eq[idx], 2).tolist(), "dd": np.round(dd[idx], 2).tolist()}
        return d


def backtest(bars: Bars, strategy: Strategy, config: BacktestConfig | None = None, ctx: Context | None = None) -> BacktestResult:
    ctx = ctx or Context(bars, config)
    run = ctx.run(strategy)
    n = len(bars)
    return BacktestResult(
        strategy,
        run,
        ctx.segment_metrics(run, 0, n),
        ctx.segment_metrics(run, 0, ctx.split),
        ctx.segment_metrics(run, ctx.split, n),
        ctx.split,
        bars,
    )
