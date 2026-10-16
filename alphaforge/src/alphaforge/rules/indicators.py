"""Indicator implementations with explicitly documented definitions.

Every indicator value at bar ``t`` uses only data at bars ``<= t`` (no
look-ahead). Warm-up values are NaN, and any comparison involving NaN is False.

Definitions match TradingView Pine Script's ``ta.*`` built-ins, which exported
Pine code relies on:

- ``sma``: arithmetic mean of the last n values.
- ``ema``: alpha = 2/(n+1), seeded with the SMA of the first n values.
- ``rma`` (Wilder): alpha = 1/n, seeded with the SMA of the first n values.
- ``rsi``: Wilder RSI using rma of gains/losses; 100 when losses are 0, 0 when gains are 0.
- ``atr``: rma of true range; the first bar's true range is high - low.
- ``stdev``: population standard deviation (ddof=0) of the last n values.
- ``highest``/``lowest``: max/min of the last n values including the current bar.
- ``roc``: 100 * (x - x[n]) / x[n].
- ``stoch_k``: 100 * (close - lowest(low, n)) / (highest(high, n) - lowest(low, n)); NaN when the range is 0.
- ``ibs``: (close - low) / (high - low); NaN when high == low.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .._jit import jit


def sma(x: np.ndarray, n: int) -> np.ndarray:
    return pd.Series(x).rolling(n, min_periods=n).mean().to_numpy()


def stdev(x: np.ndarray, n: int) -> np.ndarray:
    return pd.Series(x).rolling(n, min_periods=n).std(ddof=0).to_numpy()


def highest(x: np.ndarray, n: int) -> np.ndarray:
    return pd.Series(x).rolling(n, min_periods=n).max().to_numpy()


def lowest(x: np.ndarray, n: int) -> np.ndarray:
    return pd.Series(x).rolling(n, min_periods=n).min().to_numpy()


@jit
def _seeded_ewm(x, n, alpha):
    out = np.full(x.shape[0], np.nan)
    # first index where n consecutive non-NaN values are available
    count = 0
    acc = 0.0
    start = -1
    for i in range(x.shape[0]):
        if np.isnan(x[i]):
            count = 0
            acc = 0.0
            continue
        count += 1
        acc += x[i]
        if count == n:
            start = i
            break
        if count > n:
            break
    if start < 0:
        return out
    # recompute the seed exactly over the window [start-n+1, start]
    s = 0.0
    for j in range(start - n + 1, start + 1):
        s += x[j]
    prev = s / n
    out[start] = prev
    for i in range(start + 1, x.shape[0]):
        xi = x[i]
        if np.isnan(xi):
            out[i] = prev
            continue
        prev = alpha * xi + (1.0 - alpha) * prev
        out[i] = prev
    return out


def ema(x: np.ndarray, n: int) -> np.ndarray:
    return _seeded_ewm(np.asarray(x, dtype=np.float64), int(n), 2.0 / (n + 1.0))


def rma(x: np.ndarray, n: int) -> np.ndarray:
    return _seeded_ewm(np.asarray(x, dtype=np.float64), int(n), 1.0 / n)


def rsi(x: np.ndarray, n: int) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    ch = np.empty_like(x)
    ch[0] = np.nan
    ch[1:] = np.diff(x)
    up = rma(np.where(np.isnan(ch), np.nan, np.maximum(ch, 0.0)), n)
    dn = rma(np.where(np.isnan(ch), np.nan, np.maximum(-ch, 0.0)), n)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = 100.0 - 100.0 / (1.0 + up / dn)
    out = np.where(dn == 0.0, 100.0, out)
    out = np.where((up == 0.0) & (dn != 0.0), 0.0, out)
    out[np.isnan(up) | np.isnan(dn)] = np.nan
    return out


def true_range(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    prev = np.r_[np.nan, close[:-1]]
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev), np.abs(low - prev)))
    tr[0] = high[0] - low[0]
    return tr


def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, n: int) -> np.ndarray:
    return rma(true_range(high, low, close), n)


def roc(x: np.ndarray, n: int) -> np.ndarray:
    prev = lag(x, n)
    with np.errstate(divide="ignore", invalid="ignore"):
        return 100.0 * (x - prev) / prev


def stoch_k(high: np.ndarray, low: np.ndarray, close: np.ndarray, n: int) -> np.ndarray:
    hh = highest(high, n)
    ll = lowest(low, n)
    rng = hh - ll
    with np.errstate(divide="ignore", invalid="ignore"):
        out = 100.0 * (close - ll) / rng
    out[rng == 0] = np.nan
    return out


def ibs(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    rng = high - low
    with np.errstate(divide="ignore", invalid="ignore"):
        out = (close - low) / rng
    out[rng == 0] = np.nan
    return out


def lag(x: np.ndarray, n: int) -> np.ndarray:
    n = int(n)
    if n == 0:
        return x
    out = np.full_like(np.asarray(x, dtype=np.float64), np.nan)
    if n < len(x):
        out[n:] = x[:-n]
    return out
