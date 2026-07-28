# EXP001 — Projected minutes vs previous-game minutes

**Run:** 2026-07-25T15:08:24+00:00  |  **Author:** analytics_lab  |  **Status:** complete
**Baseline:** `reconstructed_production_logic_v1` (`reconstructed_production_logic`)  |  **Model fingerprint:** `e7353c24f46e9ada`

## Executive summary

**Question.** Does feeding the minutes model's projection into the stat models' `minutes` feature produce more accurate projections than the previous-game actual minutes production currently serves?

**Result.** Pooled MAE moves from **1.5734** (baseline) to **1.5364** (variant), **-2.35%**, across 13,802 paired player-games and 6 stat categories.

**Meaningful.** The change is statistically significant after Holm correction *and* clears the practical threshold. Worth a dedicated follow-up study before anyone discusses production.

Direction: the variant is **better** than the baseline overall. Per-stat verdicts: 3 meaningful, 3 not_significant.

## Question

Does feeding the minutes model's projection into the stat models' `minutes` feature produce more accurate projections than the previous-game actual minutes production currently serves?

**Hypothesis.** Yes. A single previous observation is a noisy estimate of the minutes a player is about to log; a model fitted on prior-game features should estimate it better, and the stat models consume that slot heavily.

**Expected improvement.** 3-5% pooled MAE reduction, based on the Phase 2C variant sweep.

**Feature(s) modified.** `minutes`

**Columns the run verified as changed.** `minutes`

## Method

Current production stat-model binaries fed the inputs production actually serves: previous-game actual minutes, one-game-stale rolling features, and UTC-date-differenced rest days clipped to 0-7.

The variant frame is identical to the baseline frame except in the declared
columns; the runner aborts if any other column moves. Both sides are scored
with the same production model binaries on the same player-games, so every
comparison below is paired.

The minutes model (`models/wnba_minutes_model.joblib`) is run on the same as-of feature frame, its output clipped to [5, 40] exactly as production does, and written into the `minutes` column. Nothing else changes.

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
| points | 13,802 | 4.4112 | 4.2627 | -0.1485 | -3.37% | [-0.1922, -0.1021] | 2.86e-11 | -0.056 | 52.5% | `meaningful` |
| rebounds | 13,802 | 1.8410 | 1.7875 | -0.0535 | -2.91% | [-0.0708, -0.0360] | 2.86e-11 | -0.053 | 52.7% | `meaningful` |
| assists | 13,802 | 1.2459 | 1.2388 | -0.0071 | -0.57% | [-0.0165, +0.0032] | 4.37e-01 | -0.012 | 49.8% | `not_significant` |
| threes_made | 13,802 | 0.7485 | 0.7352 | -0.0133 | -1.78% | [-0.0180, -0.0085] | 8.29e-05 | -0.046 | 49.9% | `meaningful` |
| steals | 13,802 | 0.7072 | 0.7094 | +0.0022 | +0.32% | [-0.0018, +0.0062] | 2.18e-02 | +0.009 | 48.6% | `not_significant` |
| blocks | 13,802 | 0.4869 | 0.4849 | -0.0020 | -0.42% | [-0.0042, +0.0001] | 5.72e-01 | -0.015 | 49.5% | `not_significant` |

Negative Δ favours the variant. A CI spanning zero means the paired
difference is not distinguishable from no change.

### Full metric set

| Stat | Side | n | MAE | RMSE | Bias | Median abs err | Correlation |
|---|---|---|---|---|---|---|---|
| assists | baseline | 13,802 | 1.2459 | 1.7074 | -0.0702 | 0.9596 | 0.6648 |
| assists | variant | 13,802 | 1.2388 | 1.7035 | -0.1399 | 0.9005 | 0.6665 |
| blocks | baseline | 13,802 | 0.4869 | 0.7077 | -0.0105 | 0.3464 | 0.4459 |
| blocks | variant | 13,802 | 0.4849 | 0.7066 | -0.0242 | 0.3183 | 0.4494 |
| points | baseline | 13,802 | 4.4112 | 5.8424 | -0.3244 | 3.4896 | 0.6429 |
| points | variant | 13,802 | 4.2627 | 5.6730 | -0.7550 | 3.2622 | 0.6622 |
| rebounds | baseline | 13,802 | 1.8410 | 2.4717 | -0.1138 | 1.4242 | 0.6518 |
| rebounds | variant | 13,802 | 1.7875 | 2.4096 | -0.2319 | 1.3413 | 0.6689 |
| steals | baseline | 13,802 | 0.7072 | 0.9513 | -0.0288 | 0.5729 | 0.3515 |
| steals | variant | 13,802 | 0.7094 | 0.9457 | -0.0552 | 0.5517 | 0.3589 |
| threes_made | baseline | 13,802 | 0.7485 | 1.0694 | -0.0130 | 0.5345 | 0.5063 |
| threes_made | variant | 13,802 | 0.7352 | 1.0591 | -0.0607 | 0.5035 | 0.5192 |

### Top-ranked projections

Each side judged on the rows *it* would have surfaced, so the two row
sets differ by construction. Reported separately from the paired tests
for that reason.

| Top-N | Stat | baseline MAE | variant MAE | Δ |
|---|---|---|---|---|
| 10 | assists | 1.8601 | 1.8329 | -0.0271 |
| 10 | blocks | 0.8260 | 0.8097 | -0.0163 |
| 10 | points | 5.5823 | 5.4288 | -0.1535 |
| 10 | rebounds | 2.6296 | 2.5653 | -0.0643 |
| 10 | steals | 0.9554 | 0.9447 | -0.0106 |
| 10 | threes_made | 1.2222 | 1.1949 | -0.0273 |
| 20 | assists | 1.6235 | 1.6064 | -0.0171 |
| 20 | blocks | 0.6987 | 0.6938 | -0.0049 |
| 20 | points | 5.3047 | 5.1224 | -0.1823 |
| 20 | rebounds | 2.2905 | 2.2699 | -0.0205 |
| 20 | steals | 0.8762 | 0.8576 | -0.0187 |
| 20 | threes_made | 1.0709 | 1.0489 | -0.0221 |

### By season (all stats pooled)

| Segment | n | baseline MAE | variant MAE | Δ |
|---|---|---|---|---|
| 2024 | 26,556 | 1.5569 | 1.5204 | -0.0365 |
| 2025 | 32,418 | 1.5870 | 1.5465 | -0.0405 |
| 2026 | 23,838 | 1.5734 | 1.5406 | -0.0329 |

### By player role (all stats pooled)

| Segment | n | baseline MAE | variant MAE | Δ |
|---|---|---|---|---|
| bench | 39,288 | 1.2230 | 1.1959 | -0.0271 |
| starter | 43,524 | 1.8898 | 1.8438 | -0.0460 |

### By expected-minutes bucket (all stats pooled)

| Segment | n | baseline MAE | variant MAE | Δ |
|---|---|---|---|---|
| 0-10 | 15,540 | 0.8625 | 0.8857 | +0.0232 |
| 10-20 | 22,308 | 1.4210 | 1.3195 | -0.1015 |
| 20-28 | 20,694 | 1.7795 | 1.7078 | -0.0717 |
| 28-34 | 16,872 | 1.9379 | 1.9254 | -0.0126 |
| 34+ | 7,398 | 2.1188 | 2.1909 | +0.0721 |

### By rest status (all stats pooled)

| Segment | n | baseline MAE | variant MAE | Δ |
|---|---|---|---|---|
| 2-3d | 52,878 | 1.5521 | 1.5248 | -0.0273 |
| 4-5d | 19,194 | 1.5980 | 1.5718 | -0.0262 |
| 6d+ | 6,990 | 1.6422 | 1.5154 | -0.1268 |
| b2b | 3,732 | 1.6198 | 1.5593 | -0.0605 |

## Interpretation

The substitution moves pooled MAE by -2.35% across 13,802 paired player-games.

This is the one experiment in the catalog testing a change that requires no new data and no retraining — the projection already exists in the production run and is discarded. 3,969 of 13,802 rows (28.8%) have the player's minutes moving by 8 or more from their previous game; those are the rows where a single prior observation is least defensible as an estimate, and where the per-segment tables should be read first.

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
- **The minutes model is itself scored in-sample**, so its projection is flattered relative to what a freshly fitted minutes model would achieve out of sample. The gap this experiment measures is an upper bound.
- The stat models were trained with `minutes` meaning *actual* minutes. Substituting a projection shifts that input's distribution, so a refit could change the size of the effect in either direction.

## Recommendation

This is a research finding, not a deployment proposal. No production change
is recommended here and none was made.

The effect is large and consistent enough to justify a dedicated follow-up study — ideally with retraining, so the ceiling can be measured rather than inferred from a fixed model's response.

## Future work

- Refit the stat models with projected minutes on both sides of training and serving, to measure the effect without the train/serve mismatch.
- Test whether a minutes model trained walk-forward, rather than the current in-sample binary, preserves the gain.

## Reproduction

```bash
python3 learning/analytics_lab/experiments/framework/runner.py EXP001
```

Artifacts: `experiments/runs/EXP001/`

