"""Phase 5 — correlated Monte Carlo engine.

Totals are OUTPUTS. For each player-game we draw, per simulation:
  minutes  (P1)  : Normal(min_mean, min_std), gated by a Bernoulli play draw
  pace     (P2)  : shared game possession draw (one per game -> teammate/game corr)
  usage    (P3.5): usage_share with noise -> poss_used = usage*pace*min_mult
  efficiency(P4) : per-stat rate draws; counts via Poisson/Binomial
Then stat = rate x opportunity. WITHIN-PLAYER CORRELATION is induced by sharing the
SAME minutes / pace / usage draws across all of that player's stats, so a big night
lifts points+rebounds+assists together — which is what makes PA/PR/PRA correct.

Combos are summed per-simulation from the correlated draws (never from marginals).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

STATS = ["points", "rebounds", "assists", "threes_made", "steals", "blocks"]
COMBOS = {"pa": ["points", "assists"], "pr": ["points", "rebounds"],
          "ra": ["rebounds", "assists"], "pra": ["points", "rebounds", "assists"]}


def _tn(mean, std, n, rng, lo=0.0):
    """Truncated-at-lo normal draw."""
    return np.clip(rng.normal(mean, max(std, 1e-4), n), lo, None)


def simulate_player(row, n_sims: int, rng, shared_pace=None, calib=None) -> dict:
    """Return {stat: ndarray(n_sims)} including combos, for one player-game row.

    `calib` (optional) is a dict of per-stat multiplicative scale factors fit on a
    training window (Phase 5.1) that removes the simulator's aggregate scale bias.
    Applied to the base stats BEFORE combos are summed, so combos inherit the fix."""
    # --- shared latent draws (drive cross-stat correlation) ---
    plays = rng.random(n_sims) < float(row["play_prob"])
    minutes = _tn(row["min_mean"], row["min_std"], n_sims, rng) * plays
    court = np.clip(minutes / 40.0, 0, 1.2)
    min_mult = np.clip(minutes / max(float(row["typ_min"]), 5.0), 0, 2.5)

    pace = shared_pace if shared_pace is not None else _tn(row["team_poss_lag"], 4.7, n_sims, rng)
    usage = np.clip(rng.normal(float(row["usage_share_pred"]), 0.02, n_sims), 0.0, 0.5)
    poss_used = np.clip(usage * pace * min_mult, 0, None)

    # --- efficiency draws x opportunity ---
    pts_rate = _tn(row["points_mean"], row["points_std"], n_sims, rng)
    points = pts_rate * poss_used

    reb_rate = _tn(row["rebounds_mean"], row["rebounds_std"], n_sims, rng)
    rebounds = reb_rate * float(row["reb_pool_lag"]) * court

    ast_rate = _tn(row["assists_mean"], row["assists_std"], n_sims, rng)
    assists = ast_rate * float(row["tmfg_pool_lag"]) * court

    # 3PM = Binomial(3PA, 3P%)  -> correct discrete count
    fg3a_rate = _tn(row["fg3a_mean"], row["fg3a_std"], n_sims, rng)
    fg3a = np.maximum(np.round(fg3a_rate * poss_used).astype(int), 0)
    fg3pct = np.clip(rng.normal(row["fg3_pct_mean"], max(row["fg3_pct_std"], 0.02), n_sims), 0.02, 0.95)
    threes = rng.binomial(fg3a, fg3pct)

    # steals / blocks = Poisson(rate x defensive possessions x court)  -> correct dispersion
    def_poss = pace * court
    steals = rng.poisson(np.clip(row["steals_mean"], 0, None) * def_poss)
    blocks = rng.poisson(np.clip(row["blocks_mean"], 0, None) * def_poss)

    out = {"points": points, "rebounds": rebounds, "assists": assists,
           "threes_made": threes.astype(float), "steals": steals.astype(float),
           "blocks": blocks.astype(float)}
    if calib:
        for s in list(out):
            out[s] = out[s] * float(calib.get(s, 1.0))   # remove aggregate scale bias
    for name, parts in COMBOS.items():
        out[name] = sum(out[p] for p in parts)   # summed per-sim -> correct combo variance
    return out


def prob_over(samples: np.ndarray, line: float) -> float:
    """P(stat > line); pushes (== line) split, matching over/under grading."""
    over = float(np.mean(samples > line))
    push = float(np.mean(np.isclose(samples, line)))
    return over + 0.5 * push


def summarize(samples: np.ndarray) -> dict:
    return {"mean": float(samples.mean()), "p10": float(np.percentile(samples, 10)),
            "p50": float(np.percentile(samples, 50)), "p90": float(np.percentile(samples, 90))}
