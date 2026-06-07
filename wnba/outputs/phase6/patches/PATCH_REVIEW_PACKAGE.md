# Phase 6A — Patch Review Package

## Patches
| Patch | Scope | Status | Deploy |
|---|---|---|---|
| **A — Availability fix** | `fetch_wnba_data.py` (UA + <5KB guard) | Validated (Phase 6B) | **DEPLOYED** |
| **B — Minutes-driven stat architecture** | core projection path + new rate models | Draft, canary-gated | **DO NOT DEPLOY** |

## File list

### Patch A (deployed)
- `sports/wnba/fetch_wnba_data.py` — 2 hunks (line 335 UA; +size guard after line 375). 12-line diff.
- Side effect on deploy: `data/raw/wnba_player_status.csv` now populates (9 rows today).

### Patch B (draft — files it WOULD touch on promotion)
- `sports/wnba/simulate_wnba_today.py` — `build_projection_rows`: inject `projected_minutes`
  into the `minutes` feature (B.1) and/or swap stat totals for rate × projected minutes (B.2).
- `sports/wnba/wnba_model_utils.py` — add `minutes_rolling_mean/std_3/5/10` to
  `feature_columns()` (Phase-3 Variant-C minutes model).
- NEW `sports/wnba/train_wnba_rate_models.py` + `data/models/wnba_{stat}_rate_model.joblib` ×6.
- `data/processed/wnba_training_dataset.csv` — rebuild to current season.
- `models/wnba_minutes_model.joblib` — retrain with Variant-C features.

## Risk assessment

| Item | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **A:** ESPN HTML/class change breaks parser | low | low (falls back to empty = today's behavior) | <5KB guard raises; parser already tolerant; canary surfaces 0-row weeks |
| **A:** ESPN blocks generic UA later | low | low | guard raises → fallback; rotate UA if needed |
| **A:** wrongly excludes an active player | very low | medium | only `out/doubtful/inactive/suspended` excluded; today 0 excluded; statuses sourced verbatim |
| **B:** projection regression on thin in-season data | medium | medium | canary 30d gate; promote only after 3 consecutive passing weeks |
| **B:** rate model unstable for low-minute players | medium | low | rate trained on `minutes>=8`; totals clipped ≥0; hybrid (D) available |
| **B:** train/serve minutes mismatch | low | medium | serve `projected_minutes`; validated leakage-free in Phase 5 |
| **B:** breaks confidence/guardrail assumptions | low | medium | confidence + MC blend unchanged; only `*_proj` source changes |

## Rollback
- **A:** `cp backups/wnba_phase6_20260607_005334/fetch_wnba_data.py sports/wnba/` (verify `Chrome/124.0` returns).
- **B:** restore `simulate_wnba_today.py`, `wnba_model_utils.py` from backup; `rm data/models/wnba_*_rate_model.joblib`;
  restore dataset + minutes model from `backups/wnba_phase3_20260607_001016/`.

## Validation entry points
- A: `phase5e_availability.py` / commands in `PATCH_A_availability.md`.
- B: `wnba_canary_validation.py` (weekly) → `wnba_promotion_readiness.py` (scorecard).
