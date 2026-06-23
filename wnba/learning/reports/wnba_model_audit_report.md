# WNBA Model Audit Report

Generated: 2026-06-23T04:25:05Z

## Feature Impact
The trained stat model report shows points and rebounds have the highest predictive signal by R2, while steals and blocks have weak R2 and are dominated by event variance. The active feature set is heavily driven by rolling player rates, rolling minutes, season averages, team/opponent last-10 context, position allowance, rest, and home/away.

## Outdated Assumptions
- Confidence still overstates certainty in several high-probability buckets.
- Player status is treated through current status snapshots, but historical injury flags are not persistently stored with every graded bet unless this audit ledger is enabled.
- Combo markets inherit base-stat simulation assumptions and need market-specific validation, not just aggregate grading.
- Current production Phase 7 realism gates default ON; future experimental changes should use separate OFF-by-default flags.

## Systematic Bias
Use `signed_projection_bias` in `data/processed/wnba_market_validation_report.csv`: positive means overestimation, negative means underestimation. The challenger uses only prior observed market bias to avoid lookahead.

## Worst Markets
 market  sample_size  win_pct      mae  signed_projection_bias  calibration
     pa          210 0.466346 7.652078               -2.625910    -0.321341
assists           72 0.476923 2.159916               -0.156184    -0.317064
 steals           15 0.533333 0.845517                0.140514    -0.232939
     pr          355 0.544160 7.114602               -2.367589    -0.258641
     ra           80 0.545455 3.503860               -0.559617    -0.197302

## Stale or Heuristic Components
- Player positions and player statuses remain CSV/manual-source dependent.
- Confidence scoring is a heuristic blend of agreement, volatility, and minutes stability.
- Best-bet caps and thresholds are fixed constants.
- Promotion is advisory; no automatic production activation is wired.

## Highest-Leverage Improvements
- Market-level calibration and gating by market/side/confidence bucket.
- Minutes-error-aware confidence caps.
- Persistent graded ledger with context for long-term drift detection.
- Shadow challenger backtests with explicit promotion criteria.
