# WNBA Phase 13 Combo Hybrid Minutes Production Report

Generated: 2026-06-24T22:32:27Z

## Production Logic
- Rollback flag: `WNBA_ENABLE_COMBO_HYBRID_MINUTES_PRODUCTION` (default: ON).
- Applies only to PA, PR, and PRA combo-market projection samples.
- PA uses 25% shadow role-pattern minutes and 75% current production minutes.
- PR uses 100% shadow role-pattern minutes.
- PRA uses 50% shadow role-pattern minutes and 50% current production minutes.
- Points, rebounds, assists, RA, steals, blocks, 3PM, and SB base-market outputs are not rewritten.

## Before/After Summary
- PA: rows=113, avg before=8.858, avg after=8.969, avg delta=0.110, max abs delta=10.141
- PR: rows=113, avg before=10.203, avg after=10.128, avg delta=-0.075, max abs delta=10.831
- PRA: rows=113, avg before=11.963, avg after=12.054, avg delta=0.092, max abs delta=12.427

## Report Files
- CSV comparison: `/home/ubuntu/EdgeRanked/sports/wnba/data/processed/wnba_phase13_combo_hybrid_minutes_projection_comparison.csv`
- Markdown report: `/home/ubuntu/EdgeRanked/sports/wnba/learning/reports/wnba_phase13_combo_hybrid_minutes_production_report.md`

## Rollback
- Set `WNBA_ENABLE_COMBO_HYBRID_MINUTES_PRODUCTION=0` and rerun `python3 run_wnba_model.py`.
- The canary remains independent via `WNBA_ENABLE_COMBO_HYBRID_MINUTES_CANARY=1`.
