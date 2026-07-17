# WNBA Phase 10 Selective Feature Canary

Generated: 2026-07-17T04:30:09Z

New rows processed this run: 12

This is a shadow-only canary for upgraded points/rebounds feature models. It appends only newly graded rows after the canary checkpoint.

## Report Paths
- Daily: `/home/ubuntu/EdgeRanked/sports/wnba/data/processed/wnba_selective_feature_canary_daily_report.csv`
- Rolling: `/home/ubuntu/EdgeRanked/sports/wnba/data/processed/wnba_selective_feature_canary_rolling_report.csv`
- Market: `/home/ubuntu/EdgeRanked/sports/wnba/data/processed/wnba_selective_feature_canary_market_report.csv`
- Confidence buckets: `/home/ubuntu/EdgeRanked/sports/wnba/data/processed/wnba_selective_feature_canary_confidence_buckets.csv`
- Promotion JSON: `/home/ubuntu/EdgeRanked/sports/wnba/data/processed/wnba_selective_feature_canary_promotion_recommendation.json`

## Current Aggregate
- production: n=294, win rate 58.2%, MAE 4.128, RMSE 5.941, calibration error 0.066
- selective: n=294, win rate 62.4%, MAE 3.887, RMSE 5.499, calibration error 0.051

## Promotion Recommendation
- Decision: **recommend_production_enablement**
- Reason: Selective canary cleared win-rate, MAE, calibration, and sample-size promotion gates.

## Production Safety
- Default behavior remains OFF unless WNBA_ENABLE_SELECTIVE_FEATURE_SHADOW=1 or WNBA_ENABLE_SELECTIVE_FEATURE_CANARY=1 is set.
- Production model files, grading files, public board, and publish outputs are not written.
