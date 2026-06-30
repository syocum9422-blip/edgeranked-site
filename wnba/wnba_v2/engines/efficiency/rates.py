"""Phase 4 — efficiency rate targets + leak-free features.

Models RATES PER OPPORTUNITY, never totals. Minutes is used ONLY to construct each
rate's opportunity denominator (how the rate is defined and how Phase 5 reconstructs
the stat); it is NEVER a model feature. The simulator computes
    stat = rate x opportunity,  opportunity = f(projected minutes, pace, usage)
so the efficiency models must predict the minutes-independent rate from skill /
role / matchup signal only.

Rate targets:
  points   : pts / poss_used            (poss_used = fga + 0.44*fta + tov)
  rebounds : reb / reb_opp              (reb_opp = (team_reb+opp_reb) * min/40)
  assists  : ast / tmfg_opp             (tmfg_opp = (team_fgm-player_fgm) * min/40)
  fg3a     : fg3a / poss_used           (3PA rate; 3PM = fg3a_rate * fg3_pct)
  fg3_pct  : fg3m / fg3a                (proportion -> Bayesian)
  steals   : stl / def_poss             (def_poss = opp_poss * min/40)
  blocks   : blk / def_poss
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from wnba_v2 import config as C
from wnba_v2.data.player_boxscores import PLAYER_GAMES_PATH
from wnba_v2.data.team_boxscores import TEAM_GAMES_PATH
from wnba_v2.engines.usage.features import ESPN_TO_PLAYER, REAL_TEAMS

# name -> (numerator col, denominator key, model family)
RATE_SPECS = {
    "points":   ("points", "poss_used", "gbm"),
    "rebounds": ("reb",    "reb_opp",   "gbm"),
    "assists":  ("ast",    "tmfg_opp",  "gbm"),
    "fg3a":     ("fg3a",   "poss_used", "gbm"),
    "steals":   ("stl",    "def_poss",  "bayes"),
    "blocks":   ("blk",    "def_poss",  "bayes"),
    "fg3_pct":  ("fg3m",   "fg3a",      "bayes_beta"),
}
GBM_RATES = [r for r, s in RATE_SPECS.items() if s[2] == "gbm"]
BAYES_RATES = [r for r, s in RATE_SPECS.items() if s[2] != "gbm"]

CONTEXT_FEATURES = ["pos_G", "pos_F", "pos_C", "prior_games", "opp_def_rating_lag",
                    "opp_pace_lag", "is_home"]


def _team_context() -> pd.DataFrame:
    tg = pd.read_csv(TEAM_GAMES_PATH, parse_dates=["date"])
    tg["team"] = tg["team"].replace(ESPN_TO_PLAYER)
    tg = tg[tg["team"].isin(REAL_TEAMS)].copy().sort_values(["team", "date"])
    g = tg.groupby("team", group_keys=False)
    tg["def_rating_lag"] = g["def_rating"].apply(lambda s: s.shift(1).rolling(10, min_periods=1).mean())
    tg["pace_lag"] = g["possessions"].apply(lambda s: s.shift(1).rolling(10, min_periods=1).mean())
    return tg


def build_rate_frame() -> pd.DataFrame:
    pg = pd.read_csv(PLAYER_GAMES_PATH, parse_dates=["date"])
    pg = pg[pg["played"] == 1].copy()
    tg = _team_context()

    den = tg[["date", "team", "possessions", "opp_possessions", "reb", "fgm", "home_away",
              "def_rating_lag", "pace_lag"]].rename(
        columns={"possessions": "team_poss", "opp_possessions": "opp_poss",
                 "reb": "team_reb", "fgm": "team_fgm"})
    opp = tg[["date", "team", "reb", "def_rating_lag", "pace_lag"]].rename(
        columns={"team": "opponent", "reb": "opp_reb",
                 "def_rating_lag": "opp_def_rating_lag", "pace_lag": "opp_pace_lag"})
    df = pg.merge(den, on=["date", "team"], how="inner").merge(opp, on=["date", "opponent"], how="inner")

    mf = (df["minutes"] / 40.0).clip(0.05, 1.3)          # minutes used ONLY for denominators
    df["poss_used"] = (df["fga"] + 0.44 * df["fta"] + df["tov"]).clip(lower=1)
    df["reb_opp"] = ((df["team_reb"] + df["opp_reb"]) * mf).clip(lower=1)
    df["tmfg_opp"] = ((df["team_fgm"] - df["fgm"]).clip(lower=0) * mf).clip(lower=1)
    df["def_poss"] = (df["opp_poss"] * mf).clip(lower=1)

    # rate targets
    for name, (num, den_key, fam) in RATE_SPECS.items():
        if fam == "bayes_beta":
            df[f"rate_{name}"] = df[num] / df[den_key].replace(0, np.nan)   # 3P%
        else:
            df[f"rate_{name}"] = df[num] / df[den_key]

    # context features
    df["pos_G"] = (df["position"] == "G").astype(int)
    df["pos_F"] = (df["position"] == "F").astype(int)
    df["pos_C"] = (df["position"] == "C").astype(int)
    df["is_home"] = (df["home_away"] == "home").astype(int)
    df = df.sort_values(["player_id", "date"])
    df["prior_games"] = df.groupby("player_id").cumcount()    # experience / rookie signal

    # leak-free lagged rate features (the primary predictor of each rate)
    g = df.groupby("player_id", group_keys=False)
    lag = {}
    for name in RATE_SPECS:
        r = f"rate_{name}"
        lag[f"{name}_lag5"] = g[r].apply(lambda s: s.shift(1).rolling(5, min_periods=1).mean())
        lag[f"{name}_lag10"] = g[r].apply(lambda s: s.shift(1).rolling(10, min_periods=1).mean())
        lag[f"{name}_lstd10"] = g[r].apply(lambda s: s.shift(1).rolling(10, min_periods=2).std())
    # Cumulative PRIOR counts for Bayesian partial pooling (leak-free expanding sums).
    cum = {}
    cum["cum_stl"] = g["stl"].apply(lambda s: s.shift(1).expanding().sum())
    cum["cum_blk"] = g["blk"].apply(lambda s: s.shift(1).expanding().sum())
    cum["cum_defposs"] = g["def_poss"].apply(lambda s: s.shift(1).expanding().sum())
    cum["cum_fg3m"] = g["fg3m"].apply(lambda s: s.shift(1).expanding().sum())
    cum["cum_fg3a"] = g["fg3a"].apply(lambda s: s.shift(1).expanding().sum())
    df = pd.concat([df, pd.DataFrame(lag, index=df.index), pd.DataFrame(cum, index=df.index)], axis=1)
    return df.reset_index(drop=True)


def gbm_features(name: str) -> list[str]:
    return [f"{name}_lag5", f"{name}_lag10", f"{name}_lstd10"] + CONTEXT_FEATURES
