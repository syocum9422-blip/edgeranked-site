"""Phase 4B: Threshold optimization on the full re-sim scores.

For thresholds 0.50..0.60, for variants A (production) and C (variant C), on the 30d window:
coverage (plays), accuracy (qualified win-rate), brier/log-loss of selected plays, and an
ROI proxy assuming -110 odds (win = +0.909u, loss = -1u, push = 0).
Determines the threshold that best restores/optimizes coverage & ROI under C.
"""
from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SCORES = HERE / "reports" / "resim_bet_scores.csv"
OUT = HERE / "reports"
THRESHOLDS = [0.50, 0.52, 0.54, 0.56, 0.58, 0.60]
EPS = 1e-6
WIN_PAYOUT = 100 / 110  # -110 odds


def roi_proxy(df):
    w = (df["bet_result"] == "win").sum()
    l = (df["bet_result"] == "loss").sum()
    n = w + l
    if n == 0:
        return np.nan
    return round((w * WIN_PAYOUT - l) / n, 4)


def block(g, col, label):
    rows = []
    for thr in THRESHOLDS:
        sel = g[g[col] >= thr]
        res = sel.dropna(subset=["result_binary"])
        y = res["result_binary"].values
        p = np.clip(res[col].values, EPS, 1 - EPS)
        rows.append({
            "variant": label, "threshold": thr, "coverage": int(len(sel)),
            "n_resolved": int(len(res)),
            "qualified_winrate": round(float(y.mean()), 4) if len(y) else np.nan,
            "brier": round(float(np.mean((p - y) ** 2)), 4) if len(y) else np.nan,
            "log_loss": round(float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))), 4) if len(y) else np.nan,
            "roi_proxy": roi_proxy(res),
        })
    return rows


def main():
    g = pd.read_csv(SCORES)
    g["bet_date"] = pd.to_datetime(g["bet_date"], errors="coerce")
    last = g["bet_date"].max()
    g30 = g[g["bet_date"] >= last - pd.Timedelta(days=29)].copy()

    rows = block(g30, "hit_rate_A", "A_production") + block(g30, "hit_rate_C_w30", "C_variant")
    tbl = pd.DataFrame(rows)
    tbl.to_csv(OUT / "threshold_optimization.csv", index=False)

    base_cov = int((g30["hit_rate_A"] >= 0.56).sum())  # production baseline coverage at 0.56
    # recovery: smallest C threshold whose coverage is within 5% of baseline AND best ROI
    c = tbl[tbl["variant"] == "C_variant"].copy()
    c["cov_vs_base_pct"] = (c["coverage"] - base_cov) / base_cov * 100
    within5 = c[c["cov_vs_base_pct"].abs() <= 5]
    rec = within5.sort_values("roi_proxy", ascending=False).head(1)

    print("=== Threshold optimization (30d window, full re-sim) ===")
    print(tbl.to_string(index=False))
    print(f"\nproduction baseline coverage @0.56 = {base_cov}")
    print("\nVariant C coverage vs baseline by threshold:")
    print(c[["threshold", "coverage", "cov_vs_base_pct", "qualified_winrate", "brier", "roi_proxy"]].to_string(index=False))
    if len(rec):
        r = rec.iloc[0]
        print(f"\nRecommended C threshold (coverage within 5% of baseline, max ROI): "
              f"{r['threshold']} -> coverage {int(r['coverage'])} ({r['cov_vs_base_pct']:+.1f}%), "
              f"winrate {r['qualified_winrate']}, ROI {r['roi_proxy']}")
    pd.DataFrame([{
        "production_baseline_coverage_56": base_cov,
        "recommended_C_threshold": float(rec.iloc[0]["threshold"]) if len(rec) else 0.56,
        "recommended_C_coverage": int(rec.iloc[0]["coverage"]) if len(rec) else int(c[c.threshold == 0.56]["coverage"].iloc[0]),
    }]).to_csv(OUT / "recommended_threshold.csv", index=False)


if __name__ == "__main__":
    main()
