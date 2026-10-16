import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings, strategies as st

from alphaforge.rules import indicators as ind


def ref_seeded(x, n, alpha):
    out = [np.nan] * len(x)
    if len(x) < n:
        return np.array(out)
    prev = sum(x[:n]) / n
    out[n - 1] = prev
    for i in range(n, len(x)):
        prev = alpha * x[i] + (1 - alpha) * prev
        out[i] = prev
    return np.array(out)


def test_sma_hand_values():
    x = np.array([1, 2, 3, 4, 5], float)
    np.testing.assert_allclose(ind.sma(x, 3), [np.nan, np.nan, 2, 3, 4])


def test_ema_and_rma_match_reference():
    rng = np.random.default_rng(0)
    x = 100 + rng.normal(0, 1, 300).cumsum()
    for n in (2, 5, 14, 50):
        np.testing.assert_allclose(ind.ema(x, n), ref_seeded(x, n, 2 / (n + 1)), rtol=1e-12)
        np.testing.assert_allclose(ind.rma(x, n), ref_seeded(x, n, 1 / n), rtol=1e-12)


def test_rsi_extremes_and_reference():
    up = np.arange(1, 40, dtype=float)
    assert np.nanmin(ind.rsi(up, 14)) == 100.0
    down = up[::-1].copy()
    assert np.nanmax(ind.rsi(down, 14)) == 0.0
    rng = np.random.default_rng(1)
    x = 50 + rng.normal(0, 1, 200).cumsum()
    ch = np.diff(x)
    g = ref_seeded(np.maximum(ch, 0), 14, 1 / 14)
    l = ref_seeded(np.maximum(-ch, 0), 14, 1 / 14)
    expected = np.r_[np.nan, 100 - 100 / (1 + g / l)]
    np.testing.assert_allclose(ind.rsi(x, 14), expected, rtol=1e-10)


def test_atr_first_bar_and_wilder():
    h = np.array([10, 12, 11, 13], float)
    l = np.array([9, 10, 9, 11], float)
    c = np.array([9.5, 11, 10, 12], float)
    tr = ind.true_range(h, l, c)
    np.testing.assert_allclose(tr, [1, 2.5, 2, 3])
    a = ind.atr(h, l, c, 2)
    np.testing.assert_allclose(a, [np.nan, 1.75, 1.875, 2.4375])


def test_stdev_is_population():
    x = np.array([2, 4, 4, 4, 5, 5, 7, 9], float)
    assert ind.stdev(x, 8)[-1] == pytest.approx(2.0)


def test_stoch_and_ibs_undefined_on_flat_range():
    h = np.array([5, 5, 5], float)
    assert np.isnan(ind.stoch_k(h, h, h, 2)[-1])
    assert np.isnan(ind.ibs(h, h, h)[-1])


@settings(max_examples=40, deadline=None)
@given(st.lists(st.floats(1, 1000), min_size=30, max_size=120), st.integers(2, 20), st.integers(0, 25))
def test_indicators_are_causal(values, n, cut):
    """Changing data after bar k never changes indicator values at bars <= k."""
    x = np.array(values)
    k = min(cut, len(x) - 2)
    y = x.copy()
    y[k + 1 :] = y[k + 1 :] * 1.7 + 3
    for f in (ind.sma, ind.ema, ind.rsi, ind.stdev, ind.highest, ind.lowest, ind.roc):
        a, b = f(x, n)[: k + 1], f(y, n)[: k + 1]
        np.testing.assert_array_equal(np.isnan(a), np.isnan(b))
        np.testing.assert_allclose(a[~np.isnan(a)], b[~np.isnan(b)])


def test_lag():
    x = np.array([1, 2, 3], float)
    np.testing.assert_array_equal(ind.lag(x, 1)[1:], [1, 2])
    assert np.isnan(ind.lag(x, 1)[0])
    assert np.isnan(ind.lag(x, 5)).all()
