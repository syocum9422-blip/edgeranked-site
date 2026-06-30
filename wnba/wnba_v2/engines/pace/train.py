"""Phase 2 — pace engine walk-forward validation.

Proves the model beats the naive pair-mean pace anchor out-of-sample. Honest by
design: if it does NOT beat naive, that is reported, not hidden.

Run:  .venv/bin/python -m wnba_v2.engines.pace.train
"""
from __future__ import annotations

import json

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error

from wnba_v2 import config as C
from wnba_v2.engines.pace.features import build_pace_features, feature_list
from wnba_v2.engines.pace.model import PaceModel

OUT = C.OUTPUTS / "pace"


def walk_forward(df: pd.DataFrame, features: list[str]) -> dict:
    df = df.sort_values("date").reset_index(drop=True)
    seasons = sorted(df["season"].unique())
    rows, preds = [], []
    # Expanding window: test each season using all prior seasons + that season's
    # earlier games is overkill at this size — test the latest 2 seasons, train on prior.
    for test_season in seasons[1:]:
        train = df[(df["season"] < test_season) & df["target_game_possessions"].notna()]
        test = df[df["season"] == test_season]
        if len(train) < 100 or len(test) < 30:
            continue
        m = PaceModel().fit(train, features)
        # fair comparison: only score games where the naive anchor is defined
        test = test[test["pace_pair_mean5"].notna() & test["target_game_possessions"].notna()]
        if len(test) < 30:
            continue
        pred = m.predict_mean(test)
        y = test["target_game_possessions"].values
        naive = test["pace_pair_mean5"].values
        rows.append({
            "test_season": int(test_season),
            "n_train": len(train), "n_test": len(test),
            "mae_model": round(mean_absolute_error(y, pred), 4),
            "mae_naive": round(mean_absolute_error(y, naive), 4),
            "rmse_model": round(float(np.sqrt(np.mean((y - pred) ** 2))), 4),
            "resid_std": round(m.resid_std, 3),
        })
        t = test[["date", "game_id", "season"]].copy()
        t["y"], t["pred"], t["naive"] = y, pred, naive
        preds.append(t)
    folds = pd.DataFrame(rows)
    pooled = pd.concat(preds) if preds else pd.DataFrame()
    return {"folds": folds, "preds": pooled}


def run() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    df = build_pace_features(use_vegas=True)
    feats = feature_list(df)
    res = walk_forward(df, feats)
    folds, preds = res["folds"], res["preds"]

    summary = {"features_used": feats, "vegas_in_use": any("vegas" in f for f in feats),
               "n_games": int(len(df))}
    if not preds.empty:
        y, p, nv = preds["y"].values, preds["pred"].values, preds["naive"].values
        summary.update({
            "oos_mae_model": round(mean_absolute_error(y, p), 4),
            "oos_mae_naive": round(mean_absolute_error(y, nv), 4),
            "oos_rmse_model": round(float(np.sqrt(np.mean((y - p) ** 2))), 4),
            "improvement_vs_naive_pct": round((mean_absolute_error(y, nv) - mean_absolute_error(y, p))
                                              / mean_absolute_error(y, nv) * 100, 2),
            "beats_naive": bool(mean_absolute_error(y, p) < mean_absolute_error(y, nv)),
        })
    # Auto-select the OOS winner: use the learned model only if it actually beats naive.
    chosen_mode = "ridge" if summary.get("beats_naive") else "naive"
    summary["chosen_mode"] = chosen_mode
    summary["selection_rule"] = "learned model used only when it beats the naive pace anchor OOS"

    folds.to_csv(OUT / "walkforward_folds.csv", index=False)
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, default=str))

    final = PaceModel(mode=chosen_mode).fit(df, feats)
    joblib.dump(final, OUT / "pace_model_v2.joblib")
    return summary


if __name__ == "__main__":
    s = run()
    print(json.dumps(s, indent=2, default=str))
    print(f"\nArtifacts -> {OUT}")
