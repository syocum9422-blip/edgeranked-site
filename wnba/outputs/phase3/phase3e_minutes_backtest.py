"""Phase 3E (primary gate): leakage-free shadow minutes backtest.

Isolates the FEATURE change. For each window (7/14/30d ending at the last log date) we train
two models with the SAME cutoff and data, differing only in features:
  - BASELINE  : production feature_columns() (minus 'minutes')
  - ENHANCED  : baseline + rolling-minutes features (+ rotation features merged in)
Train on game_date < cutoff; evaluate minutes MAE/RMSE/bias on game_date >= cutoff.

Writes:
  - minutes_backtest_results.csv
  - shadow_minutes_predictions.csv   (per validation row, both models — feeds secondary gate)
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
import joblib

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # wnba root on path
from wnba_model_utils import feature_columns, build_regression_pipeline, clean_feature_frame  # noqa: E402

PROD_MODEL = Path(__file__).resolve().parents[2] / "models" / "wnba_minutes_model.joblib"

HERE = Path(__file__).resolve().parent
WNBA = HERE.parents[1]
SHADOW_DS = HERE / "shadow" / "wnba_training_dataset_2026.csv"
ROTATION = HERE / "reports" / "rotation_features.csv"
OUT = HERE / "reports"

ROLLING_MIN_FEATS = [
    "minutes_rolling_mean_3", "minutes_rolling_std_3",
    "minutes_rolling_mean_5", "minutes_rolling_std_5",
    "minutes_rolling_mean_10", "minutes_rolling_std_10",
]
ROTATION_FEATS = ["starts_last_10", "consec_starts", "consec_bench", "minutes_trend", "usage_trend"]
WINDOWS = [7, 14, 30]


def load_data() -> pd.DataFrame:
    ds = pd.read_csv(SHADOW_DS, low_memory=False)
    ds["game_date"] = pd.to_datetime(ds["game_date"], errors="coerce")
    ds["player_key"] = ds["player_name"].astype(str).str.lower().str.strip()
    rot = pd.read_csv(ROTATION)
    rot["game_date"] = pd.to_datetime(rot["game_date"], errors="coerce")
    rot["player_key"] = rot["player_name"].astype(str).str.lower().str.strip()
    ds = ds.merge(rot[["player_key", "game_date", *ROTATION_FEATS]],
                  on=["player_key", "game_date"], how="left")
    return ds


def fit_predict(train, valid, feats):
    X_tr = clean_feature_frame(train, feats)
    y_tr = train["minutes"].astype(float)
    ridge, tree, _, _ = build_regression_pipeline(X_tr)
    ridge.fit(X_tr, y_tr)
    tree.fit(X_tr, y_tr)
    Xv = clean_feature_frame(valid, feats)
    pred = np.clip((np.clip(ridge.predict(Xv), 0, None) + np.clip(tree.predict(Xv), 0, None)) / 2.0, 0, None)
    return pred


def metrics(y, p):
    e = np.asarray(p) - np.asarray(y)
    return {"mae": float(np.abs(e).mean()), "rmse": float(math.sqrt((e ** 2).mean())), "bias": float(e.mean())}


def prod_predict(valid):
    """Live production (stale) model prediction — the true 'before'."""
    b = joblib.load(PROD_MODEL)
    feats = b["feature_list"]
    Xv = clean_feature_frame(valid, feats)
    r = np.clip(b["ridge_model"].predict(Xv), 0, None)
    t = np.clip(b["tree_model"].predict(Xv), 0, None)
    return np.clip((r + t) / 2.0, 0, None)


def main():
    ds = load_data().dropna(subset=["minutes"]).copy()
    last_date = ds["game_date"].max()
    base_feats = [c for c in feature_columns() if c != "minutes"]
    variants = {
        "B_retrain_base": base_feats,
        "C_plus_rolling_min": base_feats + ROLLING_MIN_FEATS,
        "D_plus_rolling_rotation": base_feats + ROLLING_MIN_FEATS + ROTATION_FEATS,
    }

    results = []
    all_preds = []
    for w in WINDOWS:
        cutoff = last_date - pd.Timedelta(days=w - 1)
        train = ds[ds["game_date"] < cutoff].copy()
        valid = ds[ds["game_date"] >= cutoff].copy()
        if valid.empty or train.empty:
            continue
        yv = valid["minutes"].astype(float).values
        preds = {"A_live_production": prod_predict(valid)}
        for name, feats in variants.items():
            preds[name] = fit_predict(train, valid, feats)

        row = {"window_days": w, "cutoff": cutoff.date(), "train_rows": len(train), "valid_rows": len(valid)}
        for name, p in preds.items():
            m = metrics(yv, p)
            row[f"{name}_mae"] = round(m["mae"], 4)
            row[f"{name}_rmse"] = round(m["rmse"], 4)
            row[f"{name}_bias"] = round(m["bias"], 4)
        results.append(row)

        v = valid[["player_key", "player_name", "team", "opponent", "game_date", "minutes"]].copy()
        v["window_days"] = w
        for name, p in preds.items():
            v[f"pred_{name}"] = p
        all_preds.append(v)

    res = pd.DataFrame(results)
    res.to_csv(OUT / "minutes_backtest_results.csv", index=False)
    pd.concat(all_preds, ignore_index=True).to_csv(OUT / "shadow_minutes_predictions.csv", index=False)

    print(f"last log date: {last_date.date()}")
    print("\n=== Minutes backtest MAE by variant ===")
    mae_cols = ["window_days", "valid_rows", "A_live_production_mae", "B_retrain_base_mae",
                "C_plus_rolling_min_mae", "D_plus_rolling_rotation_mae"]
    print(res[mae_cols].to_string(index=False))
    print("\n=== Minutes backtest RMSE by variant ===")
    rmse_cols = ["window_days", "A_live_production_rmse", "B_retrain_base_rmse",
                 "C_plus_rolling_min_rmse", "D_plus_rolling_rotation_rmse"]
    print(res[rmse_cols].to_string(index=False))
    print("\n=== Bias by variant ===")
    bias_cols = ["window_days", "A_live_production_bias", "B_retrain_base_bias",
                 "C_plus_rolling_min_bias", "D_plus_rolling_rotation_bias"]
    print(res[bias_cols].to_string(index=False))


if __name__ == "__main__":
    main()
