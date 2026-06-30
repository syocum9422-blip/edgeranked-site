"""Phase 5 — unified simulation-input spine.

One row per played player-game with everything the Monte Carlo needs, all
leak-free (prior games only) and on a single key (player_id, date):

  minutes  (P1 method): min_mean, min_std, play_prob, typ_min
  pace     (P2):        team_poss_lag (+ shared pace std), opp_poss≈team_poss
  usage    (P3.5):      usage_share_pred (redistribution model)
  context  pools:       reb_pool_lag (team+opp reb), tmfg_pool_lag (teammate FGM)
  efficiency (P4):      <rate>_mean / <rate>_std for every rate (from rate_uncertainty)
"""
from __future__ import annotations

import re

import joblib
import numpy as np
import pandas as pd

from wnba_v2 import config as C
from wnba_v2.data.player_boxscores import PLAYER_GAMES_PATH
from wnba_v2.data.team_boxscores import TEAM_GAMES_PATH
from wnba_v2.engines.usage.features import ESPN_TO_PLAYER, REAL_TEAMS
from wnba_v2.engines.usage.roles import build_redistribution_frame

RATE_UNC = C.OUTPUTS / "efficiency" / "rate_uncertainty.csv"
REDIS_MODEL = C.OUTPUTS / "usage" / "redistribution_model_v2.joblib"
PACE_STD = 4.7   # game-possession residual std from Phase 2


def norm_name(s) -> str:
    return re.sub(r"[^a-z]", "", str(s).lower())


def fix_play_prob(spine: pd.DataFrame) -> pd.DataFrame:
    """Rotation regulars (the bet population) play almost every game. The raw rolling
    played-rate is dragged low by the 16.8% league-wide DNP base rate, which zeroed
    too many sims. Floor play_prob by recent minutes (true availability comes from the
    injury report in production)."""
    floor = np.select(
        [spine["min_mean"] >= 24, spine["min_mean"] >= 16, spine["min_mean"] >= 10],
        [0.98, 0.95, 0.90], default=0.75)
    spine["play_prob"] = np.maximum(spine["play_prob"].fillna(0.9), floor).clip(0.3, 1.0)
    return spine


def _minutes_lags() -> pd.DataFrame:
    pg = pd.read_csv(PLAYER_GAMES_PATH, parse_dates=["date"]).sort_values(["player_id", "date"])
    g = pg.groupby("player_id", group_keys=False)
    pg["min_mean"] = g["minutes"].apply(lambda s: s.shift(1).rolling(5, min_periods=1).mean())
    pg["min_std"] = g["minutes"].apply(lambda s: s.shift(1).rolling(8, min_periods=2).std())
    pg["play_prob"] = g["played"].apply(lambda s: s.shift(1).rolling(10, min_periods=1).mean())
    return pg[pg["played"] == 1][["player_id", "date", "min_mean", "min_std", "play_prob"]]


def _team_pools() -> pd.DataFrame:
    tg = pd.read_csv(TEAM_GAMES_PATH, parse_dates=["date"])
    tg["team"] = tg["team"].replace(ESPN_TO_PLAYER)
    tg["opponent"] = tg["opponent"].replace(ESPN_TO_PLAYER)
    tg = tg[tg["team"].isin(REAL_TEAMS) & tg["opponent"].isin(REAL_TEAMS)].copy()
    # opponent rebounds via self-join on (date, opponent)
    opp = tg[["date", "team", "reb"]].rename(columns={"team": "opponent", "reb": "opp_reb"})
    tg = tg.merge(opp, on=["date", "opponent"], how="left")
    tg["reb_pool"] = tg["reb"] + tg["opp_reb"].fillna(tg["reb"])
    tg = tg.sort_values(["team", "date"])
    g = tg.groupby("team", group_keys=False)
    tg["team_poss_lag"] = g["possessions"].apply(lambda s: s.shift(1).rolling(10, min_periods=1).mean())
    tg["reb_pool_lag"] = g["reb_pool"].apply(lambda s: s.shift(1).rolling(10, min_periods=1).mean())
    tg["tmfg_pool_lag"] = g["fgm"].apply(lambda s: s.shift(1).rolling(10, min_periods=1).mean())
    return tg[["date", "team", "team_poss_lag", "reb_pool_lag", "tmfg_pool_lag"]].drop_duplicates(["date", "team"])


def build_spine() -> pd.DataFrame:
    base = build_redistribution_frame()                      # played rows + P3.5 features
    # P3.5 usage projection (leak-free: features are all lagged)
    if REDIS_MODEL.exists():
        model = joblib.load(REDIS_MODEL)
        base = base.dropna(subset=model.features).copy()
        base["usage_share_pred"] = model.predict_raw(base)["usage_share"].clip(0, 0.45).values
    else:
        base["usage_share_pred"] = base["usage_share_lag5"].fillna(0.1)

    spine = base[["player_id", "player_name", "date", "team", "season",
                  "usage_share_pred", "n_regulars_out", "star_out"]].copy()
    spine = spine.merge(_minutes_lags(), on=["player_id", "date"], how="left")
    spine = spine.merge(_team_pools(), on=["team", "date"], how="left")

    ru = pd.read_csv(RATE_UNC, parse_dates=["date"])
    rate_cols = [c for c in ru.columns if c.endswith("_mean") or c.endswith("_std")]
    spine = spine.merge(ru[["player_id", "date"] + rate_cols], on=["player_id", "date"], how="left")

    spine["typ_min"] = spine["min_mean"].clip(lower=5)
    spine["min_std"] = spine["min_std"].fillna(5.0).clip(2.0, 12.0)
    spine = fix_play_prob(spine)
    spine["name_key"] = spine["player_name"].map(norm_name)
    return spine.dropna(subset=["min_mean", "team_poss_lag", "points_mean"]).reset_index(drop=True)
