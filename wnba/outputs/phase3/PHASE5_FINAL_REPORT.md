# WNBA Phase 5 — Minutes-Driven Stat Projection Architecture — Final Report

**Date:** 2026-06-07. Shadow-only. Production untouched (all source/model mtimes predate Phase 5).
No auto-promotion. Strict temporal validation. Phase 3/4 artifacts preserved.
**Backup:** `backups/wnba_phase3_20260607_001016/` (Phase 5 added no production changes).

## Promotion recommendation: **PROMOTE (staged / canary)** the minutes-driven architecture + **PROMOTE NOW** the availability UA fix

Phase 5 confirms the Phase 4 hypothesis: once stat projections are made minutes-aware, the
minutes-model gains finally convert into **betting** improvements. The effect is real but
modest and one month old, so the recommended path is canary, not immediate full cutover.

---

## Phase 5A — Architecture map (`reports/phase5a_architecture_map.md`)

The pipeline carries **three disconnected minutes quantities**. The stat models consume a
`minutes` **feature** (a lagged snapshot estimate), while the well-calibrated
`projected_minutes` from the minutes model is used **only** in the Monte-Carlo 35% blend and
confidence — `build_projection_rows` never assigns it to the stat-model feature. That is why
Phase 4's minutes upgrade did not reach bet probabilities. Confidence, by contrast, is 45%
driven by minutes stability.

## Phase 5B/5C — Variants & projection accuracy (`reports/phase5_projection_accuracy.csv`)

| | A (prod) | B (+proj_min feat) | C (rate×min) | D (hybrid) |
|---|---|---|---|---|
| Proj MAE 7d | 1.5326 | 1.5248 | **1.4922** | 1.4988 |
| Proj MAE 14d | 1.5287 | 1.5156 | **1.4888** | 1.4955 |
| Proj MAE 30d | **1.5867** | 1.6171 | 1.6122 | 1.6110 |

**Variant C (per-minute rate × projected minutes) improves projection MAE ~2.6% on the recent
7d/14d windows** (RMSE likewise), and is marginally worse on 30d — because the 30d cutoff
(2026-05-08) leaves the rate models almost no in-season data; C's edge grows as in-season
history accumulates. B (feed `projected_minutes` to existing models) captures part of the gain.

## Phase 5C/5D — Betting re-simulation (`reports/phase5_betting_metrics.csv`)

Full production Monte-Carlo + calibration + guardrails, leakage-free minutes feature.

**30d window (most data, most reliable):**

| 30d | A (prod) | B | **C (rate×min)** | D |
|---|---|---|---|---|
| Brier | 0.2552 | 0.2535 | **0.2520** (−1.3%) | 0.2527 |
| Log-loss | 0.7056 | 0.7013 | **0.6981** (−1.1%) | 0.6995 |
| Coverage@56 | 691 | 688 | 682 (−1.3%) | 691 |
| Qual win-rate | 0.5814 | 0.5804 | **0.5892** (+0.8pp) | 0.5861 |

**14d:** win-rate improves +1pp for B/C/D (A 0.5802 → C 0.5902); coverage rises (A 249 → D 261).
**7d:** mixed — A has the best Brier (small, noisy sample), but B lifts win-rate 0.559→0.590 and
coverage 104→125.

## Phase 5D — Does minutes accuracy now reach betting? **Yes.**

- In Phase 4 (stat models minutes-blind) the minutes upgrade left Brier/log-loss **dead flat**.
- In Phase 5 (Variant C: rate × projected minutes) the same minutes model now **improves 30d
  Brier, log-loss, and win-rate**, with coverage within tolerance. The Phase-3 Variant-C
  minutes model **gains value** exactly as predicted once the stat layer is minutes-driven.
- Magnitude is modest (~1% Brier, +0.8pp win-rate on 30d) and the 7d window regresses on Brier,
  so this is a directional win to confirm with more data — not a blowout.

## Phase 5E — Availability integration (shadow UA fix) (`reports/phase5e_*`)

The one-line UA fix (`Mozilla/5.0`) restores the ESPN feed: **298,114 bytes (was a 1,987-byte
stub) → 9 injuries across 7 teams** parsed, with a < 5 KB guard so silent stubbing cannot
recur. Today: of 52 projected players, **2 flagged Day-To-Day** (Caitlin Clark, Chennedy
Carter → confidence-cap), **0 OUT removals** (none ruled out today; impact is larger on OUT
days). Detection rate = 100% of what ESPN lists. Shadow status written to
`shadow/wnba_player_status_shadow.csv`; production untouched.

---

## Recommendation detail

1. **Promote the availability UA fix now** — standalone, safe, clearly beneficial (1-line UA +
   < 5 KB guard in `fetch_wnba_data.py:334`). Restores a dead feed.
2. **Promote the minutes-driven stat architecture (Variant C: per-minute rate × projected
   minutes, fed by the Phase-3 Variant-C minutes model) to canary.** It is the first validated
   change that converts minutes accuracy into betting edge: 30d Brier/log-loss/win-rate improve,
   coverage within 5%, projection MAE better on recent windows. Hold full production promotion
   until 2–4 more weeks confirm the 30d gains persist and the 7d Brier dip is noise; the rate
   models also strengthen as in-season data accumulates (explains the 30d-cutoff dip).
3. **Sequence:** ship UA fix → run Variant C in canary alongside production → re-run this
   re-sim weekly → promote on sustained Brier/log-loss/win-rate improvement.

## Gate summary (A → Variant C, 30d)
Projection MAE ▲ recent / ▼ 30d-cutoff · Minutes MAE ▲ · Brier ▲ (−1.3%) · Log-loss ▲ (−1.1%)
· Win-rate ▲ (+0.8pp) · Coverage ▲ within 5% (−1.3%). Calibration not degraded on 14/30d.

## Files
**Created (under `sports/wnba/outputs/phase3/`):** `phase5b_stat_variants.py`,
`phase5c_betting_resim.py`, `phase5e_availability.py`; reports —
`phase5a_architecture_map.md`, `phase5_projection_accuracy.csv`,
`phase5_projection_by_market.csv`, `phase5_stat_projections.csv`, `phase5_betting_metrics.csv`,
`phase5_resim_bet_scores.csv`, `phase5e_availability_summary.json`,
`phase5e_projected_player_corrections.csv`, this report; shadow —
`shadow/wnba_player_status_shadow.csv`.
**Modified production files:** none. **Backups:** `backups/wnba_phase3_20260607_001016/`.
