import json

import numpy as np
import pytest

from alphaforge.rules import Evaluator, Signal, all_signals
from alphaforge.rules.expr import C, Cmp, Cross, Lag, Logic, call, from_dict, k, lag, max_lookback
from conftest import bars_from


def test_every_library_signal_builds_evaluates_and_roundtrips(synth):
    ev = Evaluator(synth)
    sigs = all_signals()
    assert len(sigs) > 500
    for s in sigs:
        e = s.expr()
        arr = ev.boolean(e)
        assert arr.dtype == np.bool_ and len(arr) == len(synth)
        assert from_dict(json.loads(json.dumps(e.to_dict()))) == e
        assert Signal.from_dict(s.to_dict()) == s


def test_negative_lag_rejected():
    with pytest.raises(ValueError):
        Lag(C, -1)


def test_nan_comparisons_are_false():
    b = bars_from([(10, 11, 9, 10)] * 5)
    ev = Evaluator(b)
    assert not ev.boolean(Cmp(">", C, call("sma", C, 10))).any()
    assert not ev.boolean(Cmp("<", C, call("sma", C, 10))).any()


def test_cross_definition():
    rows = [(1, 1, 1, c) for c in (5, 4, 6, 6, 7, 5)]
    ev = Evaluator(bars_from(rows))
    up = ev.boolean(Cross("above", C, k(5.5)))
    np.testing.assert_array_equal(up, [False, False, True, False, False, False])


def test_logic_and_lookback():
    e = Logic("and", (Cmp(">", C, lag(C, 3)), Cmp(">", C, call("sma", C, 20))))
    assert max_lookback(e) >= 20
    assert "close[3]" in str(e)


def test_dayofweek_iso(synth):
    ev = Evaluator(synth)
    s = Signal.of("day_of_week", day=1)
    mask = ev.boolean(s.expr())
    days = synth.datetime_index()[mask].dayofweek
    assert (days == 0).all() and mask.any()
