"""Bar-by-bar trade simulation kernel.

Execution model (identical for every strategy, documented in docs/engine.md):

1. Rules are evaluated on completed bars. A decision made at the close of bar t
   is executed with a market order at the open of bar t+1. There is no
   same-bar-close execution, which removes the most common look-ahead bug.
2. At the open of each bar, pending exits fill first, then pending entries.
   Only one position is held at a time; entries are considered only when flat
   at a bar close.
3. Stop, trailing-stop and target levels are fixed from ATR on the signal bar
   and the actual entry fill price. They are active from the entry bar on.
   If the bar opens through a level the fill is at the open (gaps hurt stops and
   help targets). If a stop and a target are both touched within one bar the
   stop is assumed to fill first (conservative, because intrabar order is unknown).
4. Market and stop fills pay ``slip`` adverse price per side; target (limit)
   fills do not. Commission is charged per unit per side.
5. An open position at the last bar is closed at that bar's close (with slippage).

Exit reason codes: 1 stop, 2 target, 3 trailing stop, 4 time, 5 exit signal,
6 profitable close, 7 end of data.
"""

from __future__ import annotations

import numpy as np

from .._jit import jit

REASONS = {1: "stop", 2: "target", 3: "trail", 4: "time", 5: "signal", 6: "profit_close", 7: "end"}


@jit
def simulate(
    o,
    h,
    lo,
    c,
    entry,
    exit_sig,
    atr,
    direction,
    stop_mult,
    target_mult,
    trail_mult,
    max_bars,
    profitable_close,
    slip,
    comm,
    qty,
    point_value,
    start,
    end,
):
    n_cap = (end - start) // 2 + 2
    t_entry_idx = np.empty(n_cap, np.int64)
    t_exit_idx = np.empty(n_cap, np.int64)
    t_entry_px = np.empty(n_cap, np.float64)
    t_exit_px = np.empty(n_cap, np.float64)
    t_reason = np.empty(n_cap, np.int64)
    t_pnl = np.empty(n_cap, np.float64)
    t_mae = np.empty(n_cap, np.float64)
    t_mfe = np.empty(n_cap, np.float64)
    equity = np.zeros(end - start, np.float64)
    in_market = np.zeros(end - start, np.bool_)

    d = direction
    mult = qty * point_value
    realized = 0.0
    pos = 0
    n_tr = 0
    pending_entry = False
    pending_exit = 0
    entry_px = 0.0
    entry_i = 0
    bars_in = 0
    stop = np.nan
    target = np.nan
    trail = np.nan
    ref_atr = np.nan
    extreme = 0.0
    worst = 0.0
    best = 0.0

    for t in range(start, end):
        # ---- open of bar t: pending market orders
        if pos != 0 and pending_exit != 0:
            px = o[t] - d * slip
            pnl = d * (px - entry_px) * mult - 2.0 * comm * qty
            realized += d * (px - entry_px) * mult - comm * qty
            t_entry_idx[n_tr] = entry_i
            t_exit_idx[n_tr] = t
            t_entry_px[n_tr] = entry_px
            t_exit_px[n_tr] = px
            t_reason[n_tr] = pending_exit
            t_pnl[n_tr] = pnl
            t_mae[n_tr] = worst * mult
            t_mfe[n_tr] = best * mult
            n_tr += 1
            pos = 0
        pending_exit = 0
        if pos == 0 and pending_entry:
            ref_atr = atr[t - 1]
            entry_px = o[t] + d * slip
            entry_i = t
            bars_in = 0
            realized -= comm * qty
            stop = entry_px - d * stop_mult * ref_atr if stop_mult > 0 else np.nan
            target = entry_px + d * target_mult * ref_atr if target_mult > 0 else np.nan
            trail = entry_px - d * trail_mult * ref_atr if trail_mult > 0 else np.nan
            extreme = entry_px
            worst = 0.0
            best = 0.0
            pos = d
        pending_entry = False

        # ---- intrabar: protective and target orders
        if pos != 0:
            bars_in += 1
            exit_px = np.nan
            reason = 0
            # effective protective level: the tighter of stop and trailing stop
            prot = stop
            prot_reason = 1
            if not np.isnan(trail):
                if np.isnan(prot) or (d == 1 and trail > prot) or (d == -1 and trail < prot):
                    prot = trail
                    prot_reason = 3
            if not np.isnan(prot):
                if d == 1 and lo[t] <= prot:
                    exit_px = (o[t] if o[t] < prot else prot) - slip
                    reason = prot_reason
                elif d == -1 and h[t] >= prot:
                    exit_px = (o[t] if o[t] > prot else prot) + slip
                    reason = prot_reason
            if reason == 0 and not np.isnan(target):
                if d == 1 and h[t] >= target:
                    exit_px = o[t] if o[t] > target else target
                    reason = 2
                elif d == -1 and lo[t] <= target:
                    exit_px = o[t] if o[t] < target else target
                    reason = 2
            # excursions are measured before the exit price is known
            adverse = (lo[t] - entry_px) if d == 1 else (entry_px - h[t])
            favour = (h[t] - entry_px) if d == 1 else (entry_px - lo[t])
            if reason != 0:
                # nothing after an intrabar exit counts towards the trade's excursions
                ex_move = d * (exit_px - entry_px)
                if reason == 1 or reason == 3:
                    adverse = max(adverse, ex_move)
                elif reason == 2:
                    favour = min(favour, ex_move)
            if adverse < worst:
                worst = adverse
            if favour > best:
                best = favour
            if reason != 0:
                pnl = d * (exit_px - entry_px) * mult - 2.0 * comm * qty
                realized += d * (exit_px - entry_px) * mult - comm * qty
                t_entry_idx[n_tr] = entry_i
                t_exit_idx[n_tr] = t
                t_entry_px[n_tr] = entry_px
                t_exit_px[n_tr] = exit_px
                t_reason[n_tr] = reason
                t_pnl[n_tr] = pnl
                t_mae[n_tr] = worst * mult
                t_mfe[n_tr] = best * mult
                n_tr += 1
                pos = 0

        # ---- close of bar t
        if pos != 0:
            if t == end - 1:
                px = c[t] - d * slip
                pnl = d * (px - entry_px) * mult - 2.0 * comm * qty
                realized += d * (px - entry_px) * mult - comm * qty
                t_entry_idx[n_tr] = entry_i
                t_exit_idx[n_tr] = t
                t_entry_px[n_tr] = entry_px
                t_exit_px[n_tr] = px
                t_reason[n_tr] = 7
                t_pnl[n_tr] = pnl
                t_mae[n_tr] = worst * mult
                t_mfe[n_tr] = best * mult
                n_tr += 1
                pos = 0
            else:
                if trail_mult > 0:
                    if d == 1 and h[t] > extreme:
                        extreme = h[t]
                    elif d == -1 and lo[t] < extreme:
                        extreme = lo[t]
                    cand = extreme - d * trail_mult * ref_atr
                    if (d == 1 and cand > trail) or (d == -1 and cand < trail):
                        trail = cand
                if max_bars > 0 and bars_in >= max_bars:
                    pending_exit = 4
                elif exit_sig[t]:
                    pending_exit = 5
                elif profitable_close and d * (c[t] - entry_px) > 0:
                    pending_exit = 6
        if pos == 0 and t < end - 1 and entry[t]:
            need_atr = stop_mult > 0 or target_mult > 0 or trail_mult > 0
            if (not need_atr) or (not np.isnan(atr[t])):
                pending_entry = True
        open_pnl = d * (c[t] - entry_px) * mult if pos != 0 else 0.0
        equity[t - start] = realized + open_pnl
        in_market[t - start] = pos != 0

    return (
        t_entry_idx[:n_tr],
        t_exit_idx[:n_tr],
        t_entry_px[:n_tr],
        t_exit_px[:n_tr],
        t_reason[:n_tr],
        t_pnl[:n_tr],
        t_mae[:n_tr],
        t_mfe[:n_tr],
        equity,
        in_market,
    )
