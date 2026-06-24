# WNBA Phase 13 Combo Hybrid Minutes Rollback

Phase 13 promotes the Phase 12 combo hybrid minutes blend into production for combo markets only.

## Production Flag

`WNBA_ENABLE_COMBO_HYBRID_MINUTES_PRODUCTION=1`

The flag defaults ON in `simulate_wnba_today.py`. Set it to `0`, `false`, `no`, or `off` to disable the production promotion.

## Scope

Enabled markets:

- PA: 25% shadow role-pattern minutes, 75% current production minutes
- PR: 100% shadow role-pattern minutes
- PRA: 50% shadow role-pattern minutes, 50% current production minutes

Unaffected markets:

- Points
- Rebounds
- Assists
- RA
- Steals
- Blocks
- 3PM
- SB

## Rollback Procedure

```bash
WNBA_ENABLE_COMBO_HYBRID_MINUTES_PRODUCTION=0 python3 run_wnba_model.py
```

This reruns the normal projection pipeline with PA, PR, and PRA restored to the pre-Phase 13 production combo samples.

## Monitoring

The Phase 12 canary remains in the production pipeline and runs with:

```bash
WNBA_ENABLE_COMBO_HYBRID_MINUTES_CANARY=1 python3 wnba_combo_hybrid_minutes_canary.py
```

Canary outputs remain separate from production outputs.

## Validation Artifacts

- `data/processed/wnba_phase13_combo_hybrid_minutes_projection_comparison.csv`
- `learning/reports/wnba_phase13_combo_hybrid_minutes_production_report.md`
- `data/processed/wnba_combo_hybrid_minutes_canary_market_report.csv`
- `learning/reports/wnba_combo_hybrid_minutes_canary_report.md`
