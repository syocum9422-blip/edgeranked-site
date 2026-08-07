# WNBA Model Audit Report

Generated: 2026-08-07T04:25:08Z

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
     ra          173 0.469880 3.671464               -0.827773    -0.214835
     pr          650 0.499220 7.476874               -2.922295    -0.230502
assists           99 0.500000 2.156516               -0.388036    -0.251887
     pa          415 0.506083 6.757484               -2.260684    -0.211130

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
