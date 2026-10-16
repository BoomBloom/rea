# AlphaForge

Independent, open-source strategy generation, backtesting, robustness testing
and code export for systematic traders. Runs locally on **Linux and macOS**.

AlphaForge was designed from the publicly documented feature set of commercial
strategy builders such as BuildAlpha (see
[docs/research/buildalpha-feature-inventory.md](docs/research/buildalpha-feature-inventory.md)).
It contains no code from any of them and is not affiliated with any vendor.

> **Backtests are hypothetical.** A strategy found by searching historical data
> is expected to look better than it will trade. AlphaForge shows out-of-sample
> results, robustness tests and a selection-bias-adjusted (deflated) Sharpe
> ratio to help you judge that, but no test proves future profitability.

## What it does

- **Import data** from CSV/TXT (TradeStation, NinjaTrader, MetaTrader, Yahoo and
  generic layouts) with a validation report, or generate synthetic null data.
- **Generate strategies** with a genetic search over ~1,200 signals (price
  action, trend, oscillators, breakouts, volatility, momentum, volume,
  seasonality) and ATR stops, targets, trailing stops, time, signal and
  profitable-close exits. Selection uses in-sample data only.
- **Backtest** with a documented execution model: decide at bar close, fill at
  next open, commission and slippage on every fill, conservative intrabar
  stop/target handling ([docs/engine.md](docs/engine.md)).
- **Test robustness**: out-of-sample, Monte Carlo, noise, vs random entries,
  permutation, delayed entry, win-rate variance, parameter stability, other
  markets, walk-forward ([docs/robustness.md](docs/robustness.md)).
- **Export code** for Python (verified against the engine), TradingView Pine
  Script, TradeStation/MultiCharts EasyLanguage, NinjaTrader 8 and MetaTrader 5
  ([docs/export.md](docs/export.md)).

## Install

Requires Python 3.11 or newer. Works the same on Linux and macOS (Intel and
Apple Silicon).

```bash
cd alphaforge
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[fast]"        # [fast] adds Numba; omit it to run pure Python
```

With [uv](https://docs.astral.sh/uv/): `uv venv && uv pip install -e ".[fast]"`.

macOS notes: use a python.org, Homebrew or uv-managed Python 3.11+. Apple's
system Python 3.9 is too old. No compiler or Xcode tools are needed; all
dependencies ship wheels for macOS arm64 and x86-64.

## Use the app

```bash
alphaforge serve --open        # http://127.0.0.1:8765
```

1. **Data**: import a CSV (set point value and tick size for futures, e.g. ES =
   50 / 0.25) or create a synthetic dataset to try things out.
2. **Build**: choose direction, fitness, exits, costs and search size; start.
3. **Results**: compare in-sample and out-of-sample metrics and the deflated
   Sharpe ratio; click a row.
4. **Strategy**: equity and drawdown, trades, robustness tests, walk-forward,
   code export, save.

Data and results are stored under `~/.local/share/AlphaForge` (Linux) or
`~/Library/Application Support/AlphaForge` (macOS); set `ALPHAFORGE_HOME` to
change it.

## Use the CLI

```bash
alphaforge demo-data demo.csv --mean-reversion 0.15
alphaforge generate demo.csv --population 120 --generations 25 --quantity 100 \
    --commission 0.005 --slippage 1 -o run.json
python - <<'EOF'
import json; r = json.load(open("run.json"))["results"][0]
json.dump(r["strategy"], open("best.json", "w"), indent=2)
EOF
alphaforge backtest demo.csv best.json
alphaforge robustness demo.csv best.json --quick
alphaforge walkforward demo.csv best.json --windows 5
alphaforge export best.json --target pine -o best.pine
```

`alphaforge <command> --help` lists all options.

## Develop

```bash
uv venv && uv pip install -e ".[dev]"
pytest                                   # with Numba
ALPHAFORGE_DISABLE_JIT=1 pytest          # pure-Python path
```

The suite covers hand-computed fills and costs, look-ahead (truncation)
properties, out-of-sample isolation of the search, exact trade parity of the
Python export, data import formats, robustness invariants and the HTTP API. CI
runs it on Ubuntu and macOS (`.github/workflows/alphaforge.yml`).

Documentation: [architecture](docs/architecture.md) ·
[engine semantics](docs/engine.md) · [robustness](docs/robustness.md) ·
[export](docs/export.md) · [decisions](docs/decisions.md) ·
[roadmap](docs/roadmap.md) · [REA evaluation](docs/research/rea-evaluation.md)

## Licence

MIT. Vendored: uPlot (MIT, `src/alphaforge/app/static/vendor/uPlot.LICENSE`).
