"""Performance metrics with explicit formulas.

All money figures are in account currency. ``equity`` is cumulative P&L
(mark-to-market at bar closes, net of costs), starting at 0. Returns used for
Sharpe/Sortino are per-bar changes in equity divided by (capital + previous
equity), annualised with the observed bar frequency.
"""

from __future__ import annotations

import math

import numpy as np

# Fitness functions selectable in the UI/CLI: key -> (label, higher_is_better)
FITNESS = {
    "net_profit": ("Net profit", True),
    "profit_factor": ("Profit factor", True),
    "sharpe": ("Sharpe ratio", True),
    "sortino": ("Sortino ratio", True),
    "return_dd": ("Net profit / max drawdown", True),
    "win_rate": ("Win rate", True),
    "avg_trade": ("Average trade", True),
    "win_loss_ratio": ("Average win / average loss", True),
    "sqn": ("System quality number", True),
    "t_stat": ("Trade t-statistic", True),
    "k_ratio": ("K-ratio", True),
    "cpc": ("CPC ratio", True),
    "cagr": ("CAGR", True),
    "equity_r2": ("Equity curve R²", True),
    "max_drawdown": ("Max drawdown (smaller is better)", False),
}


def bars_per_year(time_ns: np.ndarray) -> float:
    if len(time_ns) < 3:
        return 252.0
    span_years = (time_ns[-1] - time_ns[0]) / 1e9 / (365.25 * 86400)
    if span_years <= 0:
        return 252.0
    return (len(time_ns) - 1) / span_years


def _safe(x: float) -> float:
    if x is None or not np.isfinite(x):
        return 0.0
    return float(x)


def compute(
    pnl: np.ndarray,
    equity: np.ndarray,
    in_market: np.ndarray,
    bars_held: np.ndarray,
    time_ns: np.ndarray,
    capital: float,
) -> dict:
    """Compute metrics for one segment (trades and the equity slice that belongs to it)."""
    n = int(len(pnl))
    m: dict[str, float] = {"trades": n}
    wins = pnl[pnl > 0]
    losses = pnl[pnl <= 0]
    gp = float(wins.sum())
    gl = float(-losses.sum())
    m["net_profit"] = float(pnl.sum())
    m["gross_profit"] = gp
    m["gross_loss"] = gl
    m["profit_factor"] = gp / gl if gl > 0 else (float("inf") if gp > 0 else 0.0)
    m["win_rate"] = len(wins) / n if n else 0.0
    m["avg_trade"] = m["net_profit"] / n if n else 0.0
    m["avg_win"] = float(wins.mean()) if len(wins) else 0.0
    m["avg_loss"] = float(losses.mean()) if len(losses) else 0.0
    m["win_loss_ratio"] = m["avg_win"] / -m["avg_loss"] if m["avg_loss"] < 0 else (float("inf") if m["avg_win"] > 0 else 0.0)
    m["largest_win"] = float(pnl.max()) if n else 0.0
    m["largest_loss"] = float(pnl.min()) if n else 0.0
    sd = float(pnl.std(ddof=1)) if n > 1 else 0.0
    # Van Tharp SQN, trade count capped at 100 so it measures quality, not quantity
    m["sqn"] = math.sqrt(min(n, 100)) * m["avg_trade"] / sd if sd > 0 else 0.0
    m["t_stat"] = math.sqrt(n) * m["avg_trade"] / sd if sd > 0 else 0.0
    m["cpc"] = (m["profit_factor"] * m["win_rate"] * m["win_loss_ratio"]) if np.isfinite(m["profit_factor"]) and np.isfinite(m["win_loss_ratio"]) else 0.0
    m["avg_bars"] = float(bars_held.mean()) if n else 0.0
    m["exposure"] = float(in_market.mean()) if len(in_market) else 0.0

    eq = equity
    if len(eq):
        peak = np.maximum.accumulate(np.r_[0.0, eq])[1:]
        dd = eq - peak
        m["max_drawdown"] = float(-dd.min())
        acct_peak = capital + peak
        m["max_drawdown_pct"] = float((-(dd / acct_peak)).max()) if (acct_peak > 0).all() else 1.0
        # Ulcer index on percentage drawdowns
        m["ulcer_index"] = float(np.sqrt(np.mean((100 * dd / acct_peak) ** 2))) if (acct_peak > 0).all() else 0.0
    else:
        m["max_drawdown"] = m["max_drawdown_pct"] = m["ulcer_index"] = 0.0
    m["return_dd"] = m["net_profit"] / m["max_drawdown"] if m["max_drawdown"] > 0 else (float("inf") if m["net_profit"] > 0 else 0.0)

    bpy = bars_per_year(time_ns)
    if len(eq) > 2:
        acct = capital + np.r_[0.0, eq]
        rets = np.diff(acct) / acct[:-1]
        mu, sig = rets.mean(), rets.std(ddof=1)
        m["sharpe"] = mu / sig * math.sqrt(bpy) if sig > 0 else 0.0
        down = np.minimum(rets, 0.0)
        dsd = math.sqrt(np.mean(down**2))
        m["sortino"] = mu / dsd * math.sqrt(bpy) if dsd > 0 else 0.0
        years = len(eq) / bpy
        final = acct[-1] / capital
        m["cagr"] = final ** (1 / years) - 1 if final > 0 and years > 0 else -1.0
        # K-ratio (Kestner 2003 form): slope of equity regression / (stderr * sqrt(n))
        x = np.arange(len(eq), dtype=np.float64)
        xm = x - x.mean()
        sxx = float((xm**2).sum())
        slope = float((xm * (eq - eq.mean())).sum() / sxx)
        resid = eq - (eq.mean() + slope * xm)
        se = math.sqrt(float((resid**2).sum()) / (len(eq) - 2) / sxx) if len(eq) > 2 else 0.0
        m["k_ratio"] = slope / (se * math.sqrt(len(eq))) if se > 0 else 0.0
        ss_tot = float(((eq - eq.mean()) ** 2).sum())
        r2 = 1 - float((resid**2).sum()) / ss_tot if ss_tot > 0 else 0.0
        m["equity_r2"] = r2 if slope > 0 else -r2
    else:
        m["sharpe"] = m["sortino"] = m["cagr"] = m["k_ratio"] = m["equity_r2"] = 0.0
    capped = ("profit_factor", "win_loss_ratio", "return_dd")
    out = {k: ((float(v) if np.isfinite(v) else 999.0) if k in capped else _safe(v)) for k, v in m.items()}
    out["trades"] = n
    return out


def fitness_value(metrics: dict, key: str) -> float:
    if key not in FITNESS:
        raise ValueError(f"unknown fitness {key!r}")
    v = metrics.get(key, 0.0)
    return v if FITNESS[key][1] else -v
