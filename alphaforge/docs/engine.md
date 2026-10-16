# Backtest engine semantics

This page is the contract. The kernel (`engine/kernel.py`), the Python export
and the tests all implement exactly this.

## Timing

- Rules are evaluated on **completed bars**. A decision at the close of bar _t_
  becomes a **market order at the open of bar _t+1_**. Nothing executes at the
  close of the bar whose close triggered it.
- Indicator values at bar _t_ use data at bars ≤ _t_ only. Lags must be ≥ 0
  (negative lags are rejected when the rule is built).
- Warm-up: indicators are NaN until they have enough history; any comparison
  with NaN is false, so no trade can be triggered by a partial indicator.

## Order of events within bar _t_

1. **Open**: pending market exit fills (`open − dir × slippage`), then a pending
   entry fills (`open + dir × slippage`). One position at a time; entries are
   only considered when flat at a bar close.
2. **Intrabar**: protective stop (the tighter of fixed stop and trailing stop)
   and profit target are checked against the bar's low/high.
   - A level that the bar _opens through_ fills at the open (gaps hurt stops,
     help targets).
   - If both stop and target are touched in the same bar, the **stop** fills
     (conservative: intrabar order is unknown from OHLC).
   - Stops pay slippage; targets (limit orders) do not.
   - Stops and targets are active on the entry bar, measured from the actual
     entry fill and ATR of the signal bar.
3. **Close**: the trailing stop ratchets using the bar's extreme; time, signal
   and profitable-close exits are decided for the next open; if flat and the
   entry rule is true, an entry is queued for the next open. An open position on
   the final bar is closed at that bar's close (with slippage).

## Exits

| Exit             | Definition                                                                                                    |
| ---------------- | ------------------------------------------------------------------------------------------------------------- |
| Stop             | `entry − dir × k × ATR(n)[signal bar]`                                                                        |
| Target           | `entry + dir × k × ATR(n)[signal bar]`                                                                        |
| Trailing stop    | starts at `entry − dir × k × ATR`; after each close moves to `extreme since entry − dir × k × ATR` if tighter |
| Max bars         | the entry bar counts as bar 1; after the N-th bar's close, exit at the next open                              |
| Exit signal      | signal true at a close → exit at the next open                                                                |
| Profitable close | first close beyond the entry price → exit at the next open                                                    |

Precedence at a close: time exit, then exit signal, then profitable close (only
one exit is queued; the reason recorded is the first that applies).

## Costs and money

- `pnl = dir × (exit − entry) × quantity × point_value − 2 × commission × quantity`.
- Slippage is `slippage_ticks × tick_size` price units per side.
- Equity is mark-to-market at each close; the entry commission is charged at
  entry, the exit commission at exit.
- Position size is a fixed quantity. Percent-of-equity sizing is on the roadmap.

## In-sample / out-of-sample

The last `oos_fraction` of bars is out-of-sample. During generation the
simulator is run only on bars `[0, split)`, so out-of-sample prices are never
read for selection (`tests/test_generator.py::test_selection_never_reads_out_of_sample`
scrambles every out-of-sample bar and asserts the search is unchanged).
Reported metrics come from one full run, with trades assigned to a segment by
**entry bar**. A trade entered in-sample that is still open at the split is
therefore reported in-sample with its real exit.

## Metrics

Formulas are in `engine/metrics.py`. Notes:

- Profit factor, win/loss ratio and net/max-DD are reported as 999 when the
  denominator is zero (no losses), instead of infinity.
- Sharpe and Sortino use per-bar returns on `capital + equity`, annualised with
  the observed bar frequency, risk-free rate 0.
- SQN caps the trade count at 100 (quality, not quantity).
- K-ratio: slope of a linear fit of equity divided by (standard error × √n).

## Known simplifications

- One instrument per strategy, one position at a time, no pyramiding.
- No bid/ask modelling beyond slippage; no partial fills; no borrow costs, swap
  or funding; no margin calls. Results are not adjusted for dividends unless the
  data is.
- Intrabar path is unknown; the stop-first rule is pessimistic for strategies
  whose stop and target are both within a typical bar range.
