from __future__ import annotations

import math
import os
import zlib

import numpy as np
import pandas as pd

from wnba_model_config import (
    APP_VIEW_PROJECTIONS_PATH,
    MINUTES_MODEL_PATH,
    MONTE_CARLO_SIMS,
    PROJECTIONS_PATH,
    PROJECTIONS_ARCHIVE_DIR,
    SIMULATION_DETAIL_PATH,
    STAT_ALIASES,
    STAT_TARGETS,
    TODAY_FEATURES_PATH,
)
from wnba_model_utils import (
    archive_dataframe,
    clean_feature_frame,
    compute_confidence_label,
    compute_minutes_distribution,
    gamma_sample,
    load_inputs_for_pipeline,
    load_model_bundle,
    setup_logging,
)


STAT_MODEL_PATHS = {
    "points": "models/wnba_points_model.joblib",
    "rebounds": "models/wnba_rebounds_model.joblib",
    "assists": "models/wnba_assists_model.joblib",
    "threes_made": "models/wnba_threes_made_model.joblib",
    "steals": "models/wnba_steals_model.joblib",
    "blocks": "models/wnba_blocks_model.joblib",
}

STAT_DISPLAY = {
    "points": ("PTS", "Points"),
    "rebounds": ("REB", "Rebounds"),
    "assists": ("AST", "Assists"),
    "threes_made": ("FG3M", "3PM"),
    "steals": ("STL", "Steals"),
    "blocks": ("BLK", "Blocks"),
}



STATUS_ACTIVE_PROBABILITY = {
    "available": 1.0,
    "active": 1.0,
    "healthy": 1.0,
    "probable": 0.95,
    "questionable": 0.75,
    "day-to-day": 0.85,
    "day to day": 0.85,
    "dtd": 0.85,
    "gtd": 0.75,
    "game-time decision": 0.75,
    "doubtful": 0.25,
    "out": 0.0,
    "inactive": 0.0,
    "suspended": 0.0,
}


def _p7_flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


# Phase 7 realism flags. Each gate is independent so any fix can be rolled back via env
# without touching code. Defaults reflect the validated production configuration.
P7_ACTIVE_PROB = _p7_flag("WNBA_P7_ACTIVE_PROB", True)
P7_REDISTRIBUTION = _p7_flag("WNBA_P7_REDISTRIBUTION", True)
P7_COUPLED_SAMPLING = _p7_flag("WNBA_P7_COUPLED_SAMPLING", True)
P7_DISCRETE_COUNTS = _p7_flag("WNBA_P7_DISCRETE_COUNTS", True)
P7_DISCRETE_ASSISTS = _p7_flag("WNBA_P7_DISCRETE_ASSISTS", True)
P7_GAME_STATE = _p7_flag("WNBA_P7_GAME_STATE", True)

# Active-branch minutes haircut by status: a player listed questionable/day-to-day who does
# play tends to log fewer minutes than her healthy projection.
STATUS_MINUTES_FACTOR = {
    "probable": 0.97,
    "day-to-day": 0.92,
    "day to day": 0.92,
    "dtd": 0.92,
    "questionable": 0.90,
    "gtd": 0.90,
    "game-time decision": 0.90,
    "doubtful": 0.80,
}

# Statuses that vacate minutes for teammate redistribution.
ABSENT_STATUSES = {"out", "inactive", "suspended", "doubtful"}
KEY_PLAYER_MIN_AVG = 14.0  # recent minutes needed for an absence to trigger redistribution
# Boost shrinkage: raw with/without deltas + proportional fills overshoot observed minutes
# (validation signed bias +2.7 min unshrunk vs +0.6 baseline); deep bench rarely expands.
REDIS_BOOST_SCALE = 0.5
REDIS_BENEFICIARY_MIN_FLOOR = 12.0

DISCRETE_BASE_STATS = {"steals", "blocks", "threes_made"}

# Shared per-game environment draws.
GAME_STATE_PACE_STD = 0.055   # game-to-game pace variation around expectation
GAME_STATE_MARGIN_STD = 11.0  # WNBA final-margin spread
BLOWOUT_MARGIN = 15.0         # margin beyond which rotations shorten/expand

_GAME_STATE_CACHE: dict[tuple[str, int], dict[str, np.ndarray]] = {}


def discrete_stats() -> set[str]:
    stats = set(DISCRETE_BASE_STATS) if P7_DISCRETE_COUNTS else set()
    if P7_DISCRETE_COUNTS and P7_DISCRETE_ASSISTS:
        stats.add("assists")
    return stats


def game_key_for_row(row: pd.Series) -> str:
    teams = sorted([str(row.get("team", "")).upper(), str(row.get("opponent", "")).upper()])
    date_value = row.get("game_date", "")
    if pd.notna(date_value):
        try:
            date_value = pd.to_datetime(date_value).date().isoformat()
        except Exception:
            date_value = str(date_value)
    return f"{date_value}|{teams[0]}|{teams[1]}"


def game_state_for_row(row: pd.Series, size: int) -> dict[str, np.ndarray]:
    """Shared pace/margin draws for a game. Seeded by the game key (not the player RNG)
    so every player in the same game sees the identical environment in every draw."""
    key = game_key_for_row(row)
    cached = _GAME_STATE_CACHE.get((key, size))
    if cached is not None:
        return cached
    seed = (zlib.crc32(key.encode("utf-8")) + 7_654_321) % (2**32)
    game_rng = np.random.default_rng(seed)
    state = {
        "pace": np.clip(game_rng.normal(1.0, GAME_STATE_PACE_STD, size), 0.80, 1.20),
        "margin": game_rng.normal(0.0, GAME_STATE_MARGIN_STD, size),
    }
    if len(_GAME_STATE_CACHE) > 4096:
        _GAME_STATE_CACHE.clear()
    _GAME_STATE_CACHE[(key, size)] = state
    return state


def apply_blowout_minutes(sim_minutes: np.ndarray, margin: np.ndarray, minutes_mean: float) -> np.ndarray:
    """In draws that turn into blowouts, heavy-minute players sit late and deep bench mops up."""
    excess = np.clip(np.abs(margin) - BLOWOUT_MARGIN, 0.0, 15.0)
    starter_weight = float(np.clip((minutes_mean - 18.0) / 18.0, -1.0, 1.0))
    return np.clip(sim_minutes * (1.0 - 0.008 * excess * starter_weight), 0.0, 40.0)


def downgrade_confidence(label: object) -> str:
    return {"high": "medium", "medium": "low", "low": "low"}.get(str(label).lower(), "low")


def gamma_rate_sample(mean: float, std: float, size: int, rng: np.random.Generator) -> np.ndarray:
    """Gamma draws for per-minute rates. Unlike gamma_sample, no absolute std floor:
    rates live at the 0.01-0.6 scale where a 0.05 floor would over-disperse them."""
    mean = max(float(mean), 1e-4)
    std = max(float(std), 1e-4)
    variance = std**2
    shape = (mean**2) / variance
    scale = variance / mean
    return rng.gamma(shape=shape, scale=scale, size=size)

COMBO_STATS = {
    "pra": (["points", "rebounds", "assists"], "PRA", "Pts+Reb+Ast"),
    "pr": (["points", "rebounds"], "PR", "Pts+Reb"),
    "pa": (["points", "assists"], "PA", "Pts+Ast"),
    "ra": (["rebounds", "assists"], "RA", "Reb+Ast"),
    "sb": (["steals", "blocks"], "SB", "Stl+Blk"),
}

SIMULATION_DETAIL_COLUMNS = [
    "player_name",
    "player_key",
    "team",
    "opponent",
    "stat",
    "line",
    "sportsbook",
    "over_odds",
    "under_odds",
    "mean",
    "median",
    "floor",
    "ceiling",
    "stddev",
    "p10",
    "p50",
    "p90",
    "over_hit_rate",
    "under_hit_rate",
    "projected_minutes",
    "confidence",
    "confidence_label",
    "model_projection",
    "line_delta",
]


def load_stat_models(base_dir) -> dict[str, dict]:
    return {
        stat: load_model_bundle(base_dir / relative_path)
        for stat, relative_path in STAT_MODEL_PATHS.items()
    }


def predict_ensemble(bundle: dict, frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    features = bundle["feature_list"]
    model_frame = clean_feature_frame(frame, features)
    ridge_pred = np.clip(bundle["ridge_model"].predict(model_frame), 0, None)
    tree_pred = np.clip(bundle["tree_model"].predict(model_frame), 0, None)
    ensemble_pred = np.clip((ridge_pred + tree_pred) / 2.0, 0, None)
    return ridge_pred, tree_pred, ensemble_pred


def normalize_status(value: object) -> str:
    text = str(value).strip().lower()
    if not text or text == "nan":
        return "unknown"
    return text


def active_probability_from_status(status: str) -> float:
    return STATUS_ACTIVE_PROBABILITY.get(normalize_status(status), np.nan)


def build_status_lookup(player_status: pd.DataFrame) -> dict[str, str]:
    if player_status.empty or "player_key" not in player_status.columns:
        return {}
    lookup = {}
    for _, row in player_status.iterrows():
        key = str(row.get("player_key", "")).strip()
        if not key:
            continue
        lookup[key] = normalize_status(row.get("status", "unknown"))
    return lookup


def _normalize_date_str(values: pd.Series) -> pd.Series:
    return pd.to_datetime(values, errors="coerce").dt.strftime("%Y-%m-%d")


def _usage_points(games: pd.DataFrame) -> pd.Series:
    return (
        games["points"].fillna(0)
        + 1.2 * games["assists"].fillna(0)
        + 0.7 * games["rebounds"].fillna(0)
        + 0.6 * games["threes_made"].fillna(0)
    )


def build_absences_from_status(
    player_status: pd.DataFrame,
    games_log: pd.DataFrame,
    frame: pd.DataFrame,
    logger=None,
) -> pd.DataFrame:
    """Absent key players for today's slate: status says OUT-like, recent minutes say the
    absence vacates real playing time. Team resolved from the game log (status feed team
    names are unreliable)."""
    columns = ["game_date", "team", "player_key", "player_name", "vacated_minutes", "usage_share"]
    if player_status.empty or frame.empty or games_log.empty:
        return pd.DataFrame(columns=columns)

    slate_dates = _normalize_date_str(frame["game_date"]).dropna().unique()
    slate_date = slate_dates[0] if len(slate_dates) else None
    slate_teams = set(frame["team"].dropna().astype(str))
    log = games_log.sort_values(["player_key", "game_date"])
    latest_team = log.groupby("player_key")["team"].last().to_dict()
    recent_minutes = log.groupby("player_key")["minutes"].apply(lambda s: float(s.tail(5).mean())).to_dict()

    rows = []
    for _, status_row in player_status.iterrows():
        status = normalize_status(status_row.get("status", "unknown"))
        if status not in ABSENT_STATUSES:
            continue
        player_key = str(status_row.get("player_key", "")).strip()
        team = latest_team.get(player_key)
        if not player_key or team not in slate_teams:
            continue
        recent_min = recent_minutes.get(player_key, 0.0)
        if not np.isfinite(recent_min) or recent_min < KEY_PLAYER_MIN_AVG:
            continue

        team_log = games_log[games_log["team"] == team]
        # Fresh absences only: if the player already missed the team's last few games,
        # teammates' rolling features have absorbed the absence and boosting again
        # would double-count the vacated minutes.
        last3_dates = team_log["game_date"].drop_duplicates().nlargest(3)
        played_recently = bool(
            (team_log["game_date"].isin(last3_dates) & (team_log["player_key"] == player_key)).any()
        )
        if not played_recently:
            if logger is not None:
                logger.info(
                    "P7 absence skipped (stale, already absorbed): %s (%s)",
                    status_row.get("player_name", player_key), team,
                )
            continue
        team_dates = team_log["game_date"].drop_duplicates().nlargest(10)
        recent_team = team_log[team_log["game_date"].isin(team_dates)]
        team_usage = float(_usage_points(recent_team).sum())
        player_usage = float(_usage_points(recent_team[recent_team["player_key"] == player_key]).sum())
        usage_share = player_usage / team_usage if team_usage > 0 else 0.0

        rows.append(
            {
                "game_date": slate_date,
                "team": team,
                "player_key": player_key,
                "player_name": status_row.get("player_name", player_key),
                "vacated_minutes": round(float(recent_min), 2),
                "usage_share": round(float(np.clip(usage_share, 0.0, 0.45)), 4),
            }
        )
        if logger is not None:
            logger.info(
                "P7 absence detected: %s (%s) status=%s vacates %.1f min, usage share %.1f%%",
                status_row.get("player_name", player_key), team, status, recent_min, usage_share * 100,
            )
    return pd.DataFrame(rows, columns=columns)


def _with_without_minutes_delta(
    history: pd.DataFrame, team: str, absent_key: str, beneficiary_key: str
) -> float:
    """Observed minutes delta for a teammate in past team games without vs with the absent
    player. NaN when the sample is too thin to trust."""
    team_games = history[history["team"] == team]
    if team_games.empty:
        return float("nan")
    all_dates = set(team_games["game_date"].unique())
    with_dates = set(team_games.loc[team_games["player_key"] == absent_key, "game_date"].unique())
    without_dates = all_dates - with_dates
    bene = team_games[team_games["player_key"] == beneficiary_key]
    bene_with = bene[bene["game_date"].isin(with_dates)]["minutes"].dropna()
    bene_without = bene[bene["game_date"].isin(without_dates)]["minutes"].dropna()
    if len(bene_without) < 3 or len(bene_with) < 3:
        return float("nan")
    return float(bene_without.mean() - bene_with.mean())


def apply_absence_redistribution(
    frame: pd.DataFrame,
    games_log: pd.DataFrame,
    absences: pd.DataFrame,
    p7_events: list | None = None,
    logger=None,
) -> pd.DataFrame:
    """Redistribute vacated minutes and usage to teammates of absent key players.

    Minutes: per-beneficiary boost from historical with/without deltas when >=3 games of
    evidence exist, else proportional to current projected minutes. Boosts are shrunk by
    REDIS_BOOST_SCALE (raw estimates overshoot observed rotations), deep-bench players
    below REDIS_BENEFICIARY_MIN_FLOOR are not boosted, total boosts never exceed the
    vacated minutes, and individual minutes never exceed 38.
    Rates: multiplicative per-minute uplift scaled by the absent players' usage share —
    larger for on-ball stats (points/assists/threes) than for rebounds/stocks.
    """
    frame = frame.copy()
    frame["baseline_minutes"] = frame["projected_minutes"]
    for stat in STAT_TARGETS:
        frame[f"uplift_{stat}"] = 1.0
    if absences is None or absences.empty:
        return frame

    frame["_gd"] = _normalize_date_str(frame["game_date"])
    absences = absences.copy()
    absences["_gd"] = _normalize_date_str(absences["game_date"])

    for (game_date, team), group in absences.groupby(["_gd", "team"]):
        mask = (frame["team"] == team) & (frame["_gd"] == game_date)
        beneficiaries = frame.index[mask & ~frame["player_key"].isin(set(group["player_key"]))]
        if len(beneficiaries) == 0:
            continue
        history = games_log[_normalize_date_str(games_log["game_date"]) < game_date]
        vacated = float(np.clip(group["vacated_minutes"].sum(), 0.0, 60.0))
        usage_share = float(np.clip(group["usage_share"].sum(), 0.0, 0.45))

        boosts = {}
        fallback_pool = []
        for idx in beneficiaries:
            if float(frame.at[idx, "projected_minutes"]) < REDIS_BENEFICIARY_MIN_FLOOR:
                continue
            player_key = str(frame.at[idx, "player_key"])
            delta = 0.0
            observed = False
            for absent in group.itertuples():
                d = _with_without_minutes_delta(history, team, absent.player_key, player_key)
                if np.isfinite(d):
                    delta += float(np.clip(d, 0.0, 8.0))
                    observed = True
            if observed:
                boosts[idx] = delta
            else:
                fallback_pool.append(idx)

        observed_total = sum(boosts.values())
        remaining = max(vacated - observed_total, 0.0)
        if fallback_pool and remaining > 0:
            pool_minutes = frame.loc[fallback_pool, "projected_minutes"].clip(lower=0)
            share_base = float(pool_minutes.sum())
            for idx in fallback_pool:
                share = float(frame.at[idx, "projected_minutes"]) / share_base if share_base > 0 else 0.0
                boosts[idx] = min(remaining * share, 0.22 * float(frame.at[idx, "projected_minutes"]), 6.0)

        total = sum(boosts.values())
        scale = vacated / total if total > vacated and total > 0 else 1.0
        scale *= REDIS_BOOST_SCALE
        on_ball_uplift = float(min(1.0 + 0.45 * usage_share, 1.12))
        off_ball_uplift = float(min(1.0 + 0.18 * usage_share, 1.05))

        for idx, boost in boosts.items():
            boost = float(boost) * scale
            if boost <= 0.05:
                continue
            old_minutes = float(frame.at[idx, "projected_minutes"])
            new_minutes = float(np.clip(old_minutes + boost, 4.0, 38.0))
            frame.at[idx, "projected_minutes"] = new_minutes
            for stat in ("points", "assists", "threes_made"):
                frame.at[idx, f"uplift_{stat}"] = on_ball_uplift
            for stat in ("rebounds", "steals", "blocks"):
                frame.at[idx, f"uplift_{stat}"] = off_ball_uplift
            event = {
                "event": "redistribution",
                "game_date": game_date,
                "team": team,
                "player_name": frame.at[idx, "player_name"],
                "player_key": frame.at[idx, "player_key"],
                "absent_players": ";".join(group["player_name"].astype(str)),
                "minutes_before": round(old_minutes, 2),
                "minutes_after": round(new_minutes, 2),
                "rate_uplift_on_ball": round(on_ball_uplift, 4),
                "rate_uplift_off_ball": round(off_ball_uplift, 4),
            }
            if p7_events is not None:
                p7_events.append(event)
            if logger is not None:
                logger.info(
                    "P7 redistribution: %s (%s) minutes %.1f -> %.1f, on-ball uplift x%.3f (absent: %s)",
                    event["player_name"], team, old_minutes, new_minutes, on_ball_uplift, event["absent_players"],
                )
    return frame.drop(columns=["_gd"])


def matchup_label(team: object, opponent: object, is_home: object = None) -> str:
    team_value = str(team).strip().upper()
    opponent_value = str(opponent).strip().upper()
    if not team_value or not opponent_value:
        return team_value or opponent_value
    home_flag = pd.to_numeric(is_home, errors="coerce")
    if pd.notna(home_flag) and int(home_flag) == 0:
        return f"{team_value} @ {opponent_value}"
    return f"{team_value} vs {opponent_value}"


def summarize_samples(samples: np.ndarray) -> dict[str, float]:
    return {
        "mean": float(np.mean(samples)),
        "median": float(np.median(samples)),
        "p10": float(np.quantile(samples, 0.10)),
        "p50": float(np.quantile(samples, 0.50)),
        "p90": float(np.quantile(samples, 0.90)),
        "std": float(np.std(samples, ddof=0)),
    }


def build_projection_rows(today_features: pd.DataFrame, stat_models: dict, minutes_model: dict) -> pd.DataFrame:
    projection_frame = today_features.copy()
    m_ridge, m_tree, m_pred = predict_ensemble(minutes_model, projection_frame)
    projection_frame["projected_minutes"] = np.clip(m_pred, 5, 40)
    projection_frame["minutes_model_gap"] = np.abs(m_ridge - m_tree)
    projection_frame["minutes_stability_score"] = 1.0 / (1.0 + projection_frame["player_minutes_std_10"].fillna(4.0))

    for stat, bundle in stat_models.items():
        ridge_pred, tree_pred, pred = predict_ensemble(bundle, projection_frame)
        projection_frame[f"{stat}_ridge"] = ridge_pred
        projection_frame[f"{stat}_tree"] = tree_pred
        projection_frame[f"{stat}_proj"] = pred
        projection_frame[f"{stat}_model_gap"] = np.abs(ridge_pred - tree_pred)

    agreement_cols = [f"{stat}_model_gap" for stat in STAT_TARGETS] + ["minutes_model_gap"]
    projection_frame["model_agreement_score"] = 1.0 / (1.0 + projection_frame[agreement_cols].mean(axis=1).fillna(0))
    projection_frame["composite_volatility"] = projection_frame[
        [
            "player_points_std_10",
            "player_rebounds_std_10",
            "player_assists_std_10",
            "player_threes_made_std_10",
            "player_steals_std_10",
            "player_blocks_std_10",
        ]
    ].mean(axis=1).fillna(0) / 10.0
    projection_frame["confidence"] = projection_frame.apply(compute_confidence_label, axis=1)
    projection_frame["projected_minutes"] = projection_frame["projected_minutes"].clip(lower=8, upper=40)
    for stat in STAT_TARGETS:
        projection_frame[f"{stat}_proj"] = projection_frame[f"{stat}_proj"].clip(lower=0)
    return projection_frame


def simulate_player_row(
    row: pd.Series,
    rng: np.random.Generator,
    sportsbook_lines: pd.DataFrame,
    status_lookup: dict[str, str],
    p7_events: list | None = None,
) -> tuple[dict, list[dict]]:
    minutes_mean = float(row["projected_minutes"])
    baseline_minutes = pd.to_numeric(row.get("baseline_minutes"), errors="coerce")
    # rate back-out uses the minutes the stat projection implicitly assumed, so a
    # redistribution boost propagates fully into totals instead of cancelling out
    baseline_minutes = float(baseline_minutes) if pd.notna(baseline_minutes) and baseline_minutes > 0 else minutes_mean
    minutes_std = float(max(row.get("player_minutes_std_10", 3.0), 2.5))
    player_key = str(row.get("player_key", "")).strip()
    injury_status = status_lookup.get(player_key, "unknown")
    active_prob = active_probability_from_status(injury_status)
    confidence = str(row["confidence"])

    # Phase 7: availability drives the simulation. OUT-like => zeroed and unpriced.
    # Questionable/day-to-day => the active branch plays reduced minutes; line
    # probabilities stay conditional on playing because DNP voids the bet.
    is_out = False
    minutes_factor = 1.0
    if P7_ACTIVE_PROB and pd.notna(active_prob):
        if active_prob <= 0.0:
            is_out = True
        elif active_prob < 1.0:
            minutes_factor = STATUS_MINUTES_FACTOR.get(normalize_status(injury_status), 0.93)
            confidence = downgrade_confidence(confidence)
        if active_prob < 1.0 and p7_events is not None:
            p7_events.append(
                {
                    "event": "active_prob",
                    "game_date": str(row.get("game_date", "")),
                    "team": row.get("team", ""),
                    "player_name": row.get("player_name", ""),
                    "player_key": player_key,
                    "status": injury_status,
                    "active_prob": float(active_prob),
                    "minutes_factor": 0.0 if is_out else minutes_factor,
                    "zeroed": is_out,
                }
            )

    game_state = game_state_for_row(row, MONTE_CARLO_SIMS) if P7_GAME_STATE else None

    if is_out:
        sim_minutes = np.zeros(MONTE_CARLO_SIMS)
        minutes_mean = 0.0
    else:
        sim_minutes = compute_minutes_distribution(
            minutes_mean * minutes_factor, minutes_std, MONTE_CARLO_SIMS, rng
        )
        if game_state is not None:
            sim_minutes = apply_blowout_minutes(sim_minutes, game_state["margin"], minutes_mean)
    min_summary = summarize_samples(sim_minutes)
    game_date = pd.to_datetime(row["game_date"]).date().isoformat() if pd.notna(row.get("game_date")) else ""
    matchup = matchup_label(row["team"], row["opponent"], row.get("is_home"))

    summary = {
        "GAME_DATE": game_date,
        "PLAYER_KEY": player_key,
        "PLAYER_NAME": row["player_name"],
        "TEAM_ABBREVIATION": row["team"],
        "OPPONENT_ABBREVIATION": row["opponent"],
        "OPPONENT": row["opponent"],
        "MATCHUP": matchup,
        "GAME_ID": row.get("game_id", ""),
        "SIM_RUNS": MONTE_CARLO_SIMS,
        "ACTIVE_PROB": round(float(active_prob), 4) if pd.notna(active_prob) else np.nan,
        "INJURY_STATUS": injury_status.upper(),
        "CONFIDENCE_LABEL": confidence.title(),
        "MODEL_CONFIDENCE": confidence.upper(),
        "CONFIDENCE": confidence,
        "MIN_PROJ": round(min_summary["mean"], 2),
        "PRED_MIN": round(minutes_mean, 2),
        "SIM_MIN_P10": round(min_summary["p10"], 2),
        "SIM_MIN_P50": round(min_summary["p50"], 2),
        "SIM_MIN_P90": round(min_summary["p90"], 2),
        "SIM_MIN_STD": round(min_summary["std"], 2),
        "player_name": row["player_name"],
        "player_key": player_key,
        "team": row["team"],
        "opponent": row["opponent"],
        "matchup": matchup,
        "game_date": game_date,
        "game_id": row.get("game_id", ""),
        "projected_minutes": round(minutes_mean, 2),
        "confidence": confidence,
    }
    detail_rows: list[dict] = []
    stat_samples: dict[str, np.ndarray] = {}
    count_stats = discrete_stats()

    for stat in STAT_TARGETS:
        alias = STAT_ALIASES[stat]
        proj = float(row[f"{stat}_proj"])
        uplift = pd.to_numeric(row.get(f"uplift_{stat}"), errors="coerce")
        uplift = float(uplift) if pd.notna(uplift) and uplift > 0 else 1.0
        rate_mean = proj / max(baseline_minutes, 1.0)
        hist_rate = float(row.get(f"rate_{stat}_last_10", 0.0))
        blended_rate = max(0.01, (0.65 * rate_mean + 0.35 * hist_rate) * uplift)
        stat_std = float(max(row.get(f"player_{stat}_std_10", proj * 0.25), 0.15))

        if is_out:
            sampled_totals = np.zeros(MONTE_CARLO_SIMS)
        elif P7_COUPLED_SAMPLING:
            # Totals = minutes draw x per-minute rate draw, per draw. The historical
            # game-to-game std already contains minutes-driven variance, so the rate
            # noise gets only the residual variance not explained by minutes (and, for counts,
            # not explained by Poisson noise) — otherwise spreads double-count.
            minutes_mean_eff = float(np.mean(sim_minutes))
            minutes_var_eff = float(np.var(sim_minutes))
            mean_total = blended_rate * minutes_mean_eff
            target_var = stat_std**2
            if stat in count_stats:
                target_var -= mean_total  # Poisson contributes its own mean-sized variance
            rate_var = (target_var - (blended_rate**2) * minutes_var_eff) / max(minutes_mean_eff, 1.0) ** 2
            rate_std_coupled = math.sqrt(max(rate_var, (0.10 * blended_rate) ** 2))
            sampled_rate = gamma_rate_sample(blended_rate, rate_std_coupled, MONTE_CARLO_SIMS, rng)
            if game_state is not None:
                sampled_rate = sampled_rate * game_state["pace"]
            intensity = np.clip(np.nan_to_num(sim_minutes * sampled_rate), 0, None)
            if stat in count_stats:
                sampled_totals = rng.poisson(intensity).astype(float)
            else:
                sampled_totals = intensity
        else:
            rate_std = max(stat_std / max(minutes_mean, 1.0), blended_rate * 0.15)
            sampled_rate = np.clip(rng.normal(loc=blended_rate, scale=rate_std, size=MONTE_CARLO_SIMS), 0, None)
            sampled_mean = sim_minutes * sampled_rate
            sampled_totals = gamma_sample(sampled_mean.mean(), max(sampled_mean.std(), stat_std), MONTE_CARLO_SIMS, rng)
            sampled_totals = np.clip(0.55 * sampled_totals + 0.45 * sampled_mean, 0, None)

        stat_summary = summarize_samples(sampled_totals)
        stat_samples[stat] = sampled_totals
        stat_key = STAT_DISPLAY[stat][0]
        summary[f"{stat_key}_PROJ"] = round(stat_summary["mean"], 2)
        summary[f"SIM_{stat_key}_P10"] = round(stat_summary["p10"], 2)
        summary[f"SIM_{stat_key}_P50"] = round(stat_summary["p50"], 2)
        summary[f"SIM_{stat_key}_P90"] = round(stat_summary["p90"], 2)
        summary[f"SIM_{stat_key}_STD"] = round(stat_summary["std"], 2)
        floor = stat_summary["p10"]
        ceiling = stat_summary["p90"]

        if is_out:
            continue  # OUT players produce no priced lines
        player_lines = sportsbook_lines[
            (sportsbook_lines["player_key"] == row["player_key"]) & (sportsbook_lines["stat"] == stat)
        ]
        for _, line_row in player_lines.iterrows():
            line = float(line_row["line"])
            over_prob = float((sampled_totals > line).mean())
            under_prob = float((sampled_totals < line).mean())
            detail_rows.append(
                {
                    "player_name": row["player_name"],
                    "player_key": row["player_key"],
                    "team": row["team"],
                    "opponent": row["opponent"],
                    "stat": stat,
                    "line": line,
                    "sportsbook": line_row.get("sportsbook", "unknown"),
                    "over_odds": line_row.get("over_odds"),
                    "under_odds": line_row.get("under_odds"),
                    "mean": float(np.mean(sampled_totals)),
                    "median": float(np.median(sampled_totals)),
                    "floor": floor,
                    "ceiling": ceiling,
                    "stddev": stat_summary["std"],
                    "p10": stat_summary["p10"],
                    "p50": stat_summary["p50"],
                    "p90": stat_summary["p90"],
                    "over_hit_rate": over_prob,
                    "under_hit_rate": under_prob,
                    "projected_minutes": minutes_mean,
                    "confidence": confidence,
                    "confidence_label": confidence.title(),
                    "model_projection": proj,
                    "line_delta": float(np.mean(sampled_totals)) - line,
                }
            )


    for combo_name, (stat_list, stat_key, stat_label) in COMBO_STATS.items():
        combo_samples = np.sum([stat_samples[stat] for stat in stat_list], axis=0)
        stat_summary = summarize_samples(combo_samples)
        summary[f"{stat_key}_PROJ"] = round(stat_summary["mean"], 2)
        summary[f"SIM_{stat_key}_P10"] = round(stat_summary["p10"], 2)
        summary[f"SIM_{stat_key}_P50"] = round(stat_summary["p50"], 2)
        summary[f"SIM_{stat_key}_P90"] = round(stat_summary["p90"], 2)
        summary[f"SIM_{stat_key}_STD"] = round(stat_summary["std"], 2)

        if is_out:
            continue  # OUT players produce no priced lines
        player_lines = sportsbook_lines[
            (sportsbook_lines["player_key"] == row["player_key"]) & (sportsbook_lines["stat"] == combo_name)
        ]

        for _, line_row in player_lines.iterrows():
            line = float(line_row["line"])
            over_prob = float((combo_samples > line).mean())
            under_prob = float((combo_samples < line).mean())
            detail_rows.append(
                {
                    "player_name": row["player_name"],
                    "player_key": row["player_key"],
                    "team": row["team"],
                    "opponent": row["opponent"],
                    "stat": combo_name,
                    "line": line,
                    "sportsbook": line_row.get("sportsbook", "unknown"),
                    "over_odds": line_row.get("over_odds"),
                    "under_odds": line_row.get("under_odds"),
                    "mean": float(np.mean(combo_samples)),
                    "median": float(np.median(combo_samples)),
                    "floor": stat_summary["p10"],
                    "ceiling": stat_summary["p90"],
                    "stddev": stat_summary["std"],
                    "p10": stat_summary["p10"],
                    "p50": stat_summary["p50"],
                    "p90": stat_summary["p90"],
                    "over_hit_rate": over_prob,
                    "under_hit_rate": under_prob,
                    "projected_minutes": minutes_mean,
                    "confidence": confidence,
                    "confidence_label": confidence.title(),
                    "model_projection": np.nan,  # No single model projection for combos
                    "line_delta": float(np.mean(combo_samples)) - line,
                }
            )

    return summary, detail_rows





def build_app_view(projections: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, row in projections.iterrows():
        for stat, (stat_key, stat_label) in STAT_DISPLAY.items():
            lower_alias = STAT_ALIASES[stat]
            proj = pd.to_numeric(row.get(f"{stat_key}_PROJ", row.get(f"{lower_alias}_proj")), errors="coerce")
            if pd.isna(proj):
                continue
            p10 = pd.to_numeric(row.get(f"SIM_{stat_key}_P10", row.get(f"{lower_alias}_floor")), errors="coerce")
            p50 = pd.to_numeric(row.get(f"SIM_{stat_key}_P50", row.get(f"{lower_alias}_median")), errors="coerce")
            p90 = pd.to_numeric(row.get(f"SIM_{stat_key}_P90", row.get(f"{lower_alias}_ceiling")), errors="coerce")
            std = pd.to_numeric(row.get(f"SIM_{stat_key}_STD", row.get(f"{lower_alias}_std")), errors="coerce")
            rows.append(
                {
                    "GAME_DATE": row.get("GAME_DATE"),
                    "PLAYER_KEY": row.get("PLAYER_KEY"),
                    "PLAYER": row.get("PLAYER_NAME", row.get("player_name")),
                    "TEAM": row.get("TEAM_ABBREVIATION", row.get("team")),
                    "OPPONENT": row.get("OPPONENT_ABBREVIATION", row.get("opponent")),
                    "MATCHUP": row.get("MATCHUP", row.get("matchup")),
                    "STAT": stat_key,
                    "STAT_LABEL": stat_label,
                    "PROJECTION": round(float(proj), 2),
                    "MEDIAN": round(float(p50), 2) if pd.notna(p50) else np.nan,
                    "FLOOR": round(float(p10), 2) if pd.notna(p10) else np.nan,
                    "CEILING": round(float(p90), 2) if pd.notna(p90) else np.nan,
                    "STDDEV": round(float(std), 2) if pd.notna(std) else np.nan,
                    "MIN": row.get("MIN_PROJ", row.get("projected_minutes")),
                    "CONFIDENCE": row.get("CONFIDENCE_LABEL", row.get("confidence")),
                    "ACTIVE_PROB": row.get("ACTIVE_PROB"),
                    "INJURY_STATUS": row.get("INJURY_STATUS"),
                    "SIM_RUNS": row.get("SIM_RUNS"),
                }
            )
        for combo_name, (stat_list, stat_key, stat_label) in COMBO_STATS.items():
            proj = pd.to_numeric(row.get(f"{stat_key}_PROJ"), errors="coerce")
            if pd.isna(proj):
                continue
            p10 = pd.to_numeric(row.get(f"SIM_{stat_key}_P10"), errors="coerce")
            p50 = pd.to_numeric(row.get(f"SIM_{stat_key}_P50"), errors="coerce")
            p90 = pd.to_numeric(row.get(f"SIM_{stat_key}_P90"), errors="coerce")
            std = pd.to_numeric(row.get(f"SIM_{stat_key}_STD"), errors="coerce")
            rows.append(
                {
                    "GAME_DATE": row.get("GAME_DATE"),
                    "PLAYER_KEY": row.get("PLAYER_KEY"),
                    "PLAYER": row.get("PLAYER_NAME", row.get("player_name")),
                    "TEAM": row.get("TEAM_ABBREVIATION", row.get("team")),
                    "OPPONENT": row.get("OPPONENT_ABBREVIATION", row.get("opponent")),
                    "MATCHUP": row.get("MATCHUP", row.get("matchup")),
                    "STAT": stat_key,
                    "STAT_LABEL": stat_label,
                    "PROJECTION": round(float(proj), 2),
                    "MEDIAN": round(float(p50), 2) if pd.notna(p50) else np.nan,
                    "FLOOR": round(float(p10), 2) if pd.notna(p10) else np.nan,
                    "CEILING": round(float(p90), 2) if pd.notna(p90) else np.nan,
                    "STDDEV": round(float(std), 2) if pd.notna(std) else np.nan,
                    "MIN": row.get("MIN_PROJ", row.get("projected_minutes")),
                    "CONFIDENCE": row.get("CONFIDENCE_LABEL", row.get("confidence")),
                    "ACTIVE_PROB": row.get("ACTIVE_PROB"),
                    "INJURY_STATUS": row.get("INJURY_STATUS"),
                    "SIM_RUNS": row.get("SIM_RUNS"),
                }
            )
    app_view = pd.DataFrame(rows)
    if app_view.empty:
        return app_view
    app_view["CONFIDENCE_RANK"] = app_view["CONFIDENCE"].astype(str).str.lower().map({"high": 3, "medium": 2, "low": 1}).fillna(0)
    return app_view.sort_values(
        ["TEAM", "STAT", "PROJECTION", "PLAYER"],
        ascending=[True, True, False, True],
        kind="stable",
    ).reset_index(drop=True)


def main() -> None:
    logger = setup_logging("simulate_wnba_today")
    today_features = pd.read_csv(TODAY_FEATURES_PATH, parse_dates=["game_date"])
    if today_features.empty:
        raise ValueError("Today's feature file is empty. Run build_wnba_features_today.py first.")

    games_log, _, _, sportsbook_lines, _, player_status = load_inputs_for_pipeline(logger)
    status_lookup = build_status_lookup(player_status)
    base_dir = TODAY_FEATURES_PATH.parent.parent
    stat_models = load_stat_models(base_dir)
    minutes_model = load_model_bundle(MINUTES_MODEL_PATH)
    projections_input = build_projection_rows(today_features, stat_models, minutes_model)

    logger.info(
        "Phase 7 flags: active_prob=%s redistribution=%s coupled_sampling=%s discrete_counts=%s "
        "discrete_assists=%s game_state=%s",
        P7_ACTIVE_PROB, P7_REDISTRIBUTION, P7_COUPLED_SAMPLING, P7_DISCRETE_COUNTS,
        P7_DISCRETE_ASSISTS, P7_GAME_STATE,
    )
    p7_events: list[dict] = []
    if P7_REDISTRIBUTION:
        absences = build_absences_from_status(player_status, games_log, projections_input, logger)
        projections_input = apply_absence_redistribution(
            projections_input, games_log, absences, p7_events, logger
        )

    rng = np.random.default_rng(42)
    projection_rows = []
    simulation_rows = []
    for _, row in projections_input.iterrows():
        summary_row, detail_rows = simulate_player_row(row, rng, sportsbook_lines, status_lookup, p7_events=p7_events)
        projection_rows.append(summary_row)
        simulation_rows.extend(detail_rows)

    if p7_events:
        events_frame = pd.DataFrame(p7_events)
        events_path = TODAY_FEATURES_PATH.parent / "wnba_p7_simulation_events.csv"
        events_frame.to_csv(events_path, index=False)
        for record in p7_events:
            if record.get("event") == "active_prob":
                logger.info(
                    "P7 availability applied: %s status=%s active_prob=%.2f minutes_factor=%.2f zeroed=%s",
                    record.get("player_name"), record.get("status"), record.get("active_prob"),
                    record.get("minutes_factor"), record.get("zeroed"),
                )
        logger.info("Phase 7 wrote %d simulation events to %s", len(p7_events), events_path)

    projections = pd.DataFrame(projection_rows)
    for stat, alias in STAT_ALIASES.items():
        if f"{alias}_floor" not in projections.columns:
            projections[f"{alias}_floor"] = np.nan
            projections[f"{alias}_ceiling"] = np.nan

    ordered_columns = [
        "GAME_DATE",
        "PLAYER_KEY",
        "PLAYER_NAME",
        "TEAM_ABBREVIATION",
        "OPPONENT_ABBREVIATION",
        "OPPONENT",
        "MATCHUP",
        "GAME_ID",
        "SIM_RUNS",
        "ACTIVE_PROB",
        "INJURY_STATUS",
        "CONFIDENCE_LABEL",
        "MODEL_CONFIDENCE",
        "MIN_PROJ",
        "PRED_MIN",
        "SIM_MIN_P10",
        "SIM_MIN_P50",
        "SIM_MIN_P90",
        "SIM_MIN_STD",
        "PTS_PROJ",
        "PRED_PTS",
        "SIM_PTS_P10",
        "SIM_PTS_P50",
        "SIM_PTS_P90",
        "SIM_PTS_STD",
        "REB_PROJ",
        "PRED_REB",
        "SIM_REB_P10",
        "SIM_REB_P50",
        "SIM_REB_P90",
        "SIM_REB_STD",
        "AST_PROJ",
        "PRED_AST",
        "SIM_AST_P10",
        "SIM_AST_P50",
        "SIM_AST_P90",
        "SIM_AST_STD",
        "FG3M_PROJ",
        "PRED_FG3M",
        "SIM_FG3M_P10",
        "SIM_FG3M_P50",
        "SIM_FG3M_P90",
        "SIM_FG3M_STD",
        "STL_PROJ",
        "PRED_STL",
        "SIM_STL_P10",
        "SIM_STL_P50",
        "SIM_STL_P90",
        "SIM_STL_STD",
        "BLK_PROJ",
        "PRED_BLK",
        "SIM_BLK_P10",
        "SIM_BLK_P50",
        "SIM_BLK_P90",
        "SIM_BLK_STD",
        "PRA_PROJ",
        "SIM_PRA_P10",
        "SIM_PRA_P50",
        "SIM_PRA_P90",
        "SIM_PRA_STD",
        "PR_PROJ",
        "SIM_PR_P10",
        "SIM_PR_P50",
        "SIM_PR_P90",
        "SIM_PR_STD",
        "PA_PROJ",
        "SIM_PA_P10",
        "SIM_PA_P50",
        "SIM_PA_P90",
        "SIM_PA_STD",
        "RA_PROJ",
        "SIM_RA_P10",
        "SIM_RA_P50",
        "SIM_RA_P90",
        "SIM_RA_STD",
        "SB_PROJ",
        "SIM_SB_P10",
        "SIM_SB_P50",
        "SIM_SB_P90",
        "SIM_SB_STD",
        "player_name",
        "player_key",
        "team",
        "opponent",
        "matchup",
        "game_date",
        "game_id",
        "projected_minutes",
        "pts_proj",
        "pts_median",
        "reb_proj",
        "reb_median",
        "ast_proj",
        "ast_median",
        "fg3m_proj",
        "fg3m_median",
        "stl_proj",
        "stl_median",
        "blk_proj",
        "blk_median",
        "pts_floor",
        "pts_ceiling",
        "pts_std",
        "reb_floor",
        "reb_ceiling",
        "reb_std",
        "ast_floor",
        "ast_ceiling",
        "ast_std",
        "fg3m_floor",
        "fg3m_ceiling",
        "fg3m_std",
        "stl_floor",
        "stl_ceiling",
        "stl_std",
        "blk_floor",
        "blk_ceiling",
        "blk_std",
        "confidence",
    ]
    for column in ordered_columns:
        if column not in projections.columns:
            projections[column] = np.nan
    projections = projections[ordered_columns]
    projections.to_csv(PROJECTIONS_PATH, index=False)
    app_view = build_app_view(projections)
    app_view.to_csv(APP_VIEW_PROJECTIONS_PATH, index=False)
    archive_dataframe(projections, PROJECTIONS_ARCHIVE_DIR, "wnba_projections")

    simulation_detail = pd.DataFrame(simulation_rows, columns=SIMULATION_DETAIL_COLUMNS)
    simulation_detail.to_csv(SIMULATION_DETAIL_PATH, index=False)
    logger.info("Saved projections to %s and simulation detail to %s", PROJECTIONS_PATH, SIMULATION_DETAIL_PATH)


if __name__ == "__main__":
    main()
