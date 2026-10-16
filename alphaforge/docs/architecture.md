# Architecture

## Goals that drove the design

1. **Financial correctness first.** One execution model, documented and tested
   with hand-computed cases; no look-ahead by construction; in-sample/out-of-sample
   separation enforced in code and tested.
2. **Linux and macOS from day one.** Pure Python plus wheels that exist for both
   (x86-64 and Apple Silicon). No native toolkit, no platform-specific code.
3. **One rule representation** feeding the backtester, the exporters and the
   UI, so exported code means what the backtest tested.
4. **Fast enough to search thousands of strategies** on a laptop.

## Layers

```
            ┌──────────────┐   ┌───────────────────┐
 adapters   │ cli.py       │   │ app/server.py + UI │   (argument parsing, HTTP, rendering)
            └──────┬───────┘   └─────────┬─────────┘
                   └──────────┬──────────┘
 workflows                services.py  workspace.py       (shared use cases, storage)
                              │
      ┌──────────┬────────────┼─────────────┬──────────────┐
 domain search/   robustness/  optimize/     export/         (generation, tests, WFA, code gen)
      └──────────┴────────────┼─────────────┴──────────────┘
                         engine/                              (spec, kernel, metrics, backtest)
                              │
                         rules/  data/                        (rule IR, indicators, bars, import)
```

Dependencies only point downward. The engine knows nothing about HTTP, files
or the UI; the UI never computes a metric.

## Key components

| Module                | Responsibility                                                                                                                       |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `data/`               | `Bars` (contiguous float64 arrays, UTC ns timestamps), CSV import with validation report, synthetic data                             |
| `rules/expr.py`       | Typed expression IR: fields, constants, lags (non-negative only), indicator calls, arithmetic, comparisons, crosses, logic, calendar |
| `rules/indicators.py` | Indicator definitions (Pine `ta.*`-compatible), all causal                                                                           |
| `rules/library.py`    | 17 parameterised signal templates → ~1,200 distinct signals across 8 categories                                                      |
| `rules/evaluate.py`   | Vectorised, memoised evaluation of the IR over bars                                                                                  |
| `engine/kernel.py`    | Bar-by-bar simulation, optionally Numba-compiled; see [engine.md](engine.md)                                                         |
| `engine/metrics.py`   | 25+ metrics with formulas in the docstrings; selectable fitness functions                                                            |
| `search/generator.py` | Genetic search: tournament selection, crossover, mutation, immigrants, elitism; in-sample only                                       |
| `search/stats.py`     | Deflated Sharpe ratio (selection-bias correction)                                                                                    |
| `robustness/`         | OOS, Monte Carlo, noise, vs-random, permutation, delay, variance, parameter stability, other markets                                 |
| `optimize/`           | Parameter optimisation and walk-forward analysis                                                                                     |
| `export/`             | Python (verified), Pine Script v5, EasyLanguage, NinjaScript, MQL5                                                                   |
| `services.py`         | Workflows used by both CLI and web API                                                                                               |
| `workspace.py`        | Datasets/runs/saved strategies as CSV/JSON under the user data directory                                                             |
| `app/`                | FastAPI JSON API, background job runner, static single-page UI (vanilla JS + vendored uPlot)                                         |

## Technology decisions (summary; full log in [decisions.md](decisions.md))

- **Python 3.11+, numpy, pandas** for the quantitative core: the ecosystem
  standard, easy to audit, and what users already know.
- **Numba (optional)** compiles the simulation kernel and recursive indicators.
  The same source runs uncompiled; tests assert both paths agree bit-for-bit.
  This is the only performance dependency, and it has wheels for Linux and
  macOS (x86-64 and arm64). Rust/C++ were not justified: the compiled kernel
  already runs a 3,000-bar backtest in roughly a millisecond.
- **Local web app** (FastAPI + browser UI on 127.0.0.1) instead of a desktop
  toolkit: identical behaviour on Linux and macOS, no native dependencies, easy
  to test headlessly (the test suite drives the API; a Playwright script drives
  the UI). A desktop wrapper (e.g. pywebview) can be added later without
  changing anything below the adapter layer.
- **No database server.** Plain files are enough for a single-user tool and are
  trivially portable and inspectable.

## Performance (measured on the development container, 4 vCPU, Linux)

| Task                                                                 | Time   |
| -------------------------------------------------------------------- | ------ |
| First backtest (includes Numba compilation, cached afterwards)       | ~2.3 s |
| 100 backtests, 3,000 daily bars, 2 entry signals + 3 exits           | 0.13 s |
| Generation: population 80 × 10 generations (721 distinct strategies) | 0.6 s  |
| Quick robustness suite (8 tests)                                     | ~2 s   |
| Full test suite (59 tests)                                           | ~5 s   |

Unmeasured: macOS timings (CI runs the tests there; no benchmark yet), very
large intraday datasets (>1M bars), memory peak. Generation is single-threaded;
process-level parallelism is on the roadmap.
