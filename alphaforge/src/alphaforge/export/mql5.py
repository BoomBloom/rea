"""MetaTrader 5 (MQL5) Expert Advisor exporter.

On each new bar the EA copies recent history, recomputes AlphaForge's indicator
definitions over it (NaN during warm-up; comparisons guarded with
MathIsValidNumber) and evaluates the rules on the last *closed* bar. Market
orders therefore fill at the new bar's open. Stop and target are attached from
the fill price. Commission and spread/slippage are determined by the broker;
compare them with the backtest assumptions in the header.
"""

from __future__ import annotations

from ..rules.expr import Bin, Calendar, Call, Cmp, Const, Cross, Expr, Field, Lag, Logic, Not
from .common import ExportContext, header_lines

_FIELD = {"open": "o", "high": "h", "low": "l", "close": "c", "volume": "v"}


class _MQ:
    def __init__(self, calls):
        self.names: dict[Call, str] = {}
        self.compute: list[str] = []
        for call in calls:
            self.add(call)

    def add(self, call: Call) -> str:
        if call in self.names:
            return self.names[call]
        name = f"v{len(self.names)}_{call.fn}"
        self.names[call] = name
        n = call.params[0] if call.params else 0
        src = self.arr(call.args[0]) if call.args else None
        fn = call.fn
        if fn in ("sma", "ema", "stdev", "highest", "lowest", "roc", "rsi"):
            self.compute.append(f"AF_{fn.upper()}({src}, {n}, {name});")
        elif fn == "atr":
            self.compute.append(f"AF_ATR(h, l, c, {n}, {name});")
        elif fn == "stoch_k":
            self.compute.append(f"AF_STOCHK(h, l, c, {n}, {name});")
        elif fn == "ibs":
            self.compute.append(f"AF_IBS(h, l, c, {name});")
        return name

    def arr(self, e: Expr) -> str:
        if isinstance(e, Field):
            return _FIELD[e.name]
        if isinstance(e, Call):
            return self.add(e)
        raise TypeError("indicator inputs must be price fields or indicators")

    def r(self, e: Expr, k: str = "i") -> str:
        if isinstance(e, Field):
            return f"{_FIELD[e.name]}[{k}]"
        if isinstance(e, Const):
            return repr(float(e.value))
        if isinstance(e, Calendar):
            return f"AF_Iso_Dow(t[{k}])" if e.name == "dayofweek" else f"AF_Month(t[{k}])"
        if isinstance(e, Call):
            return f"{self.names[e]}[{k}]"
        if isinstance(e, Lag):
            return self.r(e.x, f"{k}-{e.n}")
        if isinstance(e, Bin):
            if e.op == "/":
                return f"AF_Div({self.r(e.a, k)}, {self.r(e.b, k)})"
            return f"({self.r(e.a, k)} {e.op} {self.r(e.b, k)})"
        if isinstance(e, Cmp):
            a, b = self.r(e.a, k), self.r(e.b, k)
            return f"AF_Cmp({a}, {b}, \"{e.op}\")"
        if isinstance(e, Cross):
            a0, b0 = self.r(e.a, k), self.r(e.b, k)
            a1, b1 = self.r(e.a, f"{k}-1"), self.r(e.b, f"{k}-1")
            if e.direction == "above":
                return f"(AF_Cmp({a0}, {b0}, \">\") && AF_Cmp({a1}, {b1}, \"<=\"))"
            return f"(AF_Cmp({a0}, {b0}, \"<\") && AF_Cmp({a1}, {b1}, \">=\"))"
        if isinstance(e, Logic):
            j = " && " if e.op == "and" else " || "
            return "(" + j.join(self.r(a, k) for a in e.args) + ")"
        if isinstance(e, Not):
            return f"(!{self.r(e.x, k)})"
        raise TypeError(type(e).__name__)


_HELPERS = r"""
bool AF_Valid(double x) { return MathIsValidNumber(x); }
bool AF_Cmp(double a, double b, string op)
{
   if(!AF_Valid(a) || !AF_Valid(b)) return false;
   if(op == ">") return a > b;
   if(op == "<") return a < b;
   if(op == ">=") return a >= b;
   if(op == "<=") return a <= b;
   return a == b;
}
double AF_Div(double a, double b) { return b == 0.0 ? AF_NAN : a / b; }
double AF_Iso_Dow(datetime t) { MqlDateTime s; TimeToStruct(t, s); return s.day_of_week == 0 ? 7.0 : (double)s.day_of_week; }
double AF_Month(datetime t) { MqlDateTime s; TimeToStruct(t, s); return (double)s.mon; }
void AF_Init(int n, double &out[]) { ArrayResize(out, n); ArrayInitialize(out, AF_NAN); }
void AF_SMA(const double &x[], int p, double &out[])
{
   int n = ArraySize(x); AF_Init(n, out);
   for(int i = p - 1; i < n; i++) { double s = 0; for(int j = 0; j < p; j++) s += x[i - j]; out[i] = s / p; }
}
void AF_STDEV(const double &x[], int p, double &out[])
{
   int n = ArraySize(x); AF_Init(n, out);
   for(int i = p - 1; i < n; i++) { double m = 0; for(int j = 0; j < p; j++) m += x[i - j]; m /= p;
      double s = 0; for(int j = 0; j < p; j++) s += (x[i - j] - m) * (x[i - j] - m); out[i] = MathSqrt(s / p); }
}
void AF_HIGHEST(const double &x[], int p, double &out[])
{
   int n = ArraySize(x); AF_Init(n, out);
   for(int i = p - 1; i < n; i++) { double r = x[i]; for(int j = 1; j < p; j++) r = MathMax(r, x[i - j]); out[i] = r; }
}
void AF_LOWEST(const double &x[], int p, double &out[])
{
   int n = ArraySize(x); AF_Init(n, out);
   for(int i = p - 1; i < n; i++) { double r = x[i]; for(int j = 1; j < p; j++) r = MathMin(r, x[i - j]); out[i] = r; }
}
void AF_ROC(const double &x[], int p, double &out[])
{
   int n = ArraySize(x); AF_Init(n, out);
   for(int i = p; i < n; i++) out[i] = x[i - p] == 0 ? AF_NAN : 100.0 * (x[i] - x[i - p]) / x[i - p];
}
void AF_SEEDED(const double &x[], int p, double alpha, double &out[])
{
   int n = ArraySize(x); AF_Init(n, out);
   int run = 0, start = -1;
   for(int i = 0; i < n; i++) { run = AF_Valid(x[i]) ? run + 1 : 0; if(run == p) { start = i; break; } }
   if(start < 0) return;
   double s = 0; for(int j = start - p + 1; j <= start; j++) s += x[j];
   double prev = s / p; out[start] = prev;
   for(int i = start + 1; i < n; i++) { if(AF_Valid(x[i])) prev = alpha * x[i] + (1 - alpha) * prev; out[i] = prev; }
}
void AF_EMA(const double &x[], int p, double &out[]) { AF_SEEDED(x, p, 2.0 / (p + 1.0), out); }
void AF_RSI(const double &x[], int p, double &out[])
{
   int n = ArraySize(x); double up[], dn[], ru[], rd[]; AF_Init(n, up); AF_Init(n, dn);
   for(int i = 1; i < n; i++) { double ch = x[i] - x[i - 1]; up[i] = MathMax(ch, 0); dn[i] = MathMax(-ch, 0); }
   AF_SEEDED(up, p, 1.0 / p, ru); AF_SEEDED(dn, p, 1.0 / p, rd); AF_Init(n, out);
   for(int i = 0; i < n; i++) { if(!AF_Valid(ru[i]) || !AF_Valid(rd[i])) continue;
      out[i] = rd[i] == 0 ? 100.0 : (ru[i] == 0 ? 0.0 : 100.0 - 100.0 / (1.0 + ru[i] / rd[i])); }
}
void AF_ATR(const double &h[], const double &l[], const double &c[], int p, double &out[])
{
   int n = ArraySize(c); double tr[]; ArrayResize(tr, n);
   for(int i = 0; i < n; i++) tr[i] = i == 0 ? h[i] - l[i] : MathMax(h[i] - l[i], MathMax(MathAbs(h[i] - c[i - 1]), MathAbs(l[i] - c[i - 1])));
   AF_SEEDED(tr, p, 1.0 / p, out);
}
void AF_STOCHK(const double &h[], const double &l[], const double &c[], int p, double &out[])
{
   double hh[], ll[]; AF_HIGHEST(h, p, hh); AF_LOWEST(l, p, ll); int n = ArraySize(c); AF_Init(n, out);
   for(int i = 0; i < n; i++) { double r = hh[i] - ll[i]; if(AF_Valid(r) && r != 0) out[i] = 100.0 * (c[i] - ll[i]) / r; }
}
void AF_IBS(const double &h[], const double &l[], const double &c[], double &out[])
{
   int n = ArraySize(c); AF_Init(n, out);
   for(int i = 0; i < n; i++) { double r = h[i] - l[i]; if(r != 0) out[i] = (c[i] - l[i]) / r; }
}
"""


def export_mql5(ctx: ExportContext) -> str:
    s, e = ctx.strategy, ctx.strategy.exits
    long = s.direction == "long"
    mq = _MQ(ctx.calls())
    atr_name = mq.add(Call("atr", (), (e.atr_len,)))
    names = list(mq.names.values())
    entry = " && ".join(mq.r(sig.expr()) for sig in s.entry)
    exit_c = mq.r(e.exit_signal.expr()) if e.exit_signal else "false"
    history = max(ctx.warmup() * 3, 500)
    out = header_lines(ctx, "//")
    out += [
        "#property strict",
        "#include <Trade/Trade.mqh>",
        "",
        f"input double InpLots = {s.quantity:g};",
        "input ulong  InpMagic = 20261016;",
        f"#define AF_HISTORY {history}",
        f"#define AF_DIR {1 if long else -1}",
        "const double AF_NAN = MathLog(-1.0);",
        "CTrade trade;",
        "datetime lastBar = 0;",
        "double refAtr = 0, trailPx = 0, extreme = 0;",
        _HELPERS,
        "int OnInit() { trade.SetExpertMagicNumber(InpMagic); return INIT_SUCCEEDED; }",
        "",
        "bool HasPosition()",
        "{",
        "   if(!PositionSelect(_Symbol)) return false;",
        "   return PositionGetInteger(POSITION_MAGIC) == (long)InpMagic;",
        "}",
        "",
        "void OnTick()",
        "{",
        "   datetime cur = iTime(_Symbol, _Period, 0);",
        "   if(cur == lastBar) return;",
        "   lastBar = cur;",
        "   MqlRates r[];",
        "   int n = CopyRates(_Symbol, _Period, 0, AF_HISTORY, r);  // oldest first; r[n-1] is the forming bar",
        f"   if(n < {ctx.warmup() + 2}) return;",
        "   int m = n - 1;  // closed bars only",
        "   double o[], h[], l[], c[], v[]; datetime t[];",
        "   ArrayResize(o, m); ArrayResize(h, m); ArrayResize(l, m); ArrayResize(c, m); ArrayResize(v, m); ArrayResize(t, m);",
        "   for(int k = 0; k < m; k++) { o[k] = r[k].open; h[k] = r[k].high; l[k] = r[k].low; c[k] = r[k].close; v[k] = (double)r[k].tick_volume; t[k] = r[k].time; }",
        "   double " + ", ".join(f"{x}[]" for x in names) + ";",
    ]
    out += [f"   {line}" for line in mq.compute]
    out += [
        "   int i = m - 1;  // last closed bar",
        f"   bool entryCond = {entry};",
        f"   bool exitCond = {exit_c};",
        "   if(HasPosition())",
        "   {",
        "      double openPx = PositionGetDouble(POSITION_PRICE_OPEN);",
        "      int barsIn = iBarShift(_Symbol, _Period, (datetime)PositionGetInteger(POSITION_TIME)) ;  // bars since entry bar, entry bar = 1 at its close",
    ]
    if e.trail_atr:
        out += [
            "      extreme = AF_DIR == 1 ? MathMax(extreme, h[i]) : MathMin(extreme, l[i]);",
            f"      double cand = extreme - AF_DIR * {float(e.trail_atr)!r} * refAtr;",
            "      if(AF_DIR * (cand - trailPx) > 0) { trailPx = cand; double sl = PositionGetDouble(POSITION_SL);",
            "         if(sl == 0 || AF_DIR * (trailPx - sl) > 0) trade.PositionModify(_Symbol, NormalizeDouble(trailPx, _Digits), PositionGetDouble(POSITION_TP)); }",
        ]
    conds = []
    if e.max_bars:
        conds.append(f"barsIn >= {int(e.max_bars)}")
    conds.append("exitCond")
    if e.profitable_close:
        conds.append("AF_DIR * (c[i] - openPx) > 0")
    out += [
        f"      if({' || '.join(conds)}) trade.PositionClose(_Symbol);",
        "      return;",
        "   }",
        f"   if(entryCond && AF_Valid({atr_name}[i]))",
        "   {",
        f"      refAtr = {atr_name}[i];",
        "      double px = AF_DIR == 1 ? SymbolInfoDouble(_Symbol, SYMBOL_ASK) : SymbolInfoDouble(_Symbol, SYMBOL_BID);",
        f"      double sl = {f'NormalizeDouble(px - AF_DIR * {float(e.stop_atr)!r} * refAtr, _Digits)' if e.stop_atr else '0'};",
        f"      double tp = {f'NormalizeDouble(px + AF_DIR * {float(e.target_atr)!r} * refAtr, _Digits)' if e.target_atr else '0'};",
    ]
    if e.trail_atr:
        out += [
            f"      trailPx = px - AF_DIR * {float(e.trail_atr)!r} * refAtr; extreme = px;",
            "      if(sl == 0 || AF_DIR * (trailPx - sl) > 0) sl = NormalizeDouble(trailPx, _Digits);",
        ]
    out += [
        f'      {"trade.Buy" if long else "trade.Sell"}(InpLots, _Symbol, 0, sl, tp, "AlphaForge");',
        "   }",
        "}",
    ]
    return "\n".join(out) + "\n"
