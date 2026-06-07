"""WNBA promotion-readiness scorecard (Phase 6D).

Reads the canary trend history and evaluates the Variant C promotion gates on the 30-day
window (primary) each week, tracks consecutive passing/failing weeks, and emits a
recommendation: PROMOTE | HOLD | ROLLBACK | INSUFFICIENT_DATA.

Gates (30d, A=production vs C=variant):
  - Brier improvement:        C_brier   <  A_brier
  - Log-loss improvement:     C_log_loss <  A_log_loss
  - Coverage reduction <5%:   (A_cov - C_cov)/A_cov < 0.05
  - No projection MAE regression: C_proj_mae   <= A_proj_mae * (1+TOL)
  - No minutes MAE regression:    C_minutes_mae <= A_minutes_mae * (1+TOL)

Decision policy:
  - < MIN_WEEKS distinct canary runs        -> INSUFFICIENT_DATA
  - CONSEC_PASS_REQUIRED consecutive passes  -> PROMOTE
  - ROLLBACK_FAIL_REQUIRED consecutive fails with a *material* coverage/brier regression -> ROLLBACK
  - otherwise                                -> HOLD
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

WNBA = Path(__file__).resolve().parent
OUT = WNBA / "outputs" / "phase6"
HIST = OUT / "canary_history" / "canary_trend_master.csv"
TOL = 0.005          # 0.5% noise tolerance on "no regression" gates
MIN_WEEKS = 3        # need >=3 canary runs before a PROMOTE/ROLLBACK call
CONSEC_PASS_REQUIRED = 3
ROLLBACK_FAIL_REQUIRED = 2


def evaluate_run(r: pd.Series) -> dict:
    gates = {
        "brier_improves": bool(r["C_brier"] < r["A_brier"]),
        "log_loss_improves": bool(r["C_log_loss"] < r["A_log_loss"]),
        "coverage_reduction_under_5pct": bool((r["A_coverage"] - r["C_coverage"]) / r["A_coverage"] < 0.05)
        if r["A_coverage"] else False,
        "no_proj_mae_regression": bool(r["C_proj_mae"] <= r["A_proj_mae"] * (1 + TOL)),
        "no_minutes_mae_regression": bool(r["C_minutes_mae"] <= r["A_minutes_mae"] * (1 + TOL)),
    }
    material_regression = ((r["A_coverage"] - r["C_coverage"]) / r["A_coverage"] >= 0.05 if r["A_coverage"] else False) \
        or (r["C_brier"] > r["A_brier"] * 1.02)
    return {"all_pass": all(gates.values()), "gates": gates, "material_regression": bool(material_regression)}


def main():
    if not HIST.exists():
        out = {"recommendation": "INSUFFICIENT_DATA", "reason": "no canary history yet",
               "generated_at_utc": datetime.now(timezone.utc).isoformat()}
        json.dump(out, open(OUT / "promotion_readiness_scorecard.json", "w"), indent=2)
        print(json.dumps(out, indent=2)); return

    hist = pd.read_csv(HIST)
    h30 = hist[hist["window_days"] == 30].sort_values("generated_at_utc").reset_index(drop=True)
    runs = []
    for _, r in h30.iterrows():
        ev = evaluate_run(r)
        runs.append({"generated_at_utc": r["generated_at_utc"], "data_through": r.get("data_through"),
                     **{k: r[k] for k in ["C_brier", "A_brier", "C_log_loss", "A_log_loss",
                                          "C_coverage", "A_coverage", "C_proj_mae", "A_proj_mae",
                                          "C_minutes_mae", "A_minutes_mae"]},
                     "pass": ev["all_pass"], "material_regression": ev["material_regression"],
                     "gates": ev["gates"]})

    # consecutive streaks (from most recent backwards)
    consec_pass = consec_fail = 0
    for run in reversed(runs):
        if run["pass"]:
            if consec_fail == 0:
                consec_pass += 1
            else:
                break
        else:
            if consec_pass == 0:
                consec_fail += 1
            else:
                break

    n = len(runs)
    recent_material = any(run["material_regression"] for run in runs[-ROLLBACK_FAIL_REQUIRED:])
    if n < MIN_WEEKS:
        rec = "INSUFFICIENT_DATA"
        reason = f"{n} canary run(s); need >= {MIN_WEEKS}"
    elif consec_fail >= ROLLBACK_FAIL_REQUIRED and recent_material:
        rec = "ROLLBACK"
        reason = f"{consec_fail} consecutive failing weeks with material regression"
    elif consec_pass >= CONSEC_PASS_REQUIRED:
        rec = "PROMOTE"
        reason = f"{consec_pass} consecutive passing weeks across all gates"
    else:
        rec = "HOLD"
        reason = f"consec_pass={consec_pass}, consec_fail={consec_fail}; not yet decisive"

    scorecard = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "recommendation": rec, "reason": reason,
        "canary_runs": n, "consecutive_passing_weeks": consec_pass,
        "consecutive_failing_weeks": consec_fail,
        "criteria": {"window": "30d", "noise_tolerance": TOL, "min_weeks": MIN_WEEKS,
                     "consec_pass_required": CONSEC_PASS_REQUIRED,
                     "rollback_fail_required": ROLLBACK_FAIL_REQUIRED},
        "latest_run": runs[-1] if runs else None,
        "history": runs,
    }
    json.dump(scorecard, open(OUT / "promotion_readiness_scorecard.json", "w"), indent=2, default=str)

    # Notify only on a worthy state change (no duplicates while unchanged).
    try:
        import logging
        from wnba_readiness_notify import notify_on_change
        nres = notify_on_change(scorecard, logger=logging.getLogger("wnba_readiness"))
        if nres["notified"]:
            print(f"[notify] {nres['previous_state']} -> {nres['current_state']} "
                  f"(method={nres['method']})")
        else:
            print(f"[notify] no alert (state {nres['previous_state']} -> {nres['current_state']})")
    except Exception as e:  # never let notification break the scorecard
        print(f"[notify] skipped due to error: {e}")

    # promotion manifest template (filled only when recommendation == PROMOTE)
    manifest = {
        "manifest_version": 1, "candidate": "Variant C — minutes-driven stat architecture",
        "decision": rec, "decided_at_utc": scorecard["generated_at_utc"],
        "evidence": {"canary_runs": n, "consecutive_passing_weeks": consec_pass,
                     "primary_window": "30d", "latest": runs[-1] if runs else None},
        "artifacts_to_promote": ["outputs/phase6/patches/PATCH_B_minutes_driven.md"],
        "files_changed_on_promote": ["simulate_wnba_today.py", "wnba_model_utils.py",
                                      "data/models/wnba_*_rate_model.joblib (new)",
                                      "data/processed/wnba_training_dataset.csv (rebuild)",
                                      "models/wnba_minutes_model.joblib (retrain)"],
        "preconditions": ["dataset rebuilt to current season", "backup created",
                          "rollback path verified"],
        "rollback": "restore listed files from backups/wnba_phase6_<TS>/ and backups/wnba_phase3_20260607_001016/",
    }
    json.dump(manifest, open(OUT / "promotion_manifest_template.json", "w"), indent=2, default=str)

    print(f"=== WNBA Promotion Readiness: {rec} ===")
    print(f"reason: {reason}")
    print(f"canary_runs={n} | consec_pass={consec_pass} | consec_fail={consec_fail}")
    if runs:
        print("latest gates:", json.dumps(runs[-1]["gates"]))


if __name__ == "__main__":
    main()
