# Proposed production changes — for separate review

**Date:** 2026-07-25
**Status: PROPOSED ONLY. Nothing here has been applied.** Phase 2 made no
production change; this is the queue for a later, separately approved piece of
work.

Ordered by expected benefit per unit of risk. Each entry names the file, the
defect, the evidence, and a rollback.

---

## P1 — Feed projected minutes into the stat-model feature frame

**File:** `simulate_wnba_today.py`, `build_projection_rows()` (~line 618)

**Defect.** `projected_minutes` is computed from the minutes model and stored on
the frame, but the `minutes` column the stat models actually consume is left
holding the player's *previous game's actual minutes*, carried in from
`build_wnba_features_today.py`. The minutes model's output never reaches the
stat models.

**Evidence.** [`minutes_leakage_audit.md`](minutes_leakage_audit.md).
On 13,802 eligible player-games, with the model and every other feature held
identical:

| `minutes` input | pooled MAE |
|---|---|
| `D_HISTORICAL_PROJECTED_MINUTES` (the minutes model's own output) | **1.5032** |
| `C_EWM_MINUTES` | 1.5157 |
| `B_PREVIOUS_GAME_MINUTES` — **what production ships** | 1.5670 |

**Expected effect.** −0.064 pooled MAE (−4.1%), no retraining, no new data.

**Change.** After computing `projected_minutes`, assign it into the feature frame
before the stat-model loop.

**Risk.** The stat models were trained with `minutes` meaning *actual* minutes.
Substituting a projection changes the input distribution, so the gain measured
here — which used the same substitution — should be confirmed in shadow before
promotion. Guard behind a flag defaulting off.

**Rollback.** Flag off.

---

## P2 — Retrain stat models without target-game minutes

**Files:** `wnba_model_utils.py` (`feature_columns()`), `train_wnba_models.py`

**Defect.** `minutes` is in the training feature list and is the target game's
actual value. The reported validation MAE (points 3.25) is therefore optimistic
and is not an estimate of deployed error.

**Evidence.** Same report. Actual-minutes leakage inflates apparent accuracy by
**16.3%** (1.2928 leaked vs 1.5032 best leak-safe pooled MAE). Verified
independently: `corr(minutes, points) = 0.780` vs `0.624` for the rolling form,
and 100% of served rows carry the previous game's actual minutes in that slot.

**Expected effect.** No immediate accuracy gain — an honest metric instead of an
inflated one, and a model whose training and serving inputs finally agree.

**Change.** Replace `minutes` with a leak-safe minutes estimate (P1's projection,
or `minutes_ewm`) in both training and serving, so the same quantity appears on
both sides.

**Risk.** Larger than P1: it changes the models. Needs a full shadow cycle.

**Rollback.** Restore the previous binaries — but note there are none to restore
to, which is why P5 exists.

---

## P3 — Repair the team-context pace / rating feed

**File:** `fetch_wnba_data.py` (team-context ingestion) →
`data/raw/wnba_team_context.csv`

**Defect.** `pace`, `off_rating` and `def_rating` have been null for every row
since **2026-06-28** (118 of 118 rows; 33% coverage in June 2026). Three model
features depend on them and are being median-imputed.

**Evidence.** [`team_context_reconstruction.md`](team_context_reconstruction.md).
**25.3%** of the live 2026-07-22 board has null `pace_last_10` /
`off_rating_last_10` / `def_rating_last_10`. **18 of 69** archived boards (33.3%
of archived rows) fall after the outage.

**Change.** Compute the fields from box-score totals rather than depending on the
upstream field:

```
possessions = FGA - OREB + TOV + 0.44 * FTA
off_rating  = 100 * team_points     / game_possessions
def_rating  = 100 * opponent_points / game_possessions
```

The lab reconstruction correlates **0.986–0.989** with the production values over
the 873-row healthy overlap, with a small scale offset (pace +1.0 possession,
ratings −1.3 points), so it is a validated drop-in.

**Risk.** Low. Restores a feature that is currently dead.

**Rollback.** Revert the ingestion change; behaviour returns to imputation.

---

## P4 — Settle on one date convention

**Files:** `fetch_wnba_data.py`, `wnba_model_utils.py`
(`normalize_player_games`), `wnba_model/pipeline/service.py`

**Defect.** Production runs two conventions at once:

- `wnba_player_games.game_date` is the **UTC date** (0.00% mismatch vs UTC,
  46.63% vs the ET slate date across 16,345 rows)
- the published board's `GAME_DATE` is the **ET slate date** (verified: joining
  the archive to games on the ET slate date matches every board team; joining on
  the UTC date finds zero games for an all-evening slate)

**Consequence.** Every evening game is filed a day late in the actuals. On days
mixing an afternoon and an evening game two different ET slates collapse onto one
key, producing **126 duplicate `(player_key, game_date)` rows on 7 dates**. Any
join between the board and the actuals on a date column silently mismatches
evening games.

**Change.** Store the tip-off timestamp and derive the ET slate date from it, as
`inventory/parse_espn_cache.py` does. Keep both columns; never overload one.

**Risk.** Medium — touches slate selection, grading joins and archive naming, all
at once. Sequence it after P1/P3.

**Rollback.** Revert; the duplicate rows return.

---

## P5 — Version the model binaries

**File:** `train_wnba_models.py`

**Defect.** Every training run overwrites `data/models/wnba_*_model.joblib` in
place. No historical model version exists, so no past board can be reproduced and
no rollback target exists. `model_version` in the graded ledger is a single
constant string across all 2,689 rows.

**Change.** Write to a content- or date-stamped path and symlink the current one;
record the version string on every projection row.

**Risk.** Low, additive.

**Effect.** Makes an exact historical production baseline possible in future —
Phase 2G is forced to rule it out today precisely because of this.

---

## P6 — Label preseason in the training history

**Files:** `fetch_wnba_data.py`, `build_wnba_dataset.py`

**Defect.** 937 preseason player-game rows across 32 games sit in
`wnba_player_games.csv` with no `season_type` column, so the trainer cannot
exclude them. Preseason rotations are not representative of regular-season roles.

**Change.** Carry ESPN's `season.type` through ingestion and filter to regular +
postseason for training.

**Risk.** Low. Slightly reduces the training set.

---

## Not proposed

**One-game-stale rolling features.** Real, and measured at **+0.0091 pooled MAE
(+0.59%)** — see [`rolling_staleness_audit.md`](rolling_staleness_audit.md). It
is roughly one seventh the size of the recoverable minutes gap, and fixing it
means rebuilding the serving path to construct a new upcoming-game row rather
than reusing the last stored one. That is a larger change than P1 for a smaller
return, so it should wait until P1 and P2 have landed and the benefit can be
re-measured against the corrected models.
