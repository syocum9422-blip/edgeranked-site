# Phase 5A — Stat Projection Architecture Map & Dependency Report

**Date:** 2026-06-07. Read-only. Production untouched.

## Pipeline (per slate)
`build_wnba_features_today.py` → `today_features` → `simulate_wnba_today.build_projection_rows`
(minutes model + 6 stat models predict) → `simulate_player_row` (10k Monte Carlo) →
`build_wnba_best_bets` (calibrate + guardrails + 0.56 threshold).

## The three disconnected "minutes" quantities

| # | Quantity | Source | Where used |
|---|---|---|---|
| 1 | **`minutes`** (a stat-model **feature**) | carried from the player's latest feature snapshot in `build_wnba_features_today` (a lagged/blended estimate; ≠ rolling-5, ≠ last game, ≠ season avg) | **direct input to all 6 stat models** (feature_list includes `minutes`) |
| 2 | **`projected_minutes`** | the minutes-model ensemble (`build_projection_rows` line 160-161) | **only** the Monte-Carlo rate blend (35% weight) + variance + confidence |
| 3 | `season_avg_minutes`, `minutes_rolling_mean_3/5/10`, `player_minutes_std_10` | dataset | features in both minutes and stat models |

**The disconnect (root cause confirmed by code):** `build_projection_rows` computes
`projected_minutes` (#2) and then immediately calls the stat models on the same frame, which
still carries the *separate* `minutes` feature (#1). It **never** assigns
`projection_frame["minutes"] = projected_minutes`. So the well-calibrated minutes projection
is invisible to the stat models; they instead consume a noisier lagged estimate.

## Per-market dependency report (all 6 markets share one feature set)

All stat models (`wnba_{points,rebounds,assists,threes_made,steals,blocks}_model.joblib`,
84 features each) are trained identically on `feature_columns()` minus their own target.

| Question | Answer |
|---|---|
| Inputs used | 84 features: `minutes`, `season_avg_minutes`, `minutes_trend_3_over_10`, `player_minutes_std_10`, `rate_{stat}_last_10` (per-min historical rates), the 6 stats' rolling mean/std/ewm, opponent-allowed-last-10, schedule, team/opp/pos categoricals |
| Are **projected minutes** (#2) used? | **No** — not in any stat model's feature list and never injected at inference |
| How do minutes affect projections? | (a) via the `minutes` **feature** (#1) inside the stat model — total learned ≈ rate × minutes; (b) post-hoc in `simulate_player_row`: `blended_rate = 0.65·(proj/proj_min) + 0.35·hist_rate`, `sampled_mean = sim_minutes·sampled_rate` → `E[total] = 0.65·proj + 0.35·(proj_min·hist_rate)`. Live minutes (#2) only touches the **0.35** term |
| Do minutes influence rate stats? | Indirectly: `rate_{stat}_last_10` features are per-minute historical rates; `hist_rate` enters the 35% MC blend |
| Do minutes influence confidence? | **Yes, heavily:** `minutes_stability_score = 1/(1+player_minutes_std_10)` is **45%** of the confidence score (`compute_confidence_label`); `minutes_model_gap` feeds the 35% agreement term |

## Why Phase 4 saw no betting movement
Improving the minutes **model** (#2) only changed the 0.35 MC blend term and confidence — not
the stat-model totals (driven by feature #1, which the minutes model never updates). Hence
minutes accuracy did not propagate to bet probabilities.

## Implication for Phase 5B variants
- **B (cheap, high-leverage):** inject `projected_minutes` (#2) into the stat models' `minutes`
  feature at inference — make the existing models consume the good estimate.
- **C (explicit):** train per-minute **rate** models (target = stat/minutes); total =
  `rate × projected_minutes`. Minutes now scales totals 1:1.
- **D (hybrid):** rate model + projected minutes + matchup/context, blended with the totals model.

The Phase-3 Variant-C minutes model should only gain betting value once one of these makes the
stat layer consume `projected_minutes`.
