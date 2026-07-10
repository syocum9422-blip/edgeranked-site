# WNBA Accuracy Recovery — Phase 4 Deployment & Rollback
*Deployed 2026-07-10, shadow-only. Production behavior unchanged.*

## What shipped
- `accuracy_recovery/recovery_selection.py` — the validated C1+C2+C6 selection layer
- `accuracy_recovery/variance_inflation.json` — per-market std inflation factors (trailing 30d,
  regenerate with `build_variance_inflation.py`; current: points 1.53, rebounds 1.42, assists 1.15…)
- One fail-safe hook at the end of `rank_bets()` in `build_wnba_best_bets.py`
  (captures the pre-threshold candidate pool; any exception → untouched production board)
- `grade_recovery_shadow.py` — forward grading + promotion verdict
- `test_recovery_selection.py` — regression suite (all passing)

## Feature flag
`WNBA_ACCURACY_RECOVERY` = `off` | `shadow` (**default**) | `on`

| Mode | Published board | Side effects |
|---|---|---|
| off | production, byte-identical | none |
| shadow (default) | production, byte-identical (verified `.equals()` on real slate) | writes `accuracy_recovery/shadow_boards/recovery_board_YYYYMMDD.csv` |
| on | recovery board (singles-only, variance-honest, role-guarded) | falls back to production board if recovery board empty or errors |

The layer only *removes* candidates and *shrinks* hit rates before the existing
`MIN_EDGE=0.04` / `MIN_HIT_RATE=0.56` gates — production validation gates are re-applied,
never weakened. Calibration factors, guardrail caps, market qualification: all untouched.

## Verification performed (2026-07-10)
1. `python3 -m py_compile build_wnba_best_bets.py` — OK
2. `accuracy_recovery/test_recovery_selection.py` — ALL PASSED (off/shadow parity, gate
   non-weakening, combo exclusion, inflation-only-shrinks, failure fallback)
3. End-to-end on today's real simulation detail: `rank_bets` off vs shadow published boards
   `.equals()` → True; shadow sidecar written (19 singles); on-mode board: 19 picks, 0 combos,
   honest hit rates 0.60–0.70. Today's live production board is 72% combos.
4. Existing pipeline gates (empty-state handling, calibration staleness, market qualification)
   unmodified — confirmed by diff scope: only the two hook lines in `build_wnba_best_bets.py`.

## Promotion procedure (do NOT skip)
1. Let the daily cron accumulate shadow boards (no cron changes were made; the builder emits the
   sidecar automatically in default shadow mode).
2. After each slate: `python3 accuracy_recovery/grade_recovery_shadow.py`
3. Flip only on `VERDICT: READY_TO_PROMOTE` (≥15 slates, shadow > production, p<0.10, no bad stat):
   add `export WNBA_ACCURACY_RECOVERY=on` to the WNBA cron environment (run_wnba_model.sh).
4. Refresh `variance_inflation.json` weekly (or before promotion): `python3 accuracy_recovery/build_variance_inflation.py`

## Rollback
- Instant: `export WNBA_ACCURACY_RECOVERY=off` (or unset back to `shadow`) — no code revert needed.
- Full revert: `cp backups/wnba_accuracy_recovery_20260710/build_wnba_best_bets.py .`
  (pre-change snapshot, includes the day's published board for reference).
- The `accuracy_recovery/` directory is inert without the flag in `on` mode.

## Regression snapshots
- `backups/wnba_accuracy_recovery_20260710/` — pre-change builder + that day's published board
- `accuracy_recovery/reports/replay_pool.csv` — the full backtest pool for future re-analysis
