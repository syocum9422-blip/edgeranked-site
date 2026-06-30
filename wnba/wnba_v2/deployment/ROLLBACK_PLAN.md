# WNBA V2 Rollback Plan

## Rollback Trigger

Rollback immediately if any of these are true:

- `wnba_v2/outputs/tracker/promotion_status.json` decision is `ROLLBACK_CANDIDATE`
- `wnba_v2/outputs/tracker/dashboard.json` has V2 Brier greater than production Brier
- combo-market V2 Brier is greater than production combo Brier
- V2 ECE is greater than production ECE
- production pipeline fails while any V2 serving mode is requested
- V2 high-conviction CLV turns materially negative during staged exposure

## Rollback Command

```bash
export EDGERANKED_WNBA_SERVING_MODE=production
export EDGERANKED_WNBA_V2_TRAFFIC_PERCENT=0
export EDGERANKED_WNBA_V2_ROLLBACK_FORCE_PRODUCTION=1
python run_wnba_model.py
```

## Confirm Rollback

```bash
cat data/processed/wnba_production_status.json
```

Expected fields:

```json
{
  "WNBA_PRODUCTION_STATUS": "PASS",
  "serving_mode": "production",
  "v2_traffic_percent": 0,
  "v2_rollback_force_production": true
}
```

If the pipeline fails before producing fresh outputs, the existing production runner restores the last-good snapshot from `outputs/wnba_last_good`.

Keep Phase 6 tracking running after rollback so the reason remains visible in `wnba_v2/outputs/tracker/DASHBOARD.md`.
