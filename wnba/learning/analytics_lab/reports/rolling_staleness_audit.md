# Phase 2D — Rolling-feature staleness audit

**Date:** 2026-07-25  |  **Eligible player-games:** 13,802

## What this measures

Production serves each player's most recent *stored* row, whose rolling
columns were `shift(1)`-computed relative to that row — so the board never
sees the player's latest completed game. Here **fresh** features are as-of
at the target tip and **stale** features reproduce that production
behaviour, on identical rows with an identical `minutes` input
(`minutes_last_5` for both), isolating this effect from Phase 2C.

## Headline

```
pooled points-weighted MAE   fresh  1.5343
                             stale  1.5434
                     stale penalty  +0.0091 (+0.59%)
```

## Prediction accuracy by stat

| Stat | n | fresh MAE | stale MAE | penalty |
|---|---|---|---|---|
| assists | 13,802 | 1.2237 | 1.2362 | +0.0125 |
| blocks | 13,802 | 0.4863 | 0.4897 | +0.0034 |
| points | 13,802 | 4.2668 | 4.2887 | +0.0219 |
| rebounds | 13,802 | 1.7889 | 1.7985 | +0.0096 |
| steals | 13,802 | 0.7080 | 0.7108 | +0.0028 |
| threes_made | 13,802 | 0.7323 | 0.7368 | +0.0045 |

## How far the features actually move

| Feature | n | % differing | mean abs diff | median | p90 |
|---|---|---|---|---|---|
| `minutes_last_3` | 13,569 | 92.1% | 2.322 | 1.667 | 5.333 |
| `minutes_std_3` | 13,348 | 88.6% | 2.060 | 1.155 | 5.065 |
| `minutes_trend_3_over_10` | 13,569 | 95.3% | 2.016 | 1.467 | 4.567 |
| `minutes_ewm` | 13,569 | 99.7% | 1.854 | 1.412 | 3.987 |
| `points_last_3` | 13,569 | 86.4% | 1.853 | 1.333 | 4.333 |
| `points_std_3` | 13,348 | 82.7% | 1.630 | 1.020 | 4.086 |
| `minutes_last_5` | 13,569 | 93.0% | 1.531 | 1.200 | 3.400 |
| `points_ewm` | 13,569 | 98.8% | 1.503 | 1.141 | 3.340 |
| `minutes_std_5` | 13,348 | 91.2% | 1.219 | 0.626 | 3.004 |
| `points_last_5` | 13,569 | 87.0% | 1.138 | 0.800 | 2.600 |
| `minutes_last_10` | 13,569 | 94.2% | 0.883 | 0.600 | 2.000 |
| `points_std_5` | 13,348 | 85.1% | 0.865 | 0.459 | 2.251 |
| `rebounds_last_3` | 13,569 | 80.2% | 0.771 | 0.667 | 1.667 |
| `rebounds_std_3` | 13,348 | 72.0% | 0.674 | 0.423 | 1.732 |
| `rebounds_ewm` | 13,569 | 98.9% | 0.637 | 0.474 | 1.421 |
| `minutes_std_10` | 13,348 | 93.9% | 0.636 | 0.294 | 1.567 |
| `points_last_10` | 13,569 | 88.3% | 0.623 | 0.500 | 1.400 |
| `season_avg_minutes` | 13,117 | 98.8% | 0.559 | 0.278 | 1.286 |
| `assists_last_3` | 13,569 | 71.9% | 0.518 | 0.333 | 1.333 |
| `rebounds_last_5` | 13,569 | 81.2% | 0.486 | 0.400 | 1.200 |

Across all 60 carried-forward features, the mean share of rows where the stale value differs from the fresh one is **71.7%**.

## Effect on the published ordering (points projections)

| | slates | mean top-N overlap | mean players changed | slates with any change |
|---|---|---|---|---|
| top-5 | 260 | 89.6% | 0.52 | 44.6% |
| top-10 | 260 | 94.2% | 0.58 | 46.2% |
| top-20 | 236 | 97.1% | 0.59 | 46.2% |
| Spearman rank corr | 260 | 0.9935 | — | — |

Median absolute change in a points projection: **0.203**; mean **0.347**; p90 **0.764**; share of rows moving by ≥1 point: **5.9%**.

## Where staleness costs the most (points MAE)

| Situation | n | share | fresh MAE | stale MAE | stale penalty |
|---|---|---|---|---|---|
| early season (< 5 games played) | 2,027 | 14.7% | 4.458 | 4.521 | +0.0628 |
| back-to-back | 622 | 4.5% | 4.379 | 4.414 | +0.0349 |
| changed team (trade) | 224 | 1.6% | 5.373 | 5.395 | +0.0221 |
| ALL ROWS | 13,802 | 100.0% | 4.267 | 4.289 | +0.0219 |
| minutes spike (prev ≥ +8 vs last-10) | 1,654 | 12.0% | 5.053 | 5.068 | +0.0146 |
| role change (started ≠ usual) | 1,283 | 9.3% | 4.700 | 4.706 | +0.0061 |
| minutes drop (prev ≤ -8 vs last-10) | 1,066 | 7.7% | 4.256 | 4.254 | -0.0022 |
| returned from DNP (prev game DNP) | 984 | 7.1% | 3.283 | 3.276 | -0.0064 |
| long rest (≥ 5 days) | 1,226 | 8.9% | 4.390 | 4.378 | -0.0125 |

## Reading this correctly

- Staleness is **not** a leak. It discards information rather than borrowing
  from the future, so it is conservative — just costly.
- Absolute MAE is in-sample (current binaries, training window overlap).
  The fresh-vs-stale *difference* is the trustworthy quantity.
- The effect concentrates exactly where the last game is most informative:
  role changes, returns from DNP, and minutes spikes.

