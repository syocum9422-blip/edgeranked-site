"""Phase 1 — Minutes engine walk-forward training & validation.

Proves the engine beats naive baselines on the metrics that matter for a
DISTRIBUTION: pinball (quantile) loss + coverage calibration, plus point MAE of
the median. Expanding-window walk-forward over the 2026 betting season.

Run:  .venv/bin/python -m wnba_v2.engines.minutes.train
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, roc_auc_score

from wnba_v2 import config as C
from wnba_v2.engines.minutes.features import build_minutes_features
from wnba_v2.engines.minutes.model import QUANTILES, MinutesModel
from wnba_v2.evaluation.metrics import brier_score

DATASET = C.PROD_ROOT / "data" / "processed" / "wnba_training_dataset.csv"
OUT = C.OUTPUTS / "minutes"


def pinball_loss(y: np.ndarray, q_pred: np.ndarray, tau: float) -> float:
    d = y - q_pred
    return float(np.mean(np.maximum(tau * d, (tau - 1) * d)))


def coverage(y: np.ndarray, q_pred: np.ndarray) -> float:
    """Empirical P(y <= q_pred); should equal tau for a calibrated quantile."""
    return float(np.mean(y <= q_pred))


def walk_forward(df: pd.DataFrame, test_months: list[str]) -> dict:
    """Expanding window: for each test month, train on everything strictly before it."""
    df = df.sort_values("game_date")
    fold_rows, all_pred = [], []
    for ym in test_months:
        start = pd.Timestamp(ym + "-01")
        end = start + pd.offsets.MonthEnd(1)
        train = df[df["game_date"] < start]
        test = df[(df["game_date"] >= start) & (df["game_date"] <= end)]
        if len(test) < 50 or len(train) < 500:
            continue
        model = MinutesModel().fit(train)
        played = test[test["minutes"] >= 1].copy()
        q = model.predict_quantiles(played)
        pp = model.predict_play_prob(test)
        y = played["y_minutes"].values

        rec = {"month": ym, "n_train": len(train), "n_test_played": len(played)}
        # Stage B: pinball + coverage per tau
        for tau in QUANTILES:
            col = f"q{int(tau*100)}"
            rec[f"pinball_{col}"] = round(pinball_loss(y, q[col].values, tau), 4)
            rec[f"cov_{col}"] = round(coverage(y, q[col].values), 4)
        rec["pinball_mean"] = round(np.mean([rec[f"pinball_q{int(t*100)}"] for t in QUANTILES]), 4)
        # Point accuracy of the median vs naive baselines
        rec["mae_p50"] = round(mean_absolute_error(y, q["q50"].values), 4)
        rec["mae_naive_mean5"] = round(mean_absolute_error(
            y, played["min_mean5"].fillna(played["min_mean5"].median()).values), 4)
        rec["mae_naive_season"] = round(mean_absolute_error(
            y, played["season_avg_minutes"].fillna(20).values), 4) if "season_avg_minutes" in played else None
        # Stage A: meaningful-minutes classifier quality
        ya = test["y_meaningful"].values
        if len(np.unique(ya)) > 1:
            rec["stageA_auc"] = round(roc_auc_score(ya, pp), 4)
            rec["stageA_brier"] = round(brier_score(ya, pp), 4)
        fold_rows.append(rec)

        pp_played = model.predict_play_prob(played)
        tmp = played[["game_date", "player_key", "minutes", "min_mean5"]].copy()
        for col in q.columns:
            tmp[col] = q[col].values
        tmp["play_prob"] = pp_played
        all_pred.append(tmp)

    folds = pd.DataFrame(fold_rows)
    preds = pd.concat(all_pred) if all_pred else pd.DataFrame()
    return {"folds": folds, "preds": preds}


def summarize(res: dict) -> dict:
    folds, preds = res["folds"], res["preds"]
    if folds.empty:
        return {"error": "no folds produced"}
    # Pooled metrics across all OOS predictions
    pooled = {}
    y = preds["minutes"].values
    for tau in QUANTILES:
        col = f"q{int(tau*100)}"
        pooled[f"pinball_{col}"] = round(pinball_loss(y, preds[col].values, tau), 4)
        pooled[f"coverage_{col}"] = round(coverage(y, preds[col].values), 4)
        pooled[f"coverage_target_{col}"] = tau
    pooled["pinball_mean"] = round(np.mean([pooled[f"pinball_q{int(t*100)}"] for t in QUANTILES]), 4)
    pooled["mae_p50"] = round(mean_absolute_error(y, preds["q50"].values), 4)
    pooled["mae_naive_mean5"] = round(mean_absolute_error(
        y, preds["min_mean5"].fillna(preds["min_mean5"].median()).values), 4)
    pooled["mae_improvement_vs_naive_pct"] = round(
        (pooled["mae_naive_mean5"] - pooled["mae_p50"]) / pooled["mae_naive_mean5"] * 100, 2)
    return pooled


def run() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    raw = pd.read_csv(DATASET, parse_dates=["game_date"])
    df = build_minutes_features(raw)
    # 2026 WNBA season test months (matches the betting window).
    season_2026 = sorted(
        df[df["game_date"].dt.year == 2026]["game_date"].dt.strftime("%Y-%m").unique()
    )
    res = walk_forward(df, season_2026)
    pooled = summarize(res)

    res["folds"].to_csv(OUT / "walkforward_folds.csv", index=False)
    if not res["preds"].empty:
        res["preds"].to_csv(OUT / "oos_predictions.csv", index=False)
    (OUT / "summary.json").write_text(json.dumps(pooled, indent=2, default=str))

    # Fit a final production model on ALL data and persist via joblib.
    import joblib
    final = MinutesModel().fit(df)
    joblib.dump(final, OUT / "minutes_model_v2.joblib")
    return pooled


if __name__ == "__main__":
    s = run()
    print(json.dumps(s, indent=2, default=str))
    print(f"\nArtifacts -> {OUT}")
