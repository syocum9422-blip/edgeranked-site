"""Phase 3 — usage/role engine features (full-roster, exact conservation).

Shares are computed from the FULL ESPN player box scores (player_game_logs.csv),
so the team-sum of every share equals 1 by construction — real conservation, not
the ~13% coverage the curated subset gave. Each share's denominator is the team
total summed over players who played that game.

Shares modeled (all conserved within the active roster):
  usage_share = (fga + 0.44*fta + tov) / team-sum(...)
  shot_share  = fga / team_fga
  ft_share    = fta / team_fta
  ast_share   = ast / team_ast
  reb_share   = reb / team_reb
  fg3m_share  = fg3m / team_fg3m
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from wnba_v2 import config as C

PLAYER_GAMES_PATH = C.V2_ROOT / "data" / "team_games" / "player_game_logs.csv"

# ESPN team code -> player-dataset code (real franchises only).
ESPN_TO_PLAYER = {"GS": "GSV", "LA": "LAS", "LV": "LVA", "NY": "NYL", "WSH": "WAS"}
REAL_TEAMS = {"ATL", "CHI", "CON", "DAL", "GSV", "IND", "LAS", "LVA", "MIN",
              "NYL", "PHX", "POR", "SEA", "TOR", "WAS"}

SHARE_COLS = ["usage_share", "shot_share", "ft_share", "ast_share", "reb_share", "fg3m_share"]
# numerator -> team-denominator stat for each share
_NUM_DEN = {
    "shot_share": ("fga", "fga"), "ft_share": ("fta", "fta"),
    "ast_share": ("ast", "ast"), "reb_share": ("reb", "reb"),
    "fg3m_share": ("fg3m", "fg3m"),
}


def build_usage_features() -> pd.DataFrame:
    df = pd.read_csv(PLAYER_GAMES_PATH, parse_dates=["date"])
    played = df[df["played"] == 1].copy()
    played["usage_num"] = played["fga"] + 0.44 * played["fta"] + played["tov"]

    # team totals over players who played (the conservation denominators)
    agg = {"usage_num": "sum", "fga": "sum", "fta": "sum", "ast": "sum",
           "reb": "sum", "fg3m": "sum", "minutes": "sum"}
    team = played.groupby(["game_id", "team"]).agg(agg).add_prefix("team_").reset_index()
    played = played.merge(team, on=["game_id", "team"], how="left")

    shares = {"usage_share": played["usage_num"] / played["team_usage_num"].clip(lower=1)}
    for col, (num, den) in _NUM_DEN.items():
        shares[col] = played[num] / played[f"team_{den}"].clip(lower=1)
    played["minutes_share"] = played["minutes"] / played["team_minutes"].clip(lower=1)
    played = pd.concat([played, pd.DataFrame(shares, index=played.index)], axis=1)

    # leak-free lagged share/minutes form (prior games only)
    played = played.sort_values(["player_id", "date"])
    g = played.groupby("player_id", group_keys=False)
    lag = {}
    for c in SHARE_COLS + ["minutes_share"]:
        lag[f"{c}_lag5"] = g[c].apply(lambda s: s.shift(1).rolling(5, min_periods=1).mean())
        lag[f"{c}_lag10"] = g[c].apply(lambda s: s.shift(1).rolling(10, min_periods=1).mean())
    played = pd.concat([played, pd.DataFrame(lag, index=played.index)], axis=1)

    # rotation rank within team-game by lagged minutes share (1 = biggest role)
    played["rotation_rank"] = played.groupby(["game_id", "team"])["minutes_share_lag5"] \
        .rank(ascending=False, method="first")
    return played.reset_index(drop=True)


def conservation_check(df: pd.DataFrame, share_col: str) -> pd.Series:
    """Team-sum of a raw share per game — should be ~1.0 everywhere (sanity)."""
    return df.groupby(["game_id", "team"])[share_col].sum()
