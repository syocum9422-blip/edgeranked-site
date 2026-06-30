"""Phase 3.5 — positional/on-off redistribution features.

Core idea: when a player is OUT, opportunity is NOT spread proportionally. The
model learns who absorbs it by seeing, for each active player, how much usage /
assists / rebounds were VACATED by out teammates BUCKETED BY THE OUT PLAYER'S ROLE,
crossed with the active player's own role. No redistribution amount is hard-coded —
the GBM learns the absorption coefficients.

Roles (6, from ESPN position + starter + lagged behavioral form):
  primary_ball_handler, secondary_guard, wing, forward, center, bench_replacement
Role thresholds only LABEL players; the redistribution magnitudes are learned.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from wnba_v2.data.player_boxscores import PLAYER_GAMES_PATH
from wnba_v2.engines.usage.features import SHARE_COLS, build_usage_features

ROLES = ["primary_ball_handler", "secondary_guard", "wing", "forward", "center", "bench_replacement"]

# on/off context indicators + vacated-by-role features (the learnable redistribution signal)
VACATED_KINDS = ["usage", "ast", "reb"]
VACATED_FEATURES = [f"vac_{k}_by_{r}" for k in VACATED_KINDS for r in ROLES]
CONTEXT_FEATURES = ["star_out", "lead_guard_out", "frontcourt_out", "n_regulars_out"]
ROLE_ONEHOT = [f"role_{r}" for r in ROLES]
REDIS_FEATURES = (
    [f"{s}_lag5" for s in SHARE_COLS] + [f"{s}_lag10" for s in SHARE_COLS]
    + ["minutes_share_lag5", "minutes_share_lag10", "rotation_rank", "starter"]
    + ROLE_ONEHOT + VACATED_FEATURES + CONTEXT_FEATURES
)


def assign_role(pos, starter, lag_ast, lag_fg3m, lag_min) -> str:
    if (starter == 0) and (pd.isna(lag_min) or lag_min < 0.12):
        return "bench_replacement"
    if pos == "C":
        return "center"
    if pos == "G":
        return "primary_ball_handler" if (lag_ast or 0) >= 0.18 else "secondary_guard"
    if pos == "F":
        return "wing" if (lag_fg3m or 0) >= 0.15 else "forward"
    return "forward"


def _role_series(df: pd.DataFrame) -> pd.Series:
    return df.apply(lambda r: assign_role(
        r.get("position"), r.get("starter", 0),
        r.get("ast_share_lag5"), r.get("fg3m_share_lag5"), r.get("minutes_share_lag5")), axis=1)


def build_redistribution_frame() -> pd.DataFrame:
    """Active-player rows (from build_usage_features) augmented with role one-hots,
    vacated-by-role features, and on/off context. One row per played player-game."""
    base = build_usage_features()              # played players, lagged shares, rotation_rank
    base["role"] = _role_series(base)
    for r in ROLES:
        base[f"role_{r}"] = (base["role"] == r).astype(int)

    # --- usual (as-of) role + lag shares for the FULL roster, to value OUT players ---
    usual = base[["player_id", "date", "role",
                  "usage_share_lag5", "ast_share_lag5", "reb_share_lag5"]].dropna(subset=["date"])
    usual = usual.sort_values("date").rename(columns={
        "usage_share_lag5": "u_usage", "ast_share_lag5": "u_ast", "reb_share_lag5": "u_reb"})

    full = pd.read_csv(PLAYER_GAMES_PATH, parse_dates=["date"]).sort_values("date")
    # attach each roster player's most-recent known role + usual shares as of this game
    full = pd.merge_asof(full, usual, on="date", by="player_id", direction="backward")

    out = full[full["played"] == 0].dropna(subset=["role"]).copy()
    # only count OUT players who were actually regulars (had a real role)
    out = out[out["u_usage"].fillna(0) >= 0.05]

    # vacated opportunity per (game_id, team) bucketed by the OUT player's role
    vac_frames = []
    for kind, col in [("usage", "u_usage"), ("ast", "u_ast"), ("reb", "u_reb")]:
        piv = (out.groupby(["game_id", "team", "role"])[col].sum()
               .unstack("role").reindex(columns=ROLES, fill_value=0.0))
        piv.columns = [f"vac_{kind}_by_{r}" for r in ROLES]
        vac_frames.append(piv)
    vac = pd.concat(vac_frames, axis=1).reset_index()

    base = base.merge(vac, on=["game_id", "team"], how="left")
    for c in VACATED_FEATURES:
        base[c] = base.get(c, 0.0)
    base[VACATED_FEATURES] = base[VACATED_FEATURES].fillna(0.0)

    # on/off context indicators (derived from vacancies — not hard-coded boosts)
    base["lead_guard_out"] = (base["vac_ast_by_primary_ball_handler"] > 0.05).astype(int)
    base["frontcourt_out"] = ((base["vac_reb_by_center"] + base["vac_reb_by_forward"]) > 0.08).astype(int)
    base["star_out"] = (base[[f"vac_usage_by_{r}" for r in ROLES]].sum(axis=1) > 0.15).astype(int)
    n_out = out.groupby(["game_id", "team"]).size().rename("n_regulars_out").reset_index()
    base = base.merge(n_out, on=["game_id", "team"], how="left")
    base["n_regulars_out"] = base["n_regulars_out"].fillna(0).astype(int)
    return base
