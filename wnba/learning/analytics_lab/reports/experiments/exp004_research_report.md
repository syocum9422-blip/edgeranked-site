# EXP004 — Exponentially weighted vs simple rolling averages

**Run:** 2026-07-25T15:08:43+00:00  |  **Author:** analytics_lab  |  **Status:** complete
**Baseline:** `reconstructed_production_logic_v1` (`reconstructed_production_logic`)  |  **Model fingerprint:** `e7353c24f46e9ada`

## Executive summary

**Question.** Do exponentially weighted rolling averages of a player's recent stats outperform the simple fixed-window rolling averages production feeds the model?

**Result.** Pooled MAE moves from **1.5734** (baseline) to **1.5773** (variant), **+0.24%**, across 13,802 paired player-games and 6 stat categories.

**Marginal.** Either statistically detectable but too small to matter, or large enough to matter but not statistically distinguishable. Not a finding on its own — check the direction below before reading anything into it.

Direction: the variant is **worse** than the baseline overall. Per-stat verdicts: 3 marginal, 3 not_significant.

## Question

Do exponentially weighted rolling averages of a player's recent stats outperform the simple fixed-window rolling averages production feeds the model?

**Hypothesis.** No, or barely. Both summarise the same games; the EWM only reweights them. With three windows already present the model can approximate any reasonable weighting itself, so replacing all three with one series is more likely to lose information than gain it.

**Expected improvement.** None expected. This is designed as a falsification test — a plausible idea that should be ruled out cheaply.

**Feature(s) modified.** `points_rolling_mean_3`, `points_rolling_mean_5`, `points_rolling_mean_10`, `rebounds_rolling_mean_3`, `rebounds_rolling_mean_5`, `rebounds_rolling_mean_10`, `assists_rolling_mean_3`, `assists_rolling_mean_5`, `assists_rolling_mean_10`, `threes_made_rolling_mean_3`, `threes_made_rolling_mean_5`, `threes_made_rolling_mean_10`, `steals_rolling_mean_3`, `steals_rolling_mean_5`, `steals_rolling_mean_10`, `blocks_rolling_mean_3`, `blocks_rolling_mean_5`, `blocks_rolling_mean_10`

**Columns the run verified as changed.** `points_rolling_mean_3`, `points_rolling_mean_5`, `points_rolling_mean_10`, `rebounds_rolling_mean_3`, `rebounds_rolling_mean_5`, `rebounds_rolling_mean_10`, `assists_rolling_mean_3`, `assists_rolling_mean_5`, `assists_rolling_mean_10`, `threes_made_rolling_mean_3`, `threes_made_rolling_mean_5`, `threes_made_rolling_mean_10`, `steals_rolling_mean_3`, `steals_rolling_mean_5`, `steals_rolling_mean_10`, `blocks_rolling_mean_3`, `blocks_rolling_mean_5`, `blocks_rolling_mean_10`

## Method

Current production stat-model binaries fed the inputs production actually serves: previous-game actual minutes, one-game-stale rolling features, and UTC-date-differenced rest days clipped to 0-7.

The variant frame is identical to the baseline frame except in the declared
columns; the runner aborts if any other column moves. Both sides are scored
with the same production model binaries on the same player-games, so every
comparison below is paired.

Every `{stat}_rolling_mean_{3,5,10}` slot is overwritten with that stat's `{stat}_ewm` value (alpha 0.35, shift(1) applied, so the target game is still excluded). The rolling *standard deviations* and the existing `{stat}_ewm` columns are untouched, so the only change is the weighting scheme behind the level estimates.

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
| points | 13,802 | 4.4112 | 4.4227 | +0.0115 | +0.26% | [+0.0054, +0.0174] | 1.08e-03 | +0.031 | 44.1% | `marginal` |
| rebounds | 13,802 | 1.8410 | 1.8443 | +0.0033 | +0.18% | [+0.0016, +0.0051] | 6.94e-03 | +0.031 | 45.4% | `marginal` |
| assists | 13,802 | 1.2459 | 1.2505 | +0.0046 | +0.37% | [+0.0025, +0.0068] | 1.75e-03 | +0.036 | 44.3% | `marginal` |
| threes_made | 13,802 | 0.7485 | 0.7494 | +0.0010 | +0.13% | [-0.0002, +0.0020] | 7.10e-01 | +0.015 | 44.9% | `not_significant` |
| steals | 13,802 | 0.7072 | 0.7082 | +0.0010 | +0.14% | [+0.0004, +0.0017] | 5.14e-01 | +0.024 | 45.8% | `not_significant` |
| blocks | 13,802 | 0.4869 | 0.4884 | +0.0015 | +0.31% | [+0.0008, +0.0021] | 7.10e-01 | +0.038 | 44.9% | `not_significant` |

Negative Δ favours the variant. A CI spanning zero means the paired
difference is not distinguishable from no change.

### Full metric set

| Stat | Side | n | MAE | RMSE | Bias | Median abs err | Correlation |
|---|---|---|---|---|---|---|---|
| assists | baseline | 13,802 | 1.2459 | 1.7074 | -0.0702 | 0.9596 | 0.6648 |
| assists | variant | 13,802 | 1.2505 | 1.7151 | -0.0650 | 0.9631 | 0.6618 |
| blocks | baseline | 13,802 | 0.4869 | 0.7077 | -0.0105 | 0.3464 | 0.4459 |
| blocks | variant | 13,802 | 0.4884 | 0.7108 | -0.0096 | 0.3466 | 0.4388 |
| points | baseline | 13,802 | 4.4112 | 5.8424 | -0.3244 | 3.4896 | 0.6429 |
| points | variant | 13,802 | 4.4227 | 5.8580 | -0.3032 | 3.4873 | 0.6415 |
| rebounds | baseline | 13,802 | 1.8410 | 2.4717 | -0.1138 | 1.4242 | 0.6518 |
| rebounds | variant | 13,802 | 1.8443 | 2.4768 | -0.1121 | 1.4256 | 0.6507 |
| steals | baseline | 13,802 | 0.7072 | 0.9513 | -0.0288 | 0.5729 | 0.3515 |
| steals | variant | 13,802 | 0.7082 | 0.9528 | -0.0277 | 0.5724 | 0.3486 |
| threes_made | baseline | 13,802 | 0.7485 | 1.0694 | -0.0130 | 0.5345 | 0.5063 |
| threes_made | variant | 13,802 | 0.7494 | 1.0723 | -0.0125 | 0.5378 | 0.5031 |

### Top-ranked projections

Each side judged on the rows *it* would have surfaced, so the two row
sets differ by construction. Reported separately from the paired tests
for that reason.

| Top-N | Stat | baseline MAE | variant MAE | Δ |
|---|---|---|---|---|
| 10 | assists | 1.8601 | 1.8759 | +0.0158 |
| 10 | blocks | 0.8260 | 0.8282 | +0.0022 |
| 10 | points | 5.5823 | 5.6148 | +0.0325 |
| 10 | rebounds | 2.6296 | 2.6382 | +0.0086 |
| 10 | steals | 0.9554 | 0.9566 | +0.0012 |
| 10 | threes_made | 1.2222 | 1.2233 | +0.0011 |
| 20 | assists | 1.6235 | 1.6258 | +0.0022 |
| 20 | blocks | 0.6987 | 0.7029 | +0.0042 |
| 20 | points | 5.3047 | 5.3208 | +0.0161 |
| 20 | rebounds | 2.2905 | 2.3030 | +0.0126 |
| 20 | steals | 0.8762 | 0.8751 | -0.0011 |
| 20 | threes_made | 1.0709 | 1.0745 | +0.0035 |

### By season (all stats pooled)

| Segment | n | baseline MAE | variant MAE | Δ |
|---|---|---|---|---|
| 2024 | 26,556 | 1.5569 | 1.5599 | +0.0029 |
| 2025 | 32,418 | 1.5870 | 1.5915 | +0.0045 |
| 2026 | 23,838 | 1.5734 | 1.5772 | +0.0038 |

### By player role (all stats pooled)

| Segment | n | baseline MAE | variant MAE | Δ |
|---|---|---|---|---|
| bench | 39,288 | 1.2230 | 1.2251 | +0.0020 |
| starter | 43,524 | 1.8898 | 1.8952 | +0.0054 |

### By expected-minutes bucket (all stats pooled)

| Segment | n | baseline MAE | variant MAE | Δ |
|---|---|---|---|---|
| 0-10 | 15,540 | 0.8625 | 0.8629 | +0.0004 |
| 10-20 | 22,308 | 1.4210 | 1.4248 | +0.0038 |
| 20-28 | 20,694 | 1.7795 | 1.7860 | +0.0065 |
| 28-34 | 16,872 | 1.9379 | 1.9438 | +0.0059 |
| 34+ | 7,398 | 2.1188 | 2.1177 | -0.0012 |

### By rest status (all stats pooled)

| Segment | n | baseline MAE | variant MAE | Δ |
|---|---|---|---|---|
| 2-3d | 52,878 | 1.5521 | 1.5556 | +0.0036 |
| 4-5d | 19,194 | 1.5980 | 1.6020 | +0.0039 |
| 6d+ | 6,990 | 1.6422 | 1.6471 | +0.0049 |
| b2b | 3,732 | 1.6198 | 1.6247 | +0.0049 |

## Interpretation

Two changes are bundled here and the design cannot separate them: the weighting scheme (exponential vs equal) and the loss of multi-window structure (three series collapsed to one). If the result is a regression, the second is the more likely cause — the model can no longer see the gap between a player's last-3 and last-10 form, which is exactly the signal `minutes_trend_3_over_10` was built to expose.

Read this as a bound, not an answer: it says whether the EWM alone can carry the recent-form load, not whether exponential weighting is better per window.

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
- Collapsing three windows onto one series removes the model's ability to read short-term vs long-term divergence, which is a second change riding along with the weighting change. A cleaner design substitutes one window at a time; that is listed under future work.
- Alpha is fixed at production's 0.35 and was not tuned. A different alpha could change the sign of the result.

## Recommendation

This is a research finding, not a deployment proposal. No production change
is recommended here and none was made.

Not worth further work on its own. Revisit only if a related change lands that could plausibly amplify it.

## Future work

- Substitute one window at a time to separate 'EWM vs simple' from 'one series vs three'.
- Sweep alpha from 0.1 to 0.6 and report the response curve.

## Reproduction

```bash
python3 learning/analytics_lab/experiments/framework/runner.py EXP004
```

Artifacts: `experiments/runs/EXP004/`

