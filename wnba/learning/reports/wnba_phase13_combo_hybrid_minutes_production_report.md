# WNBA Phase 13 Combo Hybrid Minutes Production Report

Generated: 2026-08-01T18:01:04Z

## Production Logic
- Rollback flag: `WNBA_ENABLE_COMBO_HYBRID_MINUTES_PRODUCTION` (default: ON).
- Applies only to PA, PR, and PRA combo-market projection samples.
- PA uses 25% shadow role-pattern minutes and 75% current production minutes.
- PR uses 100% shadow role-pattern minutes.
- PRA uses 50% shadow role-pattern minutes and 50% current production minutes.
- Points, rebounds, assists, RA, steals, blocks, 3PM, and SB base-market outputs are not rewritten.

## Before/After Summary
- PA: rows=50, avg before=10.064, avg after=10.589, avg delta=0.525, max abs delta=9.963
- PR: rows=50, avg before=11.270, avg after=11.509, avg delta=0.239, max abs delta=10.980
- PRA: rows=50, avg before=13.257, avg after=13.801, avg delta=0.544, max abs delta=12.840

## Report Files
- CSV comparison: `/home/ubuntu/EdgeRanked/sports/wnba/data/processed/wnba_phase13_combo_hybrid_minutes_projection_comparison.csv`
- Markdown report: `/home/ubuntu/EdgeRanked/sports/wnba/learning/reports/wnba_phase13_combo_hybrid_minutes_production_report.md`

## Rollback
- Set `WNBA_ENABLE_COMBO_HYBRID_MINUTES_PRODUCTION=0` and rerun `python3 run_wnba_model.py`.
- The canary remains independent via `WNBA_ENABLE_COMBO_HYBRID_MINUTES_CANARY=1`.
