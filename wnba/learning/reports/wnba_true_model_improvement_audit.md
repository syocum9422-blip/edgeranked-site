# WNBA Phase 7 True Model Improvement Audit

Generated: 2026-06-20T22:04:21Z

This is a shadow-only audit. It does not write production projections, public boards, grading ledgers, or challenger publish outputs.

## Projection Pipeline Findings
- **minutes_projection_creation**: implemented. train_wnba_minutes_model.py trains target=minutes; simulate_wnba_today.build_projection_rows predicts projected_minutes and clips 8-40. Risk: Live projected_minutes is applied mainly in simulation after stat models have already predicted totals.
- **usage_rate_creation**: implemented_proxy. build_wnba_dataset.add_usage_features creates usage_proxy = points + 1.2*assists + 0.7*rebounds + 0.6*3PM per minute, then rolling 5/10. Risk: Usage is a manual proxy, not possession-level usage, and redistribution weights are heuristic.
- **points_rebounds_assists_creation**: implemented. train_wnba_models.py trains learned stat models; simulate_wnba_today.build_projection_rows predicts points/rebounds/assists/etc. Risk: Monte Carlo later blends model-implied per-minute rate with last-10 historical rate at fixed 65/35 weight.
- **combo_market_creation**: implemented. simulate_wnba_today.COMBO_STATS creates PRA/PR/PA/RA/SB by summing simulated base stat samples. Risk: Combo market calibration inherits correlated base-stat errors and line-side thresholds are not learned in projection generation.
- **injury_and_lineup_redistribution**: partial. build_absences_from_status and apply_absence_redistribution redistribute minutes/stat uplifts from status-driven absences. Risk: Starting lineup changes are inferred through status/recent minutes, not an explicit starter or role-change model.
- **recent_form_weighting**: heuristic_plus_learned. Feature set includes rolling 3/5/10, EWMs, season averages, and minutes_trend_3_over_10; simulation uses fixed 65/35 model-rate/history-rate blend. Risk: Recent form weight is not market-specific or learned from graded outcomes.
- **opponent_defensive_allowance_by_position**: created_but_not_used. Training dataset includes pos_*_allowed_last_10, but feature_columns excludes those columns. Risk: Opponent position allowance exists in data but does not currently feed the learned models.
- **pace_and_possession_environment**: implemented. pace_last_10 is in feature_columns and simulation applies game_state pace when WNBA_P7_GAME_STATE is enabled. Risk: Pace context is team-level rolling and simulated multiplicatively; no learned market-specific possession elasticity.
- **player_role_change_detection**: partial. minutes_trend_3_over_10, rolling minutes, status-based absence redistribution, and player variance features capture some role change. Risk: No explicit role-state classifier for starter, bench, returning-from-injury, or rotation promotion.
- **learned_vs_manual_weights**: mixed. Ridge/tree ensembles learn stat and minute projections; confidence labels, redistributions, caps, and simulation blends are manual. Risk: Manual post-model rules can improve realism while still failing to optimize market-level win rate.

## Minutes Error Snapshot
- Sample 1346; mean actual-projected -0.238; MAE 5.130; RMSE 6.596.

## Base Stat Error Snapshot
- points: n=1346, mean actual-projected=-0.741, MAE=4.938, RMSE=6.451
- rebounds: n=1346, mean actual-projected=0.019, MAE=1.979, RMSE=2.549
- assists: n=1346, mean actual-projected=0.045, MAE=1.424, RMSE=1.880
- threes_made: n=1346, mean actual-projected=0.058, MAE=0.888, RMSE=1.209
- steals: n=1346, mean actual-projected=0.092, MAE=0.805, RMSE=1.025
- blocks: n=1346, mean actual-projected=0.074, MAE=0.585, RMSE=0.785

## Model Validation Snapshot
- points: valid_rows=1960, MAE=3.409, RMSE=4.654, R2=0.604
- rebounds: valid_rows=1960, MAE=1.541, RMSE=2.021, R2=0.567
- assists: valid_rows=1960, MAE=1.129, RMSE=1.565, R2=0.511
- threes_made: valid_rows=1960, MAE=0.718, RMSE=1.033, R2=0.291
- steals: valid_rows=1960, MAE=0.705, RMSE=0.922, R2=0.152
- blocks: valid_rows=1960, MAE=0.489, RMSE=0.689, R2=0.212

## Challenger Overall Results
- combo_market_challenger: MAE 6.339 -> 6.171 (-0.168); RMSE -0.201; win rate 54.3% -> 53.4% (-0.9%); calibration error delta +0.009.
- market_specific_stat_challenger: MAE 6.339 -> 6.187 (-0.152); RMSE -0.196; win rate 54.3% -> 53.0% (-1.3%); calibration error delta +0.013.
- minutes_challenger: MAE 6.339 -> 6.254 (-0.085); RMSE -0.175; win rate 54.3% -> 52.9% (-1.4%); calibration error delta +0.014.
- usage_redistribution_challenger: MAE 6.339 -> 6.320 (-0.019); RMSE -0.048; win rate 54.3% -> 53.7% (-0.6%); calibration error delta +0.006.

## Best/Worst Market-Level Challenger Moves
Best MAE deltas:
- combo_market_challenger / pra: MAE delta -0.420, win-rate delta -1.9%, n=325
- market_specific_stat_challenger / pra: MAE delta -0.367, win-rate delta -1.2%, n=325
- combo_market_challenger / pr: MAE delta -0.258, win-rate delta -1.5%, n=335
- market_specific_stat_challenger / pr: MAE delta -0.244, win-rate delta -1.8%, n=335
- minutes_challenger / pr: MAE delta -0.226, win-rate delta -1.5%, n=335
- combo_market_challenger / pa: MAE delta -0.187, win-rate delta +1.5%, n=205
- minutes_challenger / pra: MAE delta -0.171, win-rate delta -1.2%, n=325
- market_specific_stat_challenger / pa: MAE delta -0.163, win-rate delta -0.5%, n=205
Worst MAE deltas:
- combo_market_challenger / ra: MAE delta +0.112, win-rate delta -6.8%, n=75
- usage_redistribution_challenger / ra: MAE delta +0.099, win-rate delta -1.4%, n=75
- market_specific_stat_challenger / ra: MAE delta +0.057, win-rate delta -2.7%, n=75
- minutes_challenger / threes_made: MAE delta +0.041, win-rate delta +0.0%, n=10
- minutes_challenger / steals: MAE delta +0.017, win-rate delta +0.0%, n=14
- minutes_challenger / pa: MAE delta +0.016, win-rate delta -0.5%, n=205
- market_specific_stat_challenger / rebounds: MAE delta +0.013, win-rate delta -1.7%, n=127
- minutes_challenger / points: MAE delta +0.012, win-rate delta -3.3%, n=345

## Promotion Recommendation
- Decision: **do_not_promote**
- Recommended challenger: none
- Reason: No challenger cleared all promotion gates without unacceptable market-side risk.

## Production Safety
- Default behavior remains OFF unless WNBA_ENABLE_TRUE_MODEL_IMPROVEMENT_AUDIT=1 is set.
- The audit reads historical artifacts and writes only Phase 7 audit outputs.
- It does not import or call publish, grading, or simulation entry points.
