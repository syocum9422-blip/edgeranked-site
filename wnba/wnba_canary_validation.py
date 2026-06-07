"""WNBA weekly canary: Production vs Variant C (shadow, read-only).

Rebuilds a shadow dataset from current raw data, then for windows 7/14/30d compares:
  A = production (prod minutes model; stat totals w/ leakage-free rolling-min feature)
  C = Variant C  (retrain+rolling-min minutes model; per-minute rate × projected minutes)
on: minutes MAE/RMSE, projection MAE/RMSE, accuracy(qual win-rate@56), Brier, log-loss, coverage.

Emits weekly_wnba_canary_report.json + .csv and appends a row to the trend history.
Does NOT modify any production file. Intended for a weekly cron.

Usage: python wnba_canary_validation.py [--sims N]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

WNBA = Path(__file__).resolve().parent
PHASE3 = WNBA / "outputs" / "phase3"
sys.path.insert(0, str(WNBA))
sys.path.insert(0, str(PHASE3))

import simulate_wnba_today as sim
import build_wnba_dataset as bd
from wnba_model_utils import feature_columns, build_regression_pipeline, clean_feature_frame, setup_logging
import phase4a_full_resim as p4  # load_graded, train_variant_c, score_bets
import phase5b_stat_variants as p5  # train_rate_model, predict_bundle, STATS, MIN_FEATS, RATE_FEATS

OUT = WNBA / "outputs" / "phase6"
HIST = OUT / "canary_history"
STAT_DIR = WNBA / "data" / "models"
PROD_MIN = WNBA / "models" / "wnba_minutes_model.joblib"
WINDOWS = [7, 14, 30]
EPS = 1e-6


def rebuild_shadow_dataset() -> Path:
    path = OUT / "canary_dataset.csv"
    bd.DATASET_PATH = path
    bd.main()
    return path


def m_mae_rmse(pred, actual):
    e = np.asarray(pred) - np.asarray(actual)
    return float(np.abs(e).mean()), float(math.sqrt((e ** 2).mean()))


def betting_metrics(df, col):
    r = df.dropna(subset=["result_binary", col])
    y = r["result_binary"].values
    p = np.clip(r[col].values, EPS, 1 - EPS)
    sel = r[r[col] >= 0.56]
    return {"brier": float(np.mean((p - y) ** 2)),
            "log_loss": float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))),
            "coverage_56": int((df[col] >= 0.56).sum()),
            "accuracy": float(sel["result_binary"].mean()) if len(sel) else float("nan")}


def run(sims: int) -> dict:
    log = setup_logging("wnba_canary")
    sim.MONTE_CARLO_SIMS = sims
    p4.sim.MONTE_CARLO_SIMS = sims
    ds_path = rebuild_shadow_dataset()
    ds = pd.read_csv(ds_path, low_memory=False)
    ds["game_date"] = pd.to_datetime(ds["game_date"], errors="coerce")
    ds["player_key"] = ds["player_name"].astype(str).str.lower().str.strip()
    stat_models = {s: joblib.load(STAT_DIR / f"wnba_{s}_model.joblib") for s in p5.STATS}
    prod_min = joblib.load(PROD_MIN)
    last = ds["game_date"].max()

    g = p4.load_graded(); g["game_date_str"] = g["bet_date"].dt.strftime("%Y-%m-%d")
    results = []
    for w in WINDOWS:
        cutoff = last - pd.Timedelta(days=w - 1)
        val = ds[(ds["game_date"] >= cutoff)].dropna(subset=["minutes"]).copy()
        if val.empty:
            continue
        cmodel = p4.train_variant_c(ds, cutoff)
        Xc = clean_feature_frame(val, cmodel["feature_list"])
        proj_min = np.clip((np.clip(cmodel["ridge_model"].predict(Xc), 0, None)
                            + np.clip(cmodel["tree_model"].predict(Xc), 0, None)) / 2, 5, 40)
        roll_min = val["minutes_rolling_mean_5"].fillna(val["season_avg_minutes"]).fillna(15.0).values
        Xp = clean_feature_frame(val, prod_min["feature_list"])
        prod_pred_min = np.clip((np.clip(prod_min["ridge_model"].predict(Xp), 0, None)
                                 + np.clip(prod_min["tree_model"].predict(Xp), 0, None)) / 2, 5, 40)
        y_min = val["minutes"].astype(float).values
        a_mmae, a_mrmse = m_mae_rmse(prod_pred_min, y_min)
        c_mmae, c_mrmse = m_mae_rmse(proj_min, y_min)

        rate_models = {s: p5.train_rate_model(ds, s, cutoff) for s in p5.STATS}
        a_abs, a_sq, c_abs, c_sq = [], [], [], []
        for stat in p5.STATS:
            actual = val[stat].astype(float).values
            fA = val.copy(); fA["minutes"] = roll_min
            tA = p5.predict_bundle(stat_models[stat], fA)
            tC = p5.predict_bundle(rate_models[stat], val) * proj_min
            mask = ~np.isnan(actual)
            a_abs += list(np.abs(tA[mask] - actual[mask])); a_sq += list((tA[mask] - actual[mask]) ** 2)
            c_abs += list(np.abs(tC[mask] - actual[mask])); c_sq += list((tC[mask] - actual[mask]) ** 2)
        a_pmae, a_prmse = float(np.mean(a_abs)), float(math.sqrt(np.mean(a_sq)))
        c_pmae, c_prmse = float(np.mean(c_abs)), float(math.sqrt(np.mean(c_sq)))

        # betting re-sim
        betsw = g[g["bet_date"] >= cutoff]
        import phase5c_betting_resim as p5c
        fA = p5c.base_frame(val, stat_models, prod_min, roll_min)
        scA = p4.score_bets(fA, betsw, seed_base=1000)
        fC = p5c.base_frame(val, stat_models, cmodel, proj_min)
        keyC = list(zip(fC["player_key"], pd.to_datetime(fC["game_date"])))
        for stat in p5.STATS:
            tC = p5.predict_bundle(rate_models[stat], val) * proj_min
            ratemap = dict(zip(list(zip(val["player_key"], val["game_date"])), tC))
            fC[f"{stat}_proj"] = [ratemap.get(k, fC[f"{stat}_proj"].iloc[i]) for i, k in enumerate(keyC)]
        scC = p4.score_bets(fC, betsw, seed_base=1000)
        betsw = betsw.copy()
        betsw["pA"] = betsw.index.map(scA); betsw["pC"] = betsw.index.map(scC)
        bmA = betting_metrics(betsw, "pA"); bmC = betting_metrics(betsw, "pC")

        results.append({
            "window_days": w, "n_val": int(len(val)), "n_bets": int(len(betsw)),
            "A_minutes_mae": round(a_mmae, 4), "C_minutes_mae": round(c_mmae, 4),
            "A_minutes_rmse": round(a_mrmse, 4), "C_minutes_rmse": round(c_mrmse, 4),
            "A_proj_mae": round(a_pmae, 4), "C_proj_mae": round(c_pmae, 4),
            "A_proj_rmse": round(a_prmse, 4), "C_proj_rmse": round(c_prmse, 4),
            "A_brier": round(bmA["brier"], 4), "C_brier": round(bmC["brier"], 4),
            "A_log_loss": round(bmA["log_loss"], 4), "C_log_loss": round(bmC["log_loss"], 4),
            "A_coverage": bmA["coverage_56"], "C_coverage": bmC["coverage_56"],
            "A_accuracy": round(bmA["accuracy"], 4), "C_accuracy": round(bmC["accuracy"], 4),
        })

    report = {"generated_at_utc": datetime.now(timezone.utc).isoformat(),
              "data_through": str(last.date()), "monte_carlo_sims": sims,
              "windows": results}
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sims", type=int, default=6000)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True); HIST.mkdir(parents=True, exist_ok=True)
    report = run(args.sims)

    json.dump(report, open(OUT / "weekly_wnba_canary_report.json", "w"), indent=2)
    df = pd.DataFrame(report["windows"]); df.insert(0, "generated_at_utc", report["generated_at_utc"])
    df.insert(1, "data_through", report["data_through"])
    df.to_csv(OUT / "weekly_wnba_canary_report.csv", index=False)
    # append trend history (one file per run + a rolling master)
    stamp = report["generated_at_utc"].replace(":", "").replace("-", "")[:15]
    df.to_csv(HIST / f"canary_{stamp}.csv", index=False)
    master = HIST / "canary_trend_master.csv"
    df.to_csv(master, mode="a", header=not master.exists(), index=False)

    print(f"=== WNBA canary report (data through {report['data_through']}, sims={args.sims}) ===")
    cols = ["window_days", "C_minutes_mae", "A_minutes_mae", "C_proj_mae", "A_proj_mae",
            "C_brier", "A_brier", "C_log_loss", "A_log_loss", "C_coverage", "A_coverage",
            "C_accuracy", "A_accuracy"]
    print(df[cols].to_string(index=False))
    print(f"\nwrote: {OUT/'weekly_wnba_canary_report.json'}\n       {OUT/'weekly_wnba_canary_report.csv'}\n       {master} (appended)")


if __name__ == "__main__":
    main()
