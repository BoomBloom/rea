import numpy as np

from alphaforge.data import Bars
from alphaforge.engine import BacktestConfig, CostModel
from alphaforge.search import Generator, GeneratorConfig, deflated_sharpe, expected_max_sharpe

CFG = dict(population=30, generations=4, quantity=100, min_trades_is=15, min_trades_oos=0, seed=3)


def test_deterministic(synth):
    a = Generator(synth, GeneratorConfig(**CFG)).run()
    b = Generator(synth, GeneratorConfig(**CFG)).run()
    assert [r.strategy.key() for r in a.results] == [r.strategy.key() for r in b.results]
    assert a.evaluated == b.evaluated


def test_selection_never_reads_out_of_sample(synth):
    """Scrambling every out-of-sample bar must not change which strategies the search evaluates or how it ranks them."""
    bt = BacktestConfig(CostModel(0.01, 1), oos_fraction=0.3)
    g1 = Generator(synth, GeneratorConfig(**CFG), bt)
    split = g1.ctx.split
    rng = np.random.default_rng(0)
    scale = np.ones(len(synth))
    scale[split:] = rng.uniform(0.5, 1.5, len(synth) - split)
    widen = np.where(np.arange(len(synth)) >= split, 0.01, 0.0)
    s2 = Bars(synth.time, synth.open * scale, synth.high * scale * (1 + widen), synth.low * scale * (1 - widen), synth.close * scale, synth.volume * scale, synth.instrument)
    g2 = Generator(s2, GeneratorConfig(**CFG), bt)
    r1, r2 = g1.run(), g2.run()
    assert list(g1.cache) == list(g2.cache)
    f1 = {k: (v.fitness if v else None) for k, v in g1.cache.items()}
    f2 = {k: (v.fitness if v else None) for k, v in g2.cache.items()}
    assert f1 == f2
    # but the reported out-of-sample metrics do differ
    assert any(a.metrics_oos != b.metrics_oos for a, b in zip(r1.results, r2.results))


def test_results_respect_filters(synth):
    rep = Generator(synth, GeneratorConfig(**{**CFG, "min_trades_oos": 5})).run()
    for r in rep.results:
        assert r.metrics_is["trades"] >= 15 and r.metrics_oos["trades"] >= 5
    sigs = [r.run.entry_idx.tobytes() + r.run.exit_idx.tobytes() for r in rep.results]
    assert len(sigs) == len(set(sigs))


def test_deflated_sharpe_penalises_more_trials():
    rng = np.random.default_rng(1)
    r = rng.normal(0.0005, 0.01, 1000)
    one = deflated_sharpe(r, 1)["dsr"]
    many = deflated_sharpe(r, 10_000)["dsr"]
    assert many < one
    assert expected_max_sharpe(1000, 0.01) > expected_max_sharpe(10, 0.01) > 0
