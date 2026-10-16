"""TradingView Pine Script v5 exporter.

Pine's ``ta.*`` definitions are the reference our indicators follow, and Pine's
default broker emulator fills market orders at the next bar's open, matching our
execution model. Known differences (also printed in the script header):

- On the entry bar the stop/target are placed from the signal bar's close
  (Pine cannot know the fill price before the fill); from the next bar on they
  are recomputed from ``strategy.position_avg_price`` like AlphaForge does.
- When a stop and target are both inside one bar, Pine assumes an intrabar path
  from the bar's open; AlphaForge always assumes the stop fills first.
"""

from __future__ import annotations

from ..rules.expr import Bin, Calendar, Call, Cmp, Const, Cross, Expr, Field, Lag, Logic, Not
from .common import ExportContext, header_lines


def _r(e: Expr) -> str:
    if isinstance(e, Field):
        return e.name
    if isinstance(e, Const):
        v = e.value
        return str(int(v)) if float(v).is_integer() else repr(float(v))
    if isinstance(e, Calendar):
        if e.name == "dayofweek":
            return "isoDow"
        return "month"
    if isinstance(e, Lag):
        inner = _r(e.x)
        return f"{inner}[{e.n}]" if isinstance(e.x, (Field, Call, Calendar)) else f"({inner})[{e.n}]"
    if isinstance(e, Call):
        p = ", ".join(str(x) for x in e.params)
        if e.fn == "atr":
            return f"ta.atr({p})"
        if e.fn == "stoch_k":
            return f"ta.stoch(close, high, low, {p})"
        if e.fn == "ibs":
            return "(high - low != 0 ? (close - low) / (high - low) : na)"
        fn = {"stdev": "ta.stdev", "highest": "ta.highest", "lowest": "ta.lowest"}.get(e.fn, f"ta.{e.fn}")
        return f"{fn}({_r(e.args[0])}, {p})"
    if isinstance(e, Bin):
        return f"({_r(e.a)} {e.op} {_r(e.b)})"
    if isinstance(e, Cmp):
        op = "==" if e.op == "==" else e.op
        return f"({_r(e.a)} {op} {_r(e.b)})"
    if isinstance(e, Cross):
        a, b = _r(e.a), _r(e.b)
        if e.direction == "above":
            return f"(({a}) > ({b}) and ({a})[1] <= ({b})[1])"
        return f"(({a}) < ({b}) and ({a})[1] >= ({b})[1])"
    if isinstance(e, Logic):
        j = " and " if e.op == "and" else " or "
        return "(" + j.join(_r(a) for a in e.args) + ")"
    if isinstance(e, Not):
        return f"(not {_r(e.x)})"
    raise TypeError(type(e).__name__)


def export_pine(ctx: ExportContext) -> str:
    s, e, c = ctx.strategy, ctx.strategy.exits, ctx.config.costs
    long = s.direction == "long"
    lines = ["//@version=5"]
    lines += header_lines(ctx, "//")
    lines += [
        "// Differences vs AlphaForge: entry-bar stop/target placed from the signal bar close;",
        "// Pine's intrabar path assumption decides stop-vs-target on bars touching both.",
        f'strategy("{ctx.name}", overlay=true, default_qty_type=strategy.fixed, default_qty_value={s.quantity:g},',
        f"     commission_type=strategy.commission.cash_per_contract, commission_value={c.commission:g}, slippage={int(round(c.slippage_ticks))},",
        "     process_orders_on_close=false, pyramiding=0)",
        "",
        "isoDow = dayofweek == dayofweek.sunday ? 7 : dayofweek - 1",
        f"atrv = ta.atr({e.atr_len})",
        f"warm = bar_index >= {ctx.warmup()}",
    ]
    for i, sig in enumerate(s.entry):
        lines.append(f"// entry {i + 1}: {sig.label()}")
        lines.append(f"e{i} = {_r(sig.expr())}")
    lines.append("entryCond = warm and " + " and ".join(f"e{i}" for i in range(len(s.entry))))
    if e.exit_signal is not None:
        lines.append(f"// exit signal: {e.exit_signal.label()}")
        lines.append(f"exitCond = {_r(e.exit_signal.expr())}")
    else:
        lines.append("exitCond = false")
    d = "1" if long else "-1"
    lines += [
        f"dir = {d}",
        "var float refAtr = na",
        "var float trailStop = na",
        "var float extreme = na",
        "flat = strategy.position_size == 0",
        "",
        "needsAtr = " + ("true" if any(v is not None for v in (e.stop_atr, e.target_atr, e.trail_atr)) else "false"),
        "if flat and entryCond and (not needsAtr or not na(atrv))",
        f'    strategy.entry("AF", {"strategy.long" if long else "strategy.short"})',
        "    refAtr := atrv",
        "    extreme := close",
        f"    trailStop := {('close - dir * ' + repr(float(e.trail_atr)) + ' * atrv') if e.trail_atr else 'na'}",
        "",
        "basePx = flat ? close : strategy.position_avg_price",
    ]
    stop = f"basePx - dir * {float(e.stop_atr)!r} * refAtr" if e.stop_atr else "na"
    tgt = f"basePx + dir * {float(e.target_atr)!r} * refAtr" if e.target_atr else "na"
    lines += [f"stopPx = {stop}", f"targetPx = {tgt}"]
    if e.trail_atr:
        lines += [
            "if not flat",
            "    extreme := dir == 1 ? math.max(nz(extreme, high), high) : math.min(nz(extreme, low), low)",
            f"    cand = extreme - dir * {float(e.trail_atr)!r} * refAtr",
            "    trailStop := na(trailStop) ? cand : (dir == 1 ? math.max(trailStop, cand) : math.min(trailStop, cand))",
            "protPx = na(stopPx) ? trailStop : na(trailStop) ? stopPx : (dir == 1 ? math.max(stopPx, trailStop) : math.min(stopPx, trailStop))",
        ]
    else:
        lines.append("protPx = stopPx")
    lines += [
        "if not na(protPx) or not na(targetPx)",
        '    strategy.exit("AF exit", "AF", stop=protPx, limit=targetPx)',
        "",
        "barsIn = flat ? 0 : bar_index - strategy.opentrades.entry_bar_index(0) + 1",
        "if not flat",
    ]
    conds = []
    if e.max_bars:
        conds.append(f"barsIn >= {int(e.max_bars)}")
    conds.append("exitCond")
    if e.profitable_close:
        conds.append("dir * (close - strategy.position_avg_price) > 0")
    lines.append(f"    if {' or '.join(conds)}")
    lines.append('        strategy.close("AF")')
    return "\n".join(lines) + "\n"
