# WNBA Model Audit Report

Generated: 2026-07-20T04:25:08Z

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
 blocks            1 0.000000 0.895640               -0.895640    -0.806900
     pa          336 0.498498 7.007870               -2.333907    -0.238082
assists           93 0.500000 2.161205               -0.284714    -0.259643
     pr          562 0.500901 7.381744               -2.870857    -0.242896
     ra          140 0.503704 3.414715               -0.631427    -0.192956

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
