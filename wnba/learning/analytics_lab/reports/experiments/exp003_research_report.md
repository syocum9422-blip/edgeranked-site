# EXP003 — Exact rest days from tip-off times

**Run:** 2026-07-25T15:08:36+00:00  |  **Author:** analytics_lab  |  **Status:** complete
**Baseline:** `reconstructed_production_logic_v1` (`reconstructed_production_logic`)  |  **Model fingerprint:** `e7353c24f46e9ada`

## Executive summary

**Question.** Does rest computed from exact tip-off timestamps improve projections over production's UTC-date-differenced, 0-7-clipped rest_days?

**Result.** Pooled MAE moves from **1.5734** (baseline) to **1.5738** (variant), **+0.02%**, across 13,802 paired player-games and 6 stat categories.

**Marginal.** Either statistically detectable but too small to matter, or large enough to matter but not statistically distinguishable. Not a finding on its own — check the direction below before reading anything into it.

Direction: the variant is **worse** than the baseline overall. Per-stat verdicts: 6 marginal.

## Question

Does rest computed from exact tip-off timestamps improve projections over production's UTC-date-differenced, 0-7-clipped rest_days?

**Hypothesis.** Marginally. Rest genuinely affects minutes and efficiency, but the production construction is wrong by at most a day for most rows, and the stat models were fitted on the miscomputed version, so a corrected input may not help a fixed model.

**Expected improvement.** Under 0.5% pooled MAE; possibly none without retraining.

**Feature(s) modified.** `rest_days`

**Columns the run verified as changed.** `rest_days`

## Method

Current production stat-model binaries fed the inputs production actually serves: previous-game actual minutes, one-game-stale rolling features, and UTC-date-differenced rest days clipped to 0-7.

The variant frame is identical to the baseline frame except in the declared
columns; the runner aborts if any other column moves. Both sides are scored
with the same production model binaries on the same player-games, so every
comparison below is paired.

`rest_days` is replaced with `floor(rest_hours / 24)` where `rest_hours` is the exact interval between the previous tip-off and this one. The same [0, 7] clip is applied so the change is the measurement, not the range. `is_back_to_back` is deliberately left on the production definition, keeping this to one variable.

**Statistics.** Wilcoxon signed-rank on paired absolute errors, Holm-corrected
across the 6 stats, α = 0.01. Practical threshold
= 1% relative MAE change. A verdict of
*meaningful* requires both. 95% bootstrap CI on the mean paired difference
(2,000 resamples, seed 42).

## Sample

- **Player-games:** 13,802 (identical for baseline and variant)
- **Seasons:** 2024, 2025, 2026
- **Date range:** 2024-05-16 → 2026-07-22
- **Distinct players:** 288  |  **games:** 727  |  **slates:** 260

Regular-season games the player actually played, with enough history for both
feature sets to be defined. Preseason and DNPs are excluded.

## Results

### Paired comparison by stat

| Stat | n | baseline MAE | variant MAE | Δ MAE | rel. | 95% CI | Holm p | d | variant wins | verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| points | 13,802 | 4.4112 | 4.4121 | +0.0008 | +0.02% | [+0.0005, +0.0012] | 1.30e-11 | +0.043 | 23.1% | `marginal` |
| rebounds | 13,802 | 1.8410 | 1.8411 | +0.0001 | +0.01% | [+0.0001, +0.0001] | 1.98e-13 | +0.065 | 23.8% | `marginal` |
| assists | 13,802 | 1.2459 | 1.2458 | -0.0001 | -0.01% | [-0.0001, -0.0001] | 1.99e-28 | -0.048 | 29.0% | `marginal` |
| threes_made | 13,802 | 0.7485 | 0.7487 | +0.0002 | +0.03% | [+0.0002, +0.0003] | 3.02e-107 | +0.119 | 17.4% | `marginal` |
| steals | 13,802 | 0.7072 | 0.7076 | +0.0005 | +0.07% | [+0.0004, +0.0005] | 2.82e-67 | +0.158 | 20.5% | `marginal` |
| blocks | 13,802 | 0.4869 | 0.4876 | +0.0007 | +0.14% | [+0.0006, +0.0007] | 2.24e-288 | +0.334 | 14.0% | `marginal` |

Negative Δ favours the variant. A CI spanning zero means the paired
difference is not distinguishable from no change.

### Full metric set

| Stat | Side | n | MAE | RMSE | Bias | Median abs err | Correlation |
|---|---|---|---|---|---|---|---|
| assists | baseline | 13,802 | 1.2459 | 1.7074 | -0.0702 | 0.9596 | 0.6648 |
| assists | variant | 13,802 | 1.2458 | 1.7074 | -0.0710 | 0.9594 | 0.6648 |
| blocks | baseline | 13,802 | 0.4869 | 0.7077 | -0.0105 | 0.3464 | 0.4459 |
| blocks | variant | 13,802 | 0.4876 | 0.7077 | -0.0091 | 0.3478 | 0.4458 |
| points | baseline | 13,802 | 4.4112 | 5.8424 | -0.3244 | 3.4896 | 0.6429 |
| points | variant | 13,802 | 4.4121 | 5.8429 | -0.3181 | 3.4948 | 0.6428 |
| rebounds | baseline | 13,802 | 1.8410 | 2.4717 | -0.1138 | 1.4242 | 0.6518 |
| rebounds | variant | 13,802 | 1.8411 | 2.4717 | -0.1125 | 1.4251 | 0.6518 |
| steals | baseline | 13,802 | 0.7072 | 0.9513 | -0.0288 | 0.5729 | 0.3515 |
| steals | variant | 13,802 | 0.7076 | 0.9513 | -0.0266 | 0.5731 | 0.3514 |
| threes_made | baseline | 13,802 | 0.7485 | 1.0694 | -0.0130 | 0.5345 | 0.5063 |
| threes_made | variant | 13,802 | 0.7487 | 1.0695 | -0.0123 | 0.5351 | 0.5063 |

### Top-ranked projections

Each side judged on the rows *it* would have surfaced, so the two row
sets differ by construction. Reported separately from the paired tests
for that reason.

| Top-N | Stat | baseline MAE | variant MAE | Δ |
|---|---|---|---|---|
| 10 | assists | 1.8601 | 1.8599 | -0.0002 |
| 10 | blocks | 0.8260 | 0.8265 | +0.0006 |
| 10 | points | 5.5823 | 5.5833 | +0.0010 |
| 10 | rebounds | 2.6296 | 2.6297 | +0.0001 |
| 10 | steals | 0.9554 | 0.9546 | -0.0007 |
| 10 | threes_made | 1.2222 | 1.2230 | +0.0008 |
| 20 | assists | 1.6235 | 1.6230 | -0.0005 |
| 20 | blocks | 0.6987 | 0.6991 | +0.0004 |
| 20 | points | 5.3047 | 5.3060 | +0.0013 |
| 20 | rebounds | 2.2905 | 2.2906 | +0.0001 |
| 20 | steals | 0.8762 | 0.8768 | +0.0006 |
| 20 | threes_made | 1.0709 | 1.0710 | +0.0001 |

### By season (all stats pooled)

| Segment | n | baseline MAE | variant MAE | Δ |
|---|---|---|---|---|
| 2024 | 26,556 | 1.5569 | 1.5573 | +0.0004 |
| 2025 | 32,418 | 1.5870 | 1.5873 | +0.0003 |
| 2026 | 23,838 | 1.5734 | 1.5738 | +0.0004 |

### By player role (all stats pooled)

| Segment | n | baseline MAE | variant MAE | Δ |
|---|---|---|---|---|
| bench | 39,288 | 1.2230 | 1.2234 | +0.0004 |
| starter | 43,524 | 1.8898 | 1.8901 | +0.0004 |

### By expected-minutes bucket (all stats pooled)

| Segment | n | baseline MAE | variant MAE | Δ |
|---|---|---|---|---|
| 0-10 | 15,540 | 0.8625 | 0.8633 | +0.0008 |
| 10-20 | 22,308 | 1.4210 | 1.4214 | +0.0004 |
| 20-28 | 20,694 | 1.7795 | 1.7798 | +0.0003 |
| 28-34 | 16,872 | 1.9379 | 1.9380 | +0.0001 |
| 34+ | 7,398 | 2.1188 | 2.1190 | +0.0001 |

### By rest status (all stats pooled)

| Segment | n | baseline MAE | variant MAE | Δ |
|---|---|---|---|---|
| 2-3d | 52,878 | 1.5521 | 1.5524 | +0.0003 |
| 4-5d | 19,194 | 1.5980 | 1.5986 | +0.0006 |
| 6d+ | 6,990 | 1.6422 | 1.6424 | +0.0002 |
| b2b | 3,732 | 1.6198 | 1.6202 | +0.0004 |

## Interpretation

The two constructions disagree on **55.4%** of rows — the systematic consequence of filing evening games under the next UTC date. A further **3.9%** of rows sit at the 7-day clip, where both constructions are equally blind to how long the layoff really was.

A null result here is informative rather than disappointing: it would mean the date-convention defect, real as it is, costs little in projection accuracy, and should be prioritised for the join correctness problems it causes elsewhere rather than for model gain.

## Limitations

Framework-wide, applying to every experiment in this catalog:

- **No retraining.** The production binaries are held fixed, so this measures
  how the *deployed* model responds to a different input construction — not
  the value that feature would have in a refit model. A feature the current
  model cannot exploit may still be valuable after retraining.
- **In-sample.** The binaries were trained on data covering this window, so
  absolute MAE is optimistic. Only the paired *difference* is trustworthy.
- **Not the historical production model.** Binaries are unversioned and
  overwritten in place, so no past model version can be recovered. The
  baseline is a reconstruction of production *logic*, not a snapshot.
- **Conditional on playing.** Availability prediction is excluded; rows are
  restricted to games the player actually played.
- **Positions are anachronistic.** ESPN's box-score position is an athlete
  profile attribute, constant across all seasons, scraped in 2026.
- `is_back_to_back` still uses production's `rest_days <= 0` rule, so part of the rest signal reaching the model remains on the old construction. That is the price of the single-variable rule; a combined test is listed under future work.
- The models were trained on the miscomputed rest, so their fitted response is calibrated to it.

## Recommendation

This is a research finding, not a deployment proposal. No production change
is recommended here and none was made.

Not worth further work on its own. Revisit only if a related change lands that could plausibly amplify it.

## Future work

- Run a two-variable version changing rest_days and is_back_to_back together, to measure the full rest correction.
- Test rest as continuous hours rather than clipped whole days.

## Reproduction

```bash
python3 learning/analytics_lab/experiments/framework/runner.py EXP003
```

Artifacts: `experiments/runs/EXP003/`

