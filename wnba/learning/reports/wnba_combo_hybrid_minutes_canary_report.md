# WNBA Phase 12 Combo Hybrid Minutes Canary

Generated: 2026-07-15T04:35:10Z

New rows processed this run: 17

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
- production: n=481, win rate 45.8%, MAE 7.639, RMSE 10.042, calibration error 0.196
- hybrid: n=481, win rate 45.6%, MAE 7.054, RMSE 9.164, calibration error 0.202

## Promotion Recommendation
- Decision: **do_not_promote**
- Reason: Combo hybrid minutes canary has not yet cleared all promotion gates on new graded picks.

## Production Safety
- Default OFF unless WNBA_ENABLE_COMBO_HYBRID_MINUTES_CANARY=1 is set.
- Production model files, grading files, public board, and publish outputs are not written.
