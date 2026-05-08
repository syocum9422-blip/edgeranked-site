from __future__ import annotations

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
    "doubtful": 0.25,
    "out": 0.0,
    "inactive": 0.0,
    "suspended": 0.0,
}

COMBO_STATS = {
    "pra": (["points", "rebounds", "assists"], "PRA", "Pts+Reb+Ast"),
    "pr": (["points", "rebounds"], "PR", "Pts+Reb"),
    "pa": (["points", "assists"], "PA", "Pts+Ast"),
    "ra": (["rebounds", "assists"], "RA", "Reb+Ast"),
    "sb": (["steals", "blocks"], "SB", "Stl+Blk"),
}


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
) -> tuple[dict, list[dict]]:
    minutes_mean = float(row["projected_minutes"])
    minutes_std = float(max(row.get("player_minutes_std_10", 3.0), 2.5))
    sim_minutes = compute_minutes_distribution(minutes_mean, minutes_std, MONTE_CARLO_SIMS, rng)
    min_summary = summarize_samples(sim_minutes)
    player_key = str(row.get("player_key", "")).strip()
    injury_status = status_lookup.get(player_key, "unknown")
    active_prob = active_probability_from_status(injury_status)
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
        "CONFIDENCE_LABEL": str(row["confidence"]).title(),
        "MODEL_CONFIDENCE": str(row["confidence"]).upper(),
        "CONFIDENCE": row["confidence"],
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
        "confidence": row["confidence"],
    }
    detail_rows: list[dict] = []
    stat_samples: dict[str, np.ndarray] = {}


    for stat in STAT_TARGETS:
        alias = STAT_ALIASES[stat]
        proj = float(row[f"{stat}_proj"])
        rate_mean = proj / max(minutes_mean, 1.0)
        hist_rate = float(row.get(f"rate_{stat}_last_10", 0.0))
        blended_rate = max(0.01, 0.65 * rate_mean + 0.35 * hist_rate)
        stat_std = float(max(row.get(f"player_{stat}_std_10", proj * 0.25), 0.15))
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
                    "confidence": row["confidence"],
                    "confidence_label": str(row["confidence"]).title(),
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
                    "confidence": row["confidence"],
                    "confidence_label": str(row["confidence"]).title(),
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

    _, _, _, sportsbook_lines, _, player_status = load_inputs_for_pipeline(logger)
    status_lookup = build_status_lookup(player_status)
    base_dir = TODAY_FEATURES_PATH.parent.parent
    stat_models = load_stat_models(base_dir)
    minutes_model = load_model_bundle(MINUTES_MODEL_PATH)
    projections_input = build_projection_rows(today_features, stat_models, minutes_model)

    rng = np.random.default_rng(42)
    projection_rows = []
    simulation_rows = []
    for _, row in projections_input.iterrows():
        summary_row, detail_rows = simulate_player_row(row, rng, sportsbook_lines, status_lookup)
        projection_rows.append(summary_row)
        simulation_rows.extend(detail_rows)

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

    simulation_detail = pd.DataFrame(simulation_rows)
    simulation_detail.to_csv(SIMULATION_DETAIL_PATH, index=False)
    logger.info("Saved projections to %s and simulation detail to %s", PROJECTIONS_PATH, SIMULATION_DETAIL_PATH)


if __name__ == "__main__":
    main()
