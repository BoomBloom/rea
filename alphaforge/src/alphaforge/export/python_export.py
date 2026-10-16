"""Export a strategy as a standalone Python (pandas) script.

The script reimplements AlphaForge's indicator definitions and execution model
in plain, readable Python so it can be audited and run without AlphaForge.
The test suite runs exported scripts and checks that they reproduce the
engine's trade list exactly.
"""

from __future__ import annotations

from ..rules.expr import Bin, Calendar, Call, Cmp, Const, Cross, Expr, Field, Lag, Logic, Not
from .common import ExportContext, header_lines

_RUNTIME = '''
import math
import sys

import numpy as np
import pandas as pd


# ---- indicator definitions (identical to AlphaForge's; see its docs/engine.md)
def sma(x, n):
    return x.rolling(n, min_periods=n).mean()


def stdev(x, n):
    return x.rolling(n, min_periods=n).std(ddof=0)


def highest(x, n):
    return x.rolling(n, min_periods=n).max()


def lowest(x, n):
    return x.rolling(n, min_periods=n).min()


def _seeded(x, n, alpha):
    vals = x.to_numpy(dtype=float)
    out = np.full(len(vals), np.nan)
    run = 0
    start = -1
    for i, v in enumerate(vals):
        run = run + 1 if not math.isnan(v) else 0
        if run == n:
            start = i
            break
    if start >= 0:
        prev = vals[start - n + 1:start + 1].sum() / n
        out[start] = prev
        for i in range(start + 1, len(vals)):
            if not math.isnan(vals[i]):
                prev = alpha * vals[i] + (1 - alpha) * prev
            out[i] = prev
    return pd.Series(out, index=x.index)


def ema(x, n):
    return _seeded(x, n, 2.0 / (n + 1.0))


def rma(x, n):
    return _seeded(x, n, 1.0 / n)


def rsi(x, n):
    ch = x.diff()
    up = rma(ch.clip(lower=0).where(ch.notna()), n)
    dn = rma((-ch).clip(lower=0).where(ch.notna()), n)
    out = 100 - 100 / (1 + up / dn)
    out = out.where(dn != 0, 100.0)
    out = out.where(~((up == 0) & (dn != 0)), 0.0)
    return out.where(up.notna() & dn.notna())


def atr(df, n):
    prev = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - prev).abs(), (df["low"] - prev).abs()], axis=1).max(axis=1)
    tr.iloc[0] = df["high"].iloc[0] - df["low"].iloc[0]
    return rma(tr, n)


def roc(x, n):
    return 100 * (x - x.shift(n)) / x.shift(n)


def stoch_k(df, n):
    hh, ll = highest(df["high"], n), lowest(df["low"], n)
    rng = hh - ll
    return (100 * (df["close"] - ll) / rng).where(rng != 0)


def ibs(df):
    rng = df["high"] - df["low"]
    return ((df["close"] - df["low"]) / rng).where(rng != 0)


def lag(x, n):
    if x.dtype == bool:
        return x.shift(n, fill_value=False)
    return x.shift(n)


def div(a, b):
    return (a / b).where(b != 0)


def load(path):
    """Read OHLCV CSV with a datetime first column (or date/time columns)."""
    df = pd.read_csv(path)
    cols = {c.lower().strip(): c for c in df.columns}
    if "datetime" in cols:
        idx = pd.to_datetime(df[cols["datetime"]])
    elif "date" in cols and "time" in cols:
        idx = pd.to_datetime(df[cols["date"]].astype(str) + " " + df[cols["time"]].astype(str))
    elif "date" in cols:
        idx = pd.to_datetime(df[cols["date"]])
    else:
        idx = pd.to_datetime(df.iloc[:, 0])
    out = pd.DataFrame({k: df[cols[k]].astype(float) for k in ("open", "high", "low", "close")})
    out["volume"] = df[cols["volume"]].astype(float) if "volume" in cols else 0.0
    out.index = pd.DatetimeIndex(idx)
    return out.sort_index()
'''

_BACKTEST = '''

def backtest(df):
    """Reproduce AlphaForge's execution model. Returns a list of trade dicts."""
    entry, exit_sig, atrv = signals(df)
    o, h, lo, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    entry, exit_sig, atrv = entry.to_numpy(bool), exit_sig.to_numpy(bool), atrv.to_numpy(float)
    d = DIRECTION
    slip = SLIPPAGE_TICKS * TICK_SIZE
    mult = QUANTITY * POINT_VALUE
    trades = []
    pos = 0
    pending_entry = False
    pending_exit = None
    n = len(df)

    def close_trade(i, px, reason):
        pnl = d * (px - st["entry_px"]) * mult - 2 * COMMISSION * QUANTITY
        trades.append({"entry_time": df.index[st["entry_i"]], "exit_time": df.index[i],
                       "entry_price": st["entry_px"], "exit_price": px, "reason": reason, "pnl": pnl})

    st = {}
    for t in range(n):
        if pos and pending_exit:
            close_trade(t, o[t] - d * slip, pending_exit)
            pos = 0
        pending_exit = None
        if not pos and pending_entry:
            ref = atrv[t - 1]
            px = o[t] + d * slip
            st = {"entry_px": px, "entry_i": t, "bars": 0, "ref": ref, "extreme": px,
                  "stop": px - d * STOP_ATR * ref if STOP_ATR > 0 else math.nan,
                  "target": px + d * TARGET_ATR * ref if TARGET_ATR > 0 else math.nan,
                  "trail": px - d * TRAIL_ATR * ref if TRAIL_ATR > 0 else math.nan}
            pos = d
        pending_entry = False
        if pos:
            st["bars"] += 1
            prot, prot_reason = st["stop"], "stop"
            if not math.isnan(st["trail"]) and (math.isnan(prot) or d * (st["trail"] - prot) > 0):
                prot, prot_reason = st["trail"], "trail"
            exit_px = None
            if not math.isnan(prot):
                if d == 1 and lo[t] <= prot:
                    exit_px, reason = min(o[t], prot) - slip, prot_reason
                elif d == -1 and h[t] >= prot:
                    exit_px, reason = max(o[t], prot) + slip, prot_reason
            if exit_px is None and not math.isnan(st["target"]):
                if d == 1 and h[t] >= st["target"]:
                    exit_px, reason = max(o[t], st["target"]), "target"
                elif d == -1 and lo[t] <= st["target"]:
                    exit_px, reason = min(o[t], st["target"]), "target"
            if exit_px is not None:
                close_trade(t, exit_px, reason)
                pos = 0
        if pos:
            if t == n - 1:
                close_trade(t, c[t] - d * slip, "end")
                pos = 0
            else:
                if TRAIL_ATR > 0:
                    st["extreme"] = max(st["extreme"], h[t]) if d == 1 else min(st["extreme"], lo[t])
                    cand = st["extreme"] - d * TRAIL_ATR * st["ref"]
                    if d * (cand - st["trail"]) > 0:
                        st["trail"] = cand
                if MAX_BARS > 0 and st["bars"] >= MAX_BARS:
                    pending_exit = "time"
                elif exit_sig[t]:
                    pending_exit = "signal"
                elif PROFITABLE_CLOSE and d * (c[t] - st["entry_px"]) > 0:
                    pending_exit = "profit_close"
        if not pos and t < n - 1 and entry[t]:
            if not NEEDS_ATR or not math.isnan(atrv[t]):
                pending_entry = True
    return trades


def latest_signal(df):
    """Return 'ENTER' if the last completed bar triggers an entry (place a market order for the next open)."""
    entry, _, _ = signals(df)
    return "ENTER" if bool(entry.iloc[-1]) else None


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python this_script.py data.csv")
        sys.exit(2)
    frame = load(sys.argv[1])
    result = backtest(frame)
    pnl = [t["pnl"] for t in result]
    print(f"trades={len(result)} net_profit={sum(pnl):.2f}")
    for tr in result[-10:]:
        print(tr)
'''


def _render(e: Expr) -> str:
    if isinstance(e, Field):
        return f'df["{e.name}"]'
    if isinstance(e, Const):
        return repr(float(e.value))
    if isinstance(e, Calendar):
        if e.name == "dayofweek":
            return "pd.Series(df.index.dayofweek + 1, index=df.index, dtype=float)"
        return "pd.Series(df.index.month, index=df.index, dtype=float)"
    if isinstance(e, Lag):
        return f"lag({_render(e.x)}, {e.n})"
    if isinstance(e, Call):
        p = ", ".join(str(int(x)) for x in e.params)
        if e.fn in ("atr", "stoch_k"):
            return f"{e.fn}(df, {p})"
        if e.fn == "ibs":
            return "ibs(df)"
        return f"{e.fn}({_render(e.args[0])}, {p})"
    if isinstance(e, Bin):
        if e.op == "/":
            return f"div({_render(e.a)}, {_render(e.b)})"
        return f"({_render(e.a)} {e.op} {_render(e.b)})"
    if isinstance(e, Cmp):
        return f"({_render(e.a)} {e.op} {_render(e.b)})"
    if isinstance(e, Cross):
        a, b = _render(e.a), _render(e.b)
        if e.direction == "above":
            return f"(({a}) > ({b})) & (lag({a}, 1) <= lag({b}, 1))"
        return f"(({a}) < ({b})) & (lag({a}, 1) >= lag({b}, 1))"
    if isinstance(e, Logic):
        j = " & " if e.op == "and" else " | "
        return "(" + j.join(_render(a) for a in e.args) + ")"
    if isinstance(e, Not):
        return f"(~{_render(e.x)})"
    raise TypeError(type(e).__name__)


def export_python(ctx: ExportContext) -> str:
    s = ctx.strategy
    e = s.exits
    lines = ["#!/usr/bin/env python3"]
    lines += header_lines(ctx, "#")
    lines.append('"""Standalone strategy script. Requires numpy and pandas. Run: python script.py data.csv"""')
    lines.append(_RUNTIME)
    lines.append(f"DIRECTION = {s.sign}")
    lines.append(f"QUANTITY = {float(s.quantity)!r}")
    lines.append(f"POINT_VALUE = {float(ctx.point_value)!r}")
    lines.append(f"TICK_SIZE = {float(ctx.tick_size)!r}")
    lines.append(f"COMMISSION = {float(ctx.config.costs.commission)!r}")
    lines.append(f"SLIPPAGE_TICKS = {float(ctx.config.costs.slippage_ticks)!r}")
    lines.append(f"STOP_ATR = {float(e.stop_atr or 0.0)!r}")
    lines.append(f"TARGET_ATR = {float(e.target_atr or 0.0)!r}")
    lines.append(f"TRAIL_ATR = {float(e.trail_atr or 0.0)!r}")
    lines.append(f"MAX_BARS = {int(e.max_bars or 0)}")
    lines.append(f"PROFITABLE_CLOSE = {bool(e.profitable_close)}")
    lines.append(f"ATR_LEN = {int(e.atr_len)}")
    lines.append("NEEDS_ATR = STOP_ATR > 0 or TARGET_ATR > 0 or TRAIL_ATR > 0")
    lines.append("")
    lines.append("")
    lines.append("def signals(df):")
    lines.append('    """Entry and exit conditions evaluated at each bar close (False during warm-up)."""')
    for i, sig in enumerate(s.entry):
        lines.append(f"    # entry {i + 1}: {sig.label()}")
        lines.append(f"    e{i} = {_render(sig.expr())}")
    lines.append("    entry = " + " & ".join(f"e{i}" for i in range(len(s.entry))))
    if e.exit_signal is not None:
        lines.append(f"    # exit signal: {e.exit_signal.label()}")
        lines.append(f"    exit_sig = {_render(e.exit_signal.expr())}")
    else:
        lines.append("    exit_sig = pd.Series(False, index=df.index)")
    lines.append("    return entry.fillna(False).astype(bool), exit_sig.fillna(False).astype(bool), atr(df, ATR_LEN)")
    lines.append(_BACKTEST)
    return "\n".join(lines)
