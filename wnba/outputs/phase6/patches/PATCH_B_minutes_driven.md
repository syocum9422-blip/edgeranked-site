# Patch B — Minutes-Driven Stat Architecture (Variant C)  **— DRAFT ONLY, DO NOT DEPLOY**

**Status:** Canary only. Not for production until the Phase 6C/6D canary confirms persistence.
**Files:** `simulate_wnba_today.py`, `wnba_model_utils.py` (rate models), new training script,
new model artifacts, dataset rebuild.
**Risk:** Medium (touches the core projection path). Requires new artifacts + retrain.
**Rollback:** restore the listed files from backup + keep prior `data/models/*` joblibs.

## What Variant C does
Project a **per-minute rate** per market and multiply by `projected_minutes`, so the
(improved) minutes projection scales the stat totals 1:1, instead of the stat models reading a
lagged `minutes` feature that ignores the minutes model.

## B.1 — Inject projected_minutes into the stat-model feature (minimal "Variant B" step)
`simulate_wnba_today.build_projection_rows`, after line 161:

**Before:**
```python
    projection_frame["projected_minutes"] = np.clip(m_pred, 5, 40)
    projection_frame["minutes_model_gap"] = np.abs(m_ridge - m_tree)
    projection_frame["minutes_stability_score"] = 1.0 / (1.0 + projection_frame["player_minutes_std_10"].fillna(4.0))

    for stat, bundle in stat_models.items():
```
**After:**
```python
    projection_frame["projected_minutes"] = np.clip(m_pred, 5, 40)
    projection_frame["minutes_model_gap"] = np.abs(m_ridge - m_tree)
    projection_frame["minutes_stability_score"] = 1.0 / (1.0 + projection_frame["player_minutes_std_10"].fillna(4.0))

    # Variant C: feed the minutes-model projection into the stat models' `minutes` feature so
    # stat projections become minutes-aware (was a lagged snapshot value).
    projection_frame["minutes"] = projection_frame["projected_minutes"]

    for stat, bundle in stat_models.items():
```

## B.2 — Rate-model wiring (full Variant C)
Add per-minute rate models (target = `stat / minutes`, drop raw `minutes` from features) and
compute totals as `rate × projected_minutes`. Reference implementation validated in
`outputs/phase3/phase5b_stat_variants.py` (`train_rate_model`, `RATE_FEATS`).

New `build_projection_rows` stat loop (conceptual):
```python
    for stat, bundle in rate_models.items():           # rate_models, not total stat_models
        _, _, rate_pred = predict_ensemble(bundle, projection_frame)   # per-minute rate
        total = np.clip(rate_pred * projection_frame["projected_minutes"], 0, None)
        projection_frame[f"{stat}_proj"] = total
```
Confidence (`minutes_stability_score`, agreement) and the Monte-Carlo blend in
`simulate_player_row` are unchanged — they continue to consume `projected_minutes`.

## B.3 — New training script & artifacts
- New `train_wnba_rate_models.py` (mirror of `train_wnba_models.py`): target `stat/minutes` on
  rows with `minutes >= 8`, features = `feature_columns()` minus `minutes`; save
  `data/models/wnba_{stat}_rate_model.joblib` (6 files).
- Keep existing `data/models/wnba_{stat}_model.joblib` for rollback / hybrid.

## B.4 — Dataset rebuild requirement
- Rebuild the processed training dataset to include the current season before retraining
  (the production processed set was stale at 2025-09-12; raw `wnba_player_games.csv` is
  current). Command: `python build_wnba_dataset.py` (writes `DATASET_PATH`). **Back up the
  existing dataset first.** Variant C's edge grows with in-season data, so the dataset must be
  current at promotion time.
- Retrain the minutes model with the Phase-3 Variant-C feature set (add the 6
  `minutes_rolling_mean/std_3/5/10` to `feature_columns()`), then `train_wnba_minutes_model.py`.

## Validation commands (canary, not production)
```bash
# leakage-free temporal re-validation (reproduces Phase 5 numbers):
.venv/bin/python outputs/phase3/phase5b_stat_variants.py     # projection MAE/RMSE
.venv/bin/python outputs/phase3/phase5c_betting_resim.py     # Brier/log-loss/coverage/winrate
# weekly canary (Phase 6C):
.venv/bin/python sports/wnba/wnba_canary_validation.py
```

## Rollback commands
```bash
# code:
cp backups/wnba_phase6_<TS>/simulate_wnba_today.py sports/wnba/
cp backups/wnba_phase6_<TS>/wnba_model_utils.py   sports/wnba/
# models (remove rate models, keep originals):
rm -f sports/wnba/data/models/wnba_*_rate_model.joblib
# dataset/minutes model: restore from backups/wnba_phase3_20260607_001016/
```

## Why not deploy now
30-day shadow gains are real but modest (Brier −1.3%, log-loss −1.1%, win-rate +0.8pp) and
one month old; the 7-day window regressed slightly on Brier. Promotion waits on the canary
(Phase 6C/6D) confirming persistence over 2–4 weeks.
