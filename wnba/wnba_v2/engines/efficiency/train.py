"""Phase 4 — efficiency models walk-forward validation.

Validates rate accuracy, distribution CALIBRATION (coverage), tail behavior, and
robustness on rookie / low-minute slices; reports feature importance + drift; and
persists per-row mean/std/quantiles for every rate so Phase 5 can sample directly.

Per requirement 10 this does NOT promote — final promotion waits until the rates
are integrated into the simulator and combo-market calibration is measured (Phase 5).

Run:  .venv/bin/python -m wnba_v2.engines.efficiency.train
"""
from __future__ import annotations

import json

import joblib
import numpy as np
import pandas as pd
from sklearn.inspection import permutation_importance
from sklearn.metrics import mean_absolute_error

from wnba_v2 import config as C
from wnba_v2.engines.efficiency.bayes_model import BetaBinomial3P, GammaPoissonRate
from wnba_v2.engines.efficiency.gbm_model import QUANTILES, RateGBM
from wnba_v2.engines.efficiency.rates import GBM_RATES, gbm_features, build_rate_frame

OUT = C.OUTPUTS / "efficiency"


def _psi(a: pd.Series, b: pd.Series, bins: int = 10) -> float:
    a, b = a.dropna(), b.dropna()
    if len(a) < 50 or len(b) < 50:
        return float("nan")
    edges = np.quantile(a, np.linspace(0, 1, bins + 1))
    edges[0], edges[-1] = -np.inf, np.inf
    pa = np.histogram(a, edges)[0] / len(a) + 1e-6
    pb = np.histogram(b, edges)[0] / len(b) + 1e-6
    return float(np.sum((pb - pa) * np.log(pb / pa)))


def _bayes_model(name):
    if name == "fg3_pct":
        return BetaBinomial3P()
    return GammaPoissonRate(name=name, num_cum=f"cum_{ {'steals':'stl','blocks':'blk'}[name] }")


def walk_forward(df: pd.DataFrame) -> dict:
    seasons = sorted(df["season"].dropna().unique())
    gbm_rows, bayes_rows, cov_acc = [], [], {r: [] for r in GBM_RATES}
    for ts in seasons[1:]:
        tr = df[df["season"] < ts]
        te = df[df["season"] == ts].copy()
        if len(tr) < 500 or len(te) < 200:
            continue
        # ---- GBM rates ----
        for name in GBM_RATES:
            tr_n = tr.dropna(subset=[f"rate_{name}", f"{name}_lag5"])
            sub = te.dropna(subset=[f"rate_{name}"]).copy()
            m = RateGBM(name).fit(tr_n)
            pred = m.predict(sub)
            y = sub[f"rate_{name}"].values
            naive = sub[f"{name}_lag5"].fillna(tr_n[f"rate_{name}"].median()).values
            rec = {"rate": name, "season": int(ts), "n": len(sub),
                   "mae_model": round(mean_absolute_error(y, pred[f"{name}_mean"]), 4),
                   "mae_naive": round(mean_absolute_error(y, naive), 4),
                   "pct_above_q90": round(float((y > pred["q90"]).mean()), 4),
                   "pct_below_q10": round(float((y < pred["q10"]).mean()), 4)}
            rec["impr_vs_naive_pct"] = round((rec["mae_naive"] - rec["mae_model"])
                                             / rec["mae_naive"] * 100, 2)
            # rookie / low-minute slices
            for slc, mask in [("rookie", sub["prior_games"] < 10), ("low_min", sub["minutes"] < 15)]:
                if mask.sum() > 30:
                    rec[f"mae_model_{slc}"] = round(mean_absolute_error(
                        y[mask.values], pred[f"{name}_mean"].values[mask.values]), 4)
                    rec[f"mae_naive_{slc}"] = round(mean_absolute_error(
                        y[mask.values], naive[mask.values]), 4)
            gbm_rows.append(rec)
            for q in QUANTILES:
                cov_acc[name].append((q, float((y <= pred[f"q{int(q*100)}"]).mean()), len(sub)))
        # ---- Bayesian rates ----
        for name in ["steals", "blocks", "fg3_pct"]:
            sub = te.dropna(subset=[f"rate_{name}"]).copy()
            m = _bayes_model(name).fit(tr.dropna(subset=[f"rate_{name}"]))
            pred = m.predict(sub)
            y = sub[f"rate_{name}"].values
            naive = sub[f"{name}_lag5"].fillna(tr[f"rate_{name}"].mean()).values
            lo = pred[f"{name}_mean"] - 1.96 * pred[f"{name}_std"]
            hi = pred[f"{name}_mean"] + 1.96 * pred[f"{name}_std"]
            bayes_rows.append({
                "rate": name, "season": int(ts), "n": len(sub),
                "mae_model": round(mean_absolute_error(y, pred[f"{name}_mean"]), 4),
                "mae_naive": round(mean_absolute_error(y, naive), 4),
                "cov95": round(float(((y >= lo) & (y <= hi)).mean()), 4)})
    # pooled coverage per GBM rate (calibration)
    coverage = {}
    for name, recs in cov_acc.items():
        by_q = {}
        for q, c, n in recs:
            by_q.setdefault(q, []).append(c)
        coverage[name] = {f"q{int(q*100)}_cov": round(float(np.mean(v)), 3) for q, v in by_q.items()}
    return {"gbm": pd.DataFrame(gbm_rows), "bayes": pd.DataFrame(bayes_rows), "coverage": coverage}


def feature_importance(df: pd.DataFrame) -> dict:
    out = {}
    tr = df[df["season"] < max(df["season"].dropna())]
    for name in GBM_RATES:
        sub = tr.dropna(subset=[f"rate_{name}", f"{name}_lag5"]).sample(
            min(3000, len(tr)), random_state=0)
        feats = gbm_features(name)
        m = RateGBM(name).fit(sub)
        med = m.qmodels[0.5]
        pi = permutation_importance(med, sub[feats], sub[f"rate_{name}"],
                                    n_repeats=3, random_state=0, scoring="neg_mean_absolute_error")
        order = np.argsort(pi.importances_mean)[::-1][:5]
        out[name] = {feats[i]: round(float(pi.importances_mean[i]), 5) for i in order}
    return out


def run() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    df = build_rate_frame()
    res = walk_forward(df)
    fi = feature_importance(df)
    drift = {}
    seasons = sorted(df["season"].dropna().unique())
    if len(seasons) >= 2:
        first, last = df[df.season == seasons[0]], df[df.season == seasons[-1]]
        for name in GBM_RATES + ["steals", "blocks", "fg3_pct"]:
            drift[f"psi_{name}_lag5"] = round(_psi(first[f"{name}_lag5"], last[f"{name}_lag5"]), 4)

    summary = {
        "n_rows": int(len(df)),
        "gbm_pooled": res["gbm"].groupby("rate")[["mae_model", "mae_naive", "impr_vs_naive_pct"]]
        .mean().round(4).to_dict("index") if not res["gbm"].empty else {},
        "bayes_pooled": res["bayes"].groupby("rate")[["mae_model", "mae_naive", "cov95"]]
        .mean().round(4).to_dict("index") if not res["bayes"].empty else {},
        "gbm_calibration_coverage": res["coverage"],
        "feature_importance_top5": fi,
        "drift_psi_train_to_latest": drift,
        "promotion": "NOT PROMOTED — pending Phase 5 sim integration + combo calibration (req 10)",
    }
    res["gbm"].to_csv(OUT / "gbm_walkforward.csv", index=False)
    res["bayes"].to_csv(OUT / "bayes_walkforward.csv", index=False)
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, default=str))

    # ---- persist final models + per-row uncertainty for Phase 5 ----
    models = {name: RateGBM(name).fit(df.dropna(subset=[f"rate_{name}", f"{name}_lag5"]))
              for name in GBM_RATES}
    for name in ["steals", "blocks", "fg3_pct"]:
        models[name] = _bayes_model(name).fit(df.dropna(subset=[f"rate_{name}"]))
    joblib.dump(models, OUT / "efficiency_models_v2.joblib")

    unc = df[["date", "game_id", "team", "player_id", "player_name", "minutes"]].copy()
    for name in GBM_RATES:
        p = models[name].predict(df)
        unc[f"{name}_mean"] = p[f"{name}_mean"].values
        unc[f"{name}_std"] = p[f"{name}_std"].values
    for name in ["steals", "blocks", "fg3_pct"]:
        p = models[name].predict(df)
        unc[f"{name}_mean"] = p[f"{name}_mean"].values
        unc[f"{name}_std"] = p[f"{name}_std"].values
    unc.to_csv(OUT / "rate_uncertainty.csv", index=False)
    return summary


if __name__ == "__main__":
    s = run()
    print(json.dumps(s, indent=2, default=str))
    print(f"\nArtifacts -> {OUT}")
