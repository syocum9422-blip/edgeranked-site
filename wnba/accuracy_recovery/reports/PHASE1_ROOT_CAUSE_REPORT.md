# WNBA Accuracy Recovery — Phase 1 Root Cause Report
*Generated 2026-07-10 · data through 2026-07-09 · all analysis read-only (accuracy_recovery/phase1_diagnostics.py)*

## Headline

| Window | Hit rate | n | Brier | Overconfidence (pred − actual) |
|---|---|---|---|---|
| Early (May 1 – Jun 7) | **57.5%** | 1,021 | 0.347 | +0.300 |
| Late (Jun 8 – Jul 9) | **48.9%** | 1,099 | 0.279 | +0.155 |

Decline is real and highly significant (two-proportion z-test p = 0.00008). The inflection is a
**step change on Jun 6–7**, not a gradual drift.

## Root causes (ranked by contribution)

### RC1 — Combo-prop overexposure meets a sharpened market (primary, ~7pp)
- Combos (PRA/PR/PA/RA) are **64% of the book**. Early: 56.7% hit. Late: **45.2%** (n=701).
- Combo **unders** are half the late book (n=556) and fell 59.9% → **44.6%**.
- Singles held up: 58.9% early → **55.5%** late (n=398). Points 56.1%, rebounds 59.0% late.
- Mechanism: PrizePicks lines converged to true player distributions mid-June (model board MAE
  simultaneously *improved* — PTS MAE 5.55→4.25 — so measured "edge" collapsed 0.375→0.145).
  Remaining large model-vs-line gaps are now mostly model error (winner's curse).

### RC2 — Dishonest simulator variance → overconfident tail probabilities (mechanism behind RC1)
- Realized z-scores ((actual − proj)/sim_std) have std **1.7–2.2 across every market** (honest = 1.0).
  The sim claims distributions ~half as wide as reality; every tail probability is inflated.
- Combos are doubly wrong: real residual correlations are corr(PTS,REB)=0.30, corr(PTS,AST)=0.18,
  corr(REB,AST)=0.19, but sim-implied corr(PTS,REB) is only 0.05–0.11 (near-independence).
- Consequence: late-window calibration is **inverted** — claimed 55–60% hits 55.3%, claimed 70–75%
  hits 44.4%, claimed 75%+ hits **30.0%**. The model's strongest disagreements with the market are
  its worst picks.

### RC3 — Jun 6 calibration-layer activation changed pick selection (trigger, not cause)
- `calibrate_wnba_model.py` wrote empty artifacts ("No graded bets available yet") until
  **2026-06-06 23:28**, when the first real calibration factors landed. Mean claimed hit_rate
  stepped 0.88 → 0.63 that day; Phase 7 sim realism (Jun 12) further widened distributions
  (pick STDDEV 3.6 → 5.5+). These were *directionally correct* fixes — but they reshuffled which
  props qualify (hit_rate ≥ 0.56 / edge ≥ 0.04), while the underlying tail overconfidence (RC2)
  remained, so the gate admits many fake 60–70% edges.

### RC4 — Minutes projection bias, worsening (~1–2pp, cuts across all markets)
- Minutes bias (projected − played) drifted −1.08 → **−1.71**; league minutes rose 27.2 → 28.6
  (rotations tightened) and the model lags.
- Outcome coupling is strong: picks where minutes were under-projected by 8+ hit **36.3%** (n=267);
  over-projected by 4–8 hit 66%. |minutes error| vs win: r = −0.122, p < 1e-6.
- Known gap (Phase 3A): recent-minutes rolling features exist in the dataset but the minutes model
  ignores them.

### RC5 — Expansion-team / role-change blind spot (~0.5–1pp)
- New starters (bench→starter mid-season): 41.6% hit (n=77) — Malonga, Gustafson, Fam, Barker, Taylor.
- Team-level signed error: POR −5.3, PHX −4.9, MIN −4.4, TOR −3.9 (under-projected);
  WAS +4.8 (over-projected). TOR picks hit 43.5%.
- Top under-projected players are expansion/breakout: Leite −8.9, Stewart −7.6, Copper −7.4,
  McBride −6.2 (21% hit). Top over-projected: Amoore +12.2 (23% hit), Clark +3.4 (40% hit) —
  injury/absence handling.

## Answers to the mandated questions
- **Has prediction error increased?** No — board MAE/RMSE *improved* in the late window for all 7
  stats (e.g. PTS 5.55→4.25 MAE, MIN 5.49→4.88). The decline is in *bet selection quality*, i.e.
  edge vs a sharper market, not raw projection skill. Daily metric series: `daily_metrics.csv`,
  `board_error_by_day.csv`.
- **When did degradation begin?** Step change Jun 6–7 (selection change); market-sharpening decay
  visible through June (combo unders progressively worse).
- **Feature drift (KS, p<0.01):** claimed hit_rate 0.875→0.645, edge 0.375→0.145, quality score
  56→25, pick STDDEV 3.69→5.44, minutes played 27.2→28.6, projected minutes 26.1→27.0, minutes
  error −1.08→−1.71, projection mean 13.8→14.4. No pace/off-rating/def-rating drift detected.
  Full table: `feature_drift.csv`. (Usage, travel, implied totals: not captured in graded history —
  flagged as instrumentation gaps.)
- **Sportsbook:** 100% PrizePicks; favorite/underdog not applicable (no team ML odds captured).
- **Calibration:** see table above and `calibration.csv` — monotonically *inverted* in the late
  window above the 60% bucket.
- **Residuals:** minutes error dominant; blowouts affect minutes error (+2.2 swing) but not hit
  rate; back-to-back: no rest_days populated in ledger (instrumentation gap); rookies ≈ neutral
  except expansion breakouts; new starters strongly negative. `residuals.json`.
- **Players/teams:** `top25_overestimated.csv`, `top25_underestimated.csv`, `team_bias.csv`.

## Segment deterioration (largest, early→late, n≥30 both windows)
| Segment | Early | Late | Δ |
|---|---|---|---|
| stat=pr | 57.6% | 42.0% | −15.6pp |
| stat=pra | 58.2% | 48.8% | −9.4pp |
| stat=pa | 53.7% | 43.8% | −9.9pp |
| side=under | 60.1% | 48.3% | −11.8pp |
| stat=rebounds | 70.8% | 59.0% | −11.8pp (still best market) |
| stat=points | 56.8% | 56.1% | −0.7pp (stable) |
