"""Phase 3D: Minutes Floor/Ceiling model (shadow-only, side-by-side).

For each validation player-game (30d window) produces expected / floor / ceiling / volatility,
using the shadow expected minutes (variant C) and the rotation-engine last-5 volatility.

Compares two interval methods against realized minutes:
  - FIXED   : constant league std (volatility-blind) -> nominal 80% interval
  - VOLAWARE: per-player volatility from rotation engine -> nominal 80% interval
Reports empirical coverage (should ~0.80), mean interval width, and width for stable vs
volatile players. Range-aware is better if it holds coverage while tightening stable players.

Writes: minutes_range_report.csv, volatility_report.csv, floor_ceiling_validation.csv
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
WNBA = HERE.parents[1]
PREDS = HERE / "reports" / "shadow_minutes_predictions.csv"
ROT = HERE / "reports" / "rotation_features.csv"
OUT = HERE / "reports"
Z80 = 1.2816  # nominal 80% two-sided


def main():
    p = pd.read_csv(PREDS)
    p = p[p["window_days"] == 30].copy()
    p["game_date"] = pd.to_datetime(p["game_date"], errors="coerce")
    rot = pd.read_csv(ROT)
    rot["game_date"] = pd.to_datetime(rot["game_date"], errors="coerce")
    rot["player_key"] = rot["player_name"].astype(str).str.lower().str.strip()
    df = p.merge(rot[["player_key", "game_date", "min_std_5", "min_std_10", "rotation_class"]],
                 on=["player_key", "game_date"], how="left")

    df["expected"] = df["pred_C_plus_rolling_min"]
    df["actual"] = df["minutes"]
    league_std = float(df["min_std_5"].median())
    df["volatility"] = df["min_std_5"].fillna(league_std).clip(lower=1.5)

    # Two interval methods.
    df["fixed_floor"] = (df["expected"] - Z80 * league_std).clip(lower=0)
    df["fixed_ceiling"] = (df["expected"] + Z80 * league_std).clip(upper=40)
    df["vol_floor"] = (df["expected"] - Z80 * df["volatility"]).clip(lower=0)
    df["vol_ceiling"] = (df["expected"] + Z80 * df["volatility"]).clip(upper=40)

    def cov(lo, hi):
        return float(((df["actual"] >= df[lo]) & (df["actual"] <= df[hi])).mean())

    def width(lo, hi):
        return float((df[hi] - df[lo]).mean())

    report = pd.DataFrame([
        {"method": "FIXED (league std)", "nominal": 0.80, "empirical_coverage": round(cov("fixed_floor", "fixed_ceiling"), 4),
         "mean_width": round(width("fixed_floor", "fixed_ceiling"), 3)},
        {"method": "VOLAWARE (per-player)", "nominal": 0.80, "empirical_coverage": round(cov("vol_floor", "vol_ceiling"), 4),
         "mean_width": round(width("vol_floor", "vol_ceiling"), 3)},
    ])
    report.to_csv(OUT / "floor_ceiling_validation.csv", index=False)

    # Width by stability: volatility-aware should tighten stable, widen volatile.
    df["stable"] = np.where(df["volatility"] <= 4, "stable(<=4)", np.where(df["volatility"] >= 7, "volatile(>=7)", "mid"))
    vol_rows = []
    for seg, g in df.groupby("stable"):
        vol_rows.append({
            "volatility_segment": seg, "n": len(g),
            "fixed_width": round((g["fixed_ceiling"] - g["fixed_floor"]).mean(), 2),
            "volaware_width": round((g["vol_ceiling"] - g["vol_floor"]).mean(), 2),
            "fixed_coverage": round((((g["actual"] >= g["fixed_floor"]) & (g["actual"] <= g["fixed_ceiling"]))).mean(), 3),
            "volaware_coverage": round((((g["actual"] >= g["vol_floor"]) & (g["actual"] <= g["vol_ceiling"]))).mean(), 3),
        })
    volrep = pd.DataFrame(vol_rows)
    volrep.to_csv(OUT / "volatility_report.csv", index=False)

    # Per-row range report (sample saved fully).
    rng = df[["player_name", "team", "game_date", "rotation_class", "expected", "vol_floor",
              "vol_ceiling", "volatility", "actual"]].round(2)
    rng = rng.rename(columns={"vol_floor": "floor", "vol_ceiling": "ceiling"})
    rng.to_csv(OUT / "minutes_range_report.csv", index=False)

    print(f"validation rows: {len(df)} | league median last-5 std: {league_std:.2f}")
    print("\n=== Floor/ceiling 80% interval calibration ===")
    print(report.to_string(index=False))
    print("\n=== Width & coverage by volatility segment ===")
    print(volrep.to_string(index=False))
    print("\n=== Sample range report ===")
    print(rng.sort_values("volatility", ascending=False).head(10).to_string(index=False))


if __name__ == "__main__":
    main()
