# Code export

| Target                                                | Verified how                                                                                                                                         | Known differences from the AlphaForge engine                                                                                                                                                                         |
| ----------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Python (pandas)                                       | **Executed in tests**: 60 random strategies (long/short, all exit types, costs) must reproduce the engine's trade list, P&L and exit reasons exactly | None known                                                                                                                                                                                                           |
| TradingView Pine Script v5                            | Rendered for 40 random strategies; structure checks only                                                                                             | Entry-bar stop/target placed from the signal bar close (Pine cannot know the fill price yet); Pine's intrabar path assumption decides stop-vs-target on bars touching both                                           |
| TradeStation EasyLanguage / MultiCharts PowerLanguage | Structure checks only                                                                                                                                | Recursive indicators (EMA, Wilder RSI/ATR) seeded at the platform's first bar, so values converge to ours after the warm-up guard; `SetDollarTrailing` trails from peak open profit rather than from the bar extreme |
| NinjaTrader 8 NinjaScript                             | Structure checks only                                                                                                                                | Indicators recomputed with our definitions; stops attached after fill in `OnExecutionUpdate`                                                                                                                         |
| MetaTrader 5 MQL5                                     | Structure checks only                                                                                                                                | Broker spread/commission apply instead of the backtest's; `tick_volume` replaces volume; SL/TP computed from the quote at order time                                                                                 |

**Platform exports have not been compiled or run on their platforms** in this
project (no licences or platform runtimes are available in the build
environment). Before trading any export: compile it, backtest it on the platform
over the same data, and compare trade lists with AlphaForge's (`alphaforge
backtest ... -o result.json`).

Every export starts with a header that states the rules, the execution model,
the cost assumptions and a hypothetical-performance warning.
