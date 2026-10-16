"""OHLCV bar container shared by every layer.

Bars are stored as contiguous float64 numpy arrays so the simulation kernel and
indicator code can use them without copies. Timestamps are UTC nanoseconds
(int64); the original timezone label is kept for display only.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class InstrumentSpec:
    """Contract facts needed to turn price moves into money.

    point_value: currency per 1.0 price move per unit (e.g. 50 for ES futures,
    1 for stocks). tick_size: minimum price increment, used for slippage in ticks.
    """

    symbol: str = "UNKNOWN"
    point_value: float = 1.0
    tick_size: float = 0.01

    def to_dict(self) -> dict:
        return {"symbol": self.symbol, "point_value": self.point_value, "tick_size": self.tick_size}

    @staticmethod
    def from_dict(d: dict) -> "InstrumentSpec":
        return InstrumentSpec(
            symbol=str(d.get("symbol", "UNKNOWN")),
            point_value=float(d.get("point_value", 1.0)),
            tick_size=float(d.get("tick_size", 0.01)),
        )


@dataclass(frozen=True)
class Bars:
    time: np.ndarray  # int64 UTC nanoseconds, strictly increasing
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    instrument: InstrumentSpec = field(default_factory=InstrumentSpec)
    timezone: str = "UTC"

    def __post_init__(self) -> None:
        n = len(self.time)
        for name in ("open", "high", "low", "close", "volume"):
            arr = getattr(self, name)
            if len(arr) != n:
                raise ValueError(f"{name} has length {len(arr)}, expected {n}")

    def __len__(self) -> int:
        return len(self.time)

    def slice(self, start: int, stop: int) -> "Bars":
        return Bars(
            self.time[start:stop],
            self.open[start:stop],
            self.high[start:stop],
            self.low[start:stop],
            self.close[start:stop],
            self.volume[start:stop],
            self.instrument,
            self.timezone,
        )

    def with_prices(self, open_, high, low, close) -> "Bars":
        return Bars(self.time, open_, high, low, close, self.volume, self.instrument, self.timezone)

    def datetime_index(self) -> pd.DatetimeIndex:
        idx = pd.to_datetime(self.time, utc=True)
        if self.timezone and self.timezone != "UTC":
            idx = idx.tz_convert(self.timezone)
        return idx

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "open": self.open,
                "high": self.high,
                "low": self.low,
                "close": self.close,
                "volume": self.volume,
            },
            index=self.datetime_index(),
        )

    @staticmethod
    def from_frame(df: pd.DataFrame, instrument: InstrumentSpec | None = None) -> "Bars":
        """Build Bars from a DataFrame indexed by timestamps with OHLC(V) columns."""
        idx = pd.DatetimeIndex(df.index)
        tz = "UTC"
        if idx.tz is None:
            idx = idx.tz_localize("UTC")
        else:
            tz = str(idx.tz)
            idx = idx.tz_convert("UTC")
        vol = df["volume"] if "volume" in df.columns else pd.Series(0.0, index=df.index)
        return Bars(
            time=idx.as_unit("ns").asi8.astype(np.int64).copy(),
            open=np.ascontiguousarray(df["open"].to_numpy(dtype=np.float64)),
            high=np.ascontiguousarray(df["high"].to_numpy(dtype=np.float64)),
            low=np.ascontiguousarray(df["low"].to_numpy(dtype=np.float64)),
            close=np.ascontiguousarray(df["close"].to_numpy(dtype=np.float64)),
            volume=np.ascontiguousarray(vol.to_numpy(dtype=np.float64)),
            instrument=instrument or InstrumentSpec(),
            timezone=tz,
        )
