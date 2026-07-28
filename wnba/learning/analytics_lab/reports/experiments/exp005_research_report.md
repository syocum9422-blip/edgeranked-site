# EXP005 — Recent form vs season-to-date average

**Run:** 2026-07-25T15:08:49+00:00  |  **Author:** analytics_lab  |  **Status:** complete
**Baseline:** `reconstructed_production_logic_v1` (`reconstructed_production_logic`)  |  **Model fingerprint:** `e7353c24f46e9ada`

## Executive summary

**Question.** Does a player's recent form carry information beyond her season-to-date average, or would the season average alone serve the model as well?

**Result.** Pooled MAE moves from **1.5734** (baseline) to **1.5762** (variant), **+0.17%**, across 13,802 paired player-games and 6 stat categories.

**Marginal.** Either statistically detectable but too small to matter, or large enough to matter but not statistically distinguishable. Not a finding on its own — check the direction below before reading anything into it.

Direction: the variant is **worse** than the baseline overall. Per-stat verdicts: 5 not_significant, 1 marginal.

## Question

Does a player's recent form carry information beyond her season-to-date average, or would the season average alone serve the model as well?

**Hypothesis.** Recent form matters. Roles change mid-season through trades, injuries and rotation shifts, and 16.8% of player-seasons involve more than one team, so a season average should lag reality and error should rise measurably when recent windows are removed.

**Expected improvement.** A regression is the expected and desired outcome: the size of the degradation measures how much recent form is worth.

**Feature(s) modified.** `points_rolling_mean_3`, `points_rolling_mean_5`, `points_rolling_mean_10`, `rebounds_rolling_mean_3`, `rebounds_rolling_mean_5`, `rebounds_rolling_mean_10`, `assists_rolling_mean_3`, `assists_rolling_mean_5`, `assists_rolling_mean_10`, `threes_made_rolling_mean_3`, `threes_made_rolling_mean_5`, `threes_made_rolling_mean_10`, `steals_rolling_mean_3`, `steals_rolling_mean_5`, `steals_rolling_mean_10`, `blocks_rolling_mean_3`, `blocks_rolling_mean_5`, `blocks_rolling_mean_10`, `points_ewm`, `rebounds_ewm`, `assists_ewm`, `threes_made_ewm`, `steals_ewm`, `blocks_ewm`

**Columns the run verified as changed.** `points_ewm`, `points_rolling_mean_3`, `points_rolling_mean_5`, `points_rolling_mean_10`, `rebounds_ewm`, `rebounds_rolling_mean_3`, `rebounds_rolling_mean_5`, `rebounds_rolling_mean_10`, `assists_ewm`, `assists_rolling_mean_3`, `assists_rolling_mean_5`, `assists_rolling_mean_10`, `threes_made_ewm`, `threes_made_rolling_mean_3`, `threes_made_rolling_mean_5`, `threes_made_rolling_mean_10`, `steals_ewm`, `steals_rolling_mean_3`, `steals_rolling_mean_5`, `steals_rolling_mean_10`, `blocks_ewm`, `blocks_rolling_mean_3`, `blocks_rolling_mean_5`, `blocks_rolling_mean_10`

## Method

Current production stat-model binaries fed the inputs production actually serves: previous-game actual minutes, one-game-stale rolling features, and UTC-date-differenced rest days clipped to 0-7.

The variant frame is identical to the baseline frame except in the declared
columns; the runner aborts if any other column moves. Both sides are scored
with the same production model binaries on the same player-games, so every
comparison below is paired.

Every recent-form *level* estimate is overwritten with `season_avg_{stat}`, the shift(1) expanding mean within the current season: all three `{stat}_rolling_mean_{3,5,10}` slots **and** the `{stat}_ewm` slot. The EWM has to go too — leaving it in would keep supplying recent form through the back door and the experiment would answer nothing. Rolling standard deviations and the `season_avg_*` columns themselves are untouched, so dispersion information is preserved and only the level estimate changes.

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
| points | 13,802 | 4.4112 | 4.4152 | +0.0039 | +0.09% | [-0.0020, +0.0101] | 1.00e+00 | +0.011 | 46.2% | `not_significant` |
| rebounds | 13,802 | 1.8410 | 1.8454 | +0.0044 | +0.24% | [+0.0011, +0.0077] | 5.96e-01 | +0.022 | 46.6% | `not_significant` |
| assists | 13,802 | 1.2459 | 1.2487 | +0.0028 | +0.23% | [-0.0004, +0.0059] | 1.00e+00 | +0.015 | 45.9% | `not_significant` |
| threes_made | 13,802 | 0.7485 | 0.7506 | +0.0021 | +0.28% | [+0.0009, +0.0032] | 3.83e-02 | +0.030 | 45.1% | `not_significant` |
| steals | 13,802 | 0.7072 | 0.7079 | +0.0007 | +0.10% | [-0.0002, +0.0015] | 1.00e+00 | +0.014 | 46.7% | `not_significant` |
| blocks | 13,802 | 0.4869 | 0.4893 | +0.0025 | +0.50% | [+0.0014, +0.0035] | 1.01e-06 | +0.039 | 43.0% | `marginal` |

Negative Δ favours the variant. A CI spanning zero means the paired
difference is not distinguishable from no change.

### Full metric set

| Stat | Side | n | MAE | RMSE | Bias | Median abs err | Correlation |
|---|---|---|---|---|---|---|---|
| assists | baseline | 13,802 | 1.2459 | 1.7074 | -0.0702 | 0.9596 | 0.6648 |
| assists | variant | 13,802 | 1.2487 | 1.7149 | -0.0810 | 0.9606 | 0.6608 |
| blocks | baseline | 13,802 | 0.4869 | 0.7077 | -0.0105 | 0.3464 | 0.4459 |
| blocks | variant | 13,802 | 0.4893 | 0.7097 | -0.0089 | 0.3498 | 0.4412 |
| points | baseline | 13,802 | 4.4112 | 5.8424 | -0.3244 | 3.4896 | 0.6429 |
| points | variant | 13,802 | 4.4152 | 5.8480 | -0.3372 | 3.5041 | 0.6419 |
| rebounds | baseline | 13,802 | 1.8410 | 2.4717 | -0.1138 | 1.4242 | 0.6518 |
| rebounds | variant | 13,802 | 1.8454 | 2.4764 | -0.1189 | 1.4232 | 0.6495 |
| steals | baseline | 13,802 | 0.7072 | 0.9513 | -0.0288 | 0.5729 | 0.3515 |
| steals | variant | 13,802 | 0.7079 | 0.9527 | -0.0283 | 0.5740 | 0.3482 |
| threes_made | baseline | 13,802 | 0.7485 | 1.0694 | -0.0130 | 0.5345 | 0.5063 |
| threes_made | variant | 13,802 | 0.7506 | 1.0721 | -0.0133 | 0.5375 | 0.5029 |

### Top-ranked projections

Each side judged on the rows *it* would have surfaced, so the two row
sets differ by construction. Reported separately from the paired tests
for that reason.

| Top-N | Stat | baseline MAE | variant MAE | Δ |
|---|---|---|---|---|
| 10 | assists | 1.8601 | 1.8623 | +0.0023 |
| 10 | blocks | 0.8260 | 0.8310 | +0.0050 |
| 10 | points | 5.5823 | 5.6232 | +0.0409 |
| 10 | rebounds | 2.6296 | 2.6044 | -0.0252 |
| 10 | steals | 0.9554 | 0.9445 | -0.0108 |
| 10 | threes_made | 1.2222 | 1.2311 | +0.0089 |
| 20 | assists | 1.6235 | 1.6266 | +0.0031 |
| 20 | blocks | 0.6987 | 0.7057 | +0.0070 |
| 20 | points | 5.3047 | 5.3086 | +0.0040 |
| 20 | rebounds | 2.2905 | 2.2851 | -0.0053 |
| 20 | steals | 0.8762 | 0.8764 | +0.0002 |
| 20 | threes_made | 1.0709 | 1.0702 | -0.0008 |

### By season (all stats pooled)

| Segment | n | baseline MAE | variant MAE | Δ |
|---|---|---|---|---|
| 2024 | 26,556 | 1.5569 | 1.5569 | -0.0000 |
| 2025 | 32,418 | 1.5870 | 1.5896 | +0.0026 |
| 2026 | 23,838 | 1.5734 | 1.5794 | +0.0060 |

### By player role (all stats pooled)

| Segment | n | baseline MAE | variant MAE | Δ |
|---|---|---|---|---|
| bench | 39,288 | 1.2230 | 1.2242 | +0.0012 |
| starter | 43,524 | 1.8898 | 1.8938 | +0.0041 |

### By expected-minutes bucket (all stats pooled)

| Segment | n | baseline MAE | variant MAE | Δ |
|---|---|---|---|---|
| 0-10 | 15,540 | 0.8625 | 0.8643 | +0.0018 |
| 10-20 | 22,308 | 1.4210 | 1.4200 | -0.0010 |
| 20-28 | 20,694 | 1.7795 | 1.7827 | +0.0032 |
| 28-34 | 16,872 | 1.9379 | 1.9444 | +0.0065 |
| 34+ | 7,398 | 2.1188 | 2.1247 | +0.0059 |

### By rest status (all stats pooled)

| Segment | n | baseline MAE | variant MAE | Δ |
|---|---|---|---|---|
| 2-3d | 52,878 | 1.5521 | 1.5547 | +0.0026 |
| 4-5d | 19,194 | 1.5980 | 1.6023 | +0.0043 |
| 6d+ | 6,990 | 1.6422 | 1.6405 | -0.0017 |
| b2b | 3,732 | 1.6198 | 1.6248 | +0.0050 |

## Interpretation

Pooled MAE rose by 0.17% when the recent-form level estimates — all three rolling means and the EWM — were replaced by the season-to-date average.

**Read this as a lower bound, not as the value of recent form.** The substitution is applied to the production-shaped frame after `rate_{stat}_last_10` and `usage_proxy_last_{5,10}` have already been derived from the last-10 windows, so those columns still carry recent form into the model, as do the rolling standard deviations and `minutes_trend_3_over_10`. Roughly half the recent-form channels survive the ablation, which is the most likely reason the degradation is small.

The honest conclusion is therefore narrow: replacing the recent-form *level* estimates alone costs little, because the model has other routes to the same information. A complete answer needs a variant that neutralises every recency-bearing channel, which is more than one variable and belongs in its own experiment.

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
- This measures how much the *fixed* model relies on recent-form inputs, not how much a refit model could extract from them. A model retrained without recent form would partially compensate through other features.
- **Recent form still reaches the model through channels this ablation does not touch**, so the measured degradation is a *lower bound*, not the value of recent form. `rate_{stat}_last_10` and `usage_proxy_last_{5,10}` are derived from the last-10 windows before the substitution is applied; `{stat}_rolling_std_{3,5,10}`, `player_{stat}_std_10` and `minutes_trend_3_over_10` also encode recency. Roughly half the recent-form channels survive.
- The season average resets each season, so early-season rows have very little history on either side and the contrast is weakest exactly where recent form should matter most.

## Recommendation

This is a research finding, not a deployment proposal. No production change
is recommended here and none was made.

Not worth further work on its own. Revisit only if a related change lands that could plausibly amplify it.

## Future work

- Build a total recent-form ablation that also neutralises rate_*_last_10, usage_proxy_last_*, the rolling standard deviations and minutes_trend_3_over_10 — the only design that can answer the question outright.
- Repeat within season phases (first 5 games, mid, late) to see where the gap opens.
- Restrict to players who changed team or role mid-season, where the season average should lag hardest.

## Reproduction

```bash
python3 learning/analytics_lab/experiments/framework/runner.py EXP005
```

Artifacts: `experiments/runs/EXP005/`

