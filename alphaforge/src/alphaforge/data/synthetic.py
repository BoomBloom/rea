"""Deterministic synthetic market data for demos, tests and stress tests.

Synthetic data carries no edge by construction (unless ``drift``/``mean_reversion``
are set), which makes it the right null case: a strategy that looks great on it
is evidence of overfitting, not of skill.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .bars import Bars, InstrumentSpec


def make_bars(
    n: int = 2500,
    seed: int = 7,
    start_price: float = 100.0,
    daily_vol: float = 0.012,
    drift: float = 0.0002,
    mean_reversion: float = 0.0,
    freq: str = "B",
    start: str = "2010-01-04",
    symbol: str = "SYNTH",
    point_value: float = 1.0,
    tick_size: float = 0.01,
) -> Bars:
    """Generate OHLCV bars with volatility clustering (GARCH-like) and optional
    short-term mean reversion (negative autocorrelation of returns)."""
    rng = np.random.default_rng(seed)
    vol = np.empty(n)
    rets = np.empty(n)
    v = daily_vol
    prev = 0.0
    for i in range(n):
        # simple GARCH(1,1)-style variance update around the target vol
        v = np.sqrt(0.05 * daily_vol**2 + 0.9 * v**2 + 0.05 * prev**2)
        r = drift - mean_reversion * prev + v * rng.standard_t(5) / np.sqrt(5 / 3)
        rets[i] = r
        vol[i] = v
        prev = r
    close = start_price * np.exp(np.cumsum(rets))
    prev_close = np.r_[start_price, close[:-1]]
    gap = rng.normal(0, 0.25, n) * vol
    open_ = prev_close * np.exp(gap)
    span = np.abs(rng.normal(0, 0.6, n)) * vol + np.abs(rets) * 0.2
    high = np.maximum(open_, close) * np.exp(np.abs(rng.normal(0, 0.5, n)) * vol + span * 0.3)
    low = np.minimum(open_, close) * np.exp(-np.abs(rng.normal(0, 0.5, n)) * vol - span * 0.3)
    volume = np.round(rng.lognormal(13, 0.4, n))
    idx = pd.date_range(start=start, periods=n, freq=freq, tz="UTC")
    rnd = lambda x: np.round(x / tick_size) * tick_size  # noqa: E731
    o, h, lo, c = rnd(open_), rnd(high), rnd(low), rnd(close)
    h = np.maximum.reduce([h, o, c])
    lo = np.minimum.reduce([lo, o, c])
    df = pd.DataFrame({"open": o, "high": h, "low": lo, "close": c, "volume": volume}, index=idx)
    return Bars.from_frame(df, InstrumentSpec(symbol, point_value, tick_size))
