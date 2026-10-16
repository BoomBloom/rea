import math

import numpy as np
import pytest

from alphaforge.engine import metrics as mt


def test_trade_statistics():
    pnl = np.array([100.0, -50.0, 200.0, -50.0])
    eq = np.cumsum(pnl)
    t = np.arange(4, dtype=np.int64) * 86_400 * 10**9
    m = mt.compute(pnl, eq, np.ones(4, bool), np.ones(4), t, 10_000)
    assert m["net_profit"] == 200
    assert m["profit_factor"] == pytest.approx(3.0)
    assert m["win_rate"] == 0.5
    assert m["avg_win"] == 150 and m["avg_loss"] == -50
    assert m["win_loss_ratio"] == pytest.approx(3.0)
    assert m["max_drawdown"] == 50
    sd = np.std(pnl, ddof=1)
    assert m["t_stat"] == pytest.approx(2 * 50 / sd)
    assert m["sqn"] == pytest.approx(m["t_stat"])


def test_drawdown_counts_from_initial_zero():
    eq = np.array([-10.0, -30.0, 5.0, -5.0])
    m = mt.compute(np.array([]), eq, np.zeros(4, bool), np.array([]), np.arange(4) * 86_400 * 10**9, 1000)
    assert m["max_drawdown"] == 30


def test_no_losses_profit_factor_capped():
    m = mt.compute(np.array([5.0, 6.0]), np.array([5.0, 11.0]), np.ones(2, bool), np.ones(2), np.arange(2) * 10**9, 100)
    assert m["profit_factor"] == 999.0
    assert all(math.isfinite(v) for v in m.values())


def test_bars_per_year_daily():
    t = (np.arange(253) * 365.25 / 252 * 86400 * 1e9).astype(np.int64)
    assert mt.bars_per_year(t) == pytest.approx(252, rel=1e-6)


def test_fitness_direction():
    assert mt.fitness_value({"max_drawdown": 10}, "max_drawdown") == -10
    with pytest.raises(ValueError):
        mt.fitness_value({}, "nope")
