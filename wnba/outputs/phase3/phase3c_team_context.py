"""Phase 3C: Team Context Upgrade audit (shadow-only).

  - Audits team_context coverage.
  - Builds rolling-5 / rolling-10 / season windows of pace, off_rating, def_rating (shifted).
  - Tests whether rolling team context improves the minutes model vs the current last-10 only.
  - WAS / CHI / GSV deep-dive on minutes error AND stat-projection error.

Writes: team_context_report.csv, team_context_window_test.csv, was_chi_gsv_analysis.csv
"""
from __future__ import annotations

import math
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from wnba_model_utils import feature_columns, build_regression_pipeline, clean_feature_frame  # noqa: E402

HERE = Path(__file__).resolve().parent
WNBA = HERE.parents[1]
CTX = WNBA / "data" / "raw" / "wnba_team_context.csv"
SHADOW_DS = HERE / "shadow" / "wnba_training_dataset_2026.csv"
MIN_ERR = WNBA / "learning" / "errors" / "minutes_errors.csv"
PROJ_ERR = WNBA / "learning" / "errors" / "projection_errors.csv"
OUT = HERE / "reports"
TARGET_TEAMS = ["WAS", "CHI", "GSV"]


def build_context_windows() -> pd.DataFrame:
    t = pd.read_csv(CTX)
    t["game_date"] = pd.to_datetime(t["game_date"], errors="coerce")
    t = t.dropna(subset=["game_date"]).sort_values(["team", "game_date"])
    metrics = ["pace", "off_rating", "def_rating"]
    for col in metrics:
        t[col] = pd.to_numeric(t[col], errors="coerce")
        t[f"{col}_r5"] = t.groupby("team")[col].transform(lambda s: s.shift(1).rolling(5, min_periods=1).mean())
        t[f"{col}_r10"] = t.groupby("team")[col].transform(lambda s: s.shift(1).rolling(10, min_periods=1).mean())
        t[f"{col}_season"] = t.groupby("team")[col].transform(lambda s: s.shift(1).expanding().mean())
    return t


def audit(t: pd.DataFrame):
    metrics = ["pace", "off_rating", "def_rating", "team_rebounds", "team_assists", "team_threes_made"]
    rows = []
    for m in metrics:
        if m in t.columns:
            s = pd.to_numeric(t[m], errors="coerce")
            rows.append({"metric": m, "non_null": int(s.notna().sum()), "coverage_pct": round(100 * s.notna().mean(), 1),
                         "mean": round(s.mean(), 2) if s.notna().any() else np.nan})
    return pd.DataFrame(rows)


def window_test(t: pd.DataFrame):
    """Add rolling-5 team context to variant C; compare 30d minutes MAE vs without."""
    ds = pd.read_csv(SHADOW_DS, low_memory=False)
    ds["game_date"] = pd.to_datetime(ds["game_date"], errors="coerce")
    ctx_cols = ["pace_r5", "off_rating_r5", "def_rating_r5", "pace_season", "off_rating_season", "def_rating_season"]
    ds = ds.merge(t[["team", "game_date", *ctx_cols]], on=["team", "game_date"], how="left")
    ds = ds.dropna(subset=["minutes"])

    roll_min = ["minutes_rolling_mean_3", "minutes_rolling_std_3", "minutes_rolling_mean_5",
                "minutes_rolling_std_5", "minutes_rolling_mean_10", "minutes_rolling_std_10"]
    base = [c for c in feature_columns() if c != "minutes"] + roll_min  # variant C
    configs = {"C (current ctx=last10)": base,
               "C + rolling5 ctx": base + ["pace_r5", "off_rating_r5", "def_rating_r5"],
               "C + season ctx": base + ["pace_season", "off_rating_season", "def_rating_season"]}
    last = ds["game_date"].max()
    cutoff = last - pd.Timedelta(days=29)
    tr, va = ds[ds["game_date"] < cutoff], ds[ds["game_date"] >= cutoff]
    yv = va["minutes"].astype(float).values
    rows = []
    for name, feats in configs.items():
        Xtr = clean_feature_frame(tr, feats); Xv = clean_feature_frame(va, feats)
        ridge, tree, _, _ = build_regression_pipeline(Xtr)
        ridge.fit(Xtr, tr["minutes"].astype(float)); tree.fit(Xtr, tr["minutes"].astype(float))
        p = np.clip((np.clip(ridge.predict(Xv), 0, None) + np.clip(tree.predict(Xv), 0, None)) / 2, 0, None)
        rows.append({"config": name, "valid_rows": len(va), "mae": round(np.abs(p - yv).mean(), 4),
                     "rmse": round(math.sqrt(((p - yv) ** 2).mean()), 4)})
    return pd.DataFrame(rows)


def team_deep_dive(t: pd.DataFrame):
    me = pd.read_csv(MIN_ERR); pe = pd.read_csv(PROJ_ERR)
    rows = []
    league_min = me["absolute_error"].mean()
    league_proj = pe["absolute_error"].mean()
    # latest season-window context per team
    latest = t.sort_values("game_date").groupby("team").tail(1)
    for team in sorted(set(me["team"]) | set(TARGET_TEAMS)):
        mt = me[me["team"] == team]; pt = pe[pe["team"] == team]
        lc = latest[latest["team"] == team]
        rows.append({
            "team": team, "is_target": team in TARGET_TEAMS,
            "n_min": len(mt), "minutes_mae": round(mt["absolute_error"].mean(), 3) if len(mt) else np.nan,
            "minutes_bias": round(mt["error"].mean(), 3) if len(mt) else np.nan,
            "n_proj": len(pt), "proj_mae": round(pt["absolute_error"].mean(), 3) if len(pt) else np.nan,
            "pace_season": round(lc["pace_season"].iloc[0], 2) if len(lc) and lc["pace_season"].notna().any() else np.nan,
            "off_rating_season": round(lc["off_rating_season"].iloc[0], 2) if len(lc) and lc["off_rating_season"].notna().any() else np.nan,
            "def_rating_season": round(lc["def_rating_season"].iloc[0], 2) if len(lc) and lc["def_rating_season"].notna().any() else np.nan,
        })
    df = pd.DataFrame(rows).sort_values("proj_mae", ascending=False)
    return df, league_min, league_proj


def main():
    t = build_context_windows()
    a = audit(t); a.to_csv(OUT / "team_context_report.csv", index=False)
    print("=== Team context coverage audit ===")
    print(a.to_string(index=False))

    wt = window_test(t); wt.to_csv(OUT / "team_context_window_test.csv", index=False)
    print("\n=== Rolling vs season team-context — 30d minutes MAE ===")
    print(wt.to_string(index=False))

    dd, lm, lp = team_deep_dive(t); dd.to_csv(OUT / "was_chi_gsv_analysis.csv", index=False)
    print(f"\nleague minutes MAE={lm:.3f} | league proj MAE={lp:.3f}")
    print("\n=== Per-team minutes & projection error (targets flagged) ===")
    print(dd.to_string(index=False))


if __name__ == "__main__":
    main()
