# Robustness tests

Every test is seeded (reproducible) and returns its inputs, a distribution
summary, a verdict and the rule behind it. The thresholds are AlphaForge's own
defaults, chosen to be conservative and simple to explain; they are not claims
about any other product. **A pass is evidence against overfitting, never proof of
future profitability.**

| Test                   | Method                                                                                                                   | Verdict rule                                                                                                                  |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------- |
| Out-of-sample          | Metrics on the held-out last part of the data                                                                            | pass: OOS profitable with PF ≥ 1.1; warn: profitable                                                                          |
| Monte Carlo (resample) | Bootstrap trade P&L 1,000 times                                                                                          | pass: < 5% of paths lose money; warn: < 20%                                                                                   |
| Noise                  | Re-trade on copies where each of O/H/L/C is perturbed with probability 0.5 by U(−0.2, 0.2) × ATR(14); signals recomputed | pass: ≥ 80% of noisy runs profitable; warn: ≥ 60%                                                                             |
| Vs random              | Random entries at the same frequency, same direction and exits; p = (k+1)/(N+1)                                          | pass: p ≤ 0.05; warn: p ≤ 0.20. Also reports whether it beats the _best_ random run                                           |
| Permutation (MCPT)     | Shuffle bar-to-bar changes keeping each bar's shape; re-run the fixed rules                                              | pass: p ≤ 0.05; warn: p ≤ 0.20                                                                                                |
| Delay                  | Enter 1 and 2 bars late                                                                                                  | pass: all delayed variants profitable                                                                                         |
| Variance               | Simulate the next N trades with the win rate lowered by 5 points, drawing wins and losses from history                   | pass: < 10% of paths lose; warn: < 30%                                                                                        |
| Parameter stability    | Every numeric parameter moved about ±20% (all combinations, sampled to ≤ 400)                                            | pass: ≥ 70% of neighbours profitable, 25th-percentile neighbour profitable, and the original is not > 2× the neighbour median |
| Other markets          | Same rules on other datasets (CLI/API)                                                                                   | pass: profitable on ≥ 60%                                                                                                     |
| Walk-forward           | Re-optimise on rolling (or anchored) in-sample windows, trade the next window, stitch                                    | pass: stitched OOS profitable, efficiency ≥ 0.5, ≥ 60% of windows profitable                                                  |

## Selection bias

Generation evaluates hundreds to thousands of rule sets; the best in-sample
result is inflated by that search. Each generated strategy therefore carries a
**deflated Sharpe ratio** (Bailey & López de Prado, 2014): the probability that
its true Sharpe is above zero after accounting for the number of strategies
tried, the dispersion of their Sharpe ratios, sample length, skew and kurtosis.
Low values are the norm for data-mined strategies and are an honest signal.

## Limitations

- The permutation test checks the _final rules_. It does not re-run the search
  on each permutation, so it does not by itself correct for data mining. Use it
  together with the deflated Sharpe ratio. A selection-aware permutation test
  is on the roadmap.
- Noise and permutation tests use synthetic variations of one history; they do
  not create genuinely new market regimes.
- Thresholds are heuristics. Change them in code if your process needs others.
