# WNBA Phase 13 Combo Hybrid Minutes Production Report

Generated: 2026-07-18T22:31:03Z

## Production Logic
- Rollback flag: `WNBA_ENABLE_COMBO_HYBRID_MINUTES_PRODUCTION` (default: ON).
- Applies only to PA, PR, and PRA combo-market projection samples.
- PA uses 25% shadow role-pattern minutes and 75% current production minutes.
- PR uses 100% shadow role-pattern minutes.
- PRA uses 50% shadow role-pattern minutes and 50% current production minutes.
- Points, rebounds, assists, RA, steals, blocks, 3PM, and SB base-market outputs are not rewritten.

## Before/After Summary
- PA: rows=73, avg before=9.240, avg after=9.842, avg delta=0.602, max abs delta=7.086
- PR: rows=73, avg before=10.669, avg after=10.649, avg delta=-0.020, max abs delta=8.789
- PRA: rows=73, avg before=12.409, avg after=12.953, avg delta=0.544, max abs delta=9.726

## Report Files
- CSV comparison: `/home/ubuntu/EdgeRanked/sports/wnba/data/processed/wnba_phase13_combo_hybrid_minutes_projection_comparison.csv`
- Markdown report: `/home/ubuntu/EdgeRanked/sports/wnba/learning/reports/wnba_phase13_combo_hybrid_minutes_production_report.md`

## Rollback
- Set `WNBA_ENABLE_COMBO_HYBRID_MINUTES_PRODUCTION=0` and rerun `python3 run_wnba_model.py`.
- The canary remains independent via `WNBA_ENABLE_COMBO_HYBRID_MINUTES_CANARY=1`.
