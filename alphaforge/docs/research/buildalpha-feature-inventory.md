# BuildAlpha feature inventory (public sources)

Collected 2026-10-16. Every row cites where the claim came from and how strongly
it is established. **No BuildAlpha binary, source code, account, or private
backend was accessed.** Nothing here describes BuildAlpha's internal algorithms;
where we implement a comparable capability, the method is our own and is
documented in `docs/architecture.md`.

Evidence levels:

- **Vendor claim**: stated on buildalpha.com. Observed as text, not verified by running the product.
- **Third party**: stated by a review site or forum user. Weaker than a vendor claim.
- **Unknown**: not stated anywhere we could read.

Sources (fetched as rendered text through a web-fetch tool, because this
container's network policy blocks buildalpha.com, see `rea-evaluation.md`):

| ID  | URL                                                                           |
| --- | ----------------------------------------------------------------------------- |
| S1  | https://www.buildalpha.com/                                                   |
| S2  | https://www.buildalpha.com/faq/                                               |
| S3  | https://www.buildalpha.com/buildalpha-features/                               |
| S4  | https://buildalpha.com/robustness-testing-guide                               |
| S5  | https://www.buildalpha.com/how-to-use-buildalpha/                             |
| S6  | https://buildalpha.com/python-trading-strategy-builder                        |
| S7  | https://www.softwaresuggest.com/us/buildalpha                                 |
| S8  | https://elitetrader.com/et/threads/build-alpha-or-gsb.377431/                 |
| S9  | https://buildalpha.com/licensing/ (requires JavaScript; content not readable) |

## Platform and distribution

| Fact                                                                     | Level                 | Source                                                 |
| ------------------------------------------------------------------------ | --------------------- | ------------------------------------------------------ |
| Windows only: "MS Windows 8, 10, 11 (x86 or x64); .NET Framework 4.0"    | Vendor claim          | S2                                                     |
| Mac users are told to run it in a virtual machine; no native macOS build | Vendor claim          | S2                                                     |
| 400 MB RAM minimum, 8 GB+ recommended; 20 MB disk; 1024x768 display      | Vendor claim          | S2                                                     |
| Simulation engine described as C++ ("battle-tested")                     | Vendor claim          | S6                                                     |
| Runs offline for searches; internet needed for data updates              | Vendor claim          | S2                                                     |
| No free trial; live demo on request                                      | Vendor claim          | S2 (S7 says a trial exists; conflicting, S2 preferred) |
| Price: "$2,500/Lifetime"                                                 | Third party           | S7                                                     |
| Price: "$1500 or so was mentioned on the web"                            | Third party (hearsay) | S8                                                     |
| Official price and license terms                                         | Unknown               | S9 needs JavaScript                                    |

## Strategy generation

| Fact                                                                                                                                                                                                                                                                                                              | Level        | Source         |
| ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------ | -------------- |
| Genetic algorithm generates strategies from user-selected entries, exits, risk management, timeframes and assets                                                                                                                                                                                                  | Vendor claim | S1             |
| Point-and-click; no programming required                                                                                                                                                                                                                                                                          | Vendor claim | S1, S2         |
| Signal library of "5,000+" or "7,000+" signals (page is inconsistent)                                                                                                                                                                                                                                             | Vendor claim | S1, S3, S5     |
| Signal categories: price action, technical indicators, volume, volatility, seasonality, breadth, sentiment, yields/spreads, economic data, COT, news, option flows, intermarket, multi-timeframe, fundamentals, weather, gamma exposure, holidays                                                                 | Vendor claim | S1             |
| Price-action signals include OHLC comparisons over the past 10 bars                                                                                                                                                                                                                                               | Vendor claim | S5             |
| All entry signals are usable as exits                                                                                                                                                                                                                                                                             | Vendor claim | S5             |
| Exit types: max holding time, volatility (ATR-like) profit target and stop, trailing stop, profitable close, highest-high/lowest-low lookback                                                                                                                                                                     | Vendor claim | S5             |
| Input fields: Long or Short, Test Dates, Exit Criteria, Market, Entry Signals, Fitness Function, In-Sample Minimum Trades, Out-of-Sample Minimum Trades, Out-of-Sample Percent                                                                                                                                    | Vendor claim | S5             |
| Fitness functions (named): Winning Percentage, Net Profit, Drawdown, Profit to Drawdown Ratio, Ratio Win to Loss, Profit Factor, Average Trade, Sharpe, Sortino, System Quality Number, K-Ratio, CPC Ratio, CAGR, Correlation Coefficient, T-Statistic, System Quality Measure, Perfect Profit Percentage, Custom | Vendor claim | S5             |
| GA settings (population, generations, mutation), max signals per strategy, defaults                                                                                                                                                                                                                               | Unknown      | S5 states none |
| Custom signals via a drag-and-drop editor and Python (pandas, ta-lib, scikit-learn template; parameters between marked comments are optimized by the GA)                                                                                                                                                          | Vendor claim | S3, S6         |
| AI prompt converts a plain-English indicator into native signals                                                                                                                                                                                                                                                  | Vendor claim | S3             |
| Ensembles: strategies as signals for other strategies; voting                                                                                                                                                                                                                                                     | Vendor claim | S3             |
| Rebalance strategies (rank a universe, trade top/bottom)                                                                                                                                                                                                                                                          | Vendor claim | S3             |

## Data

| Fact                                                                               | Level                     | Source |
| ---------------------------------------------------------------------------------- | ------------------------- | ------ |
| Markets: stocks, ETFs, futures, forex (30 majors), crypto                          | Vendor claim              | S1, S2 |
| Intraday bars 1, 2, 5, 10, 15, 30, 60, 120, 240 min; daily; custom bar types       | Vendor claim              | S2     |
| Import custom TXT/CSV data and trade lists                                         | Vendor claim              | S1     |
| Providers named: Norgate, Massive, Binance, Kraken, KuCoin; Kinetick (NinjaTrader) | Vendor claim              | S1, S2 |
| Imported strategies can be stress-tested but not optimized                         | Vendor claim              | S2     |
| Streaming/live data not yet available (FAQ) vs "live data connections" (home page) | Vendor claim, conflicting | S1, S2 |

## Robustness and validation

Pass thresholds are mostly not published (S4 "General gaps").

| Test                               | What the vendor says it does                                                        | Source |
| ---------------------------------- | ----------------------------------------------------------------------------------- | ------ |
| Out-of-sample                      | Build on in-sample (commonly first 70%), test once on the rest                      | S4     |
| Randomized OOS                     | Randomly assign bars to IS/OOS, label trades by entry date, repeat 1,000+ times     | S4     |
| Walk-forward                       | Re-optimize per IS window, trade next OOS window, stitch OOS equity                 | S4     |
| Vs Random                          | Compare against the _best_ random strategy on the optimized metric; optional margin | S3, S4 |
| Monte Carlo permutation (MCPT)     | Shuffle log returns into 1,000+ synthetic paths; p-value                            | S4     |
| Noise test                         | Perturb a share of O/H/L/C by up to a fraction of ATR; 1,000 series                 | S3, S4 |
| Vs Shifted                         | Shift bar start times (e.g. 10:03 vs 10:00)                                         | S4     |
| Vs Others                          | Run on related markets                                                              | S3, S4 |
| Synthetic stress                   | Synthetic series filtered by rules (e.g. deeper drawdown than history)              | S4     |
| MC reshuffle / resample            | Reorder trades 1,000 times / draw with replacement                                  | S4     |
| Randomized exit test               | Randomly vary exit parameters per trade, 1,000+ times                               | S4     |
| Variance test                      | Degrade a metric (e.g. win rate −5%) and simulate forward N trades                  | S3, S4 |
| Delayed entries/exits              | Enter or exit 1–2 bars late                                                         | S3, S4 |
| Liquidity test                     | Fill at averaged prices (close/next open/next close/midpoint)                       | S4     |
| Parameter permutation              | ±~10% neighbors; reject spiky optima, wide spread, unprofitable median/25th pct     | S4     |
| Noise-test optimization            | Choose parameters that work across noise-adjusted data                              | S3, S4 |
| Taguchi robust design              | Judge designs on mean and variation across noise factors                            | S4     |
| Edge ratio (E-ratio)               | Favourable vs adverse excursion by bars since signal                                | S3     |
| Health scores, Intelligence Report | Ongoing monitoring; suggestions for saved strategies                                | S1, S3 |

## Optimization and portfolio

| Fact                                                                                          | Level        | Source |
| --------------------------------------------------------------------------------------------- | ------------ | ------ |
| Parameter optimization with sensitivity analysis and 3D surface; optional noise-adjusted data | Vendor claim | S1, S3 |
| Mean-variance portfolio weights; correlation matrix                                           | Vendor claim | S3     |
| Multi-strategy portfolio simulation with per-strategy sizing; AI "Portfolio Suggest"          | Vendor claim | S3     |
| Equity-curve trading overlay; regime switching (park cash in another asset)                   | Vendor claim | S3     |
| Intraday Edge: restrict daily strategies to intraday windows                                  | Vendor claim | S1, S3 |
| Seasonality and signal breakdowns                                                             | Vendor claim | S3     |

## Export and live trading

| Fact                                                                                                                                                                                                             | Level                      | Source                      |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------- | --------------------------- |
| Code export: TradeStation (EasyLanguage), MultiCharts (PowerLanguage), NinjaTrader 8 (C#), MetaTrader 4/5 (MQL), TradingView (Pine Script), ProRealTime (ProBuilder), Python for Interactive Brokers (ib_insync) | Vendor claim               | S1, S2, S6                  |
| Claim that results "match seamlessly across platforms"                                                                                                                                                           | Vendor claim, not verified | S1 (S6 makes no such claim) |
| Live monitoring through TradeStation and Interactive Brokers                                                                                                                                                     | Vendor claim               | S1, S3                      |
| Direct trading in-app "coming very soon"                                                                                                                                                                         | Vendor claim               | S1                          |

## What cannot be discovered remotely

- The GA's encoding, operators, population sizes and selection rules.
- The exact signal definitions behind the 5,000–7,000 signal library (names are marketing-level).
- Fill model details (intrabar stop/target ordering, gap handling), default costs.
- Exact formulas for proprietary metrics (e.g. "System Quality Measure", "Perfect Profit Percentage") and robustness pass thresholds.
- How exported code achieves parity with the internal engine.

Obtaining these would require running or decompiling a licensed copy. BuildAlpha
has no public trial, and decompiling licensed software can breach its license,
so this project does not attempt it. Our implementation defines and documents its
own semantics instead, which is the honest basis for an independent product.
