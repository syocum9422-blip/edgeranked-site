# WNBA Phase 10 Selective Feature Canary

Generated: 2026-06-27T04:30:07Z

New rows processed this run: 8

This is a shadow-only canary for upgraded points/rebounds feature models. It appends only newly graded rows after the canary checkpoint.

## Report Paths
- Daily: `/home/ubuntu/EdgeRanked/sports/wnba/data/processed/wnba_selective_feature_canary_daily_report.csv`
- Rolling: `/home/ubuntu/EdgeRanked/sports/wnba/data/processed/wnba_selective_feature_canary_rolling_report.csv`
- Market: `/home/ubuntu/EdgeRanked/sports/wnba/data/processed/wnba_selective_feature_canary_market_report.csv`
- Confidence buckets: `/home/ubuntu/EdgeRanked/sports/wnba/data/processed/wnba_selective_feature_canary_confidence_buckets.csv`
- Promotion JSON: `/home/ubuntu/EdgeRanked/sports/wnba/data/processed/wnba_selective_feature_canary_promotion_recommendation.json`

## Current Aggregate
- production: n=78, win rate 68.0%, MAE 4.114, RMSE 6.343, calibration error 0.040
- selective: n=78, win rate 70.7%, MAE 3.876, RMSE 6.029, calibration error 0.034

## Promotion Recommendation
- Decision: **do_not_promote**
- Reason: Selective canary has not yet cleared all promotion gates on new graded picks.

## Production Safety
- Default behavior remains OFF unless WNBA_ENABLE_SELECTIVE_FEATURE_SHADOW=1 or WNBA_ENABLE_SELECTIVE_FEATURE_CANARY=1 is set.
- Production model files, grading files, public board, and publish outputs are not written.
