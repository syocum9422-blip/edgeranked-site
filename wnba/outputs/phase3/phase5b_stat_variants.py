"""Phase 5B/5C: minutes-aware stat-projection variants (shadow, temporal validation).

Variants (stat TOTAL projection per market):
  A  production stat model, `minutes` feature = leakage-free recent rolling avg (no model minutes)
  B  production stat model, `minutes` feature = projected_minutes (Variant-C minutes model)
  C  per-minute RATE model (target = stat/minutes), total = rate_pred * projected_minutes
  D  hybrid = 0.5*B + 0.5*C

Minutes model = Phase-3 Variant C (retrain incl 2026 + rolling-minutes feats), trained < cutoff.
Eval per window (7/14/30d): Projection MAE/RMSE pooled + per-market, leakage-free.
Saves per-row stat projections for the betting re-sim (phase5c).
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

WNBA = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WNBA))
from wnba_model_utils import feature_columns, build_regression_pipeline, clean_feature_frame  # noqa

HERE = Path(__file__).resolve().parent
SHADOW_DS = HERE / "shadow" / "wnba_training_dataset_2026.csv"
STAT_DIR = WNBA / "data" / "models"
OUT = HERE / "reports"
STATS = ["points", "rebounds", "assists", "threes_made", "steals", "blocks"]
WINDOWS = [7, 14, 30]
ROLL_MIN = ["minutes_rolling_mean_3", "minutes_rolling_std_3", "minutes_rolling_mean_5",
            "minutes_rolling_std_5", "minutes_rolling_mean_10", "minutes_rolling_std_10"]
MIN_FEATS = [c for c in feature_columns() if c != "minutes"] + ROLL_MIN
STAT_FEATS = [c for c in feature_columns()]  # includes 'minutes'
RATE_FEATS = [c for c in feature_columns() if c != "minutes"]  # rate model: drop raw minutes


def train_minutes(ds, cutoff):
    tr = ds[ds["game_date"] < cutoff].dropna(subset=["minutes"])
    X = clean_feature_frame(tr, MIN_FEATS); y = tr["minutes"].astype(float)
    r, t, _, _ = build_regression_pipeline(X); r.fit(X, y); t.fit(X, y)
    return {"ridge_model": r, "tree_model": t, "feature_list": MIN_FEATS}


def predict_bundle(bundle, frame):
    X = clean_feature_frame(frame, bundle["feature_list"])
    r = np.clip(bundle["ridge_model"].predict(X), 0, None)
    t = np.clip(bundle["tree_model"].predict(X), 0, None)
    return np.clip((r + t) / 2, 0, None)


def train_rate_model(ds, stat, cutoff):
    tr = ds[(ds["game_date"] < cutoff) & (ds["minutes"] >= 8)].dropna(subset=[stat, "minutes"]).copy()
    tr["__rate"] = tr[stat] / tr["minutes"]
    X = clean_feature_frame(tr, RATE_FEATS); y = tr["__rate"].clip(0, None)
    r, t, _, _ = build_regression_pipeline(X); r.fit(X, y); t.fit(X, y)
    return {"ridge_model": r, "tree_model": t, "feature_list": RATE_FEATS}


def metrics(pred, actual):
    e = np.asarray(pred) - np.asarray(actual)
    return float(np.abs(e).mean()), float(math.sqrt((e ** 2).mean()))


def main():
    ds = pd.read_csv(SHADOW_DS, low_memory=False)
    ds["game_date"] = pd.to_datetime(ds["game_date"], errors="coerce")
    ds["player_key"] = ds["player_name"].astype(str).str.lower().str.strip()
    stat_models = {s: joblib.load(STAT_DIR / f"wnba_{s}_model.joblib") for s in STATS}
    last = ds["game_date"].max()

    rows = []
    permarket = []
    all_proj = []
    for w in WINDOWS:
        cutoff = last - pd.Timedelta(days=w - 1)
        val = ds[(ds["game_date"] >= cutoff)].dropna(subset=["minutes"]).copy()
        mins_model = train_minutes(ds, cutoff)
        proj_min = np.clip(predict_bundle(mins_model, val), 5, 40)
        # A's minutes feature = leakage-free recent rolling avg
        roll_min = val["minutes_rolling_mean_5"].fillna(val["season_avg_minutes"]).fillna(15.0).values

        rate_models = {s: train_rate_model(ds, s, cutoff) for s in STATS}

        var_err = {v: {"abs": [], "sq": []} for v in ["A", "B", "C", "D"]}
        out = val[["player_key", "player_name", "team", "opponent", "game_date", "minutes"]].copy()
        out["window_days"] = w
        out["projected_minutes"] = proj_min
        for stat in STATS:
            actual = val[stat].astype(float).values
            fA = val.copy(); fA["minutes"] = roll_min
            fB = val.copy(); fB["minutes"] = proj_min
            tA = predict_bundle(stat_models[stat], fA)
            tB = predict_bundle(stat_models[stat], fB)
            rate = predict_bundle(rate_models[stat], val)
            tC = rate * proj_min
            tD = 0.5 * tB + 0.5 * tC
            for v, pr in [("A", tA), ("B", tB), ("C", tC), ("D", tD)]:
                mask = ~np.isnan(actual)
                e = pr[mask] - actual[mask]
                var_err[v]["abs"].extend(np.abs(e)); var_err[v]["sq"].extend(e ** 2)
                out[f"{stat}_proj_{v}"] = pr
                if v == "A":
                    a_mae, a_rmse = metrics(pr[mask], actual[mask])
                if v in ("A", "B", "C", "D"):
                    mae, rmse = metrics(pr[mask], actual[mask])
                    permarket.append({"window_days": w, "stat": stat, "variant": v,
                                      "mae": round(mae, 4), "rmse": round(rmse, 4)})
            out[f"{stat}_actual"] = actual
        all_proj.append(out)
        for v in ["A", "B", "C", "D"]:
            a = np.array(var_err[v]["abs"]); s = np.array(var_err[v]["sq"])
            rows.append({"window_days": w, "variant": v, "n": len(a),
                         "proj_mae": round(a.mean(), 4), "proj_rmse": round(math.sqrt(s.mean()), 4)})

    res = pd.DataFrame(rows)
    res.to_csv(OUT / "phase5_projection_accuracy.csv", index=False)
    pd.DataFrame(permarket).to_csv(OUT / "phase5_projection_by_market.csv", index=False)
    pd.concat(all_proj, ignore_index=True).to_csv(OUT / "phase5_stat_projections.csv", index=False)

    print("=== Phase 5C: pooled projection accuracy (lower=better) ===")
    piv = res.pivot(index="window_days", columns="variant", values="proj_mae")
    print("Projection MAE by variant:\n", piv.to_string())
    pivr = res.pivot(index="window_days", columns="variant", values="proj_rmse")
    print("\nProjection RMSE by variant:\n", pivr.to_string())
    print("\n=== Per-market MAE (30d) ===")
    pm = pd.DataFrame(permarket)
    pm30 = pm[pm.window_days == 30].pivot(index="stat", columns="variant", values="mae")
    print(pm30.to_string())


if __name__ == "__main__":
    main()
