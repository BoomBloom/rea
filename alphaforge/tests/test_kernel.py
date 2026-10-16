"""Execution-model tests on hand-built bars. Every expected number is worked out by hand."""

import numpy as np
import pytest
from hypothesis import given, settings, strategies as st

from alphaforge.engine import kernel
from alphaforge.engine.kernel import simulate
from conftest import bars_from

REASON = {v: k for k, v in kernel.REASONS.items()}


def sim(b, entry, exit_sig=None, atr=None, d=1, stop=0.0, target=0.0, trail=0.0, max_bars=0, pc=False, slip=0.0, comm=0.0, qty=1.0, pv=1.0, start=0, end=None, fn=simulate):
    n = len(b)
    entry = np.array(entry, bool)
    exit_sig = np.zeros(n, bool) if exit_sig is None else np.array(exit_sig, bool)
    atr = np.full(n, 1.0) if atr is None else np.asarray(atr, float)
    out = fn(b.open, b.high, b.low, b.close, entry, exit_sig, atr, d, stop, target, trail, max_bars, pc, slip, comm, qty, pv, start, n if end is None else end)
    keys = ["entry_idx", "exit_idx", "entry_px", "exit_px", "reason", "pnl", "mae", "mfe", "equity", "in_market"]
    return dict(zip(keys, out))


FLAT = [(10, 10.5, 9.5, 10)] * 8


def test_entry_fills_next_open_and_time_exit_next_open():
    rows = [(10, 11, 9, 10), (10, 11, 9, 10), (11, 12, 10, 11), (12, 13, 11, 12), (13, 14, 12, 13), (14, 15, 13, 14)]
    b = bars_from(rows)
    r = sim(b, [0, 1, 0, 0, 0, 0], max_bars=2)
    # signal at close of bar 1 -> buy open of bar 2 (11); held bars 2,3 -> exit at open of bar 4 (13)
    assert list(r["entry_idx"]) == [2] and list(r["exit_idx"]) == [4]
    assert r["entry_px"][0] == 11 and r["exit_px"][0] == 13
    assert REASON["time"] == r["reason"][0]
    assert r["pnl"][0] == pytest.approx(2.0)


def test_stop_fills_at_level_or_gap_open():
    rows = [(10, 10.5, 9.5, 10), (10, 10.5, 9.5, 10), (10, 10.2, 8.9, 9.0), (10, 10, 10, 10)]
    b = bars_from(rows)
    r = sim(b, [1, 0, 0, 0], stop=1.0)  # entry open bar1 =10, stop 9 (atr 1)
    assert r["exit_idx"][0] == 2 and r["exit_px"][0] == 9.0 and r["reason"][0] == REASON["stop"]
    rows_gap = [(10, 10.5, 9.5, 10), (10, 10.5, 9.6, 10), (8.0, 8.5, 7.5, 8.2), (8, 8, 8, 8)]
    r = sim(bars_from(rows_gap), [1, 0, 0, 0], stop=1.0)
    assert r["exit_px"][0] == 8.0  # gapped through the stop: filled at the open


def test_target_fills_at_level_or_better_gap_and_no_slippage():
    rows = [(10, 10.5, 9.5, 10), (10, 10.5, 9.6, 10), (10.2, 11.5, 10.1, 11), (11, 11, 11, 11)]
    r = sim(bars_from(rows), [1, 0, 0, 0], target=1.0, slip=0.05)
    assert r["entry_px"][0] == pytest.approx(10.05)
    assert r["exit_px"][0] == pytest.approx(11.05)  # target = fill + 1 ATR, no slippage on the limit
    rows_gap = [(10, 10.5, 9.5, 10), (10, 10.5, 9.6, 10), (12.0, 12.5, 11.8, 12), (12, 12, 12, 12)]
    r = sim(bars_from(rows_gap), [1, 0, 0, 0], target=1.0)
    assert r["exit_px"][0] == 12.0 and r["reason"][0] == REASON["target"]


def test_stop_wins_when_both_touched_same_bar():
    rows = [(10, 10.5, 9.5, 10), (10, 10.5, 9.6, 10), (10, 11.5, 8.5, 10), (10, 10, 10, 10)]
    r = sim(bars_from(rows), [1, 0, 0, 0], stop=1.0, target=1.0)
    assert r["reason"][0] == REASON["stop"] and r["exit_px"][0] == 9.0


def test_short_is_mirror_image():
    rows = [(10, 10.5, 9.5, 10), (10, 10.5, 9.5, 10), (10, 10.2, 8.5, 9.0), (9, 9, 9, 9)]
    r = sim(bars_from(rows), [1, 0, 0, 0], d=-1, target=1.0)
    assert r["entry_px"][0] == 10 and r["exit_px"][0] == 9.0 and r["pnl"][0] == pytest.approx(1.0)
    r = sim(bars_from(rows), [1, 0, 0, 0], d=-1, stop=0.4)
    assert r["exit_px"][0] == pytest.approx(10.4) and r["pnl"][0] == pytest.approx(-0.4)


def test_costs_exact():
    rows = [(100, 101, 99, 100), (100, 101, 99, 100), (102, 103, 101, 102), (104, 105, 103, 104)]
    # qty 10, point value 50, slippage 0.25/side, commission 2/unit/side
    r = sim(bars_from(rows), [1, 0, 0, 0], max_bars=1, slip=0.25, comm=2.0, qty=10, pv=50)
    # entry open bar1 100 + .25; held 1 bar -> exit open bar2 102 - .25
    assert r["entry_px"][0] == 100.25 and r["exit_px"][0] == 101.75
    assert r["pnl"][0] == pytest.approx((101.75 - 100.25) * 10 * 50 - 2 * 2.0 * 10)
    assert r["equity"][-1] == pytest.approx(r["pnl"].sum())


def test_end_of_data_closes_at_last_close_and_no_entry_on_last_bar():
    rows = FLAT[:4]
    r = sim(bars_from(rows), [1, 0, 0, 1], max_bars=50)
    assert len(r["pnl"]) == 1 and r["reason"][0] == REASON["end"] and r["exit_idx"][0] == 3


def test_profitable_close_and_signal_exit():
    rows = [(10, 10.5, 9.5, 10), (10, 10.5, 9.5, 9.8), (9.8, 10.5, 9.7, 10.2), (10.3, 10.5, 10, 10.1), (10, 10, 10, 10)]
    r = sim(bars_from(rows), [1, 0, 0, 0, 0], pc=True)
    # entry 10 at bar1, close 9.8 (loss), bar2 close 10.2 > 10 -> exit open bar3 = 10.3
    assert r["exit_idx"][0] == 3 and r["exit_px"][0] == 10.3 and r["reason"][0] == REASON["profit_close"]
    r = sim(bars_from(rows), [1, 0, 0, 0, 0], exit_sig=[0, 1, 0, 0, 0])
    assert r["exit_idx"][0] == 2 and r["reason"][0] == REASON["signal"]


def test_trailing_stop_ratchets():
    rows = [(10, 10, 10, 10), (10, 10, 10, 10), (10, 12, 10, 12), (12, 12.5, 10.9, 11), (11, 11, 11, 11)]
    r = sim(bars_from(rows), [1, 0, 0, 0, 0], trail=1.0)
    # entry 10 @bar1; trail 9; bar2 high 12 -> trail 11 at close; bar3 low 10.9 hits 11
    assert r["reason"][0] == REASON["trail"] and r["exit_px"][0] == 11 and r["exit_idx"][0] == 3


def test_no_entry_without_atr_when_stops_used():
    atr = np.array([np.nan, np.nan, 1, 1, 1, 1])
    r = sim(bars_from(FLAT[:6]), [1, 0, 1, 0, 0, 0], atr=atr, stop=2.0, max_bars=1)
    assert list(r["entry_idx"]) == [3]


def test_one_position_at_a_time():
    r = sim(bars_from(FLAT), [1] * 8, max_bars=2)
    ent, ex = r["entry_idx"], r["exit_idx"]
    assert all(ent[i + 1] > ex[i] for i in range(len(ent) - 1))


@settings(max_examples=40, deadline=None)
@given(st.integers(0, 10_000), st.integers(30, 120))
def test_no_lookahead_truncation(seed, cut):
    """Trades that close before bar k are identical whether or not later data exists."""
    rng = np.random.default_rng(seed)
    n = 150
    c = 100 + rng.normal(0, 1, n).cumsum()
    o = c + rng.normal(0, 0.3, n)
    h = np.maximum(o, c) + rng.random(n)
    lo = np.minimum(o, c) - rng.random(n)
    b = bars_from(np.c_[o, h, lo, c])
    entry = rng.random(n) < 0.2
    kw = dict(stop=1.5, target=2.0, max_bars=5, atr=np.full(n, 1.0))
    full = sim(b, entry, **kw)
    part = sim(b, entry, end=cut, **kw)
    done = full["exit_idx"] < cut - 1
    k = int(done.sum())
    np.testing.assert_array_equal(full["entry_idx"][:k], part["entry_idx"][:k])
    np.testing.assert_allclose(full["pnl"][:k], part["pnl"][:k])
    np.testing.assert_allclose(full["equity"][: cut - 1], part["equity"][: cut - 1])


def test_jit_and_python_paths_agree():
    if not hasattr(simulate, "py_func"):
        pytest.skip("numba not installed; only the Python path exists")
    rng = np.random.default_rng(5)
    n = 400
    c = 100 + rng.normal(0, 1, n).cumsum()
    o = c + rng.normal(0, 0.3, n)
    b = bars_from(np.c_[o, np.maximum(o, c) + rng.random(n), np.minimum(o, c) - rng.random(n), c])
    entry = rng.random(n) < 0.1
    ex = rng.random(n) < 0.05
    for d in (1, -1):
        kw = dict(d=d, stop=1.0, target=2.0, trail=1.5, max_bars=7, pc=True, slip=0.02, comm=1.0, qty=3, exit_sig=ex)
        a = sim(b, entry, **kw)
        p = sim(b, entry, fn=simulate.py_func, **kw)
        for key in a:
            np.testing.assert_array_equal(a[key], p[key])
