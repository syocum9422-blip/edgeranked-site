# Phase 2C — Minutes leakage audit

**Date:** 2026-07-25  |  **Eligible player-games:** 13,802  |  **Stats:** 6

## What this measures

One knob is varied — the `minutes` feature — with the model, the rows and
every other feature held identical. Differences are therefore attributable
to that column alone.

> **The production stat-model binaries are audit artifacts here.** They were
> trained on data covering this whole window, so absolute MAE below is
> in-sample and is *not* live accuracy. They are also the only binaries that
> exist — the trainer overwrites in place with no versioning — so no
> historical model version is represented.

## Headline

```
Accuracy inflation from actual-minutes leakage
  = leak-safe MAE - leaked MAE
  = 1.5032 (D_HISTORICAL_PROJECTED_MINUTES)
  - 1.2928 (A_LEAKED_ACTUAL_MINUTES)
  = +0.2104 pooled MAE  (+16.3%)
```

Variant A is what the production training procedure optimises against. It
cannot be reproduced at prediction time, so **+0.2104 pooled MAE**
of the models' apparent accuracy is unavailable in production.

The behaviour production actually ships (B, previous-game minutes) is
**+0.0638 pooled MAE** worse than the best leak-safe estimate
(D_HISTORICAL_PROJECTED_MINUTES) — an improvement available with no model change.

## Pooled MAE by variant

| Variant | assists | blocks | points | rebounds | steals | threes_made | pooled MAE |
|---|---|---|---|---|---|---|---|
| `A_LEAKED_ACTUAL_MINUTES` **(invalid — diagnostic only)** | 1.100 | 0.478 | 3.310 | 1.503 | 0.676 | 0.691 | **1.2928** |
| `D_HISTORICAL_PROJECTED_MINUTES` | 1.213 | 0.485 | 4.140 | 1.748 | 0.705 | 0.729 | **1.5032** |
| `C_EWM_MINUTES` | 1.213 | 0.486 | 4.194 | 1.766 | 0.706 | 0.729 | **1.5157** |
| `C_LAST3_MINUTES` | 1.222 | 0.487 | 4.250 | 1.789 | 0.708 | 0.733 | **1.5315** |
| `C_STARTER_AWARE_MINUTES` | 1.222 | 0.486 | 4.256 | 1.788 | 0.707 | 0.730 | **1.5316** |
| `C_LAST5_MINUTES` | 1.224 | 0.486 | 4.267 | 1.789 | 0.708 | 0.732 | **1.5343** |
| `C_LAST10_MINUTES` | 1.225 | 0.486 | 4.285 | 1.800 | 0.708 | 0.732 | **1.5393** |
| `B_PREVIOUS_GAME_MINUTES` | 1.238 | 0.489 | 4.384 | 1.835 | 0.711 | 0.745 | **1.5670** |

## Full metric set (all stats pooled, overall segment)

| Variant | Stat | n | MAE | RMSE | Bias | MedAE | ≤1 | ≤2 | Corr |
|---|---|---|---|---|---|---|---|---|---|
| `A_LEAKED_ACTUAL_MINUTES` | assists | 13802 | 1.100 | 1.504 | -0.009 | 0.827 | 57.9% | 85.0% | 0.751 |
| `C_EWM_MINUTES` | assists | 13802 | 1.213 | 1.667 | -0.109 | 0.910 | 54.6% | 82.0% | 0.683 |
| `D_HISTORICAL_PROJECTED_MINUTES` | assists | 13802 | 1.213 | 1.666 | -0.134 | 0.877 | 55.2% | 82.1% | 0.684 |
| `C_STARTER_AWARE_MINUTES` | assists | 13802 | 1.222 | 1.683 | -0.130 | 0.918 | 54.0% | 82.1% | 0.676 |
| `C_LAST3_MINUTES` | assists | 13802 | 1.222 | 1.681 | -0.097 | 0.921 | 54.2% | 81.8% | 0.677 |
| `C_LAST5_MINUTES` | assists | 13802 | 1.224 | 1.684 | -0.117 | 0.923 | 53.9% | 81.8% | 0.676 |
| `C_LAST10_MINUTES` | assists | 13802 | 1.225 | 1.687 | -0.142 | 0.912 | 54.0% | 82.0% | 0.675 |
| `B_PREVIOUS_GAME_MINUTES` | assists | 13802 | 1.238 | 1.695 | -0.063 | 0.953 | 53.1% | 81.4% | 0.671 |
| `A_LEAKED_ACTUAL_MINUTES` | blocks | 13802 | 0.478 | 0.678 | +0.016 | 0.342 | 90.9% | 98.1% | 0.517 |
| `D_HISTORICAL_PROJECTED_MINUTES` | blocks | 13802 | 0.485 | 0.698 | -0.010 | 0.325 | 90.8% | 98.0% | 0.469 |
| `C_EWM_MINUTES` | blocks | 13802 | 0.486 | 0.702 | -0.005 | 0.330 | 90.5% | 98.0% | 0.461 |
| `C_STARTER_AWARE_MINUTES` | blocks | 13802 | 0.486 | 0.703 | -0.009 | 0.330 | 90.5% | 98.0% | 0.457 |
| `C_LAST10_MINUTES` | blocks | 13802 | 0.486 | 0.704 | -0.012 | 0.328 | 90.5% | 98.0% | 0.455 |
| `C_LAST5_MINUTES` | blocks | 13802 | 0.486 | 0.703 | -0.007 | 0.332 | 90.6% | 98.0% | 0.458 |
| `C_LAST3_MINUTES` | blocks | 13802 | 0.487 | 0.703 | -0.003 | 0.334 | 90.5% | 98.0% | 0.458 |
| `B_PREVIOUS_GAME_MINUTES` | blocks | 13802 | 0.489 | 0.705 | +0.004 | 0.345 | 90.3% | 98.0% | 0.454 |
| `A_LEAKED_ACTUAL_MINUTES` | points | 13802 | 3.310 | 4.463 | -0.012 | 2.488 | 23.5% | 42.6% | 0.803 |
| `D_HISTORICAL_PROJECTED_MINUTES` | points | 13802 | 4.140 | 5.511 | -0.706 | 3.140 | 16.0% | 34.6% | 0.684 |
| `C_EWM_MINUTES` | points | 13802 | 4.194 | 5.576 | -0.549 | 3.263 | 17.7% | 33.7% | 0.675 |
| `C_LAST3_MINUTES` | points | 13802 | 4.250 | 5.647 | -0.469 | 3.323 | 17.7% | 33.1% | 0.666 |
| `C_STARTER_AWARE_MINUTES` | points | 13802 | 4.256 | 5.672 | -0.655 | 3.290 | 17.6% | 33.4% | 0.663 |
| `C_LAST5_MINUTES` | points | 13802 | 4.267 | 5.675 | -0.579 | 3.312 | 17.7% | 33.1% | 0.663 |
| `C_LAST10_MINUTES` | points | 13802 | 4.285 | 5.710 | -0.724 | 3.298 | 17.3% | 33.2% | 0.659 |
| `B_PREVIOUS_GAME_MINUTES` | points | 13802 | 4.384 | 5.804 | -0.262 | 3.478 | 17.8% | 32.6% | 0.649 |
| `A_LEAKED_ACTUAL_MINUTES` | rebounds | 13802 | 1.503 | 2.010 | +0.007 | 1.154 | 44.5% | 73.0% | 0.783 |
| `D_HISTORICAL_PROJECTED_MINUTES` | rebounds | 13802 | 1.748 | 2.357 | -0.220 | 1.318 | 39.4% | 67.9% | 0.686 |
| `C_EWM_MINUTES` | rebounds | 13802 | 1.766 | 2.381 | -0.178 | 1.337 | 39.5% | 67.1% | 0.678 |
| `C_STARTER_AWARE_MINUTES` | rebounds | 13802 | 1.788 | 2.409 | -0.214 | 1.356 | 38.7% | 66.6% | 0.670 |
| `C_LAST5_MINUTES` | rebounds | 13802 | 1.789 | 2.412 | -0.192 | 1.359 | 38.8% | 66.6% | 0.669 |
| `C_LAST3_MINUTES` | rebounds | 13802 | 1.789 | 2.406 | -0.158 | 1.370 | 39.0% | 66.2% | 0.671 |
| `C_LAST10_MINUTES` | rebounds | 13802 | 1.800 | 2.424 | -0.239 | 1.367 | 38.8% | 66.7% | 0.666 |
| `B_PREVIOUS_GAME_MINUTES` | rebounds | 13802 | 1.835 | 2.466 | -0.102 | 1.411 | 38.4% | 64.8% | 0.655 |
| `A_LEAKED_ACTUAL_MINUTES` | steals | 13802 | 0.676 | 0.902 | +0.014 | 0.538 | 78.4% | 96.5% | 0.451 |
| `D_HISTORICAL_PROJECTED_MINUTES` | steals | 13802 | 0.705 | 0.935 | -0.037 | 0.553 | 78.1% | 96.0% | 0.382 |
| `C_EWM_MINUTES` | steals | 13802 | 0.706 | 0.944 | -0.026 | 0.557 | 77.9% | 95.9% | 0.365 |
| `C_STARTER_AWARE_MINUTES` | steals | 13802 | 0.707 | 0.946 | -0.034 | 0.557 | 78.1% | 95.8% | 0.360 |
| `C_LAST3_MINUTES` | steals | 13802 | 0.708 | 0.947 | -0.021 | 0.567 | 77.4% | 96.0% | 0.359 |
| `C_LAST10_MINUTES` | steals | 13802 | 0.708 | 0.948 | -0.039 | 0.557 | 78.1% | 95.8% | 0.357 |
| `C_LAST5_MINUTES` | steals | 13802 | 0.708 | 0.948 | -0.030 | 0.560 | 77.8% | 95.8% | 0.358 |
| `B_PREVIOUS_GAME_MINUTES` | steals | 13802 | 0.711 | 0.954 | -0.010 | 0.576 | 76.6% | 95.9% | 0.350 |
| `A_LEAKED_ACTUAL_MINUTES` | threes_made | 13802 | 0.691 | 0.984 | +0.017 | 0.488 | 76.9% | 94.8% | 0.608 |
| `D_HISTORICAL_PROJECTED_MINUTES` | threes_made | 13802 | 0.729 | 1.047 | -0.055 | 0.498 | 75.6% | 93.9% | 0.535 |
| `C_EWM_MINUTES` | threes_made | 13802 | 0.729 | 1.049 | -0.038 | 0.511 | 75.1% | 94.0% | 0.531 |
| `C_STARTER_AWARE_MINUTES` | threes_made | 13802 | 0.730 | 1.054 | -0.049 | 0.508 | 75.1% | 93.9% | 0.526 |
| `C_LAST10_MINUTES` | threes_made | 13802 | 0.732 | 1.056 | -0.055 | 0.508 | 75.1% | 93.9% | 0.523 |
| `C_LAST5_MINUTES` | threes_made | 13802 | 0.732 | 1.055 | -0.041 | 0.512 | 74.9% | 93.9% | 0.524 |
| `C_LAST3_MINUTES` | threes_made | 13802 | 0.733 | 1.053 | -0.030 | 0.515 | 74.9% | 93.9% | 0.526 |
| `B_PREVIOUS_GAME_MINUTES` | threes_made | 13802 | 0.745 | 1.063 | -0.009 | 0.530 | 74.3% | 93.8% | 0.514 |

## Error by actual-minutes bucket — points MAE

| Variant | 0-10 (n=2590) | 10-20 (n=3718) | 20-28 (n=3449) | 28-34 (n=2812) | 34+ (n=1233) |
|---|---|---|---|---|---|
| `A_LEAKED_ACTUAL_MINUTES` | 1.284 | 2.755 | 3.886 | 4.538 | 4.827 |
| `B_PREVIOUS_GAME_MINUTES` | 2.443 | 4.037 | 4.972 | 5.302 | 5.767 |
| `C_EWM_MINUTES` | 2.267 | 3.739 | 4.739 | 5.181 | 5.837 |
| `C_LAST10_MINUTES` | 2.383 | 3.744 | 4.806 | 5.340 | 6.053 |
| `C_LAST3_MINUTES` | 2.321 | 3.844 | 4.810 | 5.198 | 5.795 |
| `C_LAST5_MINUTES` | 2.319 | 3.811 | 4.811 | 5.270 | 5.923 |
| `C_STARTER_AWARE_MINUTES` | 2.320 | 3.762 | 4.795 | 5.291 | 5.946 |
| `D_HISTORICAL_PROJECTED_MINUTES` | 2.292 | 3.584 | 4.624 | 5.197 | 5.929 |

## Error by starter / bench — points MAE

| Variant | bench (n=6548) | starter (n=7254) |
|---|---|---|
| `A_LEAKED_ACTUAL_MINUTES` | 2.346 | 4.181 |
| `B_PREVIOUS_GAME_MINUTES` | 3.436 | 5.239 |
| `C_EWM_MINUTES` | 3.245 | 5.050 |
| `C_LAST10_MINUTES` | 3.349 | 5.131 |
| `C_LAST3_MINUTES` | 3.308 | 5.100 |
| `C_LAST5_MINUTES` | 3.312 | 5.129 |
| `C_STARTER_AWARE_MINUTES` | 3.310 | 5.110 |
| `D_HISTORICAL_PROJECTED_MINUTES` | 3.191 | 4.995 |

## Error by season — points MAE

| Variant | 2024 (n=4426) | 2025 (n=5403) | 2026 (n=3973) |
|---|---|---|---|
| `A_LEAKED_ACTUAL_MINUTES` | 3.217 | 3.322 | 3.398 |
| `B_PREVIOUS_GAME_MINUTES` | 4.315 | 4.405 | 4.431 |
| `C_EWM_MINUTES` | 4.079 | 4.232 | 4.270 |
| `C_LAST10_MINUTES` | 4.140 | 4.352 | 4.357 |
| `C_LAST3_MINUTES` | 4.120 | 4.284 | 4.348 |
| `C_LAST5_MINUTES` | 4.122 | 4.321 | 4.355 |
| `C_STARTER_AWARE_MINUTES` | 4.108 | 4.314 | 4.343 |
| `D_HISTORICAL_PROJECTED_MINUTES` | 4.014 | 4.158 | 4.255 |

## Error where minutes moved ≥8 vs the previous game — points MAE

| Variant | False (n=9833) | True (n=3969) |
|---|---|---|
| `A_LEAKED_ACTUAL_MINUTES` | 3.332 | 3.255 |
| `B_PREVIOUS_GAME_MINUTES` | 3.671 | 6.150 |
| `C_EWM_MINUTES` | 3.807 | 5.153 |
| `C_LAST10_MINUTES` | 4.042 | 4.890 |
| `C_LAST3_MINUTES` | 3.856 | 5.226 |
| `C_LAST5_MINUTES` | 3.955 | 5.040 |
| `C_STARTER_AWARE_MINUTES` | 3.961 | 4.988 |
| `D_HISTORICAL_PROJECTED_MINUTES` | 3.816 | 4.941 |

## How well each variant estimates actual minutes

| Variant | corr with actual minutes | MAE vs actual minutes |
|---|---|---|
| `A_LEAKED_ACTUAL_MINUTES` | 1.000 | 0.00 |
| `D_HISTORICAL_PROJECTED_MINUTES` | 0.779 | 5.09 |
| `C_EWM_MINUTES` | 0.778 | 5.15 |
| `C_STARTER_AWARE_MINUTES` | 0.759 | 5.36 |
| `C_LAST3_MINUTES` | 0.761 | 5.38 |
| `C_LAST5_MINUTES` | 0.757 | 5.40 |
| `C_LAST10_MINUTES` | 0.746 | 5.52 |
| `B_PREVIOUS_GAME_MINUTES` | 0.731 | 5.88 |

## Reading this correctly

- Variant A is **not** production accuracy and must never be quoted as such.
- All absolute numbers are in-sample; only the *differences between variants*
  are trustworthy, because the model and rows are shared.
- Rows are restricted to games the player actually played. Availability
  prediction is a separate problem and is deliberately excluded.

