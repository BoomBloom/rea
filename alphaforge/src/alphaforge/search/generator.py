"""Strategy generation by genetic search over the signal library.

Selection pressure uses **in-sample data only**. Out-of-sample bars are never
read while choosing strategies; they are evaluated once, after the search, for
the strategies being reported. The number of distinct strategies evaluated is
recorded so results can be corrected for multiple testing (see stats.py).
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field
from typing import Callable

from ..data.bars import Bars
from ..engine.backtest import BacktestResult, Context, backtest
from ..engine.metrics import FITNESS, fitness_value
from ..engine.spec import BacktestConfig, ExitSpec, Strategy
from ..rules.library import TEMPLATES, TEMPLATE_LIST, Signal


@dataclass
class GeneratorConfig:
    direction: str = "long"  # long | short | both
    max_entry_signals: int = 3
    categories: list[str] | None = None  # None = all
    stop_atr: list[float | None] = field(default_factory=lambda: [None, 1.0, 1.5, 2.0, 3.0])
    target_atr: list[float | None] = field(default_factory=lambda: [None, 1.0, 2.0, 3.0, 4.0])
    trail_atr: list[float | None] = field(default_factory=lambda: [None])
    max_bars: list[int | None] = field(default_factory=lambda: [None, 3, 5, 10, 20])
    use_exit_signals: bool = True
    allow_profitable_close: bool = True
    atr_len: int = 14
    quantity: float = 1.0
    fitness: str = "return_dd"
    min_trades_is: int = 30
    min_trades_oos: int = 10
    population: int = 120
    generations: int = 25
    mutation_rate: float = 0.35
    elite_fraction: float = 0.1
    tournament: int = 3
    max_results: int = 50
    seed: int = 1
    time_budget_s: float | None = None

    def validate(self) -> None:
        if self.direction not in ("long", "short", "both"):
            raise ValueError("direction must be long, short or both")
        if self.fitness not in FITNESS:
            raise ValueError(f"unknown fitness {self.fitness}")
        if not 1 <= self.max_entry_signals <= 5:
            raise ValueError("max_entry_signals must be 1..5")
        if self.population < 4:
            raise ValueError("population must be >= 4")

    def to_dict(self):
        return dict(self.__dict__)

    @staticmethod
    def from_dict(d: dict) -> "GeneratorConfig":
        c = GeneratorConfig()
        for k, v in d.items():
            if hasattr(c, k):
                setattr(c, k, v)
        c.validate()
        return c


@dataclass
class Candidate:
    strategy: Strategy
    fitness: float
    is_metrics: dict


@dataclass
class GenerationReport:
    results: list[BacktestResult]
    evaluated: int
    rejected_min_trades: int
    elapsed_s: float
    generations_run: int
    best_history: list[float]
    is_sharpes: list[float]  # in-sample Sharpe of every valid candidate (for deflated Sharpe)
    config: GeneratorConfig


class Generator:
    def __init__(self, bars: Bars, gen_cfg: GeneratorConfig, bt_cfg: BacktestConfig | None = None):
        gen_cfg.validate()
        self.cfg = gen_cfg
        self.ctx = Context(bars, bt_cfg)
        self.rng = random.Random(gen_cfg.seed)
        self.templates = [t for t in TEMPLATE_LIST if not gen_cfg.categories or t.category in gen_cfg.categories]
        if not self.templates:
            raise ValueError("no signal templates match the selected categories")
        self._combos = {t.id: list(t.combos()) for t in self.templates}
        self.cache: dict[str, Candidate | None] = {}
        self.rejected = 0
        self.is_sharpes: list[float] = []

    # ---- genome operators
    def random_signal(self) -> Signal:
        t = self.rng.choice(self.templates)
        return Signal.of(t.id, **self.rng.choice(self._combos[t.id]))

    def random_exits(self) -> ExitSpec:
        c = self.cfg
        for _ in range(50):
            e = ExitSpec(
                stop_atr=self.rng.choice(c.stop_atr),
                target_atr=self.rng.choice(c.target_atr),
                trail_atr=self.rng.choice(c.trail_atr),
                max_bars=self.rng.choice(c.max_bars),
                exit_signal=self.random_signal() if c.use_exit_signals and self.rng.random() < 0.25 else None,
                profitable_close=c.allow_profitable_close and self.rng.random() < 0.2,
                atr_len=c.atr_len,
            )
            if not e.is_empty():
                return e
        return ExitSpec(max_bars=10, atr_len=c.atr_len)

    def random_direction(self) -> str:
        return self.cfg.direction if self.cfg.direction != "both" else self.rng.choice(["long", "short"])

    def random_strategy(self) -> Strategy:
        n = self.rng.randint(1, self.cfg.max_entry_signals)
        entry = tuple(dict.fromkeys(self.random_signal() for _ in range(n)))
        return Strategy(self.random_direction(), entry, self.random_exits(), self.cfg.quantity)

    def mutate(self, s: Strategy) -> Strategy:
        entry = list(s.entry)
        exits = s.exits
        op = self.rng.random()
        if op < 0.35:
            entry[self.rng.randrange(len(entry))] = self.random_signal()
        elif op < 0.5 and len(entry) < self.cfg.max_entry_signals:
            entry.append(self.random_signal())
        elif op < 0.6 and len(entry) > 1:
            entry.pop(self.rng.randrange(len(entry)))
        elif op < 0.7:
            entry[self.rng.randrange(len(entry))] = self._neighbour(entry[self.rng.randrange(len(entry))])
        else:
            fresh = self.random_exits()
            fld = self.rng.choice(["stop_atr", "target_atr", "trail_atr", "max_bars", "exit_signal", "profitable_close"])
            candidate = ExitSpec(**{**exits.__dict__, fld: getattr(fresh, fld)})
            if not candidate.is_empty():
                exits = candidate
        direction = s.direction
        if self.cfg.direction == "both" and self.rng.random() < 0.05:
            direction = "short" if direction == "long" else "long"
        return Strategy(direction, tuple(dict.fromkeys(entry)), exits, s.quantity)

    def _neighbour(self, sig: Signal) -> Signal:
        """Move one parameter of a signal to an adjacent grid value."""
        t = TEMPLATES[sig.template]
        p = sig.param_dict
        keys = [k for k in p if len(t.grid[k]) > 1]
        if not keys:
            return sig
        key = self.rng.choice(keys)
        grid = t.grid[key]
        i = grid.index(p[key])
        j = min(max(i + self.rng.choice([-1, 1]), 0), len(grid) - 1)
        p[key] = grid[j]
        return Signal.of(sig.template, **p) if t.valid(**p) else sig

    def crossover(self, a: Strategy, b: Strategy) -> Strategy:
        pool = list(dict.fromkeys(a.entry + b.entry))
        n = self.rng.randint(1, min(len(pool), self.cfg.max_entry_signals))
        entry = tuple(self.rng.sample(pool, n))
        fields = {}
        for f in ("stop_atr", "target_atr", "trail_atr", "max_bars", "exit_signal", "profitable_close"):
            fields[f] = getattr(self.rng.choice([a.exits, b.exits]), f)
        exits = ExitSpec(**fields, atr_len=self.cfg.atr_len)
        if exits.is_empty():
            exits = a.exits
        return Strategy(self.rng.choice([a.direction, b.direction]), entry, exits, a.quantity)

    # ---- evaluation (in-sample only)
    def evaluate(self, s: Strategy) -> Candidate | None:
        key = s.key()
        if key in self.cache:
            return self.cache[key]
        run = self.ctx.run(s, 0, self.ctx.split)
        m = self.ctx.segment_metrics(run, 0, self.ctx.split)
        if m["trades"] < self.cfg.min_trades_is:
            self.rejected += 1
            cand = None
        else:
            cand = Candidate(s, fitness_value(m, self.cfg.fitness), m)
            self.is_sharpes.append(m["sharpe"])
        self.cache[key] = cand
        return cand

    def _tournament(self, scored: list[Candidate]) -> Strategy:
        picks = self.rng.sample(scored, min(self.cfg.tournament, len(scored)))
        return max(picks, key=lambda c: c.fitness).strategy

    def run(
        self,
        progress: Callable[[dict], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> GenerationReport:
        c = self.cfg
        t0 = time.time()
        pop = [self.random_strategy() for _ in range(c.population)]
        best_hist: list[float] = []
        gens = 0
        for g in range(c.generations + 1):
            scored = [x for x in (self.evaluate(s) for s in pop) if x is not None]
            scored.sort(key=lambda x: x.fitness, reverse=True)
            gens = g
            best = scored[0].fitness if scored else float("nan")
            best_hist.append(best)
            if progress:
                progress({
                    "generation": g,
                    "generations": c.generations,
                    "evaluated": len(self.cache),
                    "valid": len(self.is_sharpes),
                    "best_fitness": best,
                    "elapsed_s": time.time() - t0,
                })
            if g == c.generations or (cancelled and cancelled()):
                break
            if c.time_budget_s is not None and time.time() - t0 > c.time_budget_s:
                break
            n_elite = max(1, int(c.population * c.elite_fraction))
            nxt = [x.strategy for x in scored[:n_elite]]
            while len(nxt) < c.population:
                if len(scored) < 2 or self.rng.random() < 0.15:
                    child = self.random_strategy()  # immigrants keep diversity
                else:
                    child = self.crossover(self._tournament(scored), self._tournament(scored))
                    if self.rng.random() < c.mutation_rate:
                        child = self.mutate(child)
                nxt.append(child)
            pop = nxt

        ranked = sorted((x for x in self.cache.values() if x is not None), key=lambda x: x.fitness, reverse=True)
        results: list[BacktestResult] = []
        seen_trades: set[bytes] = set()
        for cand in ranked:
            if len(results) >= c.max_results:
                break
            res = backtest(self.ctx.bars, cand.strategy, ctx=self.ctx)
            if res.metrics_oos["trades"] < c.min_trades_oos:
                continue
            # different rule text can produce identical trades; report each trade set once
            sig = res.run.entry_idx.tobytes() + res.run.exit_idx.tobytes()
            if sig in seen_trades:
                continue
            seen_trades.add(sig)
            results.append(res)
        return GenerationReport(
            results=results,
            evaluated=len(self.cache),
            rejected_min_trades=self.rejected,
            elapsed_s=time.time() - t0,
            generations_run=gens,
            best_history=[b if math.isfinite(b) else None for b in best_hist],
            is_sharpes=self.is_sharpes,
            config=c,
        )


def generate(bars: Bars, gen_cfg: GeneratorConfig | None = None, bt_cfg: BacktestConfig | None = None, **kw) -> GenerationReport:
    return Generator(bars, gen_cfg or GeneratorConfig(), bt_cfg).run(**kw)
