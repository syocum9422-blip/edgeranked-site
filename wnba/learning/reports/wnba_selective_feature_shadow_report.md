# WNBA Phase 9 Selective Feature Upgrade Shadow

Generated: 2026-06-20T22:14:21Z

Shadow-only comparison of production baseline, full feature upgrade, and selective points+rebounds upgrade.

## Exact Markets Included
- points
- rebounds

## Overall Results
- production: n=475, win rate 56.6%, MAE 4.568, RMSE 6.272, calibration error 0.193
- full_feature: n=475, win rate 68.4%, MAE 3.546, RMSE 4.961, calibration error 0.013
- selective_feature: n=475, win rate 68.4%, MAE 3.546, RMSE 4.962, calibration error 0.012

## Points/Rebounds
- production / points: n=298, win rate 55.6%, MAE 6.105, RMSE 7.666, calibration error 0.213
- production / rebounds: n=106, win rate 67.7%, MAE 1.963, RMSE 2.507, calibration error 0.054
- full_feature / points: n=298, win rate 68.3%, MAE 4.587, RMSE 5.995, calibration error 0.003
- full_feature / rebounds: n=106, win rate 76.0%, MAE 1.825, RMSE 2.344, calibration error 0.102
- selective_feature / points: n=298, win rate 68.3%, MAE 4.587, RMSE 5.995, calibration error 0.003
- selective_feature / rebounds: n=106, win rate 76.0%, MAE 1.825, RMSE 2.344, calibration error 0.102

## Promotion Recommendation
- Decision: **recommend_future_shadow_canary**
- Selective beats full feature upgrade: True
- Reason: Selective points+rebounds cleared production and full-upgrade guardrails.

## Production Safety
- Default behavior remains OFF unless WNBA_ENABLE_SELECTIVE_FEATURE_SHADOW=1 is set.
- Reads Phase 8 shadow outputs and writes only Phase 9 shadow reports.
- Does not write production model files, public boards, grading ledgers, or publish outputs.
