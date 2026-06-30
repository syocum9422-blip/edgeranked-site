"""Phase 5.1 — per-stat affine scale calibration.

Removes the simulator's aggregate scale bias by matching simulated stat means to
realized means on a TRAINING window. Fit on train, applied to the OOS eval. Combos
inherit the fix automatically (they are summed from calibrated base stats).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from wnba_v2.data.player_boxscores import PLAYER_GAMES_PATH
from wnba_v2.engines.simulation.engine import simulate_player

BASE = {"points": "points", "rebounds": "reb", "assists": "ast",
        "threes_made": "fg3m", "steals": "stl", "blocks": "blk"}


def join_actuals(spine: pd.DataFrame) -> pd.DataFrame:
    pg = pd.read_csv(PLAYER_GAMES_PATH, parse_dates=["date"])
    act = pg[pg["played"] == 1][["player_id", "date"] + list(BASE.values())].copy()
    act = act.rename(columns={v: f"act_{k}" for k, v in BASE.items()})
    return spine.merge(act, on=["player_id", "date"], how="left")


def compute_calibration(train_spine: pd.DataFrame, rng, n_sims: int = 800,
                        sample: int = 1500) -> dict:
    ts = join_actuals(train_spine).dropna(subset=[f"act_{s}" for s in BASE])
    if len(ts) > sample:
        ts = ts.sample(sample, random_state=0)
    sim_sum = {s: 0.0 for s in BASE}
    act_sum = {s: 0.0 for s in BASE}
    for _, r in ts.iterrows():
        out = simulate_player(r, n_sims, rng)
        for s in BASE:
            sim_sum[s] += float(out[s].mean())
            act_sum[s] += float(r[f"act_{s}"])
    calib = {s: round(act_sum[s] / sim_sum[s], 4) if sim_sum[s] > 0 else 1.0 for s in BASE}
    return calib
