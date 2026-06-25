# WNBA Phase 12 Combo Hybrid Minutes Canary

Generated: 2026-06-25T04:35:07Z

New rows processed this run: 22

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
- production: n=90, win rate 52.3%, MAE 6.148, RMSE 8.061, calibration error 0.109
- hybrid: n=90, win rate 54.5%, MAE 5.743, RMSE 7.520, calibration error 0.093

## Promotion Recommendation
- Decision: **do_not_promote**
- Reason: Combo hybrid minutes canary has not yet cleared all promotion gates on new graded picks.

## Production Safety
- Default OFF unless WNBA_ENABLE_COMBO_HYBRID_MINUTES_CANARY=1 is set.
- Production model files, grading files, public board, and publish outputs are not written.
