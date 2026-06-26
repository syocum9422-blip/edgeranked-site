# WNBA Model Audit Report

Generated: 2026-06-26T04:25:05Z

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
     pa          222 0.459091 7.601099               -2.763580    -0.320376
assists           75 0.485294 2.155119               -0.125918    -0.303962
     ra           91 0.528736 3.498137               -0.459181    -0.202399
     pr          385 0.537037 7.108158               -2.227230    -0.253685
    pra          376 0.553476 8.058333               -2.908382    -0.261544

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
