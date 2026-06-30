# WNBA V2 Deployment Plan

## Recommendation

Current recommendation: **controlled emergency staged promotion at 5% traffic**.

This is not a full V2 promotion. It is a business-continuity policy for a production model that is underperforming while the normal Phase 6 sample gate may be too slow for a low-volume WNBA season.

Measured evidence from `wnba_v2/outputs/tracker/dashboard.json` generated on 2026-06-30:

- Graded V2 recommendations: 863
- V2 hit rate: 50.64% with 95% CI [47.31%, 53.96%]
- Production hit rate on the same ledger: 52.38% with 95% CI [49.04%, 55.69%]
- V2 Brier: 0.2594 vs production 0.3170; delta = +0.0576
- V2 ECE: 0.0977 vs production 0.2451; delta = +0.1474
- Combo-market Brier: V2 0.2632 vs production 0.3324 over 554 graded combo rows; delta = +0.0692
- Phase 6 gate: `COLLECTING`

The standard `PROMOTE` gate remains required for `staged_v2` and `v2`. The emergency path is limited to `staged_v2_emergency` and requires material calibration superiority plus rollback availability.

## Serving Modes

Default production behavior:

```bash
EDGERANKED_WNBA_SERVING_MODE=production
EDGERANKED_WNBA_V2_TRAFFIC_PERCENT=0
EDGERANKED_WNBA_V2_REQUIRE_PROMOTE_SIGNAL=1
EDGERANKED_WNBA_V2_ROLLBACK_FORCE_PRODUCTION=0
```

Standard staged promotion after Phase 6 reaches `PROMOTE`:

```bash
EDGERANKED_WNBA_SERVING_MODE=staged_v2
EDGERANKED_WNBA_V2_TRAFFIC_PERCENT=10
EDGERANKED_WNBA_V2_REQUIRE_PROMOTE_SIGNAL=1
EDGERANKED_WNBA_V2_ROLLBACK_FORCE_PRODUCTION=0
```

Emergency staged promotion while Phase 6 is still `COLLECTING`:

```bash
EDGERANKED_WNBA_SERVING_MODE=staged_v2_emergency
EDGERANKED_WNBA_V2_TRAFFIC_PERCENT=5
EDGERANKED_WNBA_V2_REQUIRE_PROMOTE_SIGNAL=1
EDGERANKED_WNBA_V2_ROLLBACK_FORCE_PRODUCTION=0
EDGERANKED_WNBA_V2_EMERGENCY_MAX_TRAFFIC_PERCENT=10
EDGERANKED_WNBA_V2_EMERGENCY_MIN_GRADED=500
EDGERANKED_WNBA_V2_EMERGENCY_MIN_BRIER_IMPROVEMENT=0.02
EDGERANKED_WNBA_V2_EMERGENCY_MIN_COMBO_BRIER_IMPROVEMENT=0.02
EDGERANKED_WNBA_V2_EMERGENCY_MIN_ECE_IMPROVEMENT=0.05
```

Full V2 promotion after standard Phase 6 promotion criteria are met:

```bash
EDGERANKED_WNBA_SERVING_MODE=v2
EDGERANKED_WNBA_V2_TRAFFIC_PERCENT=100
EDGERANKED_WNBA_V2_REQUIRE_PROMOTE_SIGNAL=1
EDGERANKED_WNBA_V2_ROLLBACK_FORCE_PRODUCTION=0
```

## Emergency Policy Checks

`staged_v2_emergency` is allowed only when all checks pass:

- `graded_recommendations >= EDGERANKED_WNBA_V2_EMERGENCY_MIN_GRADED`
- production Brier minus V2 Brier is at least `EDGERANKED_WNBA_V2_EMERGENCY_MIN_BRIER_IMPROVEMENT`
- production combo Brier minus V2 combo Brier is at least `EDGERANKED_WNBA_V2_EMERGENCY_MIN_COMBO_BRIER_IMPROVEMENT`
- production ECE minus V2 ECE is at least `EDGERANKED_WNBA_V2_EMERGENCY_MIN_ECE_IMPROVEMENT`
- Phase 6 is not `ROLLBACK_CANDIDATE`
- no major regression is detected: V2 Brier, combo Brier, and ECE are not worse than production
- rollback is available through `EDGERANKED_WNBA_V2_ROLLBACK_FORCE_PRODUCTION=1`

## Dashboard Checks

Run:

```bash
python -m wnba_v2.tracker.dashboard
cat wnba_v2/outputs/tracker/dashboard.json
cat wnba_v2/outputs/tracker/promotion_status.json
```

Required dashboard values for emergency staged serving:

```json
{
  "gate": {"decision": "COLLECTING"},
  "graded_recommendations": 863,
  "v2_overall": {"brier": 0.2594, "ece": 0.0977},
  "production_overall": {"brier": 0.317, "ece": 0.2451},
  "combos": {"v2_brier": 0.2632, "prod_brier": 0.3324, "n": 554}
}
```

Rollback immediately if dashboard decision becomes `ROLLBACK_CANDIDATE`, V2 Brier/ECE regresses above production, combo Brier regresses above production, or production pipeline health fails.

## Deployment Steps

1. Run Phase 6 tracking:

```bash
bash wnba_v2/pipeline/run_wnba_v2_data.sh all
bash wnba_v2/pipeline/run_wnba_v2_tracker.sh
```

2. Start emergency staged mode at 5%:

```bash
export EDGERANKED_WNBA_SERVING_MODE=staged_v2_emergency
export EDGERANKED_WNBA_V2_TRAFFIC_PERCENT=5
export EDGERANKED_WNBA_V2_REQUIRE_PROMOTE_SIGNAL=1
export EDGERANKED_WNBA_V2_ROLLBACK_FORCE_PRODUCTION=0
export EDGERANKED_WNBA_V2_EMERGENCY_MAX_TRAFFIC_PERCENT=10
export EDGERANKED_WNBA_V2_EMERGENCY_MIN_GRADED=500
export EDGERANKED_WNBA_V2_EMERGENCY_MIN_BRIER_IMPROVEMENT=0.02
export EDGERANKED_WNBA_V2_EMERGENCY_MIN_COMBO_BRIER_IMPROVEMENT=0.02
export EDGERANKED_WNBA_V2_EMERGENCY_MIN_ECE_IMPROVEMENT=0.05
python run_wnba_model.py
```

3. Keep Phase 6 tracking daily. Do not exceed 10% in emergency mode.

4. Move to `staged_v2` or `v2` only after the standard Phase 6 decision is `PROMOTE`.
