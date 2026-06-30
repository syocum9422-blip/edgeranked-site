"""Phase 1 — Minutes engine feature builder.

All features are computed STRICTLY from prior games (shift(1) before rolling) so
there is zero leakage from the game being predicted. This is deliberately
independent of the production rolling columns — V2 owns its point-in-time logic.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# Minutes (of a player who appears) at/above this are "meaningful" — Stage A target.
MEANINGFUL_MIN = 12.0

# Feature columns produced (consumed by the models).
NUMERIC_FEATURES = [
    "min_lag1",
    "min_mean3", "min_mean5", "min_mean10",
    "min_std5", "min_std10",
    "min_ewm",
    "min_trend",          # mean3 - mean10 (rising/falling role)
    "min_cv10",           # volatility: std10 / mean10
    "rotation_rank",      # 1 = highest projected minutes on team (from lagged mean5)
    "starter_streak",     # rolling share of recent games started-equivalent (mean5>=24)
    "rest_days",
    "is_back_to_back",
    "is_home",
    "games_played_season",
    "usage_lag5",
    "team_min_share5",    # player's share of team minutes, lagged
]
CATEGORICAL_FEATURES = ["position"]
ALL_FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES


def _lagged_roll(s: pd.Series, w: int, fn: str) -> pd.Series:
    """Rolling stat over the w PRIOR games (excludes current via shift(1))."""
    shifted = s.shift(1)
    r = shifted.rolling(window=w, min_periods=1)
    return getattr(r, fn)()


def build_minutes_features(df: pd.DataFrame) -> pd.DataFrame:
    """Return df augmented with leak-free minutes features + Stage A/B targets.

    Expects raw columns: game_date, player_key, team, minutes, rest_days,
    is_back_to_back, is_home, games_played_season, position, usage_proxy_last_5,
    team_minutes.
    """
    df = df.sort_values(["player_key", "game_date"]).copy()
    g = df.groupby("player_key", group_keys=False)

    df["min_lag1"] = g["minutes"].shift(1)
    df["min_mean3"] = g["minutes"].apply(lambda s: _lagged_roll(s, 3, "mean"))
    df["min_mean5"] = g["minutes"].apply(lambda s: _lagged_roll(s, 5, "mean"))
    df["min_mean10"] = g["minutes"].apply(lambda s: _lagged_roll(s, 10, "mean"))
    df["min_std5"] = g["minutes"].apply(lambda s: _lagged_roll(s, 5, "std"))
    df["min_std10"] = g["minutes"].apply(lambda s: _lagged_roll(s, 10, "std"))
    df["min_ewm"] = g["minutes"].apply(lambda s: s.shift(1).ewm(halflife=3, min_periods=1).mean())
    df["min_trend"] = df["min_mean3"] - df["min_mean10"]
    df["min_cv10"] = df["min_std10"] / df["min_mean10"].clip(lower=1.0)

    # Starter-equivalent streak: share of last 5 prior games with mean-minutes role >= 24.
    started_like = (g["minutes"].shift(1) >= 24).astype(float)
    df["starter_streak"] = started_like.groupby(df["player_key"]).apply(
        lambda s: s.rolling(5, min_periods=1).mean()
    ).reset_index(level=0, drop=True)

    # Team minute share (lagged): player's prior-game minutes / team minutes that game.
    if "team_minutes" in df.columns:
        share = (g["minutes"].shift(1)) / df.groupby("player_key")["team_minutes"].shift(1).clip(lower=1.0)
        df["team_min_share5"] = share.groupby(df["player_key"]).apply(
            lambda s: s.rolling(5, min_periods=1).mean()
        ).reset_index(level=0, drop=True)
    else:
        df["team_min_share5"] = np.nan

    # Usage (use prod's already-lagged proxy if present).
    df["usage_lag5"] = df.get("usage_proxy_last_5", pd.Series(np.nan, index=df.index))

    # Rotation rank within team per game-date, by lagged projected minutes (mean5).
    df["rotation_rank"] = (
        df.groupby(["game_date", "team"])["min_mean5"]
        .rank(ascending=False, method="first")
    )

    for c in ["rest_days", "is_back_to_back", "is_home", "games_played_season"]:
        if c not in df.columns:
            df[c] = np.nan
    if "position" not in df.columns:
        df["position"] = "UNK"
    df["position"] = df["position"].fillna("UNK").astype(str)

    # Targets
    df["y_minutes"] = df["minutes"]
    df["y_meaningful"] = (df["minutes"] >= MEANINGFUL_MIN).astype(int)
    return df


def feature_matrix(df: pd.DataFrame) -> pd.DataFrame:
    return df[ALL_FEATURES].copy()
