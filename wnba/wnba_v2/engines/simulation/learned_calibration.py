"""Phase 5.3 — learned calibration for the conserved simulator.

Fits Phase 5.2 simulator parameters from walk-forward training seasons. The
simulation architecture is unchanged; only parameters are learned.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

from wnba_v2 import config as C
from wnba_v2.engines.efficiency.rates import build_rate_frame
EVAL_SEASON = 2026
from wnba_v2.engines.simulation.conserved_engine import ConservedSimConfig

OUT = C.OUTPUTS / "phase53"
CALIBRATION_PATH = OUT / "phase53_learned_calibration.json"
LOW_COUNT = {
    "threes_made": "fg3m",
    "steals": "stl",
    "blocks": "blk",
}


def _clip(value: float, lo: float, hi: float) -> float:
    if not np.isfinite(value):
        return lo
    return float(min(max(value, lo), hi))


def _load_team_games(eval_season: int) -> pd.DataFrame:
    tg = pd.read_csv(C.V2_ROOT / "data" / "team_games" / "team_game_logs.csv")
    return tg[tg["season"] < eval_season].copy()


def _rolling_team_residuals(tg: pd.DataFrame) -> dict:
    work = tg.sort_values(["team", "date"]).copy()
    out = {}
    for stat, field, floor, ceil in [
        ("points", "points", 7.5, 14.0),
        ("rebounds", "reb", 4.0, 8.0),
        ("assists", "ast", 2.0, 5.0),
        ("possessions", "possessions", 3.0, 7.0),
    ]:
        pred = work.groupby("team")[field].transform(lambda s: s.shift(1).rolling(10, min_periods=3).mean())
        resid = pd.to_numeric(work[field], errors="coerce") - pred
        out[stat] = _clip(float(resid.dropna().std(ddof=1)), floor, ceil)
    return out


def _fit_usage_scale(rf: pd.DataFrame) -> float:
    poss = pd.to_numeric(rf["team_poss"], errors="coerce")
    usage = pd.to_numeric(rf["poss_used"], errors="coerce")
    by_team = pd.DataFrame({"game_id": rf["game_id"], "team": rf["team"], "poss": poss, "usage": usage}).groupby(["game_id", "team"]).agg({"poss": "mean", "usage": "sum"}).dropna()
    ratio = (by_team["usage"] / by_team["poss"]).replace([np.inf, -np.inf], np.nan).dropna()
    return _clip(float(ratio.median()), 0.90, 1.15)


def _fit_low_count(rf: pd.DataFrame) -> dict:
    params = {}
    for stat, col in LOW_COUNT.items():
        values = pd.to_numeric(rf[col], errors="coerce").dropna()
        mean = float(values.mean())
        var = float(values.var(ddof=1))
        alpha = (var - mean) / max(mean, 1e-6)
        zero_actual = float((values == 0).mean())
        zero_pois = float(np.exp(-max(mean, 1e-6)))
        # The engine has a fixed base zero floor; learn only the excess role-sensitive part.
        zero_mix = _clip((zero_actual - zero_pois) * 0.25, 0.0, 0.08)
        scale = _clip(mean / max(mean * (1.0 - zero_mix), 1e-6), 0.85, 1.80)
        params[stat] = {
            "mean": mean,
            "variance": var,
            "alpha": _clip(alpha, 0.10, 0.80),
            "zero_rate": zero_actual,
            "zero_mix": zero_mix,
            "mean_scale": scale,
        }
    return params


def _fit_role_zero_slopes(rf: pd.DataFrame) -> dict:
    slopes = {}
    minutes = pd.to_numeric(rf["minutes"], errors="coerce")
    low = minutes < 16
    high = minutes >= 24
    for stat, col in LOW_COUNT.items():
        vals = pd.to_numeric(rf[col], errors="coerce")
        low_zero = float((vals[low] == 0).mean()) if low.any() else np.nan
        high_zero = float((vals[high] == 0).mean()) if high.any() else np.nan
        slopes[stat] = _clip((low_zero - high_zero) if np.isfinite(low_zero) and np.isfinite(high_zero) else 0.0, 0.0, 1.0)
    return slopes


def _fit_latent_loadings(rf: pd.DataFrame) -> dict:
    corr_pr = float(rf["points"].corr(rf["reb"]))
    corr_pa = float(rf["points"].corr(rf["ast"]))
    corr_ra = float(rf["reb"].corr(rf["ast"]))
    # Convert observed stat correlations into conservative latent loadings. These
    # are intentionally shrunk because allocation conservation already adds corr.
    return {
        "points": _clip(0.22 + 0.24 * corr_pr + 0.16 * corr_pa, 0.20, 0.42),
        "rebounds": _clip(0.16 + 0.28 * corr_pr + 0.08 * corr_ra, 0.16, 0.36),
        "assists": _clip(0.22 + 0.28 * corr_pa + 0.08 * corr_ra, 0.20, 0.44),
        "observed_correlations": {"points_rebounds": corr_pr, "points_assists": corr_pa, "rebounds_assists": corr_ra},
    }


def _fit_blowout_effects(tg: pd.DataFrame, rf: pd.DataFrame) -> dict:
    team_minutes = rf.groupby(["game_id", "team"]).agg(
        starter_minutes=("minutes", lambda s: float(s[rf.loc[s.index, "starter"] == 1].sum())),
        bench_minutes=("minutes", lambda s: float(s[rf.loc[s.index, "starter"] != 1].sum())),
    ).reset_index()
    margins = tg[["game_id", "team", "points", "opp_points"]].copy()
    margins["abs_margin"] = (margins["points"] - margins["opp_points"]).abs()
    m = team_minutes.merge(margins[["game_id", "team", "abs_margin"]], on=["game_id", "team"], how="inner")
    if len(m) < 50:
        return {"starter_compression": 0.24, "bench_expansion": 0.35, "starter_slope": None, "bench_slope": None}
    starter_slope = float(np.polyfit(m["abs_margin"], m["starter_minutes"], 1)[0])
    bench_slope = float(np.polyfit(m["abs_margin"], m["bench_minutes"], 1)[0])
    mean_starter = max(float(m["starter_minutes"].mean()), 1.0)
    mean_bench = max(float(m["bench_minutes"].mean()), 1.0)
    # Convert minute-per-margin slopes into the engine's blowout multipliers.
    starter_compression = _clip((-starter_slope * 16.0) / mean_starter, 0.10, 0.35)
    bench_expansion = _clip((bench_slope * 16.0) / mean_bench, 0.10, 0.55)
    return {
        "starter_compression": starter_compression,
        "bench_expansion": bench_expansion,
        "starter_slope": starter_slope,
        "bench_slope": bench_slope,
    }


def fit(eval_season: int = EVAL_SEASON) -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    rf = build_rate_frame()
    train = rf[rf["season"] < eval_season].dropna(subset=["points", "reb", "ast", "fg3m", "stl", "blk", "minutes"]).copy()
    tg = _load_team_games(eval_season)
    residuals = _rolling_team_residuals(tg)
    low = _fit_low_count(train)
    role = _fit_role_zero_slopes(train)
    latent = _fit_latent_loadings(train)
    blowout = _fit_blowout_effects(tg, train)
    usage_scale = _fit_usage_scale(train)

    # Team-total variance scaling is learned from train residuals, then bounded to
    # keep the Phase 5.2 conserved simulator numerically stable.
    team_variance_scaling = {
        "points": _clip(residuals["points"] / 11.5, 0.75, 1.25),
        "rebounds": _clip(residuals["rebounds"] / 6.5, 0.75, 1.25),
        "assists": _clip(residuals["assists"] / 2.8, 0.75, 1.25),
    }

    prior = ConservedSimConfig()

    def shrink(prior_value: float, learned_value: float, weight: float) -> float:
        return float((1.0 - weight) * prior_value + weight * learned_value)

    params = {
        "n_sims": 1000,
        "pace_std": shrink(prior.pace_std, residuals["possessions"], 0.50),
        "starter_compression": blowout["starter_compression"],
        "bench_expansion": blowout["bench_expansion"],
        "usage_total_per_possession": shrink(prior.usage_total_per_possession, usage_scale, 0.10),
        "point_team_sd": shrink(prior.point_team_sd, residuals["points"], 0.80),
        "rebound_team_sd": shrink(prior.rebound_team_sd, residuals["rebounds"], 0.80),
        "assist_team_sd": shrink(prior.assist_team_sd, residuals["assists"], 0.15),
        "latent_points_loading": shrink(prior.latent_points_loading, latent["points"], 1.00),
        "latent_rebounds_loading": shrink(prior.latent_rebounds_loading, latent["rebounds"], 1.00),
        "latent_assists_loading": shrink(prior.latent_assists_loading, latent["assists"], 1.00),
        "count_alpha_3pm": shrink(prior.count_alpha_3pm, low["threes_made"]["alpha"], 0.20),
        "count_alpha_steals": shrink(prior.count_alpha_steals, low["steals"]["alpha"], 0.20),
        "count_alpha_blocks": shrink(prior.count_alpha_blocks, low["blocks"]["alpha"], 0.20),
        "zero_mix_3pm": shrink(prior.zero_mix_3pm, low["threes_made"]["zero_mix"], 0.15),
        "zero_mix_steals": shrink(prior.zero_mix_steals, low["steals"]["zero_mix"], 0.15),
        "zero_mix_blocks": shrink(prior.zero_mix_blocks, low["blocks"]["zero_mix"], 0.15),
        "threes_mean_scale": shrink(prior.threes_mean_scale, low["threes_made"]["mean_scale"], 0.10),
        "steals_mean_scale": shrink(prior.steals_mean_scale, low["steals"]["mean_scale"], 0.10),
        "blocks_mean_scale": shrink(prior.blocks_mean_scale, low["blocks"]["mean_scale"], 0.10),
        "zero_role_slope_3pm": role["threes_made"] * 0.15,
        "zero_role_slope_steals": role["steals"] * 0.15,
        "zero_role_slope_blocks": role["blocks"] * 0.15,
    }
    cfg = ConservedSimConfig.from_mapping(params)
    payload = {
        "phase": "5.3",
        "eval_season": eval_season,
        "training_seasons": sorted(int(x) for x in train["season"].dropna().unique()),
        "parameters": asdict(cfg),
        "fit_diagnostics": {
            "team_residual_sd": residuals,
            "team_total_variance_scaling": team_variance_scaling,
            "low_count": low,
            "role_zero_slopes": role,
            "latent_loadings": latent,
            "blowout_effects": blowout,
            "usage_total_per_possession": usage_scale,
        },
    }
    (OUT / "phase53_candidate_calibration.json").write_text(json.dumps(payload, indent=2, default=str))
    return payload


def load_config(path: Path = CALIBRATION_PATH, *, n_sims: int | None = None) -> ConservedSimConfig | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text())
    return ConservedSimConfig.from_mapping(payload.get("parameters", {}), n_sims=n_sims)


if __name__ == "__main__":
    payload = fit()
    print(json.dumps({"parameters": payload["parameters"], "fit_diagnostics": payload["fit_diagnostics"]}, indent=2, default=str))
