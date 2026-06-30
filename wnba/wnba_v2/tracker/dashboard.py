"""Phase 6 — cumulative dashboard + promotion gate + auto-rollback.

Reads the recommendation ledger and reports V2 vs production (hit rate, CLV, Brier,
ECE) cumulatively and at high-conviction tiers, then evaluates the promotion gate
and rollback signal. Promotion is gated to a SIGNAL (status file) rather than auto-
touching the live paid product; flipping live serving stays an explicit action.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from wnba_v2 import config as C
from wnba_v2.tracker import versions as V
from wnba_v2.tracker.ledger import load_ledger

DASH_JSON = C.OUTPUTS / "tracker" / "dashboard.json"
DASH_MD = C.OUTPUTS / "tracker" / "DASHBOARD.md"
PROMO_STATUS = C.OUTPUTS / "tracker" / "promotion_status.json"

BREAKEVEN = C.BREAKEVEN_MINUS_110
MIN_SAMPLE = 300           # min graded high-conviction bets before promotion is eligible
CONVICTION_TIERS = [0.20, 0.25, 0.30]


def _wilson(w, n, z=1.96):
    if n == 0:
        return (float("nan"), float("nan"))
    p = w / n
    d = 1 + z**2 / n
    c = (p + z**2 / (2 * n)) / d
    h = z * np.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / d
    return (round(c - h, 4), round(c + h, 4))


def _brier(p, y):
    p, y = np.asarray(p, float), np.asarray(y, float)
    return float(np.mean((p - y) ** 2)) if len(p) else float("nan")


def _ece(p, y, bins=10):
    p, y = np.asarray(p, float), np.asarray(y, float)
    if len(p) == 0:
        return float("nan")
    idx = np.clip(np.digitize(p, np.linspace(0, 1, bins + 1)) - 1, 0, bins - 1)
    return float(sum((idx == b).mean() * abs(p[idx == b].mean() - y[idx == b].mean())
                     for b in range(bins) if (idx == b).any()))


def _side_metrics(df: pd.DataFrame, who: str) -> dict:
    """who in {'v2','prod'}. Uses graded rows only."""
    g = df[df["result"].isin(["win", "loss"])] if who == "v2" else \
        df[df["prod_result"].isin(["win", "loss"])]
    n = len(g)
    if n == 0:
        return {"n": 0}
    if who == "v2":
        w = int((g["result"] == "win").sum()); p_over = g["p_over"]; clv = g["realized_clv"]
    else:
        w = int((g["prod_result"] == "win").sum()); p_over = g["prod_p_over"]; clv = pd.Series([np.nan])
    lo, hi = _wilson(w, n)
    return {"n": n, "hit_rate": round(w / n, 4), "ci95": [lo, hi],
            "brier": round(_brier(p_over, g["actual_over"]), 4),
            "ece": round(_ece(p_over, g["actual_over"]), 4),
            "mean_clv": round(float(clv.dropna().mean()), 3) if clv.notna().any() else None}


def _high_conviction(df: pd.DataFrame) -> list[dict]:
    out = []
    g = df[df["result"].isin(["win", "loss"])]
    for thr in CONVICTION_TIERS:
        s = g[g["conviction"] >= thr]
        n = len(s)
        if n == 0:
            out.append({"tier": thr, "n": 0}); continue
        w = int((s["result"] == "win").sum())
        lo, hi = _wilson(w, n)
        out.append({"tier": thr, "n": n, "hit_rate": round(w / n, 4), "ci95": [lo, hi],
                    "mean_clv": round(float(s["realized_clv"].dropna().mean()), 3)
                    if s["realized_clv"].notna().any() else None,
                    "ci_above_breakeven": bool(lo > BREAKEVEN)})
    return out


def _gate(v2: dict, prod: dict, hi: list[dict], combos_v2_b, combos_prod_b) -> dict:
    primary = next((t for t in hi if t.get("n", 0) >= MIN_SAMPLE), None)
    sample_ok = primary is not None
    hit_sig = bool(primary and primary["ci_above_breakeven"])
    clv_ok = bool(primary and primary.get("mean_clv") is not None and primary["mean_clv"] > 0)
    calib_ok = bool(v2.get("brier") is not None and prod.get("brier") is not None
                    and v2["brier"] <= prod["brier"])
    combos_ok = bool(combos_v2_b is not None and combos_prod_b is not None
                     and combos_v2_b < combos_prod_b)
    promote = bool(sample_ok and hit_sig and clv_ok and calib_ok and combos_ok)
    # rollback: V2 calibration regressed vs production OR high-conv CLV turned negative
    rollback = bool((v2.get("brier") and prod.get("brier") and v2["brier"] > prod["brier"])
                    or (primary and primary.get("mean_clv") is not None and primary["mean_clv"] < -0.05))
    decision = "PROMOTE" if promote else ("ROLLBACK_CANDIDATE" if rollback else "COLLECTING")
    return {
        "decision": decision,
        "min_sample_met": sample_ok, "primary_tier": primary,
        "hit_significant_above_breakeven": hit_sig, "clv_positive": clv_ok,
        "calibration_superior_to_prod": calib_ok, "combos_superior_to_prod": combos_ok,
        "criteria_remaining": [k for k, ok in {
            "min_sample": sample_ok, "hit_significance": hit_sig, "positive_clv": clv_ok,
            "calibration": calib_ok, "combos": combos_ok}.items() if not ok],
        "note": "PROMOTE is a signal; flipping live serving is an explicit guarded action.",
    }


def _phase55_summary() -> dict | None:
    try:
        from wnba_v2.diagnostics.phase55_comparison import run as phase55_run
        return phase55_run()
    except Exception as exc:
        return {"error": str(exc)}


def run() -> dict:
    led = load_ledger()
    v2 = _side_metrics(led, "v2")
    prod = _side_metrics(led, "prod")
    hi = _high_conviction(led)
    combo_mask = led["market"].isin(["pa", "pr", "ra", "pra"]) & led["result"].isin(["win", "loss"])
    cb = led[combo_mask]
    combos_v2_b = round(_brier(cb["p_over"], cb["actual_over"]), 4) if len(cb) else None
    combos_prod_b = round(_brier(cb["prod_p_over"], cb["actual_over"]), 4) if len(cb) else None
    phase55 = _phase55_summary()
    gate = _gate(v2, prod, hi, combos_v2_b, combos_prod_b)

    by_market = []
    for m, s in led[led["result"].isin(["win", "loss"])].groupby("market"):
        w = int((s["result"] == "win").sum())
        by_market.append({"market": m, "n": len(s), "v2_hit": round(w / len(s), 4),
                          "prod_hit": round((s["prod_result"] == "win").mean(), 4)})

    dash = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "versions": V.current(),
        "graded_recommendations": int(led["result"].isin(["win", "loss"]).sum()),
        "v2_overall": v2, "production_overall": prod,
        "combos": {"v2_brier": combos_v2_b, "prod_brier": combos_prod_b, "n": int(len(cb))},
        "high_conviction": hi, "by_market": by_market, "phase55_comparison": phase55, "gate": gate,
    }
    DASH_JSON.parent.mkdir(parents=True, exist_ok=True)
    DASH_JSON.write_text(json.dumps(dash, indent=2, default=str))
    PROMO_STATUS.write_text(json.dumps({"decision": gate["decision"], "versions": V.current(),
                                        "updated": dash["generated"],
                                        "criteria_remaining": gate["criteria_remaining"]}, indent=2))
    _write_md(dash)
    return dash


def _write_md(d: dict):
    v2, pr, g = d["v2_overall"], d["production_overall"], d["gate"]
    phase55 = d.get("phase55_comparison") or {}
    phase55_section = ""
    if phase55 and not phase55.get("error"):
        overall_lines = []
        for row in phase55.get("overall", []):
            overall_lines.append(
                f"| {row.get('engine')} | {row.get('n')} | {row.get('hit_rate')} | {row.get('brier')} | {row.get('ece')} | {row.get('combo_brier')} |"
            )
        today_lines = []
        for row in phase55.get("markets_changed_most_today", [])[:10]:
            today_lines.append(
                f"| {row.get('stat')} | {row.get('n')} | {row.get('mean_v2')} | {row.get('mean_production')} | {row.get('mean_delta_v2_minus_production')} | {row.get('mean_abs_delta')} |"
            )
        point_ra = json.dumps(phase55.get("points_ra_weakness", {}), indent=2, default=str)
        phase55_section = f"""
## Phase 5.5: Old V2 vs Conserved V2 vs Production
| Engine | n | Hit Rate | Brier | ECE | Combo Brier |
|---|---:|---:|---:|---:|---:|
{chr(10).join(overall_lines)}

### Today's Board: Largest Projection Changes
| Stat | n | Conserved V2 Mean | Production Mean | Mean Delta | Mean Abs Delta |
|---|---:|---:|---:|---:|---:|
{chr(10).join(today_lines)}

### Points / RA Weakness
```json
{point_ra}
```

### Conserved-Simulator Recommendation
{phase55.get('recommendation')}

Report: {phase55.get('artifacts', {}).get('report')}
"""
    elif phase55 and phase55.get("error"):
        phase55_section = f"""
## Phase 5.5 Comparison
Phase 5.5 comparison failed: `{phase55.get('error')}`
"""
    md = f"""# WNBA V2 Parallel Tracker — Dashboard

Generated: {d['generated']}
Versions: {d['versions']}
Graded recommendations: **{d['graded_recommendations']}**

## Cumulative: Conserved V2 vs Production
| Metric | Conserved V2 | Production |
|---|---|---|
| Hit rate | {v2.get('hit_rate')} (CI {v2.get('ci95')}) | {pr.get('hit_rate')} (CI {pr.get('ci95')}) |
| Brier | {v2.get('brier')} | {pr.get('brier')} |
| ECE | {v2.get('ece')} | {pr.get('ece')} |
| Mean CLV | {v2.get('mean_clv')} | {pr.get('mean_clv')} |

## Combo markets (PA/PR/RA/PRA)
Conserved V2 Brier {d['combos']['v2_brier']} vs Production {d['combos']['prod_brier']} (n={d['combos']['n']})

## High-conviction tiers (Conserved V2)
| Tier | n | Hit | CI95 | CLV | CI > 52.4%? |
|---|---|---|---|---|---|
""" + "".join(
        f"| ≥{t['tier']} | {t.get('n')} | {t.get('hit_rate')} | {t.get('ci95')} | {t.get('mean_clv')} | {t.get('ci_above_breakeven')} |\n"
        for t in d["high_conviction"]) + phase55_section + f"""
## Promotion gate: **{g['decision']}**
- min sample met: {g['min_sample_met']} | hit significant > breakeven: {g['hit_significant_above_breakeven']}
- CLV positive: {g['clv_positive']} | calibration superior: {g['calibration_superior_to_prod']} | combos superior: {g['combos_superior_to_prod']}
- criteria remaining: {g['criteria_remaining']}
- {g['note']}
"""
    DASH_MD.write_text(md)


if __name__ == "__main__":
    d = run()
    print(json.dumps({"versions": d["versions"], "graded": d["graded_recommendations"],
                      "v2_overall": d["v2_overall"], "production_overall": d["production_overall"],
                      "combos": d["combos"], "high_conviction": d["high_conviction"],
                      "gate": d["gate"]}, indent=2, default=str))
    print(f"\nDashboard -> {DASH_MD}")
