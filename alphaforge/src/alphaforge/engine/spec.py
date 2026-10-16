"""Strategy and cost specifications (pure data, JSON round-trippable)."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from ..rules.expr import Expr, Logic
from ..rules.library import Signal


@dataclass(frozen=True)
class CostModel:
    """Trading frictions, applied on every fill.

    commission: currency per unit (share/contract) per side.
    slippage_ticks: adverse ticks per side on market and stop fills. Limit
    (profit-target) fills get no slippage but never fill better than the limit
    unless the bar opens through it.
    """

    commission: float = 0.0
    slippage_ticks: float = 0.0

    def to_dict(self):
        return {"commission": self.commission, "slippage_ticks": self.slippage_ticks}

    @staticmethod
    def from_dict(d: dict) -> "CostModel":
        return CostModel(float(d.get("commission", 0.0)), float(d.get("slippage_ticks", 0.0)))


@dataclass(frozen=True)
class ExitSpec:
    """Exit rules. Any that fires closes the trade; the first by time wins.

    stop_atr / target_atr / trail_atr: multiples of ATR(atr_len) measured on the
    signal bar, placed relative to the entry fill price. None disables.
    max_bars: exit at the next open once the trade has been held this many bars.
    exit_signal: exit at the next open when this signal is true at a bar close.
    profitable_close: exit at the next open after the first close in profit.
    """

    stop_atr: float | None = None
    target_atr: float | None = None
    trail_atr: float | None = None
    max_bars: int | None = None
    exit_signal: Signal | None = None
    profitable_close: bool = False
    atr_len: int = 14

    def is_empty(self) -> bool:
        return (
            self.stop_atr is None
            and self.target_atr is None
            and self.trail_atr is None
            and self.max_bars is None
            and self.exit_signal is None
            and not self.profitable_close
        )

    def to_dict(self):
        return {
            "stop_atr": self.stop_atr,
            "target_atr": self.target_atr,
            "trail_atr": self.trail_atr,
            "max_bars": self.max_bars,
            "exit_signal": self.exit_signal.to_dict() if self.exit_signal else None,
            "profitable_close": self.profitable_close,
            "atr_len": self.atr_len,
        }

    @staticmethod
    def from_dict(d: dict) -> "ExitSpec":
        f = lambda key: None if d.get(key) is None else float(d[key])  # noqa: E731
        return ExitSpec(
            stop_atr=f("stop_atr"),
            target_atr=f("target_atr"),
            trail_atr=f("trail_atr"),
            max_bars=None if d.get("max_bars") is None else int(d["max_bars"]),
            exit_signal=Signal.from_dict(d["exit_signal"]) if d.get("exit_signal") else None,
            profitable_close=bool(d.get("profitable_close", False)),
            atr_len=int(d.get("atr_len", 14)),
        )


@dataclass(frozen=True)
class Strategy:
    direction: str  # "long" | "short"
    entry: tuple[Signal, ...]
    exits: ExitSpec
    quantity: float = 1.0
    name: str = ""

    def __post_init__(self):
        if self.direction not in ("long", "short"):
            raise ValueError("direction must be long or short")
        if not self.entry:
            raise ValueError("strategy needs at least one entry signal")
        if self.exits.is_empty():
            raise ValueError("strategy needs at least one exit rule")
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")

    @property
    def sign(self) -> int:
        return 1 if self.direction == "long" else -1

    def entry_expr(self) -> Expr:
        exprs = tuple(s.expr() for s in self.entry)
        return exprs[0] if len(exprs) == 1 else Logic("and", exprs)

    def key(self) -> str:
        """Canonical identity: equal keys mean identical trading rules."""
        sig = " & ".join(sorted(s.label() for s in self.entry))
        return f"{self.direction}|{sig}|{self.exits.to_dict()}|{self.quantity}"

    def describe(self) -> str:
        lines = [f"{self.direction.upper()} when " + " AND ".join(s.label() for s in self.entry)]
        e = self.exits
        if e.stop_atr is not None:
            lines.append(f"stop {e.stop_atr:g} x ATR({e.atr_len})")
        if e.target_atr is not None:
            lines.append(f"target {e.target_atr:g} x ATR({e.atr_len})")
        if e.trail_atr is not None:
            lines.append(f"trailing stop {e.trail_atr:g} x ATR({e.atr_len})")
        if e.max_bars is not None:
            lines.append(f"exit after {e.max_bars} bars")
        if e.exit_signal is not None:
            lines.append(f"exit when {e.exit_signal.label()}")
        if e.profitable_close:
            lines.append("exit on first profitable close")
        return "; ".join(lines)

    def with_(self, **kw) -> "Strategy":
        return replace(self, **kw)

    def to_dict(self):
        return {
            "name": self.name,
            "direction": self.direction,
            "entry": [s.to_dict() for s in self.entry],
            "exits": self.exits.to_dict(),
            "quantity": self.quantity,
        }

    @staticmethod
    def from_dict(d: dict) -> "Strategy":
        return Strategy(
            direction=d["direction"],
            entry=tuple(Signal.from_dict(s) for s in d["entry"]),
            exits=ExitSpec.from_dict(d["exits"]),
            quantity=float(d.get("quantity", 1.0)),
            name=str(d.get("name", "")),
        )


@dataclass(frozen=True)
class BacktestConfig:
    costs: CostModel = field(default_factory=CostModel)
    initial_capital: float = 100_000.0
    oos_fraction: float = 0.3  # last fraction of bars held out for out-of-sample

    def to_dict(self):
        return {"costs": self.costs.to_dict(), "initial_capital": self.initial_capital, "oos_fraction": self.oos_fraction}

    @staticmethod
    def from_dict(d: dict) -> "BacktestConfig":
        return BacktestConfig(
            CostModel.from_dict(d.get("costs", {})),
            float(d.get("initial_capital", 100_000.0)),
            float(d.get("oos_fraction", 0.3)),
        )
