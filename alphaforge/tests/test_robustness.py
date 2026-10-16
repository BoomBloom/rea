import numpy as np
import pytest

from alphaforge.engine import BacktestConfig, Context, ExitSpec, Strategy
from alphaforge.optimize import walk_forward
from alphaforge.robustness import add_noise, monte_carlo_trades, parameter_stability, permute_bars, run_suite, variance_test, vs_random
from alphaforge.rules import Signal

STRAT = Strategy("long", (Signal.of("rsi_level", n=2, level=10),), ExitSpec(stop_atr=2.0, max_bars=5), quantity=100)


def test_permutation_preserves_distribution(synth):
    p = permute_bars(synth, np.random.default_rng(0))
    r0 = np.sort(np.diff(np.log(synth.close)))
    r1 = np.sort(np.diff(np.log(p.close)))
    np.testing.assert_allclose(r0, r1, atol=1e-9)
    assert p.close[-1] == pytest.approx(synth.close[-1])
    assert (p.high >= np.maximum(p.open, p.close) - 1e-9).all() and (p.low <= np.minimum(p.open, p.close) + 1e-9).all()


def test_noise_keeps_bars_consistent(synth):
    n = add_noise(synth, np.random.default_rng(1), 0.3, 0.6)
    assert (n.high >= np.maximum(n.open, n.close)).all() and (n.low <= np.minimum(n.open, n.close)).all()
    assert not np.allclose(n.close, synth.close)


def test_monte_carlo_reshuffle_keeps_total():
    pnl = np.array([5, -3, 2, 8, -6, 4, -1, 3], float)
    r = monte_carlo_trades(pnl, 200, method="reshuffle")
    assert r["net_profit"]["p5"] == pytest.approx(pnl.sum()) and r["net_profit"]["p95"] == pytest.approx(pnl.sum())
    assert r["max_drawdown"]["p95"] >= r["historical_max_drawdown"] - 1e-9


def test_variance_test_degrades():
    rng = np.random.default_rng(0)
    pnl = np.where(rng.random(200) < 0.6, rng.uniform(1, 3, 200), -rng.uniform(1, 3, 200))
    a = variance_test(pnl, 0.0, seed=1)
    b = variance_test(pnl, 0.15, seed=1)
    assert b["net_profit"]["median"] < a["net_profit"]["median"]


def test_random_entries_on_random_data_are_not_significant(synth):
    """On a no-edge walk, a random-entry strategy should usually not beat random entries."""
    ctx = Context(synth, BacktestConfig())
    s = Strategy("long", (Signal.of("day_of_week", day=3),), ExitSpec(max_bars=3), quantity=100)
    r = vs_random(ctx, s, runs=200, seed=2)
    assert r["p_value"] > 0.01


def test_parameter_stability_runs(synth):
    r = parameter_stability(Context(synth), STRAT, max_variants=40)
    assert r["variants"] > 5 and r["verdict"] in ("pass", "warn", "fail")


def test_suite_and_walkforward_shapes(synth):
    out = run_suite(Context(synth), STRAT, quick=True)
    assert len(out["tests"]) == 8 and sum(out["score"].values()) == 8
    wf = walk_forward(synth, STRAT, windows=4, max_variants=30)
    assert len(wf["windows"]) == 4
    starts = [w["oos_start"] for w in wf["windows"]]
    assert starts == sorted(starts)
