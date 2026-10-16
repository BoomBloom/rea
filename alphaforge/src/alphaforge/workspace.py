"""On-disk workspace: datasets, generation runs and saved strategies.

Location: $ALPHAFORGE_HOME if set, otherwise the platform's user data directory
(``~/.local/share/AlphaForge`` on Linux, ``~/Library/Application Support/AlphaForge``
on macOS). Everything is plain CSV/JSON so it can be inspected, versioned or backed up.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from pathlib import Path

from platformdirs import user_data_dir

from .data.bars import Bars, InstrumentSpec
from .data.loader import read_ohlcv

_lock = threading.RLock()


def _safe_id(s: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", s):
        raise ValueError("invalid id")
    return s


def new_id(prefix: str) -> str:
    return f"{prefix}-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"


class Workspace:
    def __init__(self, root: str | Path | None = None):
        root = root or os.environ.get("ALPHAFORGE_HOME") or user_data_dir("AlphaForge", appauthor=False)
        self.root = Path(root)
        for sub in ("datasets", "runs", "strategies"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)
        self._bars_cache: dict[str, Bars] = {}

    # ---- datasets
    def add_dataset(self, name: str, content: bytes, instrument: InstrumentSpec, timezone: str | None = None) -> dict:
        bars, report = read_ohlcv(content, instrument, timezone)
        ds_id = new_id("ds")
        d = self.root / "datasets"
        frame = bars.to_frame()
        frame.index = frame.index.tz_convert("UTC")
        frame.to_csv(d / f"{ds_id}.csv", index_label="datetime")
        meta = {
            "id": ds_id,
            "name": name,
            "instrument": instrument.to_dict(),
            "timezone": bars.timezone,
            "report": report.to_dict(),
            "created": time.time(),
        }
        self._write(d / f"{ds_id}.json", meta)
        return meta

    def add_bars(self, name: str, bars: Bars) -> dict:
        frame = bars.to_frame()
        frame.index = frame.index.tz_convert("UTC")
        content = frame.to_csv(index_label="datetime").encode()
        return self.add_dataset(name, content, bars.instrument, "UTC")

    def datasets(self) -> list[dict]:
        out = []
        for p in sorted((self.root / "datasets").glob("*.json")):
            try:
                out.append(json.loads(p.read_text()))
            except (OSError, ValueError):
                continue
        return sorted(out, key=lambda m: m.get("created", 0), reverse=True)

    def dataset_meta(self, ds_id: str) -> dict:
        p = self.root / "datasets" / f"{_safe_id(ds_id)}.json"
        if not p.exists():
            raise KeyError(ds_id)
        return json.loads(p.read_text())

    def load_bars(self, ds_id: str) -> Bars:
        with _lock:
            if ds_id in self._bars_cache:
                return self._bars_cache[ds_id]
        meta = self.dataset_meta(ds_id)
        bars, _ = read_ohlcv(self.root / "datasets" / f"{ds_id}.csv", InstrumentSpec.from_dict(meta["instrument"]))
        if meta.get("timezone") and meta["timezone"] != "UTC":
            bars = Bars(bars.time, bars.open, bars.high, bars.low, bars.close, bars.volume, bars.instrument, meta["timezone"])
        with _lock:
            self._bars_cache[ds_id] = bars
        return bars

    def delete_dataset(self, ds_id: str) -> None:
        _safe_id(ds_id)
        for ext in ("csv", "json"):
            p = self.root / "datasets" / f"{ds_id}.{ext}"
            if p.exists():
                p.unlink()
        self._bars_cache.pop(ds_id, None)

    # ---- runs and strategies
    def save_run(self, run: dict) -> str:
        run_id = run.get("id") or new_id("run")
        run["id"] = run_id
        self._write(self.root / "runs" / f"{run_id}.json", run)
        return run_id

    def runs(self) -> list[dict]:
        out = []
        for p in sorted((self.root / "runs").glob("*.json"), reverse=True):
            try:
                r = json.loads(p.read_text())
            except (OSError, ValueError):
                continue
            out.append({k: r.get(k) for k in ("id", "dataset_id", "created", "evaluated", "elapsed_s", "kind")} | {"results": len(r.get("results", []))})
        return out

    def run(self, run_id: str) -> dict:
        p = self.root / "runs" / f"{_safe_id(run_id)}.json"
        if not p.exists():
            raise KeyError(run_id)
        return json.loads(p.read_text())

    def save_strategy(self, record: dict) -> dict:
        sid = record.get("id") or new_id("st")
        record = {**record, "id": sid, "saved": time.time()}
        self._write(self.root / "strategies" / f"{sid}.json", record)
        return record

    def strategies(self) -> list[dict]:
        out = []
        for p in sorted((self.root / "strategies").glob("*.json")):
            try:
                out.append(json.loads(p.read_text()))
            except (OSError, ValueError):
                continue
        return sorted(out, key=lambda r: r.get("saved", 0), reverse=True)

    def delete_strategy(self, sid: str) -> None:
        p = self.root / "strategies" / f"{_safe_id(sid)}.json"
        if p.exists():
            p.unlink()

    @staticmethod
    def _write(path: Path, data: dict) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, default=_json_default))
        os.replace(tmp, path)


def _json_default(o):
    import numpy as np

    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(f"not JSON serialisable: {type(o).__name__}")
