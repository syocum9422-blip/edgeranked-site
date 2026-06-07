# WNBA Phase 4 — Full Re-Simulation, Coverage Resolution & Promotion Decision

**Date:** 2026-06-07
**Mode:** Shadow-only. Production untouched. No auto-promotion.
**Backup:** `backups/wnba_phase3_20260607_001016/` (Phase 3 backup still valid; Phase 4 added
no production changes). All Phase 3 artifacts preserved under `outputs/phase3/`.

---

## Explicit promotion recommendation: **DO NOT PROMOTE (yet) — but for a new reason**

The original blocker is **disproven**, and a deeper one takes its place:

- ❌ **The Phase 3 coverage failure (−10.6%) was a first-order-propagation artifact.** A full,
  faithful re-simulation shows coverage is **neutral (−0.16% at 30d)**. The coverage gate
  **passes.**
- ✅ **Minutes MAE and RMSE improve** in every window (the stated primary objective).
- ⚠️ **Brier and log-loss are NEUTRAL, not improved** (30d 0.2293→0.2309; 14d/30d bootstrap CIs
  include zero; 7d marginally worse). Under the architecture, the minutes model **cannot** move
  betting calibration, so the literal "Brier/log-loss must improve" gates are not met.

**Gates (A → Variant C): 3 of 5 pass.** Minutes MAE ✅, Minutes RMSE ✅, Coverage ✅,
Brier ❌ (neutral), Log-loss ❌ (neutral).

**Why "do not promote yet" rather than "promote":** Variant C is *safe* (coverage- and
betting-neutral) and better on minutes — but in the **current architecture it delivers no
betting benefit**, so promoting it in isolation buys product/projection accuracy with no KPI
movement and a negligible short-window risk. The high-value sequence is: **(1) fix the
availability feed, (2) make stat projections minutes-driven (Phase 5), then (3) promote
Variant C**, at which point its minutes gains will actually flow into Brier/log-loss/ROI.

If projections are treated as a **user-facing product** (e.g. `Projections_app_view.csv`),
promoting Variant C now is reasonable and low-risk — it is strictly more accurate on playing
time with no betting regression. That is a product call for the owner; the betting case alone
does not yet justify it.

---

## Phase 4A — Full re-simulation (no first-order approximation)

Re-ran the **real** pipeline — `build_projection_rows` → `simulate_player_row` (10k-draw
Monte Carlo) → `apply_calibrated_hit_rate` → `apply_confidence_guardrails` — on all 941 graded
bets, for A = production minutes model and C = Variant C (retrained leakage-free per window).
Same stat models for both; **common random numbers** (same seed per player-game) so only
minutes differ.

| window | A brier | C brier | A logloss | C logloss | A cov@56 | C cov@56 | coverage Δ |
|---|---|---|---|---|---|---|---|
| 7d | 0.2413 | 0.2451 | 0.6763 | 0.6845 | 107 | 109 | **+1.9%** |
| 14d | 0.2327 | 0.2327 | 0.6571 | 0.6576 | 246 | 243 | **−1.2%** |
| 30d | 0.2293 | 0.2309 | 0.6497 | 0.6532 | 635 | 634 | **−0.16%** |

**Why coverage barely moves:** stat projections come from independent, minutes-*independent*
stat models; minutes enters the stat mean only via a damped 35% rate-blend
(`0.65·proj + 0.35·minutes·hist_rate`) then a further 0.55/0.45 mix. The Phase 3 propagation
wrongly scaled means *linearly* with minutes, hugely overstating the effect. 68–76% of bet
probabilities do shift under C, but they net out near-neutral on calibration.

**Paired bootstrap (C−A):** 14d & 30d brier/log-loss deltas have 95% CIs that **include zero**
(neutral); 7d is a small but significant degradation (+0.0038 brier) — smallest, noisiest
window.

## Phase 4B — Threshold optimization (30d, full re-sim)

| threshold | A cov | C cov | C cov vs base | C winrate | C ROI proxy (−110) |
|---|---|---|---|---|---|
| 0.50 | 732 | 740 | +16.5% | 0.614 | 0.171 |
| 0.54 | 667 | 675 | +6.3% | 0.632 | 0.206 |
| **0.56** | 635 | **634** | **−0.16%** | 0.644 | 0.229 |
| 0.58 | 601 | 603 | −5.0% | 0.656 | 0.252 |
| 0.60 | 558 | 563 | −11.3% | 0.673 | 0.284 |

**No threshold change is needed:** at the existing 0.56, Variant C already preserves coverage
(634 vs 635). Raising the threshold lifts win-rate/ROI for **both** A and C identically (a
separate selection decision that *reduces* coverage). Recommended threshold to hold coverage
within 5% of baseline = **0.56 (unchanged)**.

## Phase 4C — Availability audit (`reports/phase4c_availability_audit.md`)

The empty status feed is **bot-blocked by its User-Agent**, not dead: ESPN serves the scraper's
detailed Mac-Chrome UA a 1,987-byte stub but a plain `Mozilla/5.0` the full 298 KB page
(7 teams, 9 current injuries). **One-line UA fix** restores it (parser unchanged). Expected
impact: minutes MAE ceiling −4% on the over-projection tail (7 rows, 3.9% of error mass), with
the larger value in **bet-quality** (dropping OUT players pre-slate, capping Questionable/GTD
confidence). Proposal only — not integrated.

## Phase 4D — Three-way comparison (`reports/phase4_three_way_comparison.csv`)

| config | Min MAE | Min RMSE | Brier | Log-loss | Coverage | Plays | Qual win-rate |
|---|---|---|---|---|---|---|---|
| A) Production | 5.026 | 6.621 | 0.2293 | 0.6497 | 635 | 635 | 0.6458 |
| B) Variant C @0.56 | **4.957** | **6.500** | 0.2309 | 0.6532 | 634 | 634 | 0.6437 |
| C) Variant C + opt thr (=0.56) | 4.957 | 6.500 | 0.2309 | 0.6532 | 634 | 634 | 0.6437 |

(B and C are identical because the optimized threshold *is* 0.56.) Variant C: minutes clearly
better; betting metrics neutral; coverage and play-count preserved.

---

## The core architectural finding (drives the recommendation and Phase 5)

**Minutes accuracy and betting accuracy are decoupled in the current pipeline.** Stat
projections (`*_proj`) come from stat models that never see projected minutes; the Monte Carlo
re-injects minutes only through a damped blend. So a better minutes model improves the minutes
product but is near-invisible to bet probabilities. To convert minutes accuracy into betting
edge, **project per-minute rates and multiply by projected minutes** (or add `projected_minutes`
as a stat-model feature). That is the highest-leverage next step (Phase 5); Variant C should be
promoted alongside it, where it will finally move Brier/log-loss/ROI.

## Prioritized next actions
1. **Fix the availability feed UA** (1 line, standalone, clearly beneficial) + add a
   < 5 KB / 0-section guard so silent stubbing cannot recur.
2. **Re-architect stat projections to be minutes-driven** (Phase 5), then re-run this exact
   re-sim — Variant C should then pass the Brier/log-loss gates.
3. **Promote Variant C** once (2) lands (or now, if projections are a user-facing product).
4. Backfill retrospective availability from the game log; add a pre-game lineup source.

## Files
**Created (all under `sports/wnba/outputs/phase3/`):** `phase4a_full_resim.py`,
`phase4b_threshold_opt.py`; reports — `resim_window_metrics.csv`, `resim_coverage_report.csv`,
`resim_bet_scores.csv`, `threshold_optimization.csv`, `recommended_threshold.csv`,
`phase4_three_way_comparison.csv`, `phase4_gate_results.json`,
`phase4c_availability_audit.md`, this report; shadow models —
`shadow/models/wnba_minutes_model_variantC_{7,14,30}d.joblib`.
**Modified production files:** none. **Backups:** `backups/wnba_phase3_20260607_001016/`.
