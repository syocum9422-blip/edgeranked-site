# WNBA V2 Conserved Simulator Deployment Plan

## Recommendation

Current recommendation: **controlled emergency staged serving of conserved V2 only**.

The old independent simulator is retired. Emergency serving is allowed only for `simulation_version == "sim-5.4-conserved"` and only while realism gates and the accepted learned calibration remain valid.

Measured Phase 5.5 evidence:

| Engine | Hit Rate | Brier | ECE | Combo Brier |
|---|---:|---:|---:|---:|
| Old V2 independent | 50.46% | 0.2600 | 0.0997 | 0.2641 |
| New V2 conserved | 54.73% | 0.2561 | 0.0725 | 0.2543 |
| Production | 52.42% | 0.3169 | 0.2452 | 0.3321 |

Realism gates remain passing. The emergency serving policy is based on this measured evidence, not on a new model path.

## Required Environment

```bash
export EDGERANKED_WNBA_SERVING_MODE=staged_v2_emergency
export EDGERANKED_WNBA_V2_TRAFFIC_PERCENT=5
export EDGERANKED_WNBA_V2_EMERGENCY_MAX_TRAFFIC_PERCENT=10
```

Recommended explicit safety defaults:

```bash
export EDGERANKED_WNBA_V2_REQUIRE_PROMOTE_SIGNAL=1
export EDGERANKED_WNBA_V2_ROLLBACK_FORCE_PRODUCTION=0
export EDGERANKED_WNBA_V2_EMERGENCY_MIN_GRADED=500
export EDGERANKED_WNBA_V2_EMERGENCY_MIN_BRIER_IMPROVEMENT=0.02
export EDGERANKED_WNBA_V2_EMERGENCY_MIN_COMBO_BRIER_IMPROVEMENT=0.02
export EDGERANKED_WNBA_V2_EMERGENCY_MIN_ECE_IMPROVEMENT=0.05
```

## Hard Blocks

Emergency serving is blocked if any of these are true:

- dashboard `versions.simulation_version != "sim-5.4-conserved"`
- `wnba_v2/outputs/phase53/phase53_learned_calibration.json` is missing or not accepted
- `wnba_v2/outputs/phase53/phase53_validation_summary.json` is missing or realism gates are not all passing
- Phase 6 or dashboard is `ROLLBACK_CANDIDATE`
- V2 Brier, combo Brier, or ECE regresses worse than production
- requested emergency traffic exceeds `EDGERANKED_WNBA_V2_EMERGENCY_MAX_TRAFFIC_PERCENT`

## Traffic Policy

- Start: **5%** traffic.
- Maximum emergency traffic: **10%** until additional live evidence accumulates.
- Do not serve the old independent simulator under any mode.
- Keep rollback protection active with `EDGERANKED_WNBA_V2_ROLLBACK_FORCE_PRODUCTION`.

## Verification

```bash
python3 -m wnba_v2.tracker.dashboard
python3 -m wnba_v2.tracker.daily_run
```

Expected dashboard/promotion-status checks:

- `emergency_policy.allowed == true`
- `emergency_policy.metrics.simulation_version == "sim-5.4-conserved"`
- `emergency_policy.checks.realism_gates_passing == true`
- `emergency_policy.checks.learned_calibration_available == true`
- `emergency_policy.checks.old_independent_simulator_disabled == true`

## Deployment Command

```bash
export EDGERANKED_WNBA_SERVING_MODE=staged_v2_emergency
export EDGERANKED_WNBA_V2_TRAFFIC_PERCENT=5
export EDGERANKED_WNBA_V2_EMERGENCY_MAX_TRAFFIC_PERCENT=10
python3 run_wnba_model.py
```
