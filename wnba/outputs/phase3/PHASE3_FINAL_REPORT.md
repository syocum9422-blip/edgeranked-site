# WNBA Phase 3 — Minutes & Team Context Accuracy Upgrade — Final Report

**Date:** 2026-06-07
**Mode:** Shadow-only. No production model, dataset, or source file was modified. Live
production model preserved as baseline. No publish performed.
**Backup:** `backups/wnba_phase3_20260607_001016/` (production dataset, all models,
`wnba_model_utils.py`, `build_wnba_dataset.py`, graded bets, minutes errors).

## Promotion decision: **DO NOT PROMOTE** (4 of 5 gates pass)

| Gate | Result | Status |
|---|---|---|
| Minutes MAE improves (7/14/30d) | 4.38→4.14, 4.46→4.16, 5.03→4.96 | ✅ PASS |
| Minutes RMSE improves (7/14/30d) | 5.60→5.35, 5.87→5.43, 6.62→6.50 | ✅ PASS |
| Brier improves or neutral | 0.3562 → 0.3294 | ✅ PASS |
| Log-loss improves or neutral | 1.2690 → 1.0264 | ✅ PASS |
| Coverage reduction < 5% | −10.6% (941→841 @0.56) | ❌ FAIL |

The minutes-accuracy and probability-calibration objectives are met decisively. The strict
coverage gate fails, so under the stated rules the upgrade is **held, not promoted**. The
coverage drop is a first-order propagation estimate and is a *consequence* of correcting
production's minutes over-projection (see §6) — it should be resolved by full re-simulation
+ selection-threshold re-tuning before promotion, not by abandoning the minutes upgrade.

---

## Phase 3A — Minutes Audit (see `reports/phase3a_root_cause_summary.md`)

- The production minutes model is **almost entirely `season_avg_minutes`** (permutation
  importance 1.40; next feature 6× weaker).
- **Root cause #1:** `minutes_rolling_mean_3/5/10` and `_std` are computed in the dataset
  (cols 46–51) but **excluded from the model feature list**. Counterfactual: a bare last-5
  average beats production minutes MAE 5.61→4.63 (−17.5%); on low-projected players −39%.
- **Root cause #2:** over-projection tail from in-game injury/DNP; `wnba_player_status.csv`
  is empty so there is no pre-game availability signal — not fixable from minutes features.
- Error breakdown: bench MAE 7.47 vs starter 4.76; proj<10min bucket MAE 14.5 (bias −14);
  worst teams POR 7.67 / NYL 7.00 (not the originally-named WAS/CHI/GSV).
- Secondary findings: `position` is "UNK" for ~87% of rows (dead feature); processed
  training set was stale (ended 2025-09-12, zero 2026 rows).

## Phase 3B — Rotation Stability Engine (`reports/rotation_*.csv`)

Built a leakage-free per-player-game rotation layer (last-3/5/10 min avg, last-5/10 std,
starts-in-10, consecutive starts/bench, minutes & usage trend, availability) with a top-5
minutes starter proxy, and a 6-way classifier. Current snapshot (197 active players):
Stable Starter 39, Stable Rotation 50, Volatile Rotation 22, Minutes Risk 21,
Injury Return 5, Bench Flyer 60. Spot-checks are sensible (Rhyne Howard = Stable Starter
std 1.3; Rickea Jackson = Volatile std 8.4; Kelsey Plum = Injury Return on 10d+ gap).

**Modeling result:** adding rotation features *as direct regressor inputs* (variant D)
slightly **worsened** minutes MAE vs the rolling-minutes-only model (variant C). Rotation
features are therefore retained for **classification and floor/ceiling**, not fed to the
point model.

## Phase 3C — Team Context (`reports/team_context_*.csv`, `was_chi_gsv_analysis.csv`)

- **Coverage too low to be a lever:** pace/off/def-rating only 38% populated (NaN for most
  teams, including all three targets); team rebound/assist/3PM 62%.
- **Rolling vs season context barely moves minutes:** 30d MAE 4.965 (current last-10) →
  4.958 (rolling-5) → 4.947 (season) — all < 0.4%. **Recommendation: do not invest in
  rolling team-context features until coverage is fixed.**
- **Reframe of the weak-team premise:** WAS is a genuine *projection* outlier (proj MAE
  2.27, 2nd worst league-wide) but fine on minutes (bias +0.77). CHI is marginal (2.06).
  **GSV is below league-average proj MAE (1.92) — not currently a problem.** WAS's weakness
  is on the stat side and warrants a separate stat-model investigation, not minutes/context.

## Phase 3D — Floor/Ceiling & Volatility (`reports/floor_ceiling_validation.csv`, `volatility_report.csv`, `minutes_range_report.csv`)

Shadow-only minutes ranges from shadow expected minutes ± volatility (rotation last-5 std).
80% nominal intervals are globally **under-covered** (fixed 66.9%, vol-aware 63.7%) because
minutes have heavy DNP tails the last-5 std understates. But the **volatility-aware method
has the right structure**: volatile players coverage 0.60→0.87 with wider bands; stable
players tighten to width 6.3 (over-tight, coverage 0.42). Verdict: range-aware confidence
is promising for differentiating bet confidence but needs a wider global multiplier and a
volatility floor (for DNP risk on "stable" players) before any use. Kept shadow-only.

## Phase 3E — Shadow Validation (`reports/minutes_backtest_results.csv`, `secondary_gates_results.csv`, `before_after_metrics.csv`, `phase3_promotion_decision.json`)

Leakage-free retrain+timesplit across 7/14/30-day windows comparing four variants:
A = live production, B = retrain-only (prod features), C = +rolling-minutes,
D = +rolling-minutes +rotation.

- **C is best in every window** on both MAE and RMSE and beats live production everywhere.
- Decomposition: most of the gain is the **2026 data refresh** (A→B); the rolling-minutes
  features add a further consistent ~0.5–1.2% (B→C). Rotation inputs (D) hurt slightly.
- Secondary gates (first-order propagation of shadow minutes into the 941 graded bets;
  baseline reproduction matches the known production metrics exactly): Brier and log-loss
  both improve; coverage@0.56 falls 10.6%, and a threshold sweep shows it cannot be fully
  restored above 0.50 while holding qualified win-rate (~0.564 vs 0.569).

---

## 6. Why coverage falls (and why it does not invalidate the minutes win)

Production **over-projects** minutes (validation bias +0.8 to +1.7). That inflated the
modeled mean on "over" bets, pushing many just above the 0.56 selection threshold. The
shadow model removes that bias, so ~100 borderline plays drop below 0.56. This is *better
calibration* (hence Brier/log-loss improve), realized as fewer "confident" plays at a fixed
threshold. The fix is to re-tune the selection threshold against a **full re-simulation**
(not first-order propagation), which is the proper way to confirm true coverage — explicitly
out of scope for shadow and required before promotion.

## 7. Final recommendation

1. **Adopt the variant-C minutes model** (rebuild dataset with 2026 + add the six
   `minutes_rolling_mean/std_3/5/10` features to `feature_columns()`; keep rotation features
   out of the regressor). One-line change in `wnba_model_utils.feature_columns()`. It is a
   clear, robust win on the stated primary objective (playing-time accuracy) and on
   calibration.
2. **Resolve the coverage gate before promotion:** run a full historical re-simulation with
   the C model and re-tune the 0.56 play-selection threshold; confirm coverage reduction
   < 5% on real (not propagated) bets. Then promote via canary.
3. **Ship the rotation classification + floor/ceiling as shadow companions** (player role
   labels, volatility-aware ranges) — useful now for confidence differentiation; calibrate
   the interval multiplier before any betting use.
4. **Do not pursue rolling team-context features** until pace/off/def coverage is fixed.
5. **Investigate WAS stat projections** separately; drop or backfill `position`; stand up an
   `wnba_player_status` availability feed to attack the over-projection tail.

## Files

**Created (all under `sports/wnba/outputs/phase3/`, none in production):**
- `phase3a_minutes_audit.py`, `phase3b_rotation_engine.py`, `phase3c_team_context.py`,
  `phase3d_floor_ceiling.py`, `phase3e_minutes_backtest.py`, `phase3e_secondary_gates.py`
- `shadow/wnba_training_dataset_2026.csv` (rebuilt dataset, shadow path)
- `reports/` — 18 deliverable CSVs + 2 markdown summaries (this file + 3A summary)

**Modified:** none (production untouched).
**Backed up:** `backups/wnba_phase3_20260607_001016/`.
