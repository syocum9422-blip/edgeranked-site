"""Phase 5C/5D: full betting re-simulation for stat variants A/B/C/D.

For each variant, build a faithful projection frame (leakage-free minutes feature, confidence
from production logic), overwrite the 6 *_proj with the variant's clean projections, then run
the production Monte Carlo + calibration + guardrails on the graded bets. Reports Brier /
log-loss / coverage / qualified win-rate per variant per window. Answers Phase 5D: do minutes
improvements now reach betting?
"""
from __future__ import annotations

import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

WNBA = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WNBA))
import simulate_wnba_today as sim
from wnba_model_utils import setup_logging, clean_feature_frame

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import phase4a_full_resim as p4  # reuse load_graded, score_bets, train_variant_c

SHADOW_DS = HERE / "shadow" / "wnba_training_dataset_2026.csv"
STAT_DIR = WNBA / "data" / "models"
PROD_MIN = WNBA / "models" / "wnba_minutes_model.joblib"
PROJ = HERE / "reports" / "phase5_stat_projections.csv"
OUT = HERE / "reports"
STATS = ["points", "rebounds", "assists", "threes_made", "steals", "blocks"]
WINDOWS = [7, 14, 30]
EPS = 1e-6


def base_frame(val, stat_models, min_model, min_feature_values):
    """Run production build_projection_rows with a leakage-free `minutes` feature."""
    v = val.copy()
    v["minutes"] = min_feature_values
    v["game_date"] = pd.to_datetime(v["game_date"]).dt.strftime("%Y-%m-%d")
    return sim.build_projection_rows(v, stat_models, min_model)


def metrics(df, col):
    r = df.dropna(subset=["result_binary", col])
    y = r["result_binary"].values
    p = np.clip(r[col].values, EPS, 1 - EPS)
    sel = r[r[col] >= 0.56]
    return {"brier": round(float(np.mean((p - y) ** 2)), 4),
            "log_loss": round(float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))), 4),
            "coverage_56": int((df[col] >= 0.56).sum()),
            "qual_winrate": round(float(sel["result_binary"].mean()), 4) if len(sel) else np.nan}


def main():
    log = setup_logging("phase5c")
    ds = pd.read_csv(SHADOW_DS, low_memory=False)
    ds["game_date"] = pd.to_datetime(ds["game_date"], errors="coerce")
    ds["player_key"] = ds["player_name"].astype(str).str.lower().str.strip()
    stat_models = {s: joblib.load(STAT_DIR / f"wnba_{s}_model.joblib") for s in STATS}
    prod_min = joblib.load(PROD_MIN)
    pj = pd.read_csv(PROJ)
    pj["game_date"] = pd.to_datetime(pj["game_date"], errors="coerce")
    last = ds["game_date"].max()

    g = p4.load_graded()
    g["game_date_str"] = g["bet_date"].dt.strftime("%Y-%m-%d")

    score_cols = {}
    for w in WINDOWS:
        cutoff = last - pd.Timedelta(days=w - 1)
        val = ds[ds["game_date"] >= cutoff].dropna(subset=["minutes"]).copy()
        cmodel = p4.train_variant_c(ds, cutoff)
        # projected minutes (variant C) and rolling proxy
        Xc = clean_feature_frame(val, cmodel["feature_list"])
        proj_min = np.clip((np.clip(cmodel["ridge_model"].predict(Xc), 0, None)
                            + np.clip(cmodel["tree_model"].predict(Xc), 0, None)) / 2, 5, 40)
        roll_min = val["minutes_rolling_mean_5"].fillna(val["season_avg_minutes"]).fillna(15.0).values

        pjw = pj[pj["window_days"] == w].set_index(["player_key", "game_date"])
        betsw = g[g["bet_date"] >= cutoff]

        for variant, minmodel, minfeat in [("A", prod_min, roll_min),
                                           ("B", cmodel, proj_min),
                                           ("C", cmodel, proj_min),
                                           ("D", cmodel, proj_min)]:
            frame = base_frame(val, stat_models, minmodel, minfeat)
            if variant != "A":
                # overwrite *_proj with the clean variant projections from phase5b
                key = list(zip(frame["player_key"], pd.to_datetime(frame["game_date"])))
                for stat in STATS:
                    col = f"{stat}_proj_{variant}"
                    vals = [pjw[col].get(k, np.nan) if k in pjw.index else np.nan for k in key]
                    frame[f"{stat}_proj"] = np.where(np.isnan(vals), frame[f"{stat}_proj"], vals)
            sc = p4.score_bets(frame, betsw, seed_base=1000)
            colname = f"hit_{variant}_w{w}"
            for idx, vv in sc.items():
                g.loc[idx, colname] = vv
            score_cols.setdefault(variant, []).append(colname)

    g.to_csv(OUT / "phase5_resim_bet_scores.csv", index=False)

    rows = []
    for w in WINDOWS:
        cutoff = last - pd.Timedelta(days=w - 1)
        sub = g[g["bet_date"] >= cutoff]
        row = {"window_days": w, "n_bets": len(sub)}
        for variant in ["A", "B", "C", "D"]:
            m = metrics(sub, f"hit_{variant}_w{w}")
            row[f"{variant}_brier"] = m["brier"]; row[f"{variant}_logloss"] = m["log_loss"]
            row[f"{variant}_cov56"] = m["coverage_56"]; row[f"{variant}_winrate"] = m["qual_winrate"]
        rows.append(row)
    res = pd.DataFrame(rows)
    res.to_csv(OUT / "phase5_betting_metrics.csv", index=False)
    print("=== Phase 5D: betting metrics by stat variant (A=prod, B=+proj_min feat, C=rate×min, D=hybrid) ===")
    for met in ["brier", "logloss", "cov56", "winrate"]:
        cols = ["window_days"] + [f"{v}_{met}" for v in ["A", "B", "C", "D"]]
        print(f"\n{met}:")
        print(res[cols].to_string(index=False))


if __name__ == "__main__":
    main()
