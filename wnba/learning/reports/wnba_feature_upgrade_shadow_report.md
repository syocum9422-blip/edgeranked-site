# WNBA Phase 8 Feature Upgrade Shadow

Generated: 2026-06-20T22:10:13Z

This is a shadow-only learned feature upgrade. It trains separate models under `data/models/shadow_feature_upgrade` and does not alter production model files, grading, publish, or public boards.

## Excluded Features Selected
- opp_points_last_10
- pos_assists_allowed_last_10
- pos_blocks_allowed_last_10
- pos_points_allowed_last_10
- pos_rebounds_allowed_last_10
- pos_steals_allowed_last_10
- pos_threes_made_allowed_last_10

## Historical Validation
- points: MAE 3.409 -> 3.404 (-0.004); RMSE +0.001; R2 -0.000
- assists: MAE 1.129 -> 1.128 (-0.001); RMSE -0.005; R2 +0.003
- rebounds: MAE 1.541 -> 1.541 (+0.000); RMSE +0.001; R2 -0.001
- blocks: MAE 0.489 -> 0.489 (+0.000); RMSE -0.001; R2 +0.001
- steals: MAE 0.705 -> 0.713 (+0.008); RMSE +0.003; R2 -0.006
- threes_made: MAE 0.718 -> 0.726 (+0.008); RMSE -0.003; R2 +0.004

## Win Rate vs Line
- assists: n=52, win rate 54.2% -> 54.2% (+0.0%); calibration error delta -0.009
- points: n=298, win rate 67.2% -> 68.3% (+1.0%); calibration error delta -0.005
- rebounds: n=106, win rate 75.0% -> 76.0% (+1.0%); calibration error delta +0.005
- steals: n=10, win rate 60.0% -> 60.0% (+0.0%); calibration error delta -0.012
- threes_made: n=9, win rate 77.8% -> 77.8% (+0.0%); calibration error delta -0.011

## Promotion Recommendation
- Decision: **do_not_promote**
- Reason: The upgraded feature set did not clear both stat-accuracy and line-performance promotion gates.
- Improved targets: none
- Line guardrail losses: none

## Production Safety
- Default behavior remains OFF unless WNBA_ENABLE_FEATURE_UPGRADE_SHADOW=1 is set.
- Shadow models are written only to `data/models/shadow_feature_upgrade`.
- Public board and production model paths are not written.
