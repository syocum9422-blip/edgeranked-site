# WNBA Phase 12 Combo Hybrid Minutes Canary

Generated: 2026-06-23T04:35:07Z

New rows processed this run: 19

Shadow-only canary using Phase 11 combo-market blend recommendations only.

## Blend Map
- PA: 25% shadow minutes
- PR: 100% shadow minutes
- PRA: 50% shadow minutes

## Report Paths
- Daily: `/home/ubuntu/EdgeRanked/sports/wnba/data/processed/wnba_combo_hybrid_minutes_canary_daily_report.csv`
- Rolling: `/home/ubuntu/EdgeRanked/sports/wnba/data/processed/wnba_combo_hybrid_minutes_canary_rolling_report.csv`
- Market: `/home/ubuntu/EdgeRanked/sports/wnba/data/processed/wnba_combo_hybrid_minutes_canary_market_report.csv`
- Confidence buckets: `/home/ubuntu/EdgeRanked/sports/wnba/data/processed/wnba_combo_hybrid_minutes_canary_confidence_buckets.csv`
- Promotion JSON: `/home/ubuntu/EdgeRanked/sports/wnba/data/processed/wnba_combo_hybrid_minutes_canary_promotion_recommendation.json`

## Current Aggregate
- production: n=44, win rate 56.8%, MAE 5.151, RMSE 7.118, calibration error 0.057
- hybrid: n=44, win rate 63.6%, MAE 4.923, RMSE 6.569, calibration error 0.012

## Promotion Recommendation
- Decision: **recommend_production_enablement**
- Reason: Combo hybrid minutes canary cleared win-rate, MAE, calibration, and sample-size gates.

## Production Safety
- Default OFF unless WNBA_ENABLE_COMBO_HYBRID_MINUTES_CANARY=1 is set.
- Production model files, grading files, public board, and publish outputs are not written.
