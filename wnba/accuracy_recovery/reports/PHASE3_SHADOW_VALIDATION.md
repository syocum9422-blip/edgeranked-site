# WNBA Accuracy Recovery — Phase 3 Shadow Validation Results
*Replay backtest: accuracy_recovery/phase3_shadow_backtest.py · pool = 3,213 scored props over 24
slates (2026-06-11 → 2026-07-09) = full PrizePicks line universe × archived same-day production
boards × ESPN actuals. Point-in-time honest: variance-inflation factors fit only on trailing 21
days; role-guard uses only prior games; DNPs voided; pushes excluded.*

## Replay validity
Baseline replay (raw sim probabilities + production gates) reproduces live production results on the
same window: **48.5% replay vs 49.6% actual live** — the replay harness is trustworthy.

## Strategy comparison (decline window)

| Strategy | n | picks/day | Hit rate | Brier | ECE | binom p vs 0.5 |
|---|---|---|---|---|---|---|
| BASELINE (production-like) | 1045 | 43.5 | 48.5% | 0.309 | 0.221 | — |
| C1 variance-honesty | 945 | 39.4 | 49.2% | 0.278 | 0.145 | ns |
| C2 singles-only | 806 | 33.6 | 51.6% | 0.270 | 0.130 | ns |
| C3 tail-cap 0.70 | 997 | 41.5 | 49.9% | 0.273 | 0.139 | ns |
| C6 role-guard | 1027 | 42.8 | 48.7% | 0.306 | 0.219 | ns |
| **C1+C2+C6 (selected)** | **556** | **23.2** | **53.4%** | **0.258** | **0.076** | 0.117 |

## Significance of the selected candidate vs baseline
- Δ hit rate **+4.9pp**; day-clustered bootstrap (5,000 resamples) 95% CI **[+1.3pp, +8.7pp]**,
  P(Δ>0) = **99.6%**
- Day-paired Wilcoxon p = **0.026**
- Weekly consistency: beats baseline in 4 of 5 weeks (only miss: Jun 29–Jul 5, n=49)
- Brier 0.309 → 0.258; calibration error (ECE) 0.221 → **0.076** — the published probabilities
  become approximately honest
- Independent corroboration from live graded history (not the replay): singles 57.2% (n=773) vs
  combos 50.7% (n=1347) full-season, χ² p = 0.005; singles also superior in the early soft-line
  regime (58.9% vs 56.7%) — robust across both market regimes
- MAE/RMSE: unchanged by construction (selection layer only; projections untouched)
- Profitability: not directly tracked (PrizePicks, no CLV); hit rate is the tracked proxy

## Hit rate by stat (selected candidate, replay window)
points ~53%, rebounds ~53–55%, assists small-n; combos: excluded (this is the point).

## Rejected in Phase 3
- Line-movement filter: no additional gain (−0.5pp on top of C1+C2+C6)
- blend-with-market probabilities: 54.5% on pts+reb but volume collapses to ~10/day, ns — revisit
  with more data
- C4 (correlated combo re-pricing) and C5 (minutes recency model): deferred — sim/model changes
  requiring their own validation cycle; selection-layer wins banked first

## Caveats
- 24 slates; the absolute level (53.4%) is not itself significantly above coin-flip in this window —
  the *improvement over current production* is what's established (bootstrap CI excludes 0), plus
  the cross-regime singles>combos evidence.
- Volume drops from ~25 published picks to ~15–20/day. This is intended: the removed picks are the
  demonstrably broken segment.
- Forward shadow grading (grade_recovery_shadow.py) must confirm before promotion; gate: ≥15 slates,
  shadow > production, p < 0.10, no stat ≥30-n below 45%.
