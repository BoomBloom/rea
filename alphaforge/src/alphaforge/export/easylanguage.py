"""TradeStation EasyLanguage / MultiCharts PowerLanguage exporter.

Indicators that EasyLanguage defines differently from AlphaForge are computed
explicitly: ATR uses Wilder smoothing (EasyLanguage's AvgTrueRange is a simple
average) and EMA/RSI are seeded recursions. Built-in Average, Highest, Lowest
and StdDev (population) match AlphaForge's definitions. Stops and targets use
SetStopLoss/SetProfitTarget (per-contract dollars), which, like AlphaForge, are
active on the entry bar and measured from the entry price.
"""

from __future__ import annotations

from ..rules.expr import Bin, Calendar, Call, Cmp, Const, Cross, Expr, Field, Lag, Logic, Not, walk
from .common import ExportContext, header_lines

_FIELD = {"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"}


class _EL:
    def __init__(self, calls):
        self.names = {}
        self.decls = []
        self.updates = []
        for i, call in enumerate(calls):
            self._declare(call, i)

    def _declare(self, call: Call, i: int):
        name = f"v{i}_{call.fn}"
        self.names[call] = name
        n = call.params[0] if call.params else 0
        x = self.r(call.args[0]) if call.args else None
        if call.fn == "sma":
            self.decls.append(f"{name}(0)")
            self.updates.append(f"{name} = Average({x}, {n});")
        elif call.fn == "stdev":
            self.decls.append(f"{name}(0)")
            self.updates.append(f"{name} = StdDev({x}, {n});")
        elif call.fn in ("highest", "lowest"):
            self.decls.append(f"{name}(0)")
            self.updates.append(f"{name} = {call.fn.capitalize()}({x}, {n});")
        elif call.fn == "roc":
            self.decls.append(f"{name}(0)")
            self.updates.append(f"if {x}[{n}] <> 0 then {name} = 100 * ({x} - {x}[{n}]) / {x}[{n}];")
        elif call.fn in ("ema", "atr"):
            alpha = f"2 / ({n} + 1)" if call.fn == "ema" else f"1 / {n}"
            src = x if call.fn == "ema" else "TrueRange"
            self.decls.append(f"{name}(0)")
            self.updates.append(
                f"if CurrentBar = {n} then {name} = Average({src}, {n}) "
                f"else if CurrentBar > {n} then {name} = {alpha} * {src} + (1 - {alpha}) * {name}[1];"
            )
        elif call.fn == "rsi":
            up, dn = f"{name}_up", f"{name}_dn"
            self.decls += [f"{name}(0)", f"{up}(0)", f"{dn}(0)"]
            ch = f"({x} - {x}[1])"
            self.updates += [
                f"if CurrentBar = {n + 1} then begin {up} = Average(MaxList({ch}, 0), {n}); {dn} = Average(MaxList(-{ch}, 0), {n}); end",
                f"else if CurrentBar > {n + 1} then begin {up} = (MaxList({ch}, 0) + ({n} - 1) * {up}[1]) / {n}; {dn} = (MaxList(-{ch}, 0) + ({n} - 1) * {dn}[1]) / {n}; end;",
                f"if {dn} = 0 then {name} = 100 else if {up} = 0 then {name} = 0 else {name} = 100 - 100 / (1 + {up} / {dn});",
            ]
        elif call.fn == "stoch_k":
            self.decls += [f"{name}(0)", f"{name}_ok(false)"]
            self.updates.append(
                f"{name}_ok = Highest(High, {n}) - Lowest(Low, {n}) <> 0; "
                f"if {name}_ok then {name} = 100 * (Close - Lowest(Low, {n})) / (Highest(High, {n}) - Lowest(Low, {n}));"
            )
        elif call.fn == "ibs":
            self.decls += [f"{name}(0)", f"{name}_ok(false)"]
            self.updates.append(f"{name}_ok = High - Low <> 0; if {name}_ok then {name} = (Close - Low) / (High - Low);")

    def r(self, e: Expr) -> str:
        if isinstance(e, Field):
            return _FIELD[e.name]
        if isinstance(e, Const):
            v = e.value
            return str(int(v)) if float(v).is_integer() else repr(float(v))
        if isinstance(e, Calendar):
            return "IsoDow" if e.name == "dayofweek" else "Month(Date)"
        if isinstance(e, Call):
            return self.names[e]
        if isinstance(e, Lag):
            return f"{self.r(e.x)}[{e.n}]"
        if isinstance(e, Bin):
            return f"({self.r(e.a)} {e.op} {self.r(e.b)})"
        if isinstance(e, Cmp):
            op = {"==": "="}.get(e.op, e.op)
            guards = [f"{self.names[n]}_ok" for n in walk(e) if isinstance(n, Call) and n.fn in ("stoch_k", "ibs")]
            core = f"({self.r(e.a)} {op} {self.r(e.b)})"
            return f"({' and '.join(guards + [core])})" if guards else core
        if isinstance(e, Cross):
            a, b = self.r(e.a), self.r(e.b)
            if e.direction == "above":
                return f"({a} > {b} and {a}[1] <= {b}[1])"
            return f"({a} < {b} and {a}[1] >= {b}[1])"
        if isinstance(e, Logic):
            j = " and " if e.op == "and" else " or "
            return "(" + j.join(self.r(a) for a in e.args) + ")"
        if isinstance(e, Not):
            return f"(not {self.r(e.x)})"
        raise TypeError(type(e).__name__)


def export_easylanguage(ctx: ExportContext) -> str:
    s, e = ctx.strategy, ctx.strategy.exits
    long = s.direction == "long"
    el = _EL(ctx.calls())
    atr_call = Call("atr", (), (e.atr_len,))
    if atr_call not in el.names:
        el._declare(atr_call, len(el.names))
    atr_name = el.names[atr_call]
    lines = ["{"] + header_lines(ctx, " ") + [" Set commission and slippage in the strategy's Properties to match the assumptions above.", "}", ""]
    lines.append("Inputs: Qty(%g);" % s.quantity)
    decls = el.decls + ["IsoDow(0)", "EntryCond(false)", "ExitCond(false)", "RefAtr(0)"]
    lines.append("Vars: " + ", ".join(decls) + ";")
    lines.append("")
    lines.append("IsoDow = DayOfWeek(Date); if IsoDow = 0 then IsoDow = 7;")
    lines += el.updates
    lines.append("")
    conds = [el.r(sig.expr()) for sig in s.entry]
    lines.append(f"EntryCond = CurrentBar > {ctx.warmup()} and " + " and ".join(conds) + ";")
    lines.append(f"ExitCond = {el.r(e.exit_signal.expr()) if e.exit_signal else 'false'};")
    lines.append("")
    lines.append("if MarketPosition = 0 and EntryCond then begin")
    lines.append(f"    RefAtr = {atr_name};")
    lines.append(f'    {"Buy" if long else "SellShort"} ("AF") Qty contracts next bar at market;')
    lines.append("end;")
    lines.append("SetStopContract;")
    exit_word = "Sell" if long else "BuyToCover"
    if e.stop_atr:
        lines.append(f"if MarketPosition <> 0 or EntryCond then SetStopLoss({float(e.stop_atr)!r} * RefAtr * BigPointValue);")
    if e.target_atr:
        lines.append(f"if MarketPosition <> 0 or EntryCond then SetProfitTarget({float(e.target_atr)!r} * RefAtr * BigPointValue);")
    if e.trail_atr:
        lines.append(f"if MarketPosition <> 0 or EntryCond then SetDollarTrailing({float(e.trail_atr)!r} * RefAtr * BigPointValue);")
    lines.append("")
    exits = []
    if e.max_bars:
        exits.append(f"BarsSinceEntry >= {int(e.max_bars) - 1}")
    exits.append("ExitCond")
    if e.profitable_close:
        exits.append("Close > EntryPrice" if long else "Close < EntryPrice")
    lines.append(f"if MarketPosition <> 0 and ({' or '.join(exits)}) then")
    lines.append(f'    {exit_word} ("AF exit") next bar at market;')
    return "\n".join(lines) + "\n"
