# EXP002 — Opponent defensive rating in the def_rating slot

**Run:** 2026-07-25T15:08:30+00:00  |  **Author:** analytics_lab  |  **Status:** complete
**Baseline:** `reconstructed_production_logic_v1` (`reconstructed_production_logic`)  |  **Model fingerprint:** `e7353c24f46e9ada`

## Executive summary

**Question.** Does supplying the opponent's rolling defensive rating, rather than the player's own team's, improve prediction accuracy in the model's `def_rating_last_10` feature?

**Result.** Pooled MAE moves from **1.5734** (baseline) to **1.5743** (variant), **+0.05%**, across 13,802 paired player-games and 6 stat categories.

**Marginal.** Either statistically detectable but too small to matter, or large enough to matter but not statistically distinguishable. Not a finding on its own — check the direction below before reading anything into it.

Direction: the variant is **worse** than the baseline overall. Per-stat verdicts: 5 not_significant, 1 marginal.

## Question

Does supplying the opponent's rolling defensive rating, rather than the player's own team's, improve prediction accuracy in the model's `def_rating_last_10` feature?

**Hypothesis.** Yes, modestly. A player's own team's defensive rating carries almost no information about her own offensive output, so the slot is close to wasted; the opposing defence is the quantity the feature name implies and is genuinely predictive.

**Expected improvement.** 0.5-2% pooled MAE reduction on scoring-related stats.

**Feature(s) modified.** `def_rating_last_10`

**Columns the run verified as changed.** `def_rating_last_10`

## Method

Current production stat-model binaries fed the inputs production actually serves: previous-game actual minutes, one-game-stale rolling features, and UTC-date-differenced rest days clipped to 0-7.

The variant frame is identical to the baseline frame except in the declared
columns; the runner aborts if any other column moves. Both sides are scored
with the same production model binaries on the same player-games, so every
comparison below is paired.

`def_rating_last_10` is replaced with `opp_def_rating_last_10` from the lab's as-of team-context reconstruction — the opposing team's shift(1) rolling defensive rating over its last 10 completed games. Both series are built by the same code from the same box scores, so the only change is whose defence is described.

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
| points | 13,802 | 4.4112 | 4.4124 | +0.0012 | +0.03% | [-0.0003, +0.0025] | 3.73e-01 | +0.014 | 44.7% | `not_significant` |
| rebounds | 13,802 | 1.8410 | 1.8409 | -0.0001 | -0.00% | [-0.0004, +0.0003] | 7.88e-01 | -0.004 | 46.9% | `not_significant` |
| assists | 13,802 | 1.2459 | 1.2478 | +0.0019 | +0.15% | [+0.0006, +0.0031] | 5.89e-02 | +0.025 | 45.4% | `not_significant` |
| threes_made | 13,802 | 0.7485 | 0.7503 | +0.0018 | +0.24% | [+0.0011, +0.0025] | 5.98e-05 | +0.043 | 43.7% | `marginal` |
| steals | 13,802 | 0.7072 | 0.7074 | +0.0003 | +0.04% | [-0.0000, +0.0006] | 7.88e-01 | +0.015 | 47.2% | `not_significant` |
| blocks | 13,802 | 0.4869 | 0.4869 | -0.0000 | -0.01% | [-0.0001, +0.0001] | 7.88e-01 | -0.006 | 45.4% | `not_significant` |

Negative Δ favours the variant. A CI spanning zero means the paired
difference is not distinguishable from no change.

### Full metric set

| Stat | Side | n | MAE | RMSE | Bias | Median abs err | Correlation |
|---|---|---|---|---|---|---|---|
| assists | baseline | 13,802 | 1.2459 | 1.7074 | -0.0702 | 0.9596 | 0.6648 |
| assists | variant | 13,802 | 1.2478 | 1.7093 | -0.0698 | 0.9598 | 0.6639 |
| blocks | baseline | 13,802 | 0.4869 | 0.7077 | -0.0105 | 0.3464 | 0.4459 |
| blocks | variant | 13,802 | 0.4869 | 0.7077 | -0.0104 | 0.3464 | 0.4461 |
| points | baseline | 13,802 | 4.4112 | 5.8424 | -0.3244 | 3.4896 | 0.6429 |
| points | variant | 13,802 | 4.4124 | 5.8446 | -0.3242 | 3.4925 | 0.6426 |
| rebounds | baseline | 13,802 | 1.8410 | 2.4717 | -0.1138 | 1.4242 | 0.6518 |
| rebounds | variant | 13,802 | 1.8409 | 2.4717 | -0.1139 | 1.4202 | 0.6517 |
| steals | baseline | 13,802 | 0.7072 | 0.9513 | -0.0288 | 0.5729 | 0.3515 |
| steals | variant | 13,802 | 0.7074 | 0.9512 | -0.0279 | 0.5728 | 0.3519 |
| threes_made | baseline | 13,802 | 0.7485 | 1.0694 | -0.0130 | 0.5345 | 0.5063 |
| threes_made | variant | 13,802 | 0.7503 | 1.0715 | -0.0125 | 0.5354 | 0.5037 |

### Top-ranked projections

Each side judged on the rows *it* would have surfaced, so the two row
sets differ by construction. Reported separately from the paired tests
for that reason.

| Top-N | Stat | baseline MAE | variant MAE | Δ |
|---|---|---|---|---|
| 10 | assists | 1.8601 | 1.8585 | -0.0016 |
| 10 | blocks | 0.8260 | 0.8260 | +0.0000 |
| 10 | points | 5.5823 | 5.5909 | +0.0086 |
| 10 | rebounds | 2.6296 | 2.6275 | -0.0021 |
| 10 | steals | 0.9554 | 0.9573 | +0.0020 |
| 10 | threes_made | 1.2222 | 1.2217 | -0.0005 |
| 20 | assists | 1.6235 | 1.6244 | +0.0008 |
| 20 | blocks | 0.6987 | 0.6991 | +0.0004 |
| 20 | points | 5.3047 | 5.3040 | -0.0006 |
| 20 | rebounds | 2.2905 | 2.2917 | +0.0013 |
| 20 | steals | 0.8762 | 0.8775 | +0.0012 |
| 20 | threes_made | 1.0709 | 1.0726 | +0.0017 |

### By season (all stats pooled)

| Segment | n | baseline MAE | variant MAE | Δ |
|---|---|---|---|---|
| 2024 | 26,556 | 1.5569 | 1.5584 | +0.0015 |
| 2025 | 32,418 | 1.5870 | 1.5880 | +0.0010 |
| 2026 | 23,838 | 1.5734 | 1.5733 | -0.0002 |

### By player role (all stats pooled)

| Segment | n | baseline MAE | variant MAE | Δ |
|---|---|---|---|---|
| bench | 39,288 | 1.2230 | 1.2238 | +0.0008 |
| starter | 43,524 | 1.8898 | 1.8906 | +0.0008 |

### By expected-minutes bucket (all stats pooled)

| Segment | n | baseline MAE | variant MAE | Δ |
|---|---|---|---|---|
| 0-10 | 15,540 | 0.8625 | 0.8633 | +0.0008 |
| 10-20 | 22,308 | 1.4210 | 1.4222 | +0.0012 |
| 20-28 | 20,694 | 1.7795 | 1.7804 | +0.0009 |
| 28-34 | 16,872 | 1.9379 | 1.9385 | +0.0006 |
| 34+ | 7,398 | 2.1188 | 2.1189 | +0.0001 |

### By rest status (all stats pooled)

| Segment | n | baseline MAE | variant MAE | Δ |
|---|---|---|---|---|
| 2-3d | 52,878 | 1.5521 | 1.5529 | +0.0008 |
| 4-5d | 19,194 | 1.5980 | 1.5991 | +0.0011 |
| 6d+ | 6,990 | 1.6422 | 1.6431 | +0.0009 |
| b2b | 3,732 | 1.6198 | 1.6195 | -0.0003 |

## Interpretation

The baseline slot holds the player's own team's defensive rating, which describes how well *her* team defends — a quantity with no direct bearing on her own scoring. The variant holds the opposing defence's rating.

Baseline slot: mean 101.09, sd 5.92, 0.5% null. If the substitution barely moves error, the likeliest explanation is not that opponent defence is uninformative but that the fixed model gives this slot little weight — a hypothesis that only retraining can separate from the alternative.

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
- The model was fitted with own-team ratings in this slot, so its learned coefficient reflects that relationship. A slot swap without retraining understates what a correctly specified feature could contribute.
- Both series come from the lab reconstruction, not the production feed, which has carried no ratings at all since 2026-06-28.

## Recommendation

This is a research finding, not a deployment proposal. No production change
is recommended here and none was made.

Not worth further work on its own. Revisit only if a related change lands that could plausibly amplify it.

## Future work

- Add opponent defensive rating as an additional feature rather than a substitution, and retrain — the two are not mutually exclusive.
- Split by stat: an opposing defence should matter far more for points than for rebounds or blocks.

## Reproduction

```bash
python3 learning/analytics_lab/experiments/framework/runner.py EXP002
```

Artifacts: `experiments/runs/EXP002/`

