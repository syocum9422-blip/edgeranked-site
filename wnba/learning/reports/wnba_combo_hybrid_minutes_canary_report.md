# WNBA Phase 12 Combo Hybrid Minutes Canary

Generated: 2026-07-14T04:35:08Z

New rows processed this run: 27

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
- production: n=464, win rate 44.4%, MAE 7.761, RMSE 10.174, calibration error 0.209
- hybrid: n=464, win rate 46.0%, MAE 7.090, RMSE 9.239, calibration error 0.198

## Promotion Recommendation
- Decision: **do_not_promote**
- Reason: Combo hybrid minutes canary has not yet cleared all promotion gates on new graded picks.

## Production Safety
- Default OFF unless WNBA_ENABLE_COMBO_HYBRID_MINUTES_CANARY=1 is set.
- Production model files, grading files, public board, and publish outputs are not written.
