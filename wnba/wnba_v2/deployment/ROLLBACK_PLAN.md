# WNBA V2 Conserved Simulator Rollback Plan

Rollback protection remains intact. Force production immediately if emergency policy blocks, production health fails, or live metrics regress.

## Rollback Command

```bash
export EDGERANKED_WNBA_SERVING_MODE=production
export EDGERANKED_WNBA_V2_TRAFFIC_PERCENT=0
export EDGERANKED_WNBA_V2_ROLLBACK_FORCE_PRODUCTION=1
python3 run_wnba_model.py
```

## Rollback Triggers

- `emergency_policy.allowed == false` while V2 serving is requested
- dashboard or promotion status decision is `ROLLBACK_CANDIDATE`
- dashboard `versions.simulation_version != "sim-5.4-conserved"`
- realism gates fail or learned calibration is missing/not accepted
- V2 Brier, combo Brier, or ECE regresses worse than production
- production pipeline health fails
- emergency traffic is above 10%

## Confirmation

```bash
cat data/processed/wnba_production_status.json
```

Expected:

```json
{
  "serving_mode": "production",
  "v2_traffic_percent": 0,
  "v2_rollback_force_production": true
}
```

Keep Phase 6 tracking running after rollback so the dashboard records the reason.
