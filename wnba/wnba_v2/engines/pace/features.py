"""Phase 2 — pace/possession engine features.

Builds a leak-free GAME-level table (one row per game) from the canonical team
box-score logs. Each team's rolling form is computed from PRIOR games only
(shift(1)), then the two teams are joined into a home/away feature row whose
target is game_possessions (the shared pace both teams experience).

Vegas total/spread are OPTIONAL: if line history exists they merge in as extra
features; otherwise the engine trains without them and they slot in seamlessly
once enough history accrues (per directive — Vegas is additive, never required).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from wnba_v2 import config as C
from wnba_v2.data.team_boxscores import TEAM_GAMES_PATH

GAME_LINES_OPEN_CLOSE = C.V2_ROOT / "data" / "line_history" / "game_open_close.csv"

BASE_FEATURES = [
    "home_pace5", "away_pace5", "home_pace10", "away_pace10",
    "home_off5", "away_off5", "home_def5", "away_def5",
    "home_rest", "away_rest", "home_b2b", "away_b2b",
    "pace_pair_mean5",   # mean of the two teams' rolling pace = strong naive anchor
]
VEGAS_FEATURES = ["vegas_total", "vegas_spread"]   # optional, added if available


def _team_rolling(df: pd.DataFrame) -> pd.DataFrame:
    """Per-team lagged rolling features from prior games only."""
    df = df.sort_values(["team", "date"]).copy()
    g = df.groupby("team", group_keys=False)
    df["pace5"] = g["possessions"].apply(lambda s: s.shift(1).rolling(5, min_periods=1).mean())
    df["pace10"] = g["possessions"].apply(lambda s: s.shift(1).rolling(10, min_periods=1).mean())
    df["off5"] = g["off_rating"].apply(lambda s: s.shift(1).rolling(5, min_periods=1).mean())
    df["def5"] = g["def_rating"].apply(lambda s: s.shift(1).rolling(5, min_periods=1).mean())
    df["prev_date"] = g["date"].shift(1)
    df["rest"] = (pd.to_datetime(df["date"]) - pd.to_datetime(df["prev_date"])).dt.days
    df["b2b"] = (df["rest"] == 1).astype(float)
    return df


def build_pace_features(use_vegas: bool = True) -> pd.DataFrame:
    raw = pd.read_csv(TEAM_GAMES_PATH, parse_dates=["date"])
    tr = _team_rolling(raw)
    home = tr[tr["home_away"] == "home"].copy()
    away = tr[tr["home_away"] == "away"].copy()

    keep = ["game_id", "date", "season", "team", "pace5", "pace10", "off5", "def5", "rest", "b2b",
            "game_possessions", "possessions"]
    h = home[keep].add_prefix("home_").rename(columns={"home_game_id": "game_id",
                                                       "home_date": "date", "home_season": "season",
                                                       "home_game_possessions": "game_possessions"})
    a = away[keep].add_prefix("away_").rename(columns={"away_game_id": "game_id"})
    g = h.merge(a.drop(columns=["away_date", "away_season", "away_game_possessions"]), on="game_id")

    g = g.rename(columns={
        "home_pace5": "home_pace5", "away_pace5": "away_pace5",
        "home_pace10": "home_pace10", "away_pace10": "away_pace10",
        "home_off5": "home_off5", "away_off5": "away_off5",
        "home_def5": "home_def5", "away_def5": "away_def5",
        "home_rest": "home_rest", "away_rest": "away_rest",
        "home_b2b": "home_b2b", "away_b2b": "away_b2b",
    })
    g["pace_pair_mean5"] = (g["home_pace5"] + g["away_pace5"]) / 2.0
    g["target_game_possessions"] = g["game_possessions"]

    if use_vegas and GAME_LINES_OPEN_CLOSE.exists():
        v = pd.read_csv(GAME_LINES_OPEN_CLOSE)
        if {"game_date", "close_total", "close_spread"}.issubset(v.columns):
            v = v.rename(columns={"close_total": "vegas_total", "close_spread": "vegas_spread",
                                  "game_date": "date"})
            g = g.merge(v[["date", "vegas_total", "vegas_spread"]], on="date", how="left")

    return g.sort_values("date").reset_index(drop=True)


def feature_list(df: pd.DataFrame) -> list[str]:
    feats = list(BASE_FEATURES)
    for vf in VEGAS_FEATURES:
        if vf in df.columns and df[vf].notna().mean() > 0.5:
            feats.append(vf)
    return feats
