"""CSV/TXT market data import with validation.

Accepts the common layouts exported by TradeStation, NinjaTrader, MetaTrader,
Yahoo Finance and generic tools: a single datetime column or separate date and
time columns, case-insensitive OHLC(V) headers, comma/semicolon/tab separators.
Problems are reported, not silently repaired, except for the explicit and
documented fixes listed in ``ValidationReport.fixes``.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .bars import Bars, InstrumentSpec

_ALIASES = {
    "open": {"open", "o", "<open>", "opening price"},
    "high": {"high", "h", "<high>"},
    "low": {"low", "l", "<low>"},
    "close": {"close", "c", "<close>", "last", "price", "adj close*"},
    "volume": {"volume", "vol", "v", "<vol>", "<tickvol>", "tickvol", "totalvolume", "up+down"},
    "datetime": {"datetime", "timestamp", "date_time", "time stamp", "dt", "<datetime>"},
    "date": {"date", "<date>", "day"},
    "time": {"time", "<time>"},
}


class DataError(ValueError):
    """Input data cannot be used. The message says why."""


@dataclass
class ValidationReport:
    rows: int = 0
    start: str | None = None
    end: str | None = None
    median_bar_seconds: float | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    fixes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "rows": self.rows,
            "start": self.start,
            "end": self.end,
            "median_bar_seconds": self.median_bar_seconds,
            "errors": self.errors,
            "warnings": self.warnings,
            "fixes": self.fixes,
        }


def _match_columns(columns: list[str]) -> dict[str, str]:
    found: dict[str, str] = {}
    for col in columns:
        key = col.strip().lower()
        for canon, aliases in _ALIASES.items():
            if key in aliases and canon not in found:
                found[canon] = col
    # "adj close" should only be used when there is no plain close
    if "close" not in found:
        for col in columns:
            if col.strip().lower() == "adj close":
                found["close"] = col
    return found


def read_ohlcv(
    source: str | Path | bytes,
    instrument: InstrumentSpec | None = None,
    timezone: str | None = None,
    sort: bool = True,
) -> tuple[Bars, ValidationReport]:
    """Read OHLCV data and validate it.

    ``timezone`` labels naive timestamps (e.g. "America/New_York"); aware
    timestamps keep their own zone. Raises DataError when the data is unusable.
    """
    if isinstance(source, bytes):
        text = source.decode("utf-8-sig", errors="replace")
    else:
        text = Path(source).read_text(encoding="utf-8-sig", errors="replace")
    df = pd.read_csv(io.StringIO(text), sep=None, engine="python", dtype=str, keep_default_na=False)
    if df.empty:
        raise DataError("file contains no rows")
    cols = _match_columns([str(c) for c in df.columns])
    missing = [c for c in ("open", "high", "low", "close") if c not in cols]
    if missing:
        raise DataError(f"missing required columns {missing}; found {list(df.columns)}")

    if "datetime" in cols:
        stamp = df[cols["datetime"]].astype(str)
    elif "date" in cols and "time" in cols:
        tm = df[cols["time"]].astype(str).str.strip()
        # HHMM / HMM (TradeStation, MetaTrader) -> HH:MM
        compact = tm.str.fullmatch(r"\d{3,4}")
        tm = tm.where(~compact, tm.str.zfill(4).str[:2] + ":" + tm.str.zfill(4).str[2:])
        stamp = df[cols["date"]].astype(str).str.strip() + " " + tm
    elif "date" in cols:
        stamp = df[cols["date"]].astype(str)
    else:
        first = df.columns[0]
        stamp = df[first].astype(str)
    ts = _parse_timestamps(stamp)
    if ts.isna().any():
        bad = int(ts.isna().sum())
        raise DataError(f"{bad} timestamps could not be parsed (first: {stamp[ts.isna()].iloc[0]!r})")

    frame = pd.DataFrame(
        {
            k: pd.to_numeric(df[cols[k]], errors="coerce")
            for k in ("open", "high", "low", "close")
        }
    )
    frame["volume"] = pd.to_numeric(df[cols["volume"]], errors="coerce") if "volume" in cols else 0.0
    idx = pd.DatetimeIndex(ts)
    if idx.tz is None:
        idx = idx.tz_localize(timezone or "UTC", ambiguous="NaT", nonexistent="NaT")
    frame.index = idx
    return validate_frame(frame, instrument, sort=sort)


def _parse_timestamps(stamp: pd.Series) -> pd.Series:
    s = stamp.str.strip()
    # Compact numeric dates like 20240131 (TradeStation/MetaTrader exports)
    if s.str.fullmatch(r"\d{8}").all():
        return pd.to_datetime(s, format="%Y%m%d", errors="coerce")
    if s.str.fullmatch(r"\d{8} \d{2}:\d{2}(:\d{2})?").all():
        fmt = "%Y%m%d %H:%M" if len(s.iloc[0]) == 14 else "%Y%m%d %H:%M:%S"
        return pd.to_datetime(s, format=fmt, errors="coerce")
    if s.str.fullmatch(r"\d{9,13}(\.\d+)?").all():
        num = pd.to_numeric(s)
        unit = "ms" if num.max() > 1e11 else "s"
        return pd.to_datetime(num, unit=unit, utc=True)
    try:
        return pd.to_datetime(s, errors="coerce", format="mixed")
    except (TypeError, ValueError):
        return pd.to_datetime(s, errors="coerce")


def validate_frame(
    frame: pd.DataFrame, instrument: InstrumentSpec | None = None, sort: bool = True
) -> tuple[Bars, ValidationReport]:
    rep = ValidationReport()
    df = frame.copy()
    if df.index.isna().any():
        n = int(df.index.isna().sum())
        rep.warnings.append(f"dropped {n} rows with nonexistent/ambiguous local timestamps")
        df = df[~df.index.isna()]
    nan_rows = df[["open", "high", "low", "close"]].isna().any(axis=1)
    if nan_rows.any():
        rep.fixes.append(f"dropped {int(nan_rows.sum())} rows with missing prices")
        df = df[~nan_rows]
    df["volume"] = df["volume"].fillna(0.0)
    if not df.index.is_monotonic_increasing:
        if sort:
            df = df.sort_index(kind="stable")
            rep.fixes.append("sorted rows by timestamp")
        else:
            rep.errors.append("timestamps are not in increasing order")
    dup = df.index.duplicated(keep="first")
    if dup.any():
        rep.fixes.append(f"dropped {int(dup.sum())} rows with duplicate timestamps (kept first)")
        df = df[~dup]
    if len(df) < 2:
        rep.errors.append("fewer than 2 usable rows")
    o, h, lo, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    if (np.r_[o, h, lo, c] <= 0).any():
        rep.warnings.append("non-positive prices present; percentage-based features may be undefined")
    inconsistent = (h < np.maximum(o, c)) | (lo > np.minimum(o, c)) | (h < lo)
    if inconsistent.any():
        rep.errors.append(
            f"{int(inconsistent.sum())} bars violate low <= open,close <= high "
            f"(first at {df.index[np.argmax(inconsistent)]})"
        )
    if len(df) >= 3:
        secs = np.diff(df.index.as_unit("ns").asi8) / 1e9
        med = float(np.median(secs))
        rep.median_bar_seconds = med
        big = secs > med * 10
        if med < 86400 and big.sum() > 0:
            rep.warnings.append(f"{int(big.sum())} gaps longer than 10x the median bar spacing (sessions/holidays are normal)")
        rets = np.abs(np.diff(np.log(np.where(c > 0, c, np.nan))))
        if np.nanmax(rets, initial=0) > 0.5:
            rep.warnings.append("a close-to-close move above 50% exists; check for unadjusted splits or bad ticks")
    rep.rows = len(df)
    if len(df):
        rep.start = str(df.index[0])
        rep.end = str(df.index[-1])
    if rep.errors:
        raise DataError("; ".join(rep.errors))
    return Bars.from_frame(df, instrument), rep
