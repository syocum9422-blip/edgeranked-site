"""Phase 6 — Minutes mean upgrade walk-forward training & validation.

The distribution model remains the existing two-stage minutes engine. Phase 6
upgrades only the p50/mean anchor: a simple rolling recent-minutes champion is
fit inside MinutesModel and used to shift the quantile distribution.

Run:  python3 -m wnba_v2.engines.minutes.train
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
BASELINE_COLS = {
    "last1": "min_lag1",
    "last3": "min_mean3",
    "last5": "min_mean5",
    "last10": "min_mean10",
}


def pinball_loss(y: np.ndarray, q_pred: np.ndarray, tau: float) -> float:
    d = y - q_pred
    return float(np.mean(np.maximum(tau * d, (tau - 1) * d)))


def coverage(y: np.ndarray, q_pred: np.ndarray) -> float:
    """Empirical P(y <= q_pred); should equal tau for a calibrated quantile."""
    return float(np.mean(y <= q_pred))


def _mae(y_true, y_pred) -> float:
    y = np.asarray(y_true, dtype=float)
    p = np.asarray(y_pred, dtype=float)
    if len(y) == 0:
        return float("nan")
    return float(mean_absolute_error(y, p))


def _baseline_pred(df: pd.DataFrame, col: str) -> np.ndarray:
    vals = df[col].astype(float) if col in df else pd.Series(np.nan, index=df.index)
    fallback = vals.median()
    if not np.isfinite(fallback):
        fallback = df["minutes"].median() if "minutes" in df else 18.0
    return vals.fillna(fallback).to_numpy()


def _starter_proxy(df: pd.DataFrame) -> pd.Series:
    starter = pd.Series(False, index=df.index)
    if "starter_streak" in df:
        starter |= df["starter_streak"].fillna(0) >= 0.6
    if "min_mean5" in df:
        starter |= df["min_mean5"].fillna(0) >= 24
    return starter


def _add_game_context(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    keys = ["game_date", "team"]
    team_points = out.groupby(keys)["team_points"].max()

    def opponent_points(row):
        return team_points.get((row["game_date"], row["opponent"]), np.nan)

    if {"game_date", "team", "opponent", "team_points"}.issubset(out.columns):
        out["opponent_actual_points"] = out.apply(opponent_points, axis=1)
        out["game_margin"] = out["team_points"] - out["opponent_actual_points"]
        out["abs_game_margin"] = out["game_margin"].abs()
    else:
        out["opponent_actual_points"] = np.nan
        out["game_margin"] = np.nan
        out["abs_game_margin"] = np.nan
    out["game_context"] = np.select(
        [out["abs_game_margin"] <= 5, out["abs_game_margin"] >= 15],
        ["close", "blowout"],
        default="middle_or_unknown",
    )
    # Historical injury statuses are not archived in the training set. This is
    # the closest available role-disruption proxy: long rest / re-entry context.
    out["injury_context"] = np.where(
        (out.get("rest_days", pd.Series(0, index=out.index)).fillna(0) >= 7)
        | (out.get("games_played_season", pd.Series(99, index=out.index)).fillna(99) <= 2),
        "absence_return_proxy",
        "normal",
    )
    return out


def _prediction_frame(played: pd.DataFrame, q_base: pd.DataFrame, q: pd.DataFrame, pp: np.ndarray) -> pd.DataFrame:
    keep = [
        "game_date", "season", "player_key", "player_name", "team", "opponent", "position",
        "minutes", "games_played_season", "rest_days", "is_back_to_back", "is_home",
        "rotation_rank", "starter_streak", "min_lag1", "min_mean3", "min_mean5",
        "min_mean10", "min_ewm", "min_cv10", "team_points",
    ]
    cols = [c for c in keep if c in played.columns]
    tmp = played[cols].copy()
    tmp = _add_game_context(tmp)
    tmp["starter_segment"] = np.where(_starter_proxy(played), "starter_proxy", "bench_proxy")
    tmp["q50_base_gbm"] = q_base["q50"].to_numpy()
    for col in q.columns:
        tmp[col] = q[col].to_numpy()
    tmp["play_prob"] = pp
    for name, col in BASELINE_COLS.items():
        tmp[f"naive_{name}"] = _baseline_pred(played, col)
    tmp["naive_last5"] = _baseline_pred(played, "min_mean5")
    tmp["abs_error_base_gbm"] = (tmp["minutes"] - tmp["q50_base_gbm"]).abs()
    tmp["abs_error_phase6_p50"] = (tmp["minutes"] - tmp["q50"]).abs()
    tmp["abs_error_naive_last5"] = (tmp["minutes"] - tmp["naive_last5"]).abs()
    return tmp


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
        q_base = model.predict_base_quantiles(played)
        q = model.predict_quantiles(played)
        pp = model.predict_play_prob(test)
        y = played["y_minutes"].values

        rec = {"month": ym, "n_train": len(train), "n_test_played": len(played)}
        for tau in QUANTILES:
            col = f"q{int(tau*100)}"
            rec[f"pinball_{col}"] = round(pinball_loss(y, q[col].values, tau), 4)
            rec[f"cov_{col}"] = round(coverage(y, q[col].values), 4)
        rec["pinball_mean"] = round(np.mean([rec[f"pinball_q{int(t*100)}"] for t in QUANTILES]), 4)
        rec["mae_base_gbm_p50"] = round(_mae(y, q_base["q50"].values), 4)
        rec["mae_phase6_p50"] = round(_mae(y, q["q50"].values), 4)
        for name, col in BASELINE_COLS.items():
            rec[f"mae_naive_{name}"] = round(_mae(y, _baseline_pred(played, col)), 4)
        rec["mae_naive_mean5"] = rec["mae_naive_last5"]
        rec["mean_anchor_weights"] = json.dumps(model.mean_model.weights if model.mean_model else {})
        ya = test["y_meaningful"].values
        if len(np.unique(ya)) > 1:
            rec["stageA_auc"] = round(roc_auc_score(ya, pp), 4)
            rec["stageA_brier"] = round(brier_score(ya, pp), 4)
        fold_rows.append(rec)

        pp_played = model.predict_play_prob(played)
        all_pred.append(_prediction_frame(played, q_base, q, pp_played))

    folds = pd.DataFrame(fold_rows)
    preds = pd.concat(all_pred, ignore_index=True) if all_pred else pd.DataFrame()
    return {"folds": folds, "preds": preds}


def _segment_table(preds: pd.DataFrame) -> pd.DataFrame:
    specs = [("overall", pd.Series("overall", index=preds.index))]
    for col in ["starter_segment", "team", "player_key", "injury_context", "game_context"]:
        if col in preds:
            specs.append((col, preds[col].fillna("unknown").astype(str)))
    rows = []
    for segment, labels in specs:
        for label, idx in labels.groupby(labels).groups.items():
            sub = preds.loc[idx]
            if len(sub) < 1:
                continue
            rows.append({
                "segment": segment,
                "value": label,
                "n": int(len(sub)),
                "mae_base_gbm_p50": round(_mae(sub["minutes"], sub["q50_base_gbm"]), 4),
                "mae_phase6_p50": round(_mae(sub["minutes"], sub["q50"]), 4),
                "mae_naive_last1": round(_mae(sub["minutes"], sub["naive_last1"]), 4),
                "mae_naive_last3": round(_mae(sub["minutes"], sub["naive_last3"]), 4),
                "mae_naive_last5": round(_mae(sub["minutes"], sub["naive_last5"]), 4),
                "mae_naive_last10": round(_mae(sub["minutes"], sub["naive_last10"]), 4),
                "phase6_vs_last5_delta": round(_mae(sub["minutes"], sub["q50"]) - _mae(sub["minutes"], sub["naive_last5"]), 4),
                "phase6_vs_base_delta": round(_mae(sub["minutes"], sub["q50"]) - _mae(sub["minutes"], sub["q50_base_gbm"]), 4),
            })
    return pd.DataFrame(rows).sort_values(["segment", "phase6_vs_last5_delta", "n"], ascending=[True, True, False])


def summarize(res: dict) -> dict:
    folds, preds = res["folds"], res["preds"]
    if folds.empty:
        return {"error": "no folds produced"}
    y = preds["minutes"].values
    pooled = {}
    for tau in QUANTILES:
        col = f"q{int(tau*100)}"
        pooled[f"pinball_{col}"] = round(pinball_loss(y, preds[col].values, tau), 4)
        pooled[f"coverage_{col}"] = round(coverage(y, preds[col].values), 4)
        pooled[f"coverage_target_{col}"] = tau
    pooled["pinball_mean"] = round(np.mean([pooled[f"pinball_q{int(t*100)}"] for t in QUANTILES]), 4)
    pooled["mae_base_gbm_p50"] = round(_mae(y, preds["q50_base_gbm"].values), 4)
    pooled["mae_phase6_p50"] = round(_mae(y, preds["q50"].values), 4)
    for name in BASELINE_COLS:
        pooled[f"mae_naive_{name}"] = round(_mae(y, preds[f"naive_{name}"].values), 4)
    pooled["mae_naive_mean5"] = pooled["mae_naive_last5"]
    pooled["mae_improvement_vs_naive_pct"] = round(
        (pooled["mae_naive_mean5"] - pooled["mae_phase6_p50"]) / pooled["mae_naive_mean5"] * 100, 2)
    starter = preds[preds["starter_segment"] == "starter_proxy"]
    pooled["starter_mae_phase6_p50"] = round(_mae(starter["minutes"], starter["q50"]), 4)
    pooled["starter_mae_naive_mean5"] = round(_mae(starter["minutes"], starter["naive_last5"]), 4)
    pooled["starter_regression_vs_naive"] = bool(pooled["starter_mae_phase6_p50"] > pooled["starter_mae_naive_mean5"])
    pooled["promotion_gate"] = {
        "beats_naive_overall": bool(pooled["mae_phase6_p50"] < pooled["mae_naive_mean5"]),
        "no_starter_regression": not pooled["starter_regression_vs_naive"],
        "promoted": bool((pooled["mae_phase6_p50"] < pooled["mae_naive_mean5"]) and not pooled["starter_regression_vs_naive"]),
    }
    return pooled


def _write_report(pooled: dict, segments: pd.DataFrame, weights: dict) -> None:
    overall = segments[segments["segment"] == "overall"].head(1)
    starter = segments[(segments["segment"] == "starter_segment") & (segments["value"] == "starter_proxy")].head(1)
    bench = segments[(segments["segment"] == "starter_segment") & (segments["value"] == "bench_proxy")].head(1)
    worst = segments[(segments["segment"] == "team") & (segments["n"] >= 20)].sort_values("phase6_vs_last5_delta", ascending=False).head(5)
    best = segments[(segments["segment"] == "team") & (segments["n"] >= 20)].sort_values("phase6_vs_last5_delta").head(5)

    def row_text(df: pd.DataFrame) -> str:
        if df.empty:
            return "n/a"
        r = df.iloc[0]
        return (f"n={int(r['n'])}, base_gbm={r['mae_base_gbm_p50']:.4f}, "
                f"phase6={r['mae_phase6_p50']:.4f}, naive5={r['mae_naive_last5']:.4f}")

    lines = [
        "# Phase 6 Minutes Mean Upgrade",
        "",
        "## Decision",
        f"Promoted: {pooled['promotion_gate']['promoted']}",
        f"Overall MAE: Phase 6 p50 {pooled['mae_phase6_p50']:.4f} vs naive mean5 {pooled['mae_naive_mean5']:.4f} vs old GBM p50 {pooled['mae_base_gbm_p50']:.4f}.",
        f"Starter MAE: Phase 6 p50 {pooled['starter_mae_phase6_p50']:.4f} vs naive mean5 {pooled['starter_mae_naive_mean5']:.4f}.",
        "",
        "## Why The Old P50 Lost",
        "The raw quantile GBM over-smoothed recent role changes and cold-start rows. In the 2026 walk-forward sample it produced 4.57 MAE, while the leak-free last-5 rolling baseline produced 4.47 MAE. The Phase 6 anchor replaces only that mean/p50 center with a rolling recent-minutes ensemble and keeps the existing quantile spread.",
        "",
        "## Champion Anchor",
        f"Learned final weights: {json.dumps(weights, sort_keys=True)}",
        "Low-confidence rows with fewer than two usable rolling signals fall back to the naive last-5 anchor/fallback median.",
        "Historical injury status is not archived in the training data; the injury split uses an absence/return proxy based on long rest or first two season appearances.",
        "",
        "## Required Splits",
        f"Overall: {row_text(overall)}",
        f"Starters: {row_text(starter)}",
        f"Bench: {row_text(bench)}",
        "",
        "## Team Deltas vs Naive Last5",
        "Worst teams (positive means Phase 6 worse than naive):",
    ]
    for _, r in worst.iterrows():
        lines.append(f"- {r['value']}: n={int(r['n'])}, delta={r['phase6_vs_last5_delta']:.4f}, phase6={r['mae_phase6_p50']:.4f}, naive5={r['mae_naive_last5']:.4f}")
    lines.append("Best teams:")
    for _, r in best.iterrows():
        lines.append(f"- {r['value']}: n={int(r['n'])}, delta={r['phase6_vs_last5_delta']:.4f}, phase6={r['mae_phase6_p50']:.4f}, naive5={r['mae_naive_last5']:.4f}")
    lines.extend([
        "",
        "## Artifacts",
        "- walkforward_folds.csv",
        "- oos_predictions.csv",
        "- phase6_segment_diagnostics.csv",
        "- phase6_minutes_report.md",
        "- promotion_status.json",
    ])
    (OUT / "phase6_minutes_report.md").write_text("\n".join(lines) + "\n")


def run() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    raw = pd.read_csv(DATASET, parse_dates=["game_date"])
    df = build_minutes_features(raw)
    season_2026 = sorted(
        df[df["game_date"].dt.year == 2026]["game_date"].dt.strftime("%Y-%m").unique()
    )
    res = walk_forward(df, season_2026)
    pooled = summarize(res)
    segments = _segment_table(res["preds"]) if not res["preds"].empty else pd.DataFrame()

    res["folds"].to_csv(OUT / "walkforward_folds.csv", index=False)
    if not res["preds"].empty:
        res["preds"].to_csv(OUT / "oos_predictions.csv", index=False)
    if not segments.empty:
        segments.to_csv(OUT / "phase6_segment_diagnostics.csv", index=False)
    (OUT / "summary.json").write_text(json.dumps(pooled, indent=2, default=str))

    import joblib
    final = MinutesModel().fit(df)
    final_weights = final.mean_model.weights if final.mean_model else {}
    promotion_status = {
        "phase": "6_minutes_mean_upgrade",
        "model_artifact": str(OUT / "minutes_model_v2.joblib"),
        "mean_anchor": "rolling_recent_minutes_champion",
        "final_weights": final_weights,
        "gates": pooled.get("promotion_gate", {}),
        "metrics": pooled,
        "notes": [
            "Distribution model preserved; Phase 6 shifts quantiles to champion p50 anchor.",
            "Historical injury status is unavailable in the training set; injury diagnostics use absence/return proxy.",
        ],
    }
    if pooled.get("promotion_gate", {}).get("promoted"):
        joblib.dump(final, OUT / "minutes_model_v2.joblib")
        promotion_status["artifact_written"] = True
    else:
        promotion_status["artifact_written"] = False
    (OUT / "promotion_status.json").write_text(json.dumps(promotion_status, indent=2, default=str))
    _write_report(pooled, segments, final_weights)
    return pooled


if __name__ == "__main__":
    s = run()
    print(json.dumps(s, indent=2, default=str))
    print(f"\nArtifacts -> {OUT}")
