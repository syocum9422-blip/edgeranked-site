# WNBA Projection Engine Shadow

Generated: 2026-06-20T22:34:10Z

Shadow-only projection-engine work. No board ranking, confidence capping, qualification, publish, or grading logic is changed.

## Minutes
- production_like_baseline: MAE 4.305, RMSE 5.569, R2 0.681, n=2043
- role_pattern_shadow: MAE 4.175, RMSE 5.434, R2 0.696, n=2043

## Usage
- learned_usage_shadow: MAE 0.269, RMSE 0.346, R2 0.174, n=2043

## Stat Validation
- assists: MAE 1.112 -> 1.234; RMSE 1.537 -> 1.664
- blocks: MAE 0.485 -> 0.523; RMSE 0.691 -> 0.715
- points: MAE 3.379 -> 4.331; RMSE 4.592 -> 5.739
- rebounds: MAE 1.528 -> 1.777; RMSE 2.024 -> 2.290
- steals: MAE 0.689 -> 0.746; RMSE 0.910 -> 0.952
- threes_made: MAE 0.697 -> 0.753; RMSE 1.030 -> 1.092

## Market Replay vs Production Ledger
- assists: n=44, MAE delta -0.425, win-rate delta +7.3%, calibration delta -0.243
- pa: n=178, MAE delta -0.586, win-rate delta +0.0%, calibration delta -0.127
- points: n=269, MAE delta -0.303, win-rate delta -3.8%, calibration delta -0.077
- pr: n=263, MAE delta -0.822, win-rate delta -2.3%, calibration delta -0.130
- pra: n=255, MAE delta -0.939, win-rate delta -6.3%, calibration delta -0.120
- ra: n=61, MAE delta -0.466, win-rate delta +10.2%, calibration delta -0.208
- rebounds: n=98, MAE delta +0.048, win-rate delta -2.3%, calibration delta -0.030
- steals: n=8, MAE delta -0.040, win-rate delta +0.0%, calibration delta -0.023
- threes_made: n=8, MAE delta -0.076, win-rate delta -12.5%, calibration delta +0.025

## Promotion
- Decision: **do_not_promote_to_production**
- Reason: Per-market promotion requires both historical replay and fresh canary evidence. This shadow run only supplies historical replay.

## Production Safety
- Default OFF unless WNBA_ENABLE_PROJECTION_ENGINE_SHADOW=1 is set.
- Writes only shadow reports and shadow model artifacts.
