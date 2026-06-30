# WNBA V2 Migration Steps

## Files Added

- `wnba_v2/deployment/feature_flags.py`
- `wnba_v2/deployment/DEPLOYMENT_PLAN.md`
- `wnba_v2/deployment/ROLLBACK_PLAN.md`
- `wnba_v2/deployment/MIGRATION_STEPS.md`

## Files Updated

- `wnba_model/pipeline/service.py`

## Emergency Staged Migration

1. Deploy with defaults unchanged:

```bash
EDGERANKED_WNBA_SERVING_MODE=production
EDGERANKED_WNBA_V2_TRAFFIC_PERCENT=0
EDGERANKED_WNBA_V2_REQUIRE_PROMOTE_SIGNAL=1
EDGERANKED_WNBA_V2_ROLLBACK_FORCE_PRODUCTION=0
```

2. Refresh Phase 6 tracking:

```bash
bash wnba_v2/pipeline/run_wnba_v2_data.sh all
bash wnba_v2/pipeline/run_wnba_v2_tracker.sh
```

3. If Phase 6 is still `COLLECTING` but emergency checks pass, migrate to 5% emergency staged serving:

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

4. Check dashboard daily:

```bash
python -m wnba_v2.tracker.dashboard
cat wnba_v2/outputs/tracker/dashboard.json
cat wnba_v2/outputs/tracker/promotion_status.json
```

5. Roll back with:

```bash
EDGERANKED_WNBA_SERVING_MODE=production \
EDGERANKED_WNBA_V2_TRAFFIC_PERCENT=0 \
EDGERANKED_WNBA_V2_ROLLBACK_FORCE_PRODUCTION=1 \
python run_wnba_model.py
```

6. Move from emergency mode to normal staged/full V2 only when the standard Phase 6 gate reaches `PROMOTE`.
