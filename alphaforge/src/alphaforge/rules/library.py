"""Built-in signal library.

A *template* is a parameterised rule family (e.g. "close above SMA(n)"); a
*signal* is a template with concrete parameters. Templates declare their
parameter grids, so the generator can enumerate signals and the robustness
tests can perturb parameters to neighbouring values.

These definitions are our own, written from standard technical-analysis
literature. They are not copied from any vendor's signal list.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Callable

from .expr import C, H, L, O, V, Bin, Calendar, Cmp, Cross, Expr, Logic, call, k, lag

ParamGrid = dict[str, list]


@dataclass(frozen=True)
class Template:
    id: str
    category: str
    description: str
    grid: ParamGrid
    build: Callable[..., Expr]
    # optional constraint on parameter combinations
    valid: Callable[..., bool] = field(default=lambda **_: True)

    def combos(self):
        keys = list(self.grid)
        for values in itertools.product(*(self.grid[k] for k in keys)):
            p = dict(zip(keys, values))
            if self.valid(**p):
                yield p


@dataclass(frozen=True)
class Signal:
    template: str
    params: tuple[tuple[str, object], ...]

    @staticmethod
    def of(template: str, **params) -> "Signal":
        return Signal(template, tuple(sorted(params.items())))

    @property
    def param_dict(self) -> dict:
        return dict(self.params)

    def expr(self) -> Expr:
        return TEMPLATES[self.template].build(**self.param_dict)

    def label(self) -> str:
        return str(self.expr())

    def to_dict(self) -> dict:
        return {"template": self.template, "params": self.param_dict}

    @staticmethod
    def from_dict(d: dict) -> "Signal":
        if d["template"] not in TEMPLATES:
            raise ValueError(f"unknown signal template {d['template']!r}")
        return Signal.of(d["template"], **d["params"])


_PRICE = {"open": O, "high": H, "low": L, "close": C}
_LENGTHS = [5, 10, 20, 50, 100, 200]


def _price_cmp(a: str, i: int, b: str, j: int, op: str) -> Expr:
    return Cmp(op, lag(_PRICE[a], i), lag(_PRICE[b], j))


def _consecutive(direction: str, n: int) -> Expr:
    op = ">" if direction == "up" else "<"
    return Logic("and", tuple(Cmp(op, lag(C, i), lag(C, i + 1)) for i in range(n)))


TEMPLATE_LIST: list[Template] = [
    Template(
        "price_vs_price",
        "price action",
        "Compare one bar's price field with another's within the last 10 bars.",
        {
            "a": ["open", "high", "low", "close"],
            "i": list(range(0, 6)),
            "b": ["open", "high", "low", "close"],
            "j": list(range(1, 10)),
            "op": [">", "<"],
        },
        _price_cmp,
        valid=lambda a, i, b, j, op: j > i and not (op == "<" and a == b),
    ),
    Template(
        "consecutive_closes",
        "price action",
        "N consecutive higher (or lower) closes.",
        {"direction": ["up", "down"], "n": [2, 3, 4, 5]},
        _consecutive,
    ),
    Template(
        "close_vs_sma",
        "trend",
        "Close above or below its simple moving average.",
        {"n": _LENGTHS, "op": [">", "<"]},
        lambda n, op: Cmp(op, C, call("sma", C, n)),
    ),
    Template(
        "sma_vs_sma",
        "trend",
        "Fast SMA above or below slow SMA.",
        {"fast": [5, 10, 20, 50], "slow": [20, 50, 100, 200], "op": [">", "<"]},
        lambda fast, slow, op: Cmp(op, call("sma", C, fast), call("sma", C, slow)),
        valid=lambda fast, slow, op: fast < slow,
    ),
    Template(
        "close_cross_ema",
        "trend",
        "Close crosses above or below its EMA on this bar.",
        {"n": [10, 20, 50], "direction": ["above", "below"]},
        lambda n, direction: Cross(direction, C, call("ema", C, n)),
    ),
    Template(
        "rsi_level",
        "oscillator",
        "RSI below an oversold level or above an overbought level.",
        {"n": [2, 3, 5, 14], "level": [10, 20, 30, 70, 80, 90]},
        lambda n, level: Cmp("<" if level < 50 else ">", call("rsi", C, n), k(level)),
    ),
    Template(
        "stoch_level",
        "oscillator",
        "Raw stochastic %K below 20 or above 80.",
        {"n": [5, 14], "level": [20, 80]},
        lambda n, level: Cmp("<" if level < 50 else ">", call("stoch_k", n), k(level)),
    ),
    Template(
        "ibs_level",
        "price action",
        "Internal bar strength (close position within the bar's range).",
        {"level": [0.2, 0.8]},
        lambda level: Cmp("<" if level < 0.5 else ">", call("ibs"), k(level)),
    ),
    Template(
        "breakout_high",
        "breakout",
        "Close above the highest high of the previous n bars.",
        {"n": [5, 10, 20, 50]},
        lambda n: Cmp(">", C, lag(call("highest", H, n), 1)),
    ),
    Template(
        "breakout_low",
        "breakout",
        "Close below the lowest low of the previous n bars.",
        {"n": [5, 10, 20, 50]},
        lambda n: Cmp("<", C, lag(call("lowest", L, n), 1)),
    ),
    Template(
        "volatility_regime",
        "volatility",
        "Short ATR below (contraction) or above (expansion) long ATR.",
        {"fast": [5, 10], "slow": [20, 50], "op": [">", "<"]},
        lambda fast, slow, op: Cmp(op, call("atr", fast), call("atr", slow)),
    ),
    Template(
        "bollinger_touch",
        "volatility",
        "Close beyond the n-bar Bollinger band (2 population std devs).",
        {"n": [10, 20], "side": ["upper", "lower"]},
        lambda n, side: _bollinger(n, side),
    ),
    Template(
        "momentum",
        "momentum",
        "Rate of change over n bars positive or negative.",
        {"n": [5, 10, 20, 60], "op": [">", "<"]},
        lambda n, op: Cmp(op, call("roc", C, n), k(0)),
    ),
    Template(
        "volume_surge",
        "volume",
        "Volume above or below its n-bar average.",
        {"n": [10, 20], "op": [">", "<"]},
        lambda n, op: Cmp(op, V, call("sma", V, n)),
    ),
    Template(
        "day_of_week",
        "seasonality",
        "Signal bar falls on a given weekday (1 = Monday). Entry fills on the next bar.",
        {"day": [1, 2, 3, 4, 5]},
        lambda day: Cmp("==", Calendar("dayofweek"), k(day)),
    ),
    Template(
        "month_of_year",
        "seasonality",
        "Signal bar falls in a given month.",
        {"month": list(range(1, 13))},
        lambda month: Cmp("==", Calendar("month"), k(month)),
    ),
    Template(
        "up_bar",
        "price action",
        "Close above (or below) open.",
        {"op": [">", "<"]},
        lambda op: Cmp(op, C, O),
    ),
]


def _bollinger(n: int, side: str) -> Expr:
    mid = call("sma", C, n)
    dev = Bin("*", k(2), call("stdev", C, n))
    if side == "upper":
        return Cmp(">", C, Bin("+", mid, dev))
    return Cmp("<", C, Bin("-", mid, dev))


TEMPLATES: dict[str, Template] = {t.id: t for t in TEMPLATE_LIST}


def all_signals(categories: list[str] | None = None) -> list[Signal]:
    out: list[Signal] = []
    seen: set[str] = set()
    for t in TEMPLATE_LIST:
        if categories and t.category not in categories:
            continue
        for p in t.combos():
            s = Signal.of(t.id, **p)
            key = str(s.expr())
            if key in seen:
                continue
            seen.add(key)
            out.append(s)
    return out


def categories() -> list[str]:
    return sorted({t.category for t in TEMPLATE_LIST})
