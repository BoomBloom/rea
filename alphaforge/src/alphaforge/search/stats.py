"""Multiple-testing corrections for data-mined strategies.

When thousands of rule combinations are searched, the best in-sample Sharpe is
inflated by selection alone. The Deflated Sharpe Ratio (Bailey & López de Prado,
2014, "The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest
Overfitting and Non-Normality") estimates the probability that the true Sharpe
exceeds zero after accounting for the number of trials, their dispersion, the
sample length and the skew/kurtosis of returns.
"""

from __future__ import annotations

import math
from statistics import NormalDist

import numpy as np

_N = NormalDist()
EULER_GAMMA = 0.5772156649015329


def expected_max_sharpe(n_trials: int, sharpe_var: float) -> float:
    """Expected maximum of n_trials Sharpe estimates with the given variance under a zero-skill null."""
    if n_trials <= 1 or sharpe_var <= 0:
        return 0.0
    a = _N.inv_cdf(1 - 1 / n_trials)
    b = _N.inv_cdf(1 - 1 / (n_trials * math.e))
    return math.sqrt(sharpe_var) * ((1 - EULER_GAMMA) * a + EULER_GAMMA * b)


def deflated_sharpe(returns: np.ndarray, n_trials: int, trial_sharpes_per_period: np.ndarray | None = None) -> dict:
    """Return the per-period Sharpe, the selection-adjusted benchmark SR0 and DSR (a probability).

    ``returns`` are per-bar strategy returns. ``trial_sharpes_per_period`` are the
    (non-annualised) Sharpe ratios of all strategies tried; when absent, the
    variance of the Sharpe estimator under the null (1/T) is used.
    """
    r = np.asarray(returns, dtype=np.float64)
    r = r[np.isfinite(r)]
    t = len(r)
    if t < 3 or r.std(ddof=1) == 0:
        return {"sharpe": 0.0, "sr0": 0.0, "dsr": 0.0, "n_trials": n_trials, "observations": t}
    sr = r.mean() / r.std(ddof=1)
    z = (r - r.mean()) / r.std(ddof=0)
    skew = float(np.mean(z**3))
    kurt = float(np.mean(z**4))
    if trial_sharpes_per_period is not None and len(trial_sharpes_per_period) > 1:
        var = float(np.var(trial_sharpes_per_period, ddof=1))
    else:
        var = 1.0 / t
    sr0 = expected_max_sharpe(max(int(n_trials), 1), var)
    denom = 1 - skew * sr + (kurt - 1) / 4 * sr**2
    denom = math.sqrt(denom) if denom > 0 else float("nan")
    dsr = _N.cdf((sr - sr0) * math.sqrt(t - 1) / denom) if denom == denom else 0.0
    return {"sharpe": float(sr), "sr0": float(sr0), "dsr": float(dsr), "skew": skew, "kurtosis": kurt, "n_trials": int(n_trials), "observations": t}
