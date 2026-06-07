"""Phase 4A: FULL re-simulation (no first-order approximation).

Re-runs the real production pipeline (build_projection_rows -> simulate_player_row ->
apply_calibrated_hit_rate -> apply_confidence_guardrails) on the realized bet universe
(graded_bets.csv), for two minutes models:
  A = live production minutes model (the 'before')
  C = Variant C  (retrain incl 2026 + rolling-minutes features), trained leakage-free per window
Stat models (data/models) are identical for both; only the minutes model differs.
Same RNG seed per player-game across A/C so the ONLY difference is minutes.

Outputs: resim_bet_scores.csv (per bet, both variants), resim_coverage_report.csv,
         resim_window_metrics.csv
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

import simulate_wnba_today as sim
import build_wnba_best_bets as bbb
from wnba_model_utils import feature_columns, build_regression_pipeline, clean_feature_frame, setup_logging

HERE = Path(__file__).resolve().parent
SHADOW_DS = HERE / "shadow" / "wnba_training_dataset_2026.csv"
GRADED = WNBA / "Best_Bets" / "graded_bets.csv"
PROD_MIN_MODEL = WNBA / "models" / "wnba_minutes_model.joblib"
STAT_DIR = WNBA / "data" / "models"
OUT = HERE / "reports"
SHADOW_MODELS = HERE / "shadow" / "models"
SHADOW_MODELS.mkdir(parents=True, exist_ok=True)

WINDOWS = [7, 14, 30]
THRESHOLDS = [0.50, 0.52, 0.54, 0.56, 0.58, 0.60]
EPS = 1e-6
ROLL_MIN = ["minutes_rolling_mean_3", "minutes_rolling_std_3", "minutes_rolling_mean_5",
            "minutes_rolling_std_5", "minutes_rolling_mean_10", "minutes_rolling_std_10"]


def load_graded():
    g = pd.read_csv(GRADED)
    g.columns = [c.lower() for c in g.columns]
    g = g.loc[:, ~g.columns.duplicated()].copy()
    g["bet_date"] = pd.to_datetime(g["bet_date"], errors="coerce").dt.normalize()
    g["player_key"] = g["player_name"].astype(str).str.lower().str.strip()
    for c in ["line", "hit_rate", "projection_mean", "projected_minutes"]:
        g[c] = pd.to_numeric(g[c], errors="coerce")
    g["stat"] = g["stat"].astype(str).str.lower().str.strip()
    g["side"] = g["side"].astype(str).str.lower().str.strip()
    g["bet_result"] = g["bet_result"].astype(str).str.lower().str.strip()
    g["result_binary"] = np.where(g["bet_result"] == "win", 1.0,
                                  np.where(g["bet_result"] == "loss", 0.0, np.nan))
    return g[g["bet_date"].notna()].copy()


def train_variant_c(ds, cutoff):
    feats = [c for c in feature_columns() if c != "minutes"] + ROLL_MIN
    tr = ds[ds["game_date"] < cutoff].dropna(subset=["minutes"]).copy()
    X = clean_feature_frame(tr, feats)
    y = tr["minutes"].astype(float)
    ridge, tree, _, _ = build_regression_pipeline(X)
    ridge.fit(X, y); tree.fit(X, y)
    return {"ridge_model": ridge, "tree_model": tree, "feature_list": feats}


def score_bets(proj_frame, bets, seed_base):
    """For each player-game row in proj_frame, simulate and read off the bet's prob,
    then apply production calibration+guardrails. Returns dict keyed by bet index."""
    factors, _ = bbb.load_calibration_factors(setup_logging("resim_calib"))
    proj_by_key = {(r["player_key"], r["game_date"]): r for _, r in proj_frame.iterrows()}
    out = {}
    # group bets by player-game to simulate once per player-game
    for (pk, gd), grp in bets.groupby(["player_key", "game_date_str"]):
        row = proj_by_key.get((pk, gd))
        if row is None:
            continue
        # lines for this player-game across its bets
        lines = grp[["player_key", "stat", "line"]].copy()
        lines["sportsbook"] = "resim"
        lines["over_odds"] = -110
        lines["under_odds"] = -110
        seed = (seed_base + abs(hash((pk, gd)))) % (2**32)
        rng = np.random.default_rng(seed)
        _, detail = sim.simulate_player_row(row, rng, lines, {})
        # index detail by (stat, line)
        dmap = {(d["stat"], round(float(d["line"]), 2)): d for d in detail}
        for idx, b in grp.iterrows():
            d = dmap.get((b["stat"], round(float(b["line"]), 2)))
            if d is None:
                continue
            raw = d["over_hit_rate"] if b["side"] == "over" else d["under_hit_rate"]
            conf = d.get("confidence_label", row.get("confidence"))
            cal, _, _ = bbb.apply_calibrated_hit_rate(raw, b["stat"], b["side"], conf, factors)
            grow = pd.Series({**d, "line": b["line"], "mean": d.get("mean"),
                              "projected_minutes": row.get("projected_minutes"),
                              "minutes_stability_score": row.get("minutes_stability_score", 1.0)})
            final, _ = bbb.apply_confidence_guardrails(cal, grow, conf)
            out[idx] = float(final)
    return out


def main():
    log = setup_logging("phase4a_full_resim")
    ds = pd.read_csv(SHADOW_DS, low_memory=False)
    ds["game_date"] = pd.to_datetime(ds["game_date"], errors="coerce")
    ds["player_key"] = ds["player_name"].astype(str).str.lower().str.strip()

    g = load_graded()
    g["game_date_str"] = g["bet_date"].dt.strftime("%Y-%m-%d")

    stat_models = {s: joblib.load(STAT_DIR / f"wnba_{s}_model.joblib") for s in sim.STAT_TARGETS}
    prod_min = joblib.load(PROD_MIN_MODEL)
    last = ds["game_date"].max()

    # ---- Variant A (production): simulate once on all bets ----
    val_all = ds[ds["game_date"] >= (last - pd.Timedelta(days=29))].copy()
    val_all["game_date"] = val_all["game_date"].dt.strftime("%Y-%m-%d")
    frame_A = sim.build_projection_rows(val_all, stat_models, prod_min)
    scores_A = score_bets(frame_A, g, seed_base=1000)
    g["hit_rate_A"] = g.index.map(scores_A)

    # ---- Variant C: per-window leakage-free model ----
    g["hit_rate_C"] = np.nan
    for w in WINDOWS:
        cutoff = last - pd.Timedelta(days=w - 1)
        cmodel = train_variant_c(ds, cutoff)
        joblib.dump(cmodel, SHADOW_MODELS / f"wnba_minutes_model_variantC_{w}d.joblib")
        valw = ds[ds["game_date"] >= cutoff].copy()
        valw["game_date"] = valw["game_date"].dt.strftime("%Y-%m-%d")
        frame_C = sim.build_projection_rows(valw, stat_models, cmodel)
        betsw = g[g["bet_date"] >= cutoff]
        scores_C = score_bets(frame_C, betsw, seed_base=1000)  # same seed_base -> same RNG per player
        for idx, v in scores_C.items():
            g.loc[idx, f"hit_rate_C_w{w}"] = v
    # tightest available window wins (7d most data, else 14d, else 30d)
    for w in [30, 14, 7]:
        col = f"hit_rate_C_w{w}"
        if col in g.columns:
            g["hit_rate_C"] = g[col].where(g[col].notna(), g["hit_rate_C"])
    g.to_csv(OUT / "resim_bet_scores.csv", index=False)

    # ---- metrics ----
    def metrics(df, col):
        r = df.dropna(subset=["result_binary", col])
        y = r["result_binary"].values
        p = np.clip(r[col].values, EPS, 1 - EPS)
        sel = r[r[col] >= 0.56]
        return {"n": len(r), "brier": round(float(np.mean((p - y) ** 2)), 4),
                "log_loss": round(float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))), 4),
                "coverage_at_56": int((df[col] >= 0.56).sum()),
                "qual_winrate_56": round(float(sel["result_binary"].mean()), 4) if len(sel) else float("nan")}

    rows = []
    cov_rows = []
    for w in WINDOWS:
        cutoff = last - pd.Timedelta(days=w - 1)
        sub = g[g["bet_date"] >= cutoff]
        ccol = f"hit_rate_C_w{w}"  # this window's own leakage-free C model
        ma, mc = metrics(sub, "hit_rate_A"), metrics(sub, ccol)
        cov_red = (ma["coverage_at_56"] - mc["coverage_at_56"]) / ma["coverage_at_56"] * 100 if ma["coverage_at_56"] else 0
        rows.append({"window_days": w, "n_bets": len(sub),
                     "A_brier": ma["brier"], "C_brier": mc["brier"],
                     "A_log_loss": ma["log_loss"], "C_log_loss": mc["log_loss"],
                     "A_coverage_56": ma["coverage_at_56"], "C_coverage_56": mc["coverage_at_56"],
                     "coverage_reduction_pct": round(cov_red, 2),
                     "A_qual_winrate": ma["qual_winrate_56"], "C_qual_winrate": mc["qual_winrate_56"]})
        for thr in THRESHOLDS:
            cov_rows.append({"window_days": w, "threshold": thr,
                             "A_coverage": int((sub["hit_rate_A"] >= thr).sum()),
                             "C_coverage": int((sub[ccol] >= thr).sum())})
    res = pd.DataFrame(rows); res.to_csv(OUT / "resim_window_metrics.csv", index=False)
    cov = pd.DataFrame(cov_rows); cov.to_csv(OUT / "resim_coverage_report.csv", index=False)

    print("=== Phase 4A FULL re-sim: window metrics (A=production vs C=variant) ===")
    print(res.to_string(index=False))
    print("\n=== Coverage by threshold ===")
    print(cov.to_string(index=False))
    matched = g["hit_rate_C"].notna().mean()
    print(f"\nbets scored under C: {matched:.0%} | total graded bets: {len(g)}")


if __name__ == "__main__":
    main()
