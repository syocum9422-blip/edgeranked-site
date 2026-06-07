"""Phase 3E (secondary gates): propagate shadow minutes -> bet probabilities.

The shadow change is upstream of betting probabilities. Counting-stat projections scale
~linearly with minutes, so for each graded bet we:
  1. infer the implied sigma from (projection_mean, line, side, hit_rate) via a normal model,
  2. rescale the mean by (shadow_minutes / production_minutes),
  3. recompute the hit probability with the same sigma,
then compute Brier / log-loss / accuracy / coverage(>=0.56) vs the realized bet_result.

Assumption (documented): minutes is a multiplicative scaler on counting stats and sigma is
unchanged. This is a first-order estimate of the downstream effect, not a full re-simulation.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm

HERE = Path(__file__).resolve().parent
WNBA = HERE.parents[1]
GRADED = WNBA / "Best_Bets" / "graded_bets.csv"
SHADOW_PRED = HERE / "reports" / "shadow_minutes_predictions.csv"
OUT = HERE / "reports"
EPS = 1e-6
COVERAGE_THRESHOLD = 0.56


def load_graded():
    g = pd.read_csv(GRADED)
    g.columns = [c.lower() for c in g.columns]
    g = g.loc[:, ~g.columns.duplicated()].copy()  # file has both lower/UPPER duplicates
    g["bet_date"] = pd.to_datetime(g["bet_date"], errors="coerce").dt.normalize()
    g["player_key"] = g["player_name"].astype(str).str.lower().str.strip()
    for c in ["line", "hit_rate", "projection_mean", "projected_minutes"]:
        g[c] = pd.to_numeric(g[c], errors="coerce")
    g["side"] = g["side"].astype(str).str.lower().str.strip()
    g["bet_result"] = g["bet_result"].astype(str).str.lower().str.strip()
    g["result_binary"] = np.where(g["bet_result"] == "win", 1.0,
                                  np.where(g["bet_result"] == "loss", 0.0, np.nan))
    return g


def infer_sigma(mean, line, side, p):
    """Recover sigma so that modeled P(bet hits) == observed hit_rate p."""
    p = min(max(p, 0.02), 0.98)
    z = norm.ppf(p)  # P(hit)=p -> z for the hit tail
    # For 'over': p = P(X>line) = 1-Φ((line-mean)/σ) = Φ((mean-line)/σ) -> (mean-line)/σ = z
    # For 'under': p = P(X<line) = Φ((line-mean)/σ) -> (line-mean)/σ = z
    num = (mean - line) if side == "over" else (line - mean)
    if abs(z) < 1e-3:
        return None
    sigma = num / z
    if not np.isfinite(sigma) or sigma <= 0.5:
        return None
    return sigma


def recompute_prob(new_mean, line, side, sigma):
    if side == "over":
        p = 1 - norm.cdf((line - new_mean) / sigma)
    else:
        p = norm.cdf((line - new_mean) / sigma)
    return float(min(max(p, EPS), 1 - EPS))


def metrics(df, prob_col):
    r = df.dropna(subset=["result_binary"])
    y = r["result_binary"].values
    p = r[prob_col].clip(EPS, 1 - EPS).values
    brier = float(np.mean((p - y) ** 2))
    logloss = float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
    # win-rate of bets that still qualify at >=0.56 (forward-looking selection quality)
    q = r[r[prob_col] >= COVERAGE_THRESHOLD]
    qual_winrate = float(q["result_binary"].mean()) if len(q) else float("nan")
    return {"n_resolved": int(len(r)),
            "placed_winrate": round(float(y.mean()), 4),  # fixed: same resolved bets
            "brier": round(brier, 4), "log_loss": round(logloss, 4),
            "coverage_at_56": int((df[prob_col] >= COVERAGE_THRESHOLD).sum()),
            "qualified_winrate_at_56": round(qual_winrate, 4)}


def main():
    g = load_graded()
    pred = pd.read_csv(SHADOW_PRED)
    pred = pred[pred["window_days"] == 30].copy()  # 30d window spans the full graded period
    pred["game_date"] = pd.to_datetime(pred["game_date"], errors="coerce").dt.normalize()
    pred = pred[["player_key", "game_date", "pred_A_live_production", "pred_C_plus_rolling_min"]]

    m = g.merge(pred, left_on=["player_key", "bet_date"], right_on=["player_key", "game_date"], how="left")
    matched = m["pred_C_plus_rolling_min"].notna()
    print(f"graded bets: {len(g)} | matched to shadow minutes: {matched.sum()} ({matched.mean():.0%})")

    # production minutes baseline = the minutes actually used in production (projected_minutes),
    # falling back to the model's A prediction.
    m["prod_min"] = m["projected_minutes"].fillna(m["pred_A_live_production"])
    m["shadow_min"] = m["pred_C_plus_rolling_min"]

    rows = []
    for _, r in m.iterrows():
        base_p = r["hit_rate"]
        out = {"baseline_prob": base_p, "shadow_prob": base_p}
        if (pd.notna(r["shadow_min"]) and pd.notna(r["prod_min"]) and r["prod_min"] > 1
                and pd.notna(r["projection_mean"]) and pd.notna(r["line"]) and pd.notna(base_p)):
            sigma = infer_sigma(r["projection_mean"], r["line"], r["side"], base_p)
            if sigma is not None:
                scale = np.clip(r["shadow_min"] / r["prod_min"], 0.4, 2.0)
                new_mean = r["projection_mean"] * scale
                out["shadow_prob"] = recompute_prob(new_mean, r["line"], r["side"], sigma)
        rows.append(out)
    pr = pd.DataFrame(rows, index=m.index)
    m["baseline_prob"] = pr["baseline_prob"]
    m["shadow_prob"] = pr["shadow_prob"]

    mb = metrics(m, "baseline_prob")
    ms = metrics(m, "shadow_prob")
    summary = pd.DataFrame([{"variant": "baseline(production)", **mb},
                            {"variant": "shadow(C_rolling_min)", **ms}])
    summary.to_csv(OUT / "secondary_gates_results.csv", index=False)
    changed = (m["baseline_prob"] != m["shadow_prob"]).sum()
    print(f"\nbets with probability changed by shadow minutes: {changed}")
    print("\n=== Secondary gates: baseline vs shadow (propagated) ===")
    print(summary.to_string(index=False))
    cov_delta = (ms["coverage_at_56"] - mb["coverage_at_56"]) / mb["coverage_at_56"] * 100 if mb["coverage_at_56"] else 0
    print(f"\ncoverage change at 0.56: {mb['coverage_at_56']} -> {ms['coverage_at_56']} ({cov_delta:+.1f}%)")

    # Threshold sweep: what shadow threshold restores coverage / how win-rate trades off.
    print("\n=== Shadow coverage/quality vs selection threshold ===")
    res = m.dropna(subset=["result_binary"])
    sweep = []
    for thr in [0.50, 0.52, 0.54, 0.56, 0.58, 0.60]:
        q = res[res["shadow_prob"] >= thr]
        sweep.append({"threshold": thr, "shadow_n": int((m["shadow_prob"] >= thr).sum()),
                      "qualified_winrate": round(float(q["result_binary"].mean()), 4) if len(q) else float("nan")})
    sweep_df = pd.DataFrame(sweep)
    sweep_df["baseline_n_at_0.56"] = mb["coverage_at_56"]
    sweep_df.to_csv(OUT / "secondary_gates_coverage_sweep.csv", index=False)
    print(sweep_df.to_string(index=False))


if __name__ == "__main__":
    main()
