"""A small, typed rule language (intermediate representation).

Strategies are expressions over bar data. One IR feeds three consumers that must
agree: the numpy evaluator used by the backtester, the code exporters, and the
human-readable display. Keeping one representation is what lets exported code
match backtest semantics by construction (and lets tests check it).

Value semantics: an expression evaluated at bar t only uses data at bars <= t.
NaN propagates through arithmetic; comparisons with NaN are False.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union

FIELDS = ("open", "high", "low", "close", "volume")
# fn -> (number of series args, number of int params). OHLC-implicit fns take no series.
FUNCTIONS: dict[str, tuple[int, int]] = {
    "sma": (1, 1),
    "ema": (1, 1),
    "rsi": (1, 1),
    "stdev": (1, 1),
    "highest": (1, 1),
    "lowest": (1, 1),
    "roc": (1, 1),
    "atr": (0, 1),
    "stoch_k": (0, 1),
    "ibs": (0, 0),
}
ARITH = ("+", "-", "*", "/")
COMPARE = (">", "<", ">=", "<=", "==")
CALENDAR = ("dayofweek", "month")  # dayofweek: ISO, Monday=1 .. Sunday=7


class Expr:
    """Base class. Subclasses are frozen dataclasses so expressions hash and compare."""

    def to_dict(self) -> dict:  # pragma: no cover - overridden
        raise NotImplementedError

    def __str__(self) -> str:  # pragma: no cover - overridden
        raise NotImplementedError


@dataclass(frozen=True)
class Field(Expr):
    name: str

    def __post_init__(self):
        if self.name not in FIELDS:
            raise ValueError(f"unknown field {self.name}")

    def to_dict(self):
        return {"t": "field", "name": self.name}

    def __str__(self):
        return self.name


@dataclass(frozen=True)
class Const(Expr):
    value: float

    def to_dict(self):
        return {"t": "const", "value": self.value}

    def __str__(self):
        v = self.value
        return str(int(v)) if float(v).is_integer() else repr(float(v))


@dataclass(frozen=True)
class Lag(Expr):
    x: Expr
    n: int

    def __post_init__(self):
        if self.n < 0:
            raise ValueError("lag must be >= 0 (negative lag would look ahead)")

    def to_dict(self):
        return {"t": "lag", "x": self.x.to_dict(), "n": self.n}

    def __str__(self):
        inner = str(self.x)
        if not isinstance(self.x, (Field, Call, Calendar)):
            inner = f"({inner})"
        return f"{inner}[{self.n}]"


@dataclass(frozen=True)
class Call(Expr):
    fn: str
    args: tuple[Expr, ...]
    params: tuple[int, ...]

    def __post_init__(self):
        if self.fn not in FUNCTIONS:
            raise ValueError(f"unknown function {self.fn}")
        na, np_ = FUNCTIONS[self.fn]
        if len(self.args) != na or len(self.params) != np_:
            raise ValueError(f"{self.fn} expects {na} series and {np_} params")
        if any(int(p) < 1 for p in self.params):
            raise ValueError(f"{self.fn} length must be >= 1")

    def to_dict(self):
        return {"t": "call", "fn": self.fn, "args": [a.to_dict() for a in self.args], "params": list(self.params)}

    def __str__(self):
        parts = [str(a) for a in self.args] + [str(p) for p in self.params]
        return f"{self.fn}({', '.join(parts)})"


@dataclass(frozen=True)
class Bin(Expr):
    op: str
    a: Expr
    b: Expr

    def __post_init__(self):
        if self.op not in ARITH:
            raise ValueError(f"unknown arithmetic op {self.op}")

    def to_dict(self):
        return {"t": "bin", "op": self.op, "a": self.a.to_dict(), "b": self.b.to_dict()}

    def __str__(self):
        return f"({self.a} {self.op} {self.b})"


@dataclass(frozen=True)
class Cmp(Expr):
    op: str
    a: Expr
    b: Expr

    def __post_init__(self):
        if self.op not in COMPARE:
            raise ValueError(f"unknown comparison {self.op}")

    def to_dict(self):
        return {"t": "cmp", "op": self.op, "a": self.a.to_dict(), "b": self.b.to_dict()}

    def __str__(self):
        return f"{self.a} {self.op} {self.b}"


@dataclass(frozen=True)
class Cross(Expr):
    """above: a > b and a[1] <= b[1]; below: a < b and a[1] >= b[1]."""

    direction: str
    a: Expr
    b: Expr

    def __post_init__(self):
        if self.direction not in ("above", "below"):
            raise ValueError("cross direction must be above or below")

    def to_dict(self):
        return {"t": "cross", "direction": self.direction, "a": self.a.to_dict(), "b": self.b.to_dict()}

    def __str__(self):
        return f"{self.a} crosses {self.direction} {self.b}"


@dataclass(frozen=True)
class Logic(Expr):
    op: str  # and | or
    args: tuple[Expr, ...]

    def __post_init__(self):
        if self.op not in ("and", "or") or len(self.args) < 1:
            raise ValueError("logic needs op and/or and at least one arg")

    def to_dict(self):
        return {"t": "logic", "op": self.op, "args": [a.to_dict() for a in self.args]}

    def __str__(self):
        if len(self.args) == 1:
            return str(self.args[0])
        return "(" + f" {self.op} ".join(str(a) for a in self.args) + ")"


@dataclass(frozen=True)
class Not(Expr):
    x: Expr

    def to_dict(self):
        return {"t": "not", "x": self.x.to_dict()}

    def __str__(self):
        return f"not ({self.x})"


@dataclass(frozen=True)
class Calendar(Expr):
    name: str

    def __post_init__(self):
        if self.name not in CALENDAR:
            raise ValueError(f"unknown calendar field {self.name}")

    def to_dict(self):
        return {"t": "calendar", "name": self.name}

    def __str__(self):
        return self.name


ExprT = Union[Field, Const, Lag, Call, Bin, Cmp, Cross, Logic, Not, Calendar]


def from_dict(d: dict) -> Expr:
    t = d["t"]
    if t == "field":
        return Field(d["name"])
    if t == "const":
        return Const(float(d["value"]))
    if t == "lag":
        return Lag(from_dict(d["x"]), int(d["n"]))
    if t == "call":
        return Call(d["fn"], tuple(from_dict(a) for a in d["args"]), tuple(int(p) for p in d["params"]))
    if t == "bin":
        return Bin(d["op"], from_dict(d["a"]), from_dict(d["b"]))
    if t == "cmp":
        return Cmp(d["op"], from_dict(d["a"]), from_dict(d["b"]))
    if t == "cross":
        return Cross(d["direction"], from_dict(d["a"]), from_dict(d["b"]))
    if t == "logic":
        return Logic(d["op"], tuple(from_dict(a) for a in d["args"]))
    if t == "not":
        return Not(from_dict(d["x"]))
    if t == "calendar":
        return Calendar(d["name"])
    raise ValueError(f"unknown expression type {t!r}")


def walk(e: Expr):
    """Yield every node depth-first (parents before children)."""
    yield e
    if isinstance(e, Lag):
        yield from walk(e.x)
    elif isinstance(e, Call):
        for a in e.args:
            yield from walk(a)
    elif isinstance(e, (Bin, Cmp, Cross)):
        yield from walk(e.a)
        yield from walk(e.b)
    elif isinstance(e, Logic):
        for a in e.args:
            yield from walk(a)
    elif isinstance(e, Not):
        yield from walk(e.x)


def max_lookback(e: Expr) -> int:
    """Conservative number of prior bars an expression needs (for warm-up)."""
    if isinstance(e, (Field, Const, Calendar)):
        return 0
    if isinstance(e, Lag):
        return e.n + max_lookback(e.x)
    if isinstance(e, Call):
        p = e.params[0] if e.params else 1
        mult = 4 if e.fn in ("ema", "rsi", "atr") else 1  # recursive filters need settling
        inner = max((max_lookback(a) for a in e.args), default=0)
        return inner + p * mult + 1
    if isinstance(e, (Bin, Cmp)):
        return max(max_lookback(e.a), max_lookback(e.b))
    if isinstance(e, Cross):
        return max(max_lookback(e.a), max_lookback(e.b)) + 1
    if isinstance(e, Logic):
        return max(max_lookback(a) for a in e.args)
    if isinstance(e, Not):
        return max_lookback(e.x)
    return 0


# Convenience constructors used by the signal library and tests
O, H, L, C, V = (Field(f) for f in FIELDS)


def call(fn: str, *args) -> Call:
    series = tuple(a for a in args if isinstance(a, Expr))
    params = tuple(int(a) for a in args if not isinstance(a, Expr))
    return Call(fn, series, params)


def lag(x: Expr, n: int) -> Expr:
    return x if n == 0 else Lag(x, n)


def k(v: float) -> Const:
    return Const(float(v))
