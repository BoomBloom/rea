import random

import numpy as np
import pytest

from alphaforge.engine import BacktestConfig, CostModel, ExitSpec, Strategy, backtest
from alphaforge.export import TARGETS, export
from alphaforge.rules import all_signals
from alphaforge.search import Generator, GeneratorConfig


def random_strategies(n, seed=0):
    rng = random.Random(seed)
    sigs = all_signals()
    out = []
    for i in range(n):
        entry = tuple(dict.fromkeys(rng.choice(sigs) for _ in range(rng.randint(1, 3))))
        exits = ExitSpec(
            stop_atr=rng.choice([None, 1.0, 2.0]),
            target_atr=rng.choice([None, 1.5, 3.0]),
            trail_atr=rng.choice([None, None, 2.0]),
            max_bars=rng.choice([None, 3, 8]),
            exit_signal=rng.choice([None, rng.choice(sigs)]),
            profitable_close=rng.random() < 0.3,
        )
        if exits.is_empty():
            exits = ExitSpec(max_bars=5)
        out.append(Strategy(rng.choice(["long", "short"]), entry, exits, quantity=rng.choice([1, 10])))
    return out


@pytest.fixture(scope="module")
def csv_path(synth, tmp_path_factory):
    p = tmp_path_factory.mktemp("d") / "d.csv"
    synth.to_frame().to_csv(p, index_label="datetime")
    return p


def _run_python_export(code, path):
    ns = {"__name__": "exported"}
    exec(compile(code, "exported", "exec"), ns)
    return ns["backtest"](ns["load"](path))


def test_python_export_reproduces_engine_trades(synth, csv_path):
    cfg = BacktestConfig(CostModel(0.01, 2))
    checked = 0
    for s in random_strategies(60, seed=7):
        res = backtest(synth, s, cfg)
        trades = _run_python_export(export(s, "python", cfg, synth.instrument), csv_path)
        eng = res.trades_frame()
        assert len(trades) == len(eng), s.describe()
        np.testing.assert_allclose([t["pnl"] for t in trades], eng["pnl"].to_numpy(), atol=1e-7)
        assert [t["reason"] for t in trades] == list(eng["reason"])
        checked += len(trades)
    assert checked > 500


def _balanced(code, a, b):
    depth = 0
    for ch in code:
        depth += ch == a
        depth -= ch == b
        assert depth >= 0
    return depth == 0


@pytest.mark.parametrize("target", sorted(TARGETS))
def test_all_targets_render(target):
    for s in random_strategies(40, seed=11):
        code = export(s, target)
        assert "Hypothetical results" in code
        assert _balanced(code, "(", ")"), (target, s.describe())
        if target in ("ninjascript", "mql5"):
            assert _balanced(code, "{", "}")
        if target == "pine":
            assert code.startswith("//@version=5") and "strategy.entry" in code
        if target == "easylanguage":
            assert ("Buy (" in code) or ("SellShort (" in code)


def test_unknown_target():
    with pytest.raises(ValueError):
        export(random_strategies(1)[0], "fortran")
