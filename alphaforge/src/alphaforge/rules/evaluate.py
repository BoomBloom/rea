"""Vectorised evaluation of rule expressions over Bars, with memoisation.

An ``Evaluator`` is bound to one Bars object and caches every sub-expression,
so evaluating thousands of signals that share indicators (e.g. many rules using
``sma(close, 20)``) computes each indicator once.
"""

from __future__ import annotations

import numpy as np

from ..data.bars import Bars
from . import indicators as ind
from .expr import Bin, Calendar, Call, Cmp, Const, Cross, Expr, Field, Lag, Logic, Not


class Evaluator:
    def __init__(self, bars: Bars):
        self.bars = bars
        self._cache: dict[Expr, np.ndarray] = {}
        self._calendar: dict[str, np.ndarray] = {}

    def value(self, e: Expr) -> np.ndarray:
        hit = self._cache.get(e)
        if hit is not None:
            return hit
        out = self._compute(e)
        self._cache[e] = out
        return out

    def boolean(self, e: Expr) -> np.ndarray:
        """Evaluate a condition to a bool array (NaN -> False)."""
        v = self.value(e)
        if v.dtype == np.bool_:
            return v
        return np.nan_to_num(v, nan=0.0) != 0.0

    def clear(self) -> None:
        self._cache.clear()

    def _calendar_field(self, name: str) -> np.ndarray:
        if name not in self._calendar:
            idx = self.bars.datetime_index()
            if name == "dayofweek":
                self._calendar[name] = (idx.dayofweek.to_numpy() + 1).astype(np.float64)
            else:
                self._calendar[name] = idx.month.to_numpy().astype(np.float64)
        return self._calendar[name]

    def _compute(self, e: Expr) -> np.ndarray:
        b = self.bars
        if isinstance(e, Field):
            return getattr(b, e.name)
        if isinstance(e, Const):
            return np.full(len(b), e.value)
        if isinstance(e, Calendar):
            return self._calendar_field(e.name)
        if isinstance(e, Lag):
            x = self.value(e.x)
            if x.dtype == np.bool_:
                out = np.zeros_like(x)
                if e.n < len(x):
                    out[e.n :] = x[: len(x) - e.n] if e.n else x
                return out
            return ind.lag(x, e.n)
        if isinstance(e, Call):
            p = e.params
            fn = e.fn
            if fn == "atr":
                return ind.atr(b.high, b.low, b.close, p[0])
            if fn == "stoch_k":
                return ind.stoch_k(b.high, b.low, b.close, p[0])
            if fn == "ibs":
                return ind.ibs(b.high, b.low, b.close)
            x = self.value(e.args[0]).astype(np.float64)
            return getattr(ind, fn)(x, p[0])
        if isinstance(e, Bin):
            a = self.value(e.a).astype(np.float64)
            c = self.value(e.b).astype(np.float64)
            with np.errstate(divide="ignore", invalid="ignore"):
                if e.op == "+":
                    return a + c
                if e.op == "-":
                    return a - c
                if e.op == "*":
                    return a * c
                out = a / c
                out[c == 0] = np.nan
                return out
        if isinstance(e, Cmp):
            a = self.value(e.a).astype(np.float64)
            c = self.value(e.b).astype(np.float64)
            with np.errstate(invalid="ignore"):
                if e.op == ">":
                    return a > c
                if e.op == "<":
                    return a < c
                if e.op == ">=":
                    return a >= c
                if e.op == "<=":
                    return a <= c
                return a == c
        if isinstance(e, Cross):
            a = self.value(e.a).astype(np.float64)
            c = self.value(e.b).astype(np.float64)
            a1, c1 = ind.lag(a, 1), ind.lag(c, 1)
            with np.errstate(invalid="ignore"):
                if e.direction == "above":
                    return (a > c) & (a1 <= c1)
                return (a < c) & (a1 >= c1)
        if isinstance(e, Logic):
            parts = [self.boolean(a) for a in e.args]
            out = parts[0].copy()
            for p in parts[1:]:
                out = (out & p) if e.op == "and" else (out | p)
            return out
        if isinstance(e, Not):
            return ~self.boolean(e.x)
        raise TypeError(f"cannot evaluate {type(e).__name__}")
