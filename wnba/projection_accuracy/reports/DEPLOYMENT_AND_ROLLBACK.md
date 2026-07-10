# WNBA Accuracy Page Redesign — Deployment & Rollback
*2026-07-10 · deliverables 5, 7, 8*

## What changed (scope: the Accuracy PAGE only)
| File | Change |
|---|---|
| `sports/wnba/projection_accuracy/grade_projection_accuracy.py` | NEW — grades archived projections vs box scores → `projection_accuracy_report.json` (+ graded/reconcile CSVs) |
| `site/nba_model/webapp/accuracy_views.py` | Added projection-accuracy loaders/cards/analytics + a separate Best Bet Performance section, both behind a flag. Legacy code path untouched. |
| `sports/wnba/projection_accuracy/test_accuracy_page.py` | NEW — 7 regression tests |

**Not touched:** projection engine, best-bet engine (`build_wnba_best_bets.py`), simulator,
publishing, validation gates, crons, and every other sport's accuracy page (MLB/NBA verified 200 OK).

## Feature flag
`WNBA_PROJECTION_ACCURACY_PAGE` = unset/`off` (**default**) → existing legacy page.
`on` → redesigned projection-accuracy page (Cards 1–3 + analytics + separate Best Bet section).

The flag is read at render time, so flipping it needs only a process env change + restart — no code
redeploy. The page **fails safe**: if `projection_accuracy_report.json` is missing/unreadable, the
projection cards show "Not currently published" rather than erroring, and the legacy pipeline cards
still render.

## Card mapping (redesigned page)
- **Card 1 — Projection accuracy, last 30 days:** % within ±2 headline + normalized MAE / RMSE /
  bias / graded count / last graded date. Source: `projection_accuracy_report.json` only.
- **Card 2 — Season projection results:** overall normalized MAE headline + pooled MAE/RMSE/bias +
  date range. **No hit rate, no correct–incorrect, no sportsbook results.**
- **Card 3 — Daily pipeline validation:** PASS/FAIL from `wnba_production_status.json`; caption
  explicitly says "pipeline health, not model accuracy."
- **Best Bet Performance (separate section):** correct/incorrect, hit rate, pushes, singles, combos,
  overs, unders, calibration, last 7/30/season — from `graded_bets.csv`, clearly labeled as a
  separate system.

## Verification performed (2026-07-10)
1. `python3 -m py_compile accuracy_views.py` — OK.
2. `projection_accuracy/test_accuracy_page.py` — **7/7 PASS** (bet-artifact isolation via AST scan,
   grader-reads-only-archives, singles parity vs production, turnovers-excluded, flag-off preserves
   legacy, flag-on shows projection page + separates bets, season card has no hit-rate field).
3. Flask test client: `/accuracy`, `/accuracy/wnba`, `/accuracy/mlb`, `/accuracy/nba` all HTTP 200
   with flag on; `/accuracy/wnba` default (flag unset) still renders the legacy page.
4. Rendered values confirmed: headline = true projection accuracy (78.3% within ±2 / normalized MAE
   0.76); the 53.0% bet hit rate appears **only** inside Best Bet Performance.

## Deploy procedure (surgical cp, per repo topology)
1. Regenerate the report on the box that has the archives:
   `python3 sports/wnba/projection_accuracy/grade_projection_accuracy.py`
2. Copy source + report into the prod tree:
   - `cp site/nba_model/webapp/accuracy_views.py /srv/edgeranked-prod/nba_model/webapp/`
   - `cp -r sports/wnba/projection_accuracy /srv/edgeranked-prod/sports/wnba/` (report + grader)
3. Gate check: `cd /srv/edgeranked-prod && python -c "import wsgi"` (must succeed).
4. Restart: `sudo systemctl restart edgerankai.service`.
5. **Keep the flag off** and confirm the legacy page is unchanged in prod.
6. **Recommended additive cron** (does not touch existing crons or gates): run the grader daily
   after actuals ingest so the report stays fresh, e.g. after `update_wnba_learning_outputs`.
7. **Promote** by setting `WNBA_PROJECTION_ACCURACY_PAGE=on` in the service environment and
   restarting, once the rendered numbers are reviewed in prod.

## Rollback
- Instant: unset `WNBA_PROJECTION_ACCURACY_PAGE` (or `=off`) + restart → legacy page returns. No
  code revert required.
- Full revert: `cp sports/wnba/projection_accuracy/backups/accuracy_views.py.pre_projection_page_20260710`
  back over `accuracy_views.py` and redeploy.
- The `projection_accuracy/` directory is inert while the flag is off.

## Regression snapshots
- `projection_accuracy/backups/accuracy_views.py.pre_projection_page_20260710` — pre-change page.
- `projection_accuracy/reports/projection_accuracy_report.json` + graded/reconcile CSVs — the
  grading baseline for future diffs.
