# Phase 3A — Minutes Projection Audit: Root-Cause Summary

**Date:** 2026-06-07
**Scope:** Read-only audit. No production files modified.
**Graded sample:** 588 player-games (slates 2026-05-08 → 2026-06-06), every row enriched
with full minutes history (100% join coverage) from `data/raw/wnba_player_games.csv`.

**Baseline minutes accuracy:** MAE 5.613 | RMSE 7.225 | bias −1.512 (systematic under-projection).

---

## 1. The pipeline (how projected minutes are produced)

`train_wnba_minutes_model.py` → `train_ensemble_models()` (`wnba_model_utils.py`)
trains a 2-model ensemble (Ridge + HistGradientBoosting, averaged) on the 83 features
returned by `feature_columns()`. At inference (`simulate_wnba_today.py`) the same
ensemble predicts `minutes`, which then drives the Monte-Carlo stat distributions.

## 2. Features that actually move projected minutes (feature importance report)

Permutation importance (drop in MAE when shuffled) on the live tree model:

| rank | feature | perm-importance (MAE) |
|---|---|---|
| 1 | **season_avg_minutes** | **1.400** |
| 2 | points_ewm | 0.233 |
| 3 | minutes_trend_3_over_10 | 0.055 |
| 4 | points_rolling_mean_10 | 0.045 |
| 5 | assists_ewm | 0.044 |
| 6 | rebounds_ewm | 0.044 |
| 7 | team | 0.033 |

**The model is almost entirely a function of `season_avg_minutes`.** The next feature is
6× weaker. No other minutes-specific signal carries meaningful weight.

## 3. ROOT CAUSE #1 — recent-minutes signal is computed but discarded

The training dataset (`wnba_training_dataset.csv`) already contains
`minutes_rolling_mean_3/5/10` and `minutes_rolling_std_3/5/10` (columns 46–51). **None of
them are in the minutes model's feature list.** `feature_columns()` builds rolling
mean/std only for the six box-score stats (points, rebounds, …), never for `minutes`
itself. The model's only view of recent playing time is `season_avg_minutes` plus one
weak ratio (`minutes_trend_3_over_10`).

Consequence: the projection **lags every rotation change**. When a player's role expands
or contracts, the season average drags the projection toward the stale level.

### Counterfactual proof (minutes_counterfactual_baselines.csv)
Replaying the same 588 graded games with naive recent-minutes baselines the model ignores:

| method | MAE | RMSE | bias |
|---|---|---|---|
| **production** | **5.613** | **7.225** | **−1.512** |
| last-3 avg | 4.737 | 6.308 | +0.020 |
| last-5 avg | **4.630** | **6.093** | −0.175 |
| last-10 avg | 4.711 | 6.157 | −0.290 |
| season avg | 5.311 | 6.999 | −0.953 |
| blend 0.5·last3 + 0.5·last5 | **4.599** | 6.099 | −0.077 |

A bare last-5 average beats the full production model by **−17.5% MAE / −15.7% RMSE** and
removes nearly all the bias. On low-projected players (proj < 18 min, n=77) production MAE
is 9.60 vs 5.83 for last-5 — a **−39%** gap on exactly the known weakness segment.

## 4. ROOT CAUSE #2 — unmodeled in-game availability (over-projection tail)

The other failure mode is players projected at a normal load who post ~4–13 minutes due to
in-game injury, ejection, or blowout rest (Satou Sabally 25.6→4, Rickea Jackson 30→11,
Skylar Diggins 31→12). `wnba_player_status.csv` is **empty (0 rows)**, so there is no
pre-game injury/availability signal at all. These misses are **not fixable by the minutes
model** — they need an availability/status feed and belong in the floor/ceiling work
(Phase 3D) and a status pipeline, not in the point estimate.

## 5. Error breakdown (minutes_error_breakdown.csv)

| dimension | worst segments |
|---|---|
| **role** | bench MAE **7.47** (bias −4.57) vs starter 4.76 — bench/rotation is the problem |
| **proj-minutes bucket** | <10 → MAE **14.50** (bias −14.0); 10–18 → 9.03 (bias −8.5); 26+ → 4.30 |
| **volatility (last-5 std)** | high(6+) MAE 6.63 vs low(<3) 4.42 |
| **team** | POR 7.67 (bias −7.6), CON 7.22, NYL 7.00 worst; ATL 2.51 best |
| **injury-return (10d+ rest)** | n=59, MAE 4.86 but high variance; several in top-20 |

WAS (5.91), CHI (4.88), GSV (5.34) sit mid-pack on minutes — their projection-accuracy
weakness is **not primarily a minutes problem**, which reframes Phase 3C.

## 6. Top-20 misses (minutes_top20_misses.csv) — pattern

Two clean clusters:
- **Under-projection / lagged rotation (controllable):** Nia Coffey appears **5×** —
  projected ~9 (season avg 15) while her last-5 average was 21–28; she plays 25–35. Also
  Marine Johannes, Stefanie Dolson, Jessica Shepard. Every one is a case where
  `minutes_rolling_mean_5` >> `season_avg_minutes`. **Directly fixed by Root Cause #1.**
- **Over-projection / in-game availability (not controllable from minutes features):**
  Sabally, Siegrist, Hayes, R. Jackson, Diggins — normal projection, DNP-level actual.

## 7. Secondary finding — position feature is dead

`wnba_player_positions.csv` covers only **20 players**; `position` is "UNK" for ~87% of
training rows. The model's `position` categorical is effectively noise. Either backfill
positions (ESPN/stats feed) or drop the feature.

---

## Recommendations (feeds Phase 3B–3D)

1. **Add `minutes_rolling_mean_3/5/10` and `minutes_rolling_std_3/5/10` to the minutes
   model feature set** (they already exist in the dataset). Highest-leverage, lowest-risk
   change — counterfactual shows ~17% MAE / most of the bias recoverable. **Shadow-train
   and validate before promotion.**
2. **Build the rotation-stability layer (Phase 3B)** to formalize last-3/5/10, std, starts,
   consecutive starts/bench, and classify players — this both feeds the model and powers
   floor/ceiling (3D).
3. **Stand up an availability/status feed** to attack Root Cause #2; until then treat it as
   irreducible point-estimate error and capture it as downside in the floor model (3D).
4. **Re-frame Phase 3C:** WAS/CHI/GSV underperformance is not minutes-driven; investigate
   their stat-projection / team-context inputs separately.
5. **Backfill or drop `position`.**

**Deliverables produced:** `minutes_feature_report.csv`,
`minutes_error_breakdown.csv`, `minutes_top20_misses.csv`,
`minutes_counterfactual_baselines.csv`, this summary.
