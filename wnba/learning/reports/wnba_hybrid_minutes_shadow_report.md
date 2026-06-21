# WNBA Phase 11 Hybrid Minutes Shadow

Generated: 2026-06-20T22:39:50Z

Shadow-only test of role-pattern minutes as an alternative `minutes` feature inside the existing stat model structure.

## Minutes Comparison
- production_minutes_model: MAE 4.305, RMSE 5.569, R2 0.681, n=2043
- role_pattern_minutes_model: MAE 4.175, RMSE 5.434, R2 0.696, n=2043

## Recommended Historical Blends
- assists: keep production minutes; No shadow blend improved win rate without worsening MAE.
- pa: blend 0.25; win-rate delta +1.1%; MAE delta -0.005
- points: keep production minutes; No shadow blend improved win rate without worsening MAE.
- pr: blend 1.00; win-rate delta +0.4%; MAE delta -0.038
- pra: blend 0.50; win-rate delta +0.4%; MAE delta -0.022
- ra: keep production minutes; No shadow blend improved win rate without worsening MAE.
- rebounds: keep production minutes; No shadow blend improved win rate without worsening MAE.

## Production Safety
- Default OFF unless WNBA_ENABLE_HYBRID_MINUTES_SHADOW=1 is set.
- Does not write production models, grading files, publish outputs, or public boards.
