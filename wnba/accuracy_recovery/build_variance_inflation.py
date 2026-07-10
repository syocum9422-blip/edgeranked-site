#!/usr/bin/env python3
"""Compute per-market variance-inflation factors from trailing board-vs-actual data.

Writes accuracy_recovery/variance_inflation.json. Offline/manual (or cron later);
never touches production outputs. Factors = std of realized z-scores
((actual - proj) / sim_std) over the trailing window, clipped to [1.0, 2.5].
"""
import glob
import json
import os
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
WINDOW_DAYS = 30
MIN_SAMPLES = 60
CLIP = (1.0, 2.5)

MK = {"points": "PTS", "rebounds": "REB", "assists": "AST", "threes_made": "FG3M",
      "steals": "STL", "blocks": "BLK", "pra": "PRA", "pr": "PR", "pa": "PA", "ra": "RA"}
COMBO_PARTS = {"pra": ["points", "rebounds", "assists"], "pr": ["points", "rebounds"],
               "pa": ["points", "assists"], "ra": ["rebounds", "assists"]}


def main() -> None:
    pg = pd.read_csv(f"{ROOT}/data/raw/wnba_player_games.csv", parse_dates=["game_date"])
    for combo, parts in COMBO_PARTS.items():
        pg[combo] = sum(pg[p] for p in parts)

    cutoff = pd.Timestamp(datetime.now(timezone.utc).date()) - timedelta(days=WINDOW_DAYS)
    zs = {m: [] for m in MK}
    for f in sorted(glob.glob(f"{ROOT}/outputs/archive/projections/wnba_projections_*.csv")):
        try:
            day = pd.to_datetime(os.path.basename(f)[17:25])
        except ValueError:
            continue
        if day < cutoff:
            continue
        try:
            board = pd.read_csv(f)
        except Exception:
            continue
        if "PLAYER_KEY" not in board.columns:
            continue
        m = board.merge(pg[pg.game_date == day], left_on="PLAYER_KEY", right_on="player_key")
        m = m[m.minutes > 0]
        for mk, key in MK.items():
            pcol, scol = f"{key}_PROJ", f"SIM_{key}_STD"
            if mk in m.columns and pcol in m.columns and scol in m.columns:
                z = (m[mk] - m[pcol]) / m[scol].clip(lower=0.25)
                zs[mk].extend(z.dropna().tolist())

    factors = {}
    for mk, vals in zs.items():
        if len(vals) >= MIN_SAMPLES:
            factors[mk] = round(float(np.clip(np.std(vals), *CLIP)), 3)
    fallback = round(float(np.median(list(factors.values()))), 3) if factors else 1.8

    out = {
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window_days": WINDOW_DAYS,
        "fallback": fallback,
        "factors": factors,
        "n_samples": {mk: len(v) for mk, v in zs.items()},
    }
    path = os.path.join(HERE, "variance_inflation.json")
    with open(path, "w") as fh:
        json.dump(out, fh, indent=2)
    print(f"wrote {path}: {factors} fallback={fallback}")


if __name__ == "__main__":
    main()
