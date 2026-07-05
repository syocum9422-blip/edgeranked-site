# WNBA V2 Conserved Simulator Migration Steps

## Files Updated

- `wnba_v2/deployment/feature_flags.py`
- `wnba_v2/deployment/DEPLOYMENT_PLAN.md`
- `wnba_v2/deployment/ROLLBACK_PLAN.md`
- `wnba_v2/deployment/MIGRATION_STEPS.md`
- `wnba_v2/tracker/dashboard.py`

## Migration

1. Refresh tracker/dashboard evidence:

```bash
python3 -m wnba_v2.tracker.dashboard
python3 -m wnba_v2.tracker.daily_run
```

2. Confirm emergency policy:

```bash
cat wnba_v2/outputs/tracker/dashboard.json
cat wnba_v2/outputs/tracker/promotion_status.json
```

Required:

- `simulation_version = sim-5.4-conserved`
- `emergency_policy.allowed = true`
- `realism_gates_passing = true`
- `learned_calibration_available = true`
- `old_independent_simulator_disabled = true`

3. Enable emergency staged serving at 5%:

```bash
export EDGERANKED_WNBA_SERVING_MODE=staged_v2_emergency
export EDGERANKED_WNBA_V2_TRAFFIC_PERCENT=5
export EDGERANKED_WNBA_V2_EMERGENCY_MAX_TRAFFIC_PERCENT=10
python3 run_wnba_model.py
```

4. Do not exceed 10% emergency traffic until additional live evidence accumulates.

5. Roll back with:

```bash
export EDGERANKED_WNBA_SERVING_MODE=production
export EDGERANKED_WNBA_V2_TRAFFIC_PERCENT=0
export EDGERANKED_WNBA_V2_ROLLBACK_FORCE_PRODUCTION=1
python3 run_wnba_model.py
```
