"""NinjaTrader 8 NinjaScript (C#) exporter.

Indicators are recomputed in the strategy with AlphaForge's definitions
(Series<double> per indicator, NaN during warm-up, IEEE comparisons with NaN
are false), so values do not depend on NinjaTrader's built-in seeding choices.
Orders use Calculate.OnBarClose, so market orders fill at the next bar's open.
Stop and target prices are recalculated from the actual fill in OnExecutionUpdate.
"""

from __future__ import annotations

from ..rules.expr import Bin, Calendar, Call, Cmp, Const, Cross, Expr, Field, Lag, Logic, Not
from .common import ExportContext, header_lines

_FIELD = {"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"}


class _NS:
    def __init__(self, calls):
        self.names: dict[Call, str] = {}
        self.fields: list[str] = []
        self.updates: list[str] = []
        for call in calls:
            self.add(call)

    def add(self, call: Call) -> str:
        if call in self.names:
            return self.names[call]
        name = f"v{len(self.names)}_{call.fn}"
        self.names[call] = name
        n = call.params[0] if call.params else 0
        self.fields.append(name)
        x = self.series(call.args[0]) if call.args else None
        fn = call.fn
        if fn == "sma":
            self.updates.append(f"{name}[0] = CurrentBar >= {n} - 1 ? Mean({x}, {n}) : double.NaN;")
        elif fn == "stdev":
            self.updates.append(f"{name}[0] = CurrentBar >= {n} - 1 ? PopStd({x}, {n}) : double.NaN;")
        elif fn == "highest":
            self.updates.append(f"{name}[0] = CurrentBar >= {n} - 1 ? Extreme({x}, {n}, true) : double.NaN;")
        elif fn == "lowest":
            self.updates.append(f"{name}[0] = CurrentBar >= {n} - 1 ? Extreme({x}, {n}, false) : double.NaN;")
        elif fn == "roc":
            self.updates.append(f"{name}[0] = CurrentBar >= {n} && {x}[{n}] != 0 ? 100.0 * ({x}[0] - {x}[{n}]) / {x}[{n}] : double.NaN;")
        elif fn in ("ema", "atr"):
            src = x if fn == "ema" else "trSeries"
            alpha = f"2.0 / ({n} + 1.0)" if fn == "ema" else f"1.0 / {n}"
            self.updates.append(
                f"{name}[0] = CurrentBar < {n} - 1 ? double.NaN : (CurrentBar == {n} - 1 || double.IsNaN({name}[1])) ? Mean({src}, {n}) : {alpha} * {src}[0] + (1 - {alpha}) * {name}[1];"
            )
        elif fn == "rsi":
            self.fields += [f"{name}_up", f"{name}_dn"]
            self.updates += [
                f"double {name}_ch = CurrentBar > 0 ? {x}[0] - {x}[1] : double.NaN;",
                f"{name}_up[0] = CurrentBar < {n} ? double.NaN : CurrentBar == {n} ? MeanChange({x}, {n}, true) : (Math.Max({name}_ch, 0) + ({n} - 1) * {name}_up[1]) / {n};",
                f"{name}_dn[0] = CurrentBar < {n} ? double.NaN : CurrentBar == {n} ? MeanChange({x}, {n}, false) : (Math.Max(-{name}_ch, 0) + ({n} - 1) * {name}_dn[1]) / {n};",
                f"{name}[0] = double.IsNaN({name}_up[0]) ? double.NaN : {name}_dn[0] == 0 ? 100 : {name}_up[0] == 0 ? 0 : 100 - 100 / (1 + {name}_up[0] / {name}_dn[0]);",
            ]
        elif fn == "stoch_k":
            self.updates.append(
                f"{name}[0] = CurrentBar < {n} - 1 ? double.NaN : (Extreme(High, {n}, true) - Extreme(Low, {n}, false)) == 0 ? double.NaN : 100.0 * (Close[0] - Extreme(Low, {n}, false)) / (Extreme(High, {n}, true) - Extreme(Low, {n}, false));"
            )
        elif fn == "ibs":
            self.updates.append(f"{name}[0] = High[0] - Low[0] == 0 ? double.NaN : (Close[0] - Low[0]) / (High[0] - Low[0]);")
        return name

    def series(self, e: Expr) -> str:
        if isinstance(e, Field):
            return _FIELD[e.name]
        if isinstance(e, Call):
            return self.add(e)
        raise TypeError("indicator inputs must be price fields or indicators")

    def r(self, e: Expr, k: int = 0) -> str:
        if isinstance(e, Field):
            return f"{_FIELD[e.name]}[{k}]"
        if isinstance(e, Const):
            return repr(float(e.value))
        if isinstance(e, Calendar):
            if e.name == "dayofweek":
                return f"IsoDow(Time[{k}])"
            return f"(double)Time[{k}].Month"
        if isinstance(e, Call):
            return f"{self.names[e]}[{k}]"
        if isinstance(e, Lag):
            return self.r(e.x, k + e.n)
        if isinstance(e, Bin):
            if e.op == "/":
                return f"SafeDiv({self.r(e.a, k)}, {self.r(e.b, k)})"
            return f"({self.r(e.a, k)} {e.op} {self.r(e.b, k)})"
        if isinstance(e, Cmp):
            return f"({self.r(e.a, k)} {e.op} {self.r(e.b, k)})"
        if isinstance(e, Cross):
            a0, b0, a1, b1 = self.r(e.a, k), self.r(e.b, k), self.r(e.a, k + 1), self.r(e.b, k + 1)
            if e.direction == "above":
                return f"({a0} > {b0} && {a1} <= {b1})"
            return f"({a0} < {b0} && {a1} >= {b1})"
        if isinstance(e, Logic):
            j = " && " if e.op == "and" else " || "
            return "(" + j.join(self.r(a, k) for a in e.args) + ")"
        if isinstance(e, Not):
            return f"(!{self.r(e.x, k)})"
        raise TypeError(type(e).__name__)


def export_ninjascript(ctx: ExportContext) -> str:
    s, e = ctx.strategy, ctx.strategy.exits
    long = s.direction == "long"
    ns = _NS(ctx.calls())
    atr_name = ns.add(Call("atr", (), (e.atr_len,)))
    entry = " && ".join(ns.r(sig.expr()) for sig in s.entry)
    exit_c = ns.r(e.exit_signal.expr()) if e.exit_signal else "false"
    d = 1 if long else -1
    out = ["// " + x.lstrip("# ") for x in header_lines(ctx, "")]
    out += [
        "#region Using declarations",
        "using System;",
        "using NinjaTrader.Cbi;",
        "using NinjaTrader.NinjaScript;",
        "using NinjaTrader.NinjaScript.Strategies;",
        "#endregion",
        "",
        "namespace NinjaTrader.NinjaScript.Strategies",
        "{",
        f"    public class {ctx.name} : Strategy",
        "    {",
        "        private Series<double> trSeries;",
    ]
    out += [f"        private Series<double> {f};" for f in ns.fields]
    out += [
        "        private double refAtr = double.NaN, stopPx = double.NaN, targetPx = double.NaN, trailPx = double.NaN, extreme = double.NaN;",
        f"        private const int Dir = {d};",
        "",
        "        protected override void OnStateChange()",
        "        {",
        "            if (State == State.SetDefaults)",
        "            {",
        f'                Name = "{ctx.name}";',
        "                Calculate = Calculate.OnBarClose;",
        "                EntriesPerDirection = 1;",
        f"                BarsRequiredToTrade = {ctx.warmup()};",
        f"                Qty = {int(s.quantity) if float(s.quantity).is_integer() else s.quantity};",
        f"                Slippage = {ctx.config.costs.slippage_ticks:g};",
        "            }",
        "            else if (State == State.DataLoaded)",
        "            {",
        "                trSeries = new Series<double>(this, MaximumBarsLookBack.Infinite);",
    ]
    out += [f"                {f} = new Series<double>(this, MaximumBarsLookBack.Infinite);" for f in ns.fields]
    out += [
        "            }",
        "        }",
        "",
        "        [NinjaScriptProperty] public int Qty { get; set; }",
        "",
        "        protected override void OnBarUpdate()",
        "        {",
        "            trSeries[0] = CurrentBar == 0 ? High[0] - Low[0] : Math.Max(High[0] - Low[0], Math.Max(Math.Abs(High[0] - Close[1]), Math.Abs(Low[0] - Close[1])));",
    ]
    out += [f"            {u}" for u in ns.updates]
    out += [
        "            if (CurrentBar < BarsRequiredToTrade) return;",
        f"            bool entryCond = {entry};",
        f"            bool exitCond = {exit_c};",
        "            if (Position.MarketPosition != MarketPosition.Flat)",
        "            {",
    ]
    if e.trail_atr:
        out += [
            "                extreme = Dir == 1 ? Math.Max(extreme, High[0]) : Math.Min(extreme, Low[0]);",
            f"                double cand = extreme - Dir * {float(e.trail_atr)!r} * refAtr;",
            "                if (double.IsNaN(trailPx) || Dir * (cand - trailPx) > 0) { trailPx = cand; ApplyStops(); }",
        ]
    conds = []
    if e.max_bars:
        conds.append(f"BarsSinceEntryExecution() + 1 >= {int(e.max_bars)}")
    conds.append("exitCond")
    if e.profitable_close:
        conds.append("Dir * (Close[0] - Position.AveragePrice) > 0")
    exit_call = 'ExitLong("AF exit", "AF")' if long else 'ExitShort("AF exit", "AF")'
    out += [
        f"                if ({' || '.join(conds)}) {exit_call};",
        "                return;",
        "            }",
        f"            if (entryCond && !double.IsNaN({atr_name}[0]))",
        "            {",
        f"                refAtr = {atr_name}[0];",
        "                trailPx = double.NaN;",
        f'                {"EnterLong" if long else "EnterShort"}(Qty, "AF");',
        "            }",
        "        }",
        "",
        "        protected override void OnExecutionUpdate(Execution execution, string executionId, double price, int quantity, MarketPosition marketPosition, string orderId, DateTime time)",
        "        {",
        '            if (execution.Order.Name != "AF" || execution.Order.OrderState != OrderState.Filled) return;',
        f"            stopPx = {f'price - Dir * {float(e.stop_atr)!r} * refAtr' if e.stop_atr else 'double.NaN'};",
        f"            targetPx = {f'price + Dir * {float(e.target_atr)!r} * refAtr' if e.target_atr else 'double.NaN'};",
        f"            trailPx = {f'price - Dir * {float(e.trail_atr)!r} * refAtr' if e.trail_atr else 'double.NaN'};",
        "            extreme = price;",
        "            ApplyStops();",
        "        }",
        "",
        "        private void ApplyStops()",
        "        {",
        "            double prot = stopPx;",
        "            if (!double.IsNaN(trailPx) && (double.IsNaN(prot) || Dir * (trailPx - prot) > 0)) prot = trailPx;",
        '            if (!double.IsNaN(prot)) ExitStopMarket(0, true, Qty, prot, "AF stop", "AF");'.replace(
            "ExitStopMarket", "ExitLongStopMarket" if long else "ExitShortStopMarket"
        ),
        '            if (!double.IsNaN(targetPx)) ExitLimit(0, true, Qty, targetPx, "AF target", "AF");'.replace(
            "ExitLimit", "ExitLongLimit" if long else "ExitShortLimit"
        ),
        "        }",
        "",
        "        private static double Mean(ISeries<double> s, int n) { double t = 0; for (int i = 0; i < n; i++) t += s[i]; return t / n; }",
        "        private static double PopStd(ISeries<double> s, int n) { double m = Mean(s, n), t = 0; for (int i = 0; i < n; i++) t += (s[i] - m) * (s[i] - m); return Math.Sqrt(t / n); }",
        "        private static double Extreme(ISeries<double> s, int n, bool max) { double r = s[0]; for (int i = 1; i < n; i++) r = max ? Math.Max(r, s[i]) : Math.Min(r, s[i]); return r; }",
        "        private static double MeanChange(ISeries<double> s, int n, bool up) { double t = 0; for (int i = 0; i < n; i++) { double ch = s[i] - s[i + 1]; t += up ? Math.Max(ch, 0) : Math.Max(-ch, 0); } return t / n; }",
        "        private static double SafeDiv(double a, double b) { return b == 0 ? double.NaN : a / b; }",
        "        private static double IsoDow(DateTime t) { int d = (int)t.DayOfWeek; return d == 0 ? 7 : d; }",
        "    }",
        "}",
    ]
    return "\n".join(out) + "\n"
