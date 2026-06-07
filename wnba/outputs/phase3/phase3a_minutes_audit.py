"""Phase 3A: Minutes Projection Audit (read-only).

Produces:
  - minutes_feature_report.csv      (feature importance: tree permutation + ridge coef)
  - minutes_error_breakdown.csv     (MAE/RMSE/bias by team, role, position, volatility,
                                      injury-return, rookie/vet)
  - minutes_top20_misses.csv        (largest absolute misses)
  - phase3a_root_cause_summary.md   (narrative)

No production files are modified. Uses the live trained model and graded error logs.
"""
from __future__ import annotations

import math
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.inspection import permutation_importance
from sklearn.metrics import mean_absolute_error

HERE = Path(__file__).resolve().parent
WNBA = HERE.parents[1]
REPORTS = HERE / "reports"
REPORTS.mkdir(parents=True, exist_ok=True)

DATASET = WNBA / "data" / "processed" / "wnba_training_dataset.csv"
MIN_ERRORS = WNBA / "learning" / "errors" / "minutes_errors.csv"
MODEL = WNBA / "models" / "wnba_minutes_model.joblib"


def clean_feature_frame(frame: pd.DataFrame, feature_list):
    cleaned = frame.reindex(columns=feature_list).copy()
    for c in cleaned.columns:
        if pd.api.types.is_numeric_dtype(cleaned[c]):
            cleaned[c] = pd.to_numeric(cleaned[c], errors="coerce").replace([np.inf, -np.inf], np.nan).clip(-1e6, 1e6)
        else:
            cleaned[c] = cleaned[c].astype(str).replace({"nan": np.nan})
    return cleaned


def feature_importance(ds: pd.DataFrame) -> pd.DataFrame:
    bundle = joblib.load(MODEL)
    feats = bundle["feature_list"]
    tree = bundle["tree_model"]
    ridge = bundle["ridge_model"]

    md = ds.dropna(subset=["minutes"]).copy()
    md["game_date"] = pd.to_datetime(md["game_date"], errors="coerce")
    split = md["game_date"].quantile(0.8)
    valid = md[md["game_date"] > split].copy()
    Xv = clean_feature_frame(valid, feats)
    yv = valid["minutes"].astype(float)

    # Permutation importance on the gradient-boosted tree (drop in MAE when shuffled).
    perm = permutation_importance(
        tree, Xv, yv, scoring="neg_mean_absolute_error",
        n_repeats=5, random_state=42, n_jobs=-1,
    )
    imp = pd.DataFrame({
        "feature": feats,
        "tree_perm_importance_mae": perm.importances_mean,
        "tree_perm_std": perm.importances_std,
    })

    # Ridge standardized coefficients (numeric only; categoricals are one-hot, skipped here).
    try:
        pre = ridge.named_steps["preprocessor"]
        names = pre.get_feature_names_out()
        coefs = ridge.named_steps["model"].coef_
        ridge_df = pd.DataFrame({"raw": names, "ridge_coef": coefs})
        ridge_df["feature"] = ridge_df["raw"].str.replace(r"^numeric__", "", regex=True)
        ridge_df["abs_coef"] = ridge_df["ridge_coef"].abs()
        ridge_map = ridge_df[ridge_df["raw"].str.startswith("numeric__")].set_index("feature")["abs_coef"]
        imp["ridge_abs_coef"] = imp["feature"].map(ridge_map)
    except Exception as e:  # pragma: no cover
        print("ridge coef extraction failed:", e)
        imp["ridge_abs_coef"] = np.nan

    imp = imp.sort_values("tree_perm_importance_mae", ascending=False).reset_index(drop=True)
    imp["rank"] = imp.index + 1
    return imp


GAMELOG = WNBA / "data" / "raw" / "wnba_player_games.csv"
POSITIONS = WNBA / "data" / "raw" / "wnba_player_positions.csv"


def build_player_profiles(err: pd.DataFrame) -> pd.DataFrame:
    """For each graded (player, game_date), compute minutes history from PRIOR games
    in the full league game log (incl. 2026), plus career experience and position."""
    log = pd.read_csv(GAMELOG, low_memory=False)
    log["game_date"] = pd.to_datetime(log["game_date"], errors="coerce")
    log["player_key"] = log["player_name"].astype(str).str.lower().str.strip()
    log["minutes"] = pd.to_numeric(log["minutes"], errors="coerce")
    log = log.dropna(subset=["game_date"]).sort_values(["player_key", "game_date"])

    # Career experience from the full history.
    seasons = log.groupby("player_key")["season"].nunique().rename("seasons_played")
    first_season = log.groupby("player_key")["season"].min().rename("first_season")

    # Position lookup (sparse).
    try:
        pos = pd.read_csv(POSITIONS)
        pos["player_key"] = pos["player_name"].astype(str).str.lower().str.strip()
        pos_map = pos.drop_duplicates("player_key").set_index("player_key")["position"]
    except Exception:
        pos_map = pd.Series(dtype=str)

    recs = []
    keys = err[["player_key", "game_date"]].drop_duplicates()
    by_player = {k: g for k, g in log.groupby("player_key")}
    for _, r in keys.iterrows():
        pk, gd = r["player_key"], r["game_date"]
        g = by_player.get(pk)
        rec = {"player_key": pk, "game_date": gd}
        if g is not None:
            prior = g[g["game_date"] < gd]["minutes"].dropna()
            if len(prior):
                rec["games_played_season"] = len(prior)
                rec["season_avg_minutes"] = prior.mean()
                rec["minutes_rolling_mean_5"] = prior.tail(5).mean()
                rec["minutes_rolling_std_5"] = prior.tail(5).std()
                rec["minutes_rolling_mean_10"] = prior.tail(10).mean()
                # rest days = gap to most recent prior game
                last_dt = g[g["game_date"] < gd]["game_date"].max()
                rec["rest_days"] = (gd - last_dt).days if pd.notna(last_dt) else np.nan
        rec["player_minutes_std_10"] = rec.get("minutes_rolling_std_5", np.nan)
        rec["position"] = pos_map.get(pk, "UNK")
        recs.append(rec)
    prof = pd.DataFrame(recs)
    prof = prof.merge(seasons, on="player_key", how="left").merge(first_season, on="player_key", how="left")
    return prof


def enrich_errors(ds: pd.DataFrame, err: pd.DataFrame) -> pd.DataFrame:
    err = err.copy()
    err["game_date"] = pd.to_datetime(err["game_date"], errors="coerce")
    err["player_key"] = err["player_key"].astype(str).str.lower().str.strip()

    prof = build_player_profiles(err)
    e = err.merge(prof, on=["player_key", "game_date"], how="left")

    # Derived classifications.
    e["role"] = np.where(e["season_avg_minutes"].fillna(0) >= 24, "starter", "bench")
    e["proj_minutes_bucket"] = pd.cut(
        e["projected_minutes"], bins=[-1, 10, 18, 26, 100],
        labels=["<10", "10-18", "18-26", "26+"],
    )
    e["vol_last5"] = e["minutes_rolling_std_5"].fillna(e["player_minutes_std_10"])
    e["volatility_bucket"] = pd.cut(
        e["vol_last5"], bins=[-1, 3, 6, 100],
        labels=["low(<3)", "med(3-6)", "high(6+)"],
    )
    e["experience"] = np.where(e["seasons_played"].fillna(1) <= 1, "rookie", "veteran")
    # Injury-return proxy: large rest gap before the graded game.
    e["injury_return"] = np.where(e["rest_days"].fillna(0) >= 10, "return(10d+ rest)", "normal")
    e["position_grp"] = e["position"].fillna("UNK").replace({"": "UNK"})
    return e


def breakdown(e: pd.DataFrame) -> pd.DataFrame:
    rows = []

    def agg(df, dim, seg):
        if len(df) == 0:
            return
        rows.append({
            "dimension": dim, "segment": str(seg), "n": int(len(df)),
            "minutes_mae": round(df["absolute_error"].mean(), 4),
            "minutes_rmse": round(math.sqrt((df["error"] ** 2).mean()), 4),
            "minutes_bias": round(df["error"].mean(), 4),  # neg = under-projected
            "mean_proj": round(df["projected_minutes"].mean(), 2),
            "mean_actual": round(df["actual_minutes"].mean(), 2),
        })

    agg(e, "overall", "all")
    for dim, col in [("team", "team"), ("role", "role"),
                     ("proj_minutes_bucket", "proj_minutes_bucket"),
                     ("position", "position_grp"), ("volatility", "volatility_bucket"),
                     ("experience", "experience"), ("injury_return", "injury_return")]:
        for seg, df in e.groupby(col, observed=True):
            agg(df, dim, seg)

    out = pd.DataFrame(rows)
    # Sort within dimension by MAE desc to surface worst segments.
    out = out.sort_values(["dimension", "minutes_mae"], ascending=[True, False]).reset_index(drop=True)
    return out


def main():
    ds = pd.read_csv(DATASET, low_memory=False)
    err = pd.read_csv(MIN_ERRORS)
    print(f"dataset rows={len(ds)}  graded minutes rows={len(err)}")

    imp = feature_importance(ds)
    imp.to_csv(REPORTS / "minutes_feature_report.csv", index=False)
    print("\nTop 15 features by tree permutation importance:")
    print(imp[["rank", "feature", "tree_perm_importance_mae", "ridge_abs_coef"]].head(15).to_string(index=False))

    e = enrich_errors(ds, err)
    bd = breakdown(e)
    bd.to_csv(REPORTS / "minutes_error_breakdown.csv", index=False)

    top20 = e.sort_values("absolute_error", ascending=False).head(20)[[
        "slate_date", "player_name", "team", "opponent", "position_grp", "role",
        "projected_minutes", "actual_minutes", "error", "absolute_error",
        "season_avg_minutes", "minutes_rolling_mean_5", "vol_last5",
        "injury_return", "experience",
    ]].round(2)
    top20.to_csv(REPORTS / "minutes_top20_misses.csv", index=False)

    print("\nError breakdown (overall + worst segments per dimension):")
    print(bd.to_string(index=False))
    print("\nTop 20 misses:")
    print(top20.to_string(index=False))

    # match rate of enrichment join
    matched = e["season_avg_minutes"].notna().mean()
    print(f"\nenrichment join match rate (season_avg_minutes present): {matched:.1%}")


if __name__ == "__main__":
    main()
