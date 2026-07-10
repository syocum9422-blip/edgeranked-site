#!/usr/bin/env python3
"""Regression tests for the accuracy-recovery selection layer.

Verifies the production-safety contract:
  1. off    -> published board byte-identical
  2. shadow -> published board byte-identical + sidecar written
  3. on     -> singles-only, gates never weaker than production
  4. any internal failure -> untouched production board
"""
import os
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from accuracy_recovery import recovery_selection as rs

MIN_EDGE, MIN_HIT_RATE = 0.04, 0.56
GATES = dict(min_edge=MIN_EDGE, min_hit_rate=MIN_HIT_RATE,
             max_bets_total=25, max_bets_per_player=2, max_bets_per_stat=6)


def make_candidates(n=60, seed=7):
    rng = np.random.default_rng(seed)
    stats_pool = ["points", "rebounds", "assists", "pra", "pr", "pa", "ra"]
    rows = []
    for i in range(n):
        stat = stats_pool[i % len(stats_pool)]
        mean = rng.uniform(5, 30)
        sd = rng.uniform(2, 6)
        line = mean + rng.normal(0, 2)
        side = "over" if mean > line else "under"
        rows.append({
            "player_name": f"Player {i%20}", "team": "AAA", "opponent": "BBB",
            "stat": stat, "line": round(line, 1), "side": side,
            "hit_rate": rng.uniform(0.5, 0.95), "edge": 0.0,
            "projection_mean": mean, "STDDEV": sd,
            "confidence_score": 2.0, "projected_minutes": rng.uniform(15, 34),
            "line_delta": mean - line, "HIT_RATE": 0.0,
        })
    d = pd.DataFrame(rows)
    d["edge"] = d["hit_rate"] - 0.5
    return d


def run():
    failures = []
    cands = make_candidates()
    prod = cands[(cands.edge >= MIN_EDGE) & (cands.hit_rate >= MIN_HIT_RATE)].head(25).reset_index(drop=True)

    # 1. off -> identical
    os.environ["WNBA_ACCURACY_RECOVERY"] = "off"
    out = rs.maybe_apply_accuracy_recovery(cands, prod, **GATES)
    if not out.equals(prod):
        failures.append("off mode altered the production board")

    # 2. shadow -> identical + sidecar
    os.environ["WNBA_ACCURACY_RECOVERY"] = "shadow"
    sidecar = rs.SHADOW_DIR / f"recovery_board_{date.today().strftime('%Y%m%d')}.csv"
    if sidecar.exists():
        sidecar.unlink()
    out = rs.maybe_apply_accuracy_recovery(cands, prod, **GATES)
    if not out.equals(prod):
        failures.append("shadow mode altered the production board")
    if not sidecar.exists():
        failures.append("shadow mode did not write the sidecar board")

    # 3. on -> contract checks
    os.environ["WNBA_ACCURACY_RECOVERY"] = "on"
    board = rs.maybe_apply_accuracy_recovery(cands, prod, **GATES)
    if len(board):
        if board.stat.astype(str).str.lower().isin(rs.COMBO_STATS).any():
            failures.append("on mode published combo props")
        if (board.hit_rate < MIN_HIT_RATE).any():
            failures.append("on mode weakened MIN_HIT_RATE gate")
        if (board.edge < MIN_EDGE).any():
            failures.append("on mode weakened MIN_EDGE gate")
        if len(board) > 25:
            failures.append("on mode exceeded MAX_BETS_TOTAL")
        if board.groupby("player_name").size().max() > 2:
            failures.append("on mode exceeded MAX_BETS_PER_PLAYER")
    else:
        failures.append("on mode produced empty board on healthy candidates")

    # variance honesty: adjusted hit rates must not exceed raw normal-model rates
    raw_p = []
    from scipy.stats import norm
    for _, r in board.iterrows():
        p_over = 1 - norm.cdf((r.line - r.projection_mean) / max(r.STDDEV, 0.25))
        raw_p.append(p_over if r.side == "over" else 1 - p_over)
    if len(board) and (board.hit_rate.to_numpy() > np.array(raw_p) + 1e-9).any():
        failures.append("adjusted hit_rate exceeds raw hit_rate (inflation must shrink confidence)")

    # 4. failure injection -> fallback
    broken = cands.drop(columns=["STDDEV"])
    out = rs.maybe_apply_accuracy_recovery(broken, prod, **GATES)
    if not out.equals(prod):
        failures.append("failure path did not fall back to production board")

    os.environ.pop("WNBA_ACCURACY_RECOVERY", None)
    if failures:
        print("FAIL")
        for f in failures:
            print(" -", f)
        sys.exit(1)
    print(f"ALL REGRESSION CHECKS PASSED (on-mode board: {len(board)} picks, "
          f"mean adj hit_rate {board.hit_rate.mean():.3f})")


if __name__ == "__main__":
    run()
