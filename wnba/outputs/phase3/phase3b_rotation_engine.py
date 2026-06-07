"""Phase 3B: Rotation Stability Engine (shadow-only).

Builds, for every player-game in the league log, a rotation-stability feature row using
ONLY prior games (no leakage), and classifies each player. Produces:
  - rotation_features.csv               (per player-game; feeds shadow minutes model & 3D)
  - rotation_classification_report.csv  (current snapshot, one row per active player)

Starter is proxied as: among the top-5 in minutes on the player's team that game.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
WNBA = HERE.parents[1]
GAMELOG = WNBA / "data" / "raw" / "wnba_player_games.csv"
OUT = HERE / "reports"
OUT.mkdir(parents=True, exist_ok=True)


def load_log() -> pd.DataFrame:
    log = pd.read_csv(GAMELOG, low_memory=False)
    log["game_date"] = pd.to_datetime(log["game_date"], errors="coerce")
    log["player_key"] = log["player_name"].astype(str).str.lower().str.strip()
    log["minutes"] = pd.to_numeric(log["minutes"], errors="coerce")
    log = log.dropna(subset=["game_date", "minutes"]).copy()
    # usage proxy (per game) for usage-trend feature
    for c in ["points", "assists", "rebounds", "threes_made"]:
        log[c] = pd.to_numeric(log.get(c), errors="coerce").fillna(0)
    log["usage_proxy"] = (log["points"] + 1.2 * log["assists"] + 0.7 * log["rebounds"]
                          + 0.6 * log["threes_made"]) / log["minutes"].replace(0, np.nan)
    log["usage_proxy"] = log["usage_proxy"].replace([np.inf, -np.inf], np.nan).fillna(0)
    # starter proxy: top-5 minutes on team that game
    log = log.sort_values(["game_date", "team", "minutes"], ascending=[True, True, False])
    log["team_min_rank"] = log.groupby(["game_date", "team"]).cumcount() + 1
    log["started"] = (log["team_min_rank"] <= 5).astype(int)
    return log.sort_values(["player_key", "game_date"]).reset_index(drop=True)


def _consecutive(series_vals: list[int], target: int) -> int:
    """Count trailing consecutive entries equal to target (most recent backwards)."""
    n = 0
    for v in reversed(series_vals):
        if v == target:
            n += 1
        else:
            break
    return n


def build_features(log: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for pk, g in log.groupby("player_key"):
        g = g.sort_values("game_date")
        mins = g["minutes"].tolist()
        starts = g["started"].tolist()
        usage = g["usage_proxy"].tolist()
        dates = g["game_date"].tolist()
        for i in range(len(g)):
            prior_m = mins[:i]
            prior_s = starts[:i]
            prior_u = usage[:i]
            rec = {
                "player_key": pk,
                "player_name": g.iloc[i]["player_name"],
                "team": g.iloc[i]["team"],
                "game_date": dates[i],
                "actual_minutes": mins[i],
                "n_prior_games": len(prior_m),
            }
            if prior_m:
                last3, last5, last10 = prior_m[-3:], prior_m[-5:], prior_m[-10:]
                rec["min_avg_3"] = float(np.mean(last3))
                rec["min_avg_5"] = float(np.mean(last5))
                rec["min_avg_10"] = float(np.mean(last10))
                rec["min_std_5"] = float(np.std(last5, ddof=1)) if len(last5) > 1 else 0.0
                rec["min_std_10"] = float(np.std(last10, ddof=1)) if len(last10) > 1 else 0.0
                rec["starts_last_10"] = int(np.sum(prior_s[-10:]))
                rec["consec_starts"] = _consecutive(prior_s, 1)
                rec["consec_bench"] = _consecutive(prior_s, 0)
                rec["minutes_trend"] = rec["min_avg_3"] - rec["min_avg_10"]
                rec["usage_trend"] = (float(np.mean(prior_u[-3:])) - float(np.mean(prior_u[-10:]))) if prior_u else 0.0
                last_dt = dates[i - 1]
                rec["days_since_last"] = (dates[i] - last_dt).days
                rec["availability"] = "return" if rec["days_since_last"] >= 10 else "active"
            rows.append(rec)
    df = pd.DataFrame(rows)
    return df


def classify(r: pd.Series) -> str:
    """Classify a player-game by its rotation-stability profile."""
    if r.get("n_prior_games", 0) < 2 or pd.isna(r.get("min_avg_5")):
        return "Bench Flyer"  # insufficient history; treat as uncertain
    if r.get("availability") == "return":
        return "Injury Return"
    avg5 = r["min_avg_5"]; std5 = r.get("min_std_5", 0); starts10 = r.get("starts_last_10", 0)
    if avg5 >= 24 and std5 <= 5 and starts10 >= 7:
        return "Stable Starter"
    if avg5 >= 18 and std5 <= 5:
        return "Stable Rotation"
    if std5 >= 7:
        return "Volatile Rotation"
    if avg5 < 14:
        return "Bench Flyer"
    if r.get("minutes_trend", 0) <= -5 or r.get("consec_bench", 0) >= 2:
        return "Minutes Risk"
    return "Stable Rotation"


def main():
    log = load_log()
    feats = build_features(log)
    feats["rotation_class"] = feats.apply(classify, axis=1)
    feats.to_csv(OUT / "rotation_features.csv", index=False)

    # Current snapshot: latest row per player, restricted to players active in 2026.
    cur = feats[feats["game_date"] >= "2026-05-01"].sort_values("game_date").groupby("player_key").tail(1)
    cols = ["player_name", "team", "game_date", "min_avg_3", "min_avg_5", "min_avg_10",
            "min_std_5", "min_std_10", "starts_last_10", "consec_starts", "consec_bench",
            "minutes_trend", "usage_trend", "availability", "rotation_class"]
    snap = cur.reindex(columns=cols).sort_values(["rotation_class", "min_avg_5"], ascending=[True, False]).round(2)
    snap.to_csv(OUT / "rotation_classification_report.csv", index=False)

    print(f"rotation_features rows: {len(feats)}  | snapshot players: {len(snap)}")
    print("\nClassification distribution (current snapshot):")
    print(snap["rotation_class"].value_counts().to_string())
    print("\nSample of each class:")
    for cls in snap["rotation_class"].unique():
        s = snap[snap["rotation_class"] == cls].head(3)
        print(f"\n[{cls}]")
        print(s[["player_name", "team", "min_avg_5", "min_std_5", "starts_last_10",
                 "consec_starts", "consec_bench", "availability"]].to_string(index=False))


if __name__ == "__main__":
    main()
