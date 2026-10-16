# Roadmap

Status key: ✅ done · 🚧 in progress · ⏭ next · 💡 later

## Phase 0 — Research (✅)

- ✅ REA inspected, built, registered and verified; limits documented
- ✅ BuildAlpha feature inventory from public sources, with evidence levels
- ✅ Architecture and technology decisions recorded

## Phase 1 — Core engine (✅)

- ✅ CSV/TXT import (TradeStation, NinjaTrader, MetaTrader, Yahoo layouts) with validation report
- ✅ Synthetic data generator (null-hypothesis data)
- ✅ Rule IR, 17 signal templates (~1,200 signals), causal indicators
- ✅ Kernel: next-open execution, ATR stops/targets/trailing, time/signal/profitable-close exits, commission and slippage
- ✅ Metrics and 15 fitness functions

## Phase 2 — Discovery and validation (✅)

- ✅ Genetic generator with in-sample-only selection and duplicate-trade filtering
- ✅ Robustness suite: OOS, Monte Carlo, noise, vs random, permutation, delay, variance, parameter stability, other markets
- ✅ Walk-forward analysis (rolling/anchored)
- ✅ Deflated Sharpe ratio per result

## Phase 3 — Product surface (✅ first version)

- ✅ Exports: Python (verified), Pine v5, EasyLanguage, NinjaScript, MQL5
- ✅ CLI (`generate`, `backtest`, `robustness`, `walkforward`, `export`, `validate`, `serve`)
- ✅ Local web UI: data, build with live progress, results table, strategy page with equity/drawdown, robustness, walk-forward, export, saved strategies
- ✅ Test suite (59 tests) on Linux; CI workflow for Linux + macOS

## Phase 4 — Next (highest value first)

1. ⏭ Verify CI green on macOS runners (arm64 and x86-64) and record timings
2. ⏭ Parallel generation (process pool; spawn-safe for macOS)
3. ⏭ Percent-of-equity and volatility-targeted position sizing
4. ⏭ Portfolio of strategies: combined equity, correlation matrix, weights
5. ⏭ Selection-aware permutation test (re-run search on permuted data, small budget)
6. ⏭ More signal families: multi-timeframe, intermarket (second dataset), time-of-day for intraday
7. ⏭ Data connectors (optional, user-supplied keys): Yahoo/Stooq daily, broker CSV presets
8. 💡 Compile-check platform exports in CI where free toolchains exist (none for EasyLanguage/MQL5); a Pine linter
9. 💡 Desktop window wrapper (pywebview) and one-file installers (PyInstaller/Briefcase) for macOS and Linux
10. 💡 Sequence workflows (multi-round filters), equity-curve trading, regime filters
11. 💡 Strategy import from text rules

## Resuming work

- Code: `alphaforge/` on branch `claude/buildalpha-alternative-j9ysas` of BoomBloom/rea.
- Run `cd alphaforge && uv venv && uv pip install -e ".[dev]" && pytest`.
- Read `docs/decisions.md` before changing the execution model or selection logic.
