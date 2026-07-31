# WNBA Phase 10 Selective Feature Canary

Generated: 2026-07-31T04:30:08Z

New rows processed this run: 7

This is a shadow-only canary for upgraded points/rebounds feature models. It appends only newly graded rows after the canary checkpoint.

## Report Paths
- Daily: `/home/ubuntu/EdgeRanked/sports/wnba/data/processed/wnba_selective_feature_canary_daily_report.csv`
- Rolling: `/home/ubuntu/EdgeRanked/sports/wnba/data/processed/wnba_selective_feature_canary_rolling_report.csv`
- Market: `/home/ubuntu/EdgeRanked/sports/wnba/data/processed/wnba_selective_feature_canary_market_report.csv`
- Confidence buckets: `/home/ubuntu/EdgeRanked/sports/wnba/data/processed/wnba_selective_feature_canary_confidence_buckets.csv`
- Promotion JSON: `/home/ubuntu/EdgeRanked/sports/wnba/data/processed/wnba_selective_feature_canary_promotion_recommendation.json`

## Current Aggregate
- production: n=387, win rate 55.5%, MAE 4.312, RMSE 6.075, calibration error 0.093
- selective: n=387, win rate 59.7%, MAE 4.029, RMSE 5.663, calibration error 0.082

## Promotion Recommendation
- Decision: **recommend_production_enablement**
- Reason: Selective canary cleared win-rate, MAE, calibration, and sample-size promotion gates.

## Production Safety
- Default behavior remains OFF unless WNBA_ENABLE_SELECTIVE_FEATURE_SHADOW=1 or WNBA_ENABLE_SELECTIVE_FEATURE_CANARY=1 is set.
- Production model files, grading files, public board, and publish outputs are not written.
