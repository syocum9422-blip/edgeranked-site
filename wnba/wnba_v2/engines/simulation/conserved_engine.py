"""Phase 5.2 — conserved team/game simulator.

This module stops independent player stat draws. It simulates a game/team as a
joint allocation problem:
  * one possession vector per game
  * exactly 200 regulation minutes per team per draw
  * game-state minutes compression/bench expansion
  * conserved team usage counts, rebounds, assists, and points
  * overdispersed zero-inflated count models for 3PM/STL/BLK
  * shared player latent factor for points/rebounds/assists correlation
  * latent draw output for diagnostics
"""
from __future__ import annotations

from dataclasses import dataclass, fields

import numpy as np
import pandas as pd

from wnba_v2.engines.simulation.engine import COMBOS, STATS

TEAM_MINUTES = 200.0
PACE_STD = 4.7
EPS = 1e-9


@dataclass(frozen=True)
class ConservedSimConfig:
    n_sims: int = 1000
    pace_std: float = PACE_STD
    margin_std: float = 13.0
    blowout_start: float = 10.0
    blowout_full: float = 26.0
    starter_compression: float = 0.24
    bench_expansion: float = 0.35
    usage_total_per_possession: float = 1.04
    point_team_sd: float = 11.5
    rebound_team_sd: float = 6.5
    assist_team_sd: float = 2.8
    latent_sd: float = 0.28
    latent_points_loading: float = 0.32
    latent_rebounds_loading: float = 0.24
    latent_assists_loading: float = 0.34
    count_alpha_3pm: float = 0.25
    count_alpha_steals: float = 0.50
    count_alpha_blocks: float = 0.25
    zero_mix_3pm: float = 0.01
    zero_mix_steals: float = 0.01
    zero_mix_blocks: float = 0.01
    threes_mean_scale: float = 1.65
    steals_mean_scale: float = 1.16
    blocks_mean_scale: float = 1.55
    points_allocation_concentration: float = 150.0
    rebounds_allocation_concentration: float = 125.0
    assists_allocation_concentration: float = 110.0
    zero_role_slope_3pm: float = 0.0
    zero_role_slope_steals: float = 0.0
    zero_role_slope_blocks: float = 0.0

    @classmethod
    def from_mapping(cls, values: dict, *, n_sims: int | None = None) -> "ConservedSimConfig":
        allowed = {f.name for f in fields(cls)}
        data = {k: v for k, v in values.items() if k in allowed}
        if n_sims is not None:
            data["n_sims"] = n_sims
        return cls(**data)


def _as_float_array(values, n: int) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    if arr.shape == (n,):
        return arr
    return np.full(n, float(arr), dtype=float)


def _positive(x: np.ndarray | float, floor: float = EPS) -> np.ndarray | float:
    return np.maximum(x, floor)


def _weighted_probs(weights: np.ndarray) -> np.ndarray:
    w = np.asarray(weights, dtype=float)
    w = np.where(np.isfinite(w), w, 0.0)
    w = np.clip(w, 0.0, None)
    total = w.sum()
    if total <= EPS:
        return np.full(len(w), 1.0 / max(len(w), 1))
    return w / total


def _gamma_poisson(mean: np.ndarray, alpha: float, rng: np.random.Generator) -> np.ndarray:
    """Negative-binomial-like overdispersed counts via Gamma-Poisson."""
    mu = np.clip(np.asarray(mean, dtype=float), 0.0, None)
    alpha = max(float(alpha), 1e-3)
    shape = np.maximum(mu / alpha, 1e-6)
    scale = alpha
    lam = rng.gamma(shape, scale)
    return rng.poisson(lam)


def _zinb(mean: np.ndarray, alpha: float, zero_prob: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    counts = _gamma_poisson(mean, alpha, rng)
    zeros = rng.random(len(counts)) < np.clip(zero_prob, 0.0, 0.95)
    counts[zeros] = 0
    return counts.astype(float)


def _allocate_multinomial(total: int, probs: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    if total <= 0 or len(probs) == 0:
        return np.zeros(len(probs), dtype=float)
    return rng.multinomial(int(total), _weighted_probs(probs)).astype(float)




def _allocate_dirichlet_multinomial(total: int, probs: np.ndarray, concentration: float, rng: np.random.Generator) -> np.ndarray:
    if total <= 0 or len(probs) == 0:
        return np.zeros(len(probs), dtype=float)
    p = _weighted_probs(probs)
    alpha = np.maximum(p * max(float(concentration), 1.0), 1e-3)
    jittered = rng.dirichlet(alpha)
    return rng.multinomial(int(total), jittered).astype(float)

def _draw_team_totals(mean: np.ndarray, sd: float, rng: np.random.Generator, lo: float = 0.0) -> np.ndarray:
    return np.clip(rng.normal(mean, sd, len(mean)), lo, None)


def _team_context(team_rows: pd.DataFrame, cfg: ConservedSimConfig, rng: np.random.Generator) -> dict:
    poss_mean = float(team_rows["team_poss_lag"].dropna().mean())
    poss = np.clip(rng.normal(poss_mean, cfg.pace_std, cfg.n_sims), 58.0, 98.0)
    margin = rng.normal(0.0, cfg.margin_std, cfg.n_sims)
    blowout = np.clip((np.abs(margin) - cfg.blowout_start) / max(cfg.blowout_full - cfg.blowout_start, 1.0), 0.0, 1.0)
    return {"possessions": poss, "margin": margin, "blowout": blowout}


def _allocate_minutes(team_rows: pd.DataFrame, context: dict, cfg: ConservedSimConfig, rng: np.random.Generator) -> np.ndarray:
    n_players = len(team_rows)
    n_sims = cfg.n_sims
    base_mean = team_rows["min_mean"].fillna(8.0).clip(lower=0.5).to_numpy(float)
    base_std = team_rows["min_std"].fillna(5.0).clip(lower=1.0, upper=12.0).to_numpy(float)
    play_prob = team_rows["play_prob"].fillna(0.95).clip(0.3, 1.0).to_numpy(float)
    starter = team_rows.get("starter", pd.Series(np.zeros(n_players), index=team_rows.index)).fillna(0).to_numpy(float)

    raw = np.zeros((n_sims, n_players), dtype=float)
    for i in range(n_players):
        plays = rng.random(n_sims) < play_prob[i]
        raw[:, i] = np.clip(rng.normal(base_mean[i], base_std[i], n_sims), 0.0, None) * plays

    blowout = context["blowout"][:, None]
    starter_mask = starter[None, :] >= 0.5
    raw = np.where(starter_mask, raw * (1.0 - cfg.starter_compression * blowout), raw * (1.0 + cfg.bench_expansion * blowout))

    # Keep active players active enough to absorb minutes if the Bernoulli draw made a team too thin.
    thin = raw.sum(axis=1) <= EPS
    if thin.any():
        raw[thin, :] = base_mean[None, :]
    totals = raw.sum(axis=1)
    raw = raw * (TEAM_MINUTES / np.maximum(totals, EPS))[:, None]
    return raw


def _team_total_points(team_rows: pd.DataFrame, minutes: np.ndarray, usage_counts: np.ndarray,
                       latent: np.ndarray, calib: dict, cfg: ConservedSimConfig,
                       rng: np.random.Generator) -> np.ndarray:
    rates = team_rows["points_mean"].fillna(0.0).clip(lower=0.0).to_numpy(float)
    scale = float(calib.get("points", 1.0))
    player_mu = rates[None, :] * usage_counts * scale * np.exp(cfg.latent_points_loading * latent)
    mean = player_mu.sum(axis=1)
    return np.rint(_draw_team_totals(mean, cfg.point_team_sd, rng)).astype(int).clip(0)


def simulate_team(team_rows: pd.DataFrame, context: dict | None, rng: np.random.Generator,
                  cfg: ConservedSimConfig | None = None, calib: dict | None = None) -> dict:
    """Simulate one team-game jointly. Returns player stat arrays and latent draws."""
    cfg = cfg or ConservedSimConfig()
    calib = calib or {}
    team_rows = team_rows.reset_index(drop=True).copy()
    n_players, n_sims = len(team_rows), cfg.n_sims
    if n_players == 0:
        raise ValueError("simulate_team requires at least one player row")
    context = context or _team_context(team_rows, cfg, rng)

    minutes = _allocate_minutes(team_rows, context, cfg, rng)
    minute_share = minutes / TEAM_MINUTES
    poss = _as_float_array(context["possessions"], n_sims)
    blowout = _as_float_array(context["blowout"], n_sims)

    latent = rng.normal(0.0, cfg.latent_sd, size=(n_sims, n_players))
    usage_weight = team_rows["usage_share_pred"].fillna(0.08).clip(0.005, 0.45).to_numpy(float)[None, :] * _positive(minutes / np.maximum(team_rows["typ_min"].fillna(12.0).to_numpy(float)[None, :], 5.0))
    usage_weight *= np.exp(0.20 * latent)
    usage_total = np.rint(poss * cfg.usage_total_per_possession).astype(int).clip(1)
    usage_counts = np.vstack([_allocate_multinomial(total, usage_weight[j], rng) for j, total in enumerate(usage_total)])

    team_points = _team_total_points(team_rows, minutes, usage_counts, latent, calib, cfg, rng)
    point_weight = _positive(team_rows["points_mean"].fillna(0.0).to_numpy(float)[None, :] * usage_counts * np.exp(cfg.latent_points_loading * latent))
    points = np.vstack([_allocate_dirichlet_multinomial(total, point_weight[j], cfg.points_allocation_concentration, rng) for j, total in enumerate(team_points)])

    reb_mean = float(team_rows["reb_pool_lag"].dropna().mean()) * 0.45 * (poss / max(float(team_rows["team_poss_lag"].dropna().mean()), 1.0))
    team_reb = np.rint(_draw_team_totals(reb_mean, cfg.rebound_team_sd, rng)).astype(int).clip(0)
    reb_weight = _positive(team_rows["rebounds_mean"].fillna(0.0).to_numpy(float)[None, :] * minute_share * np.exp(cfg.latent_rebounds_loading * latent))
    rebounds = np.vstack([_allocate_dirichlet_multinomial(total, reb_weight[j], cfg.rebounds_allocation_concentration, rng) for j, total in enumerate(team_reb)])
    rebounds *= float(calib.get("rebounds", 1.0))

    fgm_mean = float(team_rows["tmfg_pool_lag"].dropna().mean()) * (poss / max(float(team_rows["team_poss_lag"].dropna().mean()), 1.0))
    team_fgm = np.rint(_draw_team_totals(fgm_mean, 4.3, rng)).astype(int).clip(0)
    ast_rate = np.clip(rng.normal(0.69, 0.06, n_sims), 0.40, 0.88)
    team_ast = rng.binomial(team_fgm, ast_rate).astype(int)
    team_ast = np.rint(_draw_team_totals(team_ast, cfg.assist_team_sd, rng)).astype(int).clip(0)
    ast_weight = _positive(team_rows["assists_mean"].fillna(0.0).to_numpy(float)[None, :] * minute_share * np.exp(cfg.latent_assists_loading * latent))
    assists = np.vstack([_allocate_dirichlet_multinomial(total, ast_weight[j], cfg.assists_allocation_concentration, rng) for j, total in enumerate(team_ast)])
    assists *= float(calib.get("assists", 1.0))

    # Overdispersed zero-inflated low-count stats. Means are tied to conserved usage/minutes.
    fg3a_rate = team_rows["fg3a_mean"].fillna(0.0).clip(lower=0.0).to_numpy(float)[None, :]
    fg3_pct = team_rows["fg3_pct_mean"].fillna(0.32).clip(0.02, 0.90).to_numpy(float)[None, :]
    threes_mu = fg3a_rate * np.maximum(usage_counts, 0.0) * fg3_pct * float(calib.get("threes_made", 1.0)) * cfg.threes_mean_scale
    role_zero = 1.0 + cfg.zero_role_slope_3pm * (1.0 - np.clip(minutes / 24.0, 0.0, 1.0))
    threes_zero = (cfg.zero_mix_3pm * np.exp(-minutes / 18.0) * role_zero) + 0.03
    threes = _zinb(threes_mu.ravel(), cfg.count_alpha_3pm, threes_zero.ravel(), rng).reshape(n_sims, n_players)

    def_poss = poss[:, None] * np.clip(minutes / 40.0, 0.0, 1.2)
    steals_mu = team_rows["steals_mean"].fillna(0.0).clip(lower=0.0).to_numpy(float)[None, :] * def_poss * float(calib.get("steals", 1.0)) * cfg.steals_mean_scale
    blocks_mu = team_rows["blocks_mean"].fillna(0.0).clip(lower=0.0).to_numpy(float)[None, :] * def_poss * float(calib.get("blocks", 1.0)) * cfg.blocks_mean_scale
    steals_role_zero = 1.0 + cfg.zero_role_slope_steals * (1.0 - np.clip(minutes / 24.0, 0.0, 1.0))
    blocks_role_zero = 1.0 + cfg.zero_role_slope_blocks * (1.0 - np.clip(minutes / 24.0, 0.0, 1.0))
    steals_zero = (cfg.zero_mix_steals * np.exp(-minutes / 20.0) * steals_role_zero) + 0.02
    blocks_zero = (cfg.zero_mix_blocks * np.exp(-minutes / 20.0) * blocks_role_zero) + 0.03
    steals = _zinb(steals_mu.ravel(), cfg.count_alpha_steals, steals_zero.ravel(), rng).reshape(n_sims, n_players)
    blocks = _zinb(blocks_mu.ravel(), cfg.count_alpha_blocks, blocks_zero.ravel(), rng).reshape(n_sims, n_players)

    player_stats = {
        "points": points.astype(float),
        "rebounds": rebounds.astype(float),
        "assists": assists.astype(float),
        "threes_made": threes.astype(float),
        "steals": steals.astype(float),
        "blocks": blocks.astype(float),
    }
    player_stats["pa"] = player_stats["points"] + player_stats["assists"]
    player_stats["pr"] = player_stats["points"] + player_stats["rebounds"]
    player_stats["ra"] = player_stats["rebounds"] + player_stats["assists"]
    player_stats["pra"] = player_stats["points"] + player_stats["rebounds"] + player_stats["assists"]

    return {
        "players": team_rows,
        "stats": player_stats,
        "latents": {
            "minutes": minutes,
            "possessions": poss,
            "margin": context["margin"],
            "blowout": blowout,
            "player_factor": latent,
            "usage_counts": usage_counts,
            "team_points": team_points,
            "team_rebounds": team_reb,
            "team_fgm": team_fgm,
            "team_assists": team_ast,
        },
    }


def simulate_game(game_rows: pd.DataFrame, n_sims: int, rng: np.random.Generator,
                  calib: dict | None = None, cfg: ConservedSimConfig | None = None) -> dict[str, dict]:
    """Simulate all teams in a game with one shared possession vector."""
    cfg = cfg or ConservedSimConfig(n_sims=n_sims)
    teams = sorted(game_rows["team"].dropna().unique())
    poss_mean = float(game_rows["team_poss_lag"].dropna().mean())
    poss = np.clip(rng.normal(poss_mean, cfg.pace_std, cfg.n_sims), 58.0, 98.0)
    margin = rng.normal(0.0, cfg.margin_std, cfg.n_sims)
    blowout = np.clip((np.abs(margin) - cfg.blowout_start) / max(cfg.blowout_full - cfg.blowout_start, 1.0), 0.0, 1.0)
    out = {}
    for team in teams:
        rows = game_rows[game_rows["team"] == team].copy()
        out[team] = simulate_team(rows, {"possessions": poss, "margin": margin, "blowout": blowout}, rng, cfg, calib)
    return out


def player_samples(team_result: dict, player_index: int) -> dict[str, np.ndarray]:
    return {stat: values[:, player_index] for stat, values in team_result["stats"].items()}
