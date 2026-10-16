# Decision log

Newest last. Each entry: decision, reason, alternatives, how to revisit.

## D1 · 2026-10-16 · Build from public information only

BuildAlpha is closed-source, Windows-only (.NET Framework 4.0) and has no public
trial. We use its public website and documentation to inventory features and
design our own implementation. We do not obtain, decompile or copy its program.
_Revisit if:_ the owner holds a licence whose terms permit analysis and asks for
interoperability research (e.g. import of its strategy files).

## D2 · 2026-10-16 · REA used for verified web observation; desktop analysis not attempted

REA 6.5.0 was built, registered as a local-scope MCP server for Claude Code and
verified (207 tools listed; browser inspection works). buildalpha.com is blocked
by the cloud environment's network policy, so the inventory used a web-fetch
tool. See `research/rea-evaluation.md`.
_Revisit when:_ buildalpha.com is allowed, to capture citable page Evidence.

## D3 · 2026-10-16 · Product lives in `alphaforge/` on a branch of BoomBloom/rea

No dedicated repository exists. The application is fully self-contained in its
own top-level directory with its own Python packaging and CI workflow, and does
not touch REA's code. _Revisit:_ move to a dedicated repository with
`git subtree split -P alphaforge` when one is created (history is preserved).

## D4 · 2026-10-16 · Python core with optional Numba

numpy/pandas for data and indicators; the simulation loop written once in plain
Python and compiled by Numba when available. Alternatives: Rust (PyO3) or C++
kernel — rejected because the compiled kernel already runs ~1 ms per 3,000-bar
backtest and a second language would add build complexity on macOS/Linux
without measurable benefit. _Revisit if:_ profiling shows the kernel dominates
on million-bar intraday searches.

## D5 · 2026-10-16 · Local web application rather than a desktop toolkit

FastAPI on 127.0.0.1 plus a dependency-free browser UI. Same code path on Linux
and macOS, no Qt/GTK/Electron packaging, headless-testable. Alternatives: PySide6
(heavy, platform packaging quirks), Electron (second runtime), Streamlit/NiceGUI
(less control over job handling and layout). _Revisit:_ wrap in pywebview for a
native window if users want one; no engine changes needed.

## D6 · 2026-10-16 · One execution model: decide at close, fill at next open

Removes the most common look-ahead bug and maps directly to all export targets
(Pine default, EasyLanguage "next bar at market", NinjaScript OnBarClose, MQL5
new-bar logic). Same-bar-close execution may be added later as an explicit,
labelled option.

## D7 · 2026-10-16 · Stop fills first when stop and target share a bar

OHLC data cannot reveal intrabar order; the pessimistic choice avoids inflating
results. Documented in `engine.md`.

## D8 · 2026-10-16 · Selection uses in-sample data only; OOS is reported, not optimised

The genetic search runs the simulator only on in-sample bars, enforced by a
test that scrambles OOS data. The single exception is the optional minimum OOS
trade count filter on reported results (a weak, documented use of OOS).

## D9 · 2026-10-16 · Default fitness = net profit / max drawdown

Profit factor rewarded "never take a loss" strategies (no stop + exit on first
profitable close) with near-infinite values. Mark-to-market drawdown penalises
holding losers. Users can pick 15 other fitness functions.

## D10 · 2026-10-16 · Python export is the verified reference export

Only the Python export is executed in tests (exact trade-list parity). Platform
exports are generated from the same IR with documented differences, and are
marked unverified until compiled on their platforms.

## D11 · 2026-10-16 · Deflated Sharpe ratio shown for every generated strategy

The number of strategies tried is the dominant source of false discoveries in
strategy mining. Reporting DSR next to every result keeps that visible.
