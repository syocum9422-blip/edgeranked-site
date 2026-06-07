# WNBA Phase 6 — Production Patch Prep + Automated Canary — Final Report

**Date:** 2026-06-07. **Backup:** `backups/wnba_phase6_20260607_005334/` (fetch_wnba_data.py,
prior status csv, crontab). Phase 3–5 artifacts preserved under `outputs/phase3/`.

## Final recommendation
1. **Availability Fix (Patch A): DEPLOY — ✅ DONE.** Validated and deployed; feed live (9 injuries
   / 7 teams), 0 players excluded today, full rollback path verified.
2. **Variant C (minutes-driven stats): CANARY ONLY.** Validated 30d gains persist in the canary
   (Brier/log-loss/minutes-MAE improve, coverage −1.3%), but the 30d projection-MAE gate still
   fails at the early-season cutoff and only 1 canary run exists. Promotion is **automated and
   gated**: 3 consecutive passing weekly canaries → PROMOTE. Do **not** cut over now.

---

## 6A — Patch drafts (`patches/`)
- `PATCH_A_availability.md`, `PATCH_B_minutes_driven.md`, `PATCH_REVIEW_PACKAGE.md` (file list +
  risk assessment). Patch A approved+deployed; Patch B draft-only, canary-gated.

## 6B — Availability validation & deployment
| Check | Pre-patch | Post-patch |
|---|---|---|
| scrape rows | 0 | **9** |
| response | 1,987-byte stub | 298 KB full page |
| teams | 0 | 7 |
| source label | (empty) | `api:espn_injuries` |
| schema | unchanged | unchanged (`player_name,team,status,player_key,…`) |
| players excluded today | 0 | **0** (all Day-To-Day) |

Patch A **deployed** to `fetch_wnba_data.py` (12-line diff: UA → `Mozilla/5.0` + <5 KB stub
guard). Canonical `data/raw/wnba_player_status.csv` populated (9 rows). Zero behavior change
today (no OUT players); feed now live for future OUT/Doubtful days. **Rollback verified:**
restore from backup → `Chrome/124.0` UA returns.

## 6C — Weekly canary automation
- `sports/wnba/wnba_canary_validation.py` — rebuilds a shadow dataset from current raw data,
  compares **A=production vs C=Variant C** on minutes MAE/RMSE, projection MAE/RMSE, accuracy,
  Brier, log-loss, coverage for 7/14/30d. Outputs:
  - `outputs/phase6/weekly_wnba_canary_report.json`
  - `outputs/phase6/weekly_wnba_canary_report.csv`
  - `outputs/phase6/canary_history/canary_trend_master.csv` (appended each run) + per-run snapshots.
- `site/scripts/aws/run_wnba_canary.sh` — runner (logs to `site/logs/cron/wnba_canary.log`).
- **Cron installed:** `0 12 * * 1` (Mondays 12:00 UTC). Shadow-only; touches no production file.

**First canary run (data through 2026-06-06, 4000 sims):**

| window | C/A minutes MAE | C/A proj MAE | C/A Brier | C/A log-loss | C/A coverage |
|---|---|---|---|---|---|
| 7d | 4.21 / 4.38 | 1.49 / 1.53 | 0.269 / 0.265 | 0.734 / 0.726 | 105 / 102 |
| 14d | 4.18 / 4.47 | 1.49 / 1.53 | 0.254 / 0.255 | 0.703 / 0.704 | 248 / 247 |
| **30d** | **4.97 / 5.03** | 1.61 / 1.59 | **0.252 / 0.255** | **0.699 / 0.706** | 678 / 687 |

## 6D — Promotion readiness monitor
- `sports/wnba/wnba_promotion_readiness.py` — evaluates the 30d gates per canary run, tracks
  consecutive pass/fail weeks, emits `outputs/phase6/promotion_readiness_scorecard.json` +
  `promotion_manifest_template.json`. Recommendation ∈ {PROMOTE, HOLD, ROLLBACK,
  INSUFFICIENT_DATA}.
- **Gates (30d):** Brier↓, log-loss↓, coverage reduction <5%, no projection-MAE regression
  (0.5% tol), no minutes-MAE regression. **Policy:** ≥3 runs required; 3 consecutive passes →
  PROMOTE; 2 consecutive fails with material regression → ROLLBACK.
- **Current scorecard: `INSUFFICIENT_DATA`** (1 run). Latest gates: Brier ✅, log-loss ✅,
  coverage<5% ✅, **projection-MAE ❌** (30d-cutoff data scarcity), minutes-MAE ✅ → 4/5.

## 6E — Final decision framework

| Deliverable | Status |
|---|---|
| Files changed | `fetch_wnba_data.py` (Patch A); +new automation files (non-production) |
| Backups | `backups/wnba_phase6_20260607_005334/` (+ Phase 3 backup) |
| Availability deployment | **DEPLOYED & verified** |
| Canary automation | **LIVE** (weekly cron, scorecard) |
| Patch review package | `patches/PATCH_{A,B}_*.md`, `PATCH_REVIEW_PACKAGE.md` |
| Weekly validation outputs | `weekly_wnba_canary_report.{json,csv}`, `canary_history/` |
| Promotion readiness logic | `wnba_promotion_readiness.py` + scorecard/manifest |

### Final recommendation
- **Availability Fix → DEPLOY (done).**
- **Variant C → CANARY ONLY.** Let the weekly canary accrue ≥3 runs. Expect the 30d
  projection-MAE gate to flip green as in-season data accumulates (the rate models are
  data-starved at the early-May cutoff but strengthen weekly). Promote automatically once the
  scorecard reads PROMOTE; the manifest template is pre-staged. Production integrity preserved
  throughout.

## Files created
**Production (deployed):** `sports/wnba/fetch_wnba_data.py` (Patch A).
**Automation (non-production):** `sports/wnba/wnba_canary_validation.py`,
`sports/wnba/wnba_promotion_readiness.py`, `site/scripts/aws/run_wnba_canary.sh`, crontab line.
**Docs/outputs:** `outputs/phase6/patches/*`, `outputs/phase6/weekly_wnba_canary_report.*`,
`outputs/phase6/canary_history/*`, `outputs/phase6/promotion_readiness_scorecard.json`,
`outputs/phase6/promotion_manifest_template.json`, this report.
