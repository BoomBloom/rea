import numpy as np
import pandas as pd
import pytest

from alphaforge.data import Bars, InstrumentSpec, make_bars


def bars_from(rows, point_value=1.0, tick_size=0.01, start="2024-01-01"):
    """rows: list of (open, high, low, close)."""
    a = np.asarray(rows, dtype=float)
    idx = pd.date_range(start, periods=len(a), freq="D", tz="UTC")
    df = pd.DataFrame({"open": a[:, 0], "high": a[:, 1], "low": a[:, 2], "close": a[:, 3], "volume": 1000.0}, index=idx)
    return Bars.from_frame(df, InstrumentSpec("T", point_value, tick_size))


@pytest.fixture(scope="session")
def synth():
    return make_bars(1500, seed=11, mean_reversion=0.1)
