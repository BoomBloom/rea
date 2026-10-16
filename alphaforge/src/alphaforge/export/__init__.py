"""Code exporters. Only the Python export is executed and verified in our test
suite; the platform exports are checked structurally and must be verified on
their platforms before use (see docs/export.md)."""

from __future__ import annotations

from ..data.bars import InstrumentSpec
from ..engine.spec import BacktestConfig, Strategy
from .common import ExportContext
from .easylanguage import export_easylanguage
from .mql5 import export_mql5
from .ninjascript import export_ninjascript
from .pine import export_pine
from .python_export import export_python

TARGETS = {
    "python": ("Python (pandas)", "py", export_python),
    "pine": ("TradingView Pine Script v5", "pine", export_pine),
    "easylanguage": ("TradeStation EasyLanguage / MultiCharts PowerLanguage", "el", export_easylanguage),
    "ninjascript": ("NinjaTrader 8 NinjaScript (C#)", "cs", export_ninjascript),
    "mql5": ("MetaTrader 5 MQL5", "mq5", export_mql5),
}


def export(strategy: Strategy, target: str, config: BacktestConfig | None = None, instrument: InstrumentSpec | None = None) -> str:
    if target not in TARGETS:
        raise ValueError(f"unknown export target {target!r}; choose from {sorted(TARGETS)}")
    inst = instrument or InstrumentSpec()
    ctx = ExportContext(strategy, config or BacktestConfig(), inst.tick_size, inst.point_value, inst.symbol)
    return TARGETS[target][2](ctx)


__all__ = ["TARGETS", "export"]
