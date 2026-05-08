from __future__ import annotations

import pandas as pd

from wnba_model_config import DATASET_PATH, TODAY_FEATURES_PATH
from wnba_model_utils import load_inputs_for_pipeline, setup_logging


def build_today_team_map(schedule_today: pd.DataFrame) -> pd.DataFrame:
    schedule_today = schedule_today.drop_duplicates(subset=["game_date", "home_team", "away_team", "game_id"]).copy()
    home = schedule_today[["game_date", "game_id", "home_team", "away_team"]].copy()
    home["team"] = home["home_team"]
    home["opponent"] = home["away_team"]
    home["is_home"] = 1

    away = schedule_today[["game_date", "game_id", "home_team", "away_team"]].copy()
    away["team"] = away["away_team"]
    away["opponent"] = away["home_team"]
    away["is_home"] = 0
    return pd.concat([home, away], ignore_index=True)[["game_date", "game_id", "team", "opponent", "is_home"]]


def latest_player_rows(dataset: pd.DataFrame) -> pd.DataFrame:
    latest = (
        dataset.sort_values(["player_key", "game_date"])
        .groupby("player_key", as_index=False)
        .tail(1)
        .copy()
    )
    latest["last_game_date"] = latest["game_date"]
    return latest


def apply_status_filter(frame: pd.DataFrame, player_status: pd.DataFrame) -> pd.DataFrame:
    if player_status.empty:
        return frame
    merged = frame.merge(player_status[["player_key", "status"]], on="player_key", how="left")
    excluded = {"out", "doubtful", "inactive", "suspended"}
    merged = merged[~merged["status"].fillna("available").isin(excluded)].copy()
    return merged.drop(columns=["status"])


def latest_team_snapshot(dataset: pd.DataFrame) -> pd.DataFrame:
    columns = ["team", "pace_last_10", "off_rating_last_10", "def_rating_last_10", "team_points_last_10", "opp_points_last_10"]
    return (
        dataset.sort_values(["team", "game_date"])
        .groupby("team", as_index=False)
        .tail(1)[columns]
        .drop_duplicates("team")
    )


def latest_opponent_snapshot(dataset: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "opponent",
        "opponent_points_allowed_last_10",
        "opponent_rebounds_allowed_last_10",
        "opponent_assists_allowed_last_10",
        "opponent_threes_made_allowed_last_10",
        "opponent_steals_allowed_last_10",
        "opponent_blocks_allowed_last_10",
    ]
    return (
        dataset.sort_values(["opponent", "game_date"])
        .groupby("opponent", as_index=False)
        .tail(1)[columns]
        .drop_duplicates("opponent")
    )


def latest_position_snapshot(dataset: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "opponent",
        "position",
        "pos_points_allowed_last_10",
        "pos_rebounds_allowed_last_10",
        "pos_assists_allowed_last_10",
        "pos_threes_made_allowed_last_10",
        "pos_steals_allowed_last_10",
        "pos_blocks_allowed_last_10",
    ]
    return (
        dataset.sort_values(["opponent", "position", "game_date"])
        .groupby(["opponent", "position"], as_index=False)
        .tail(1)[columns]
        .drop_duplicates(["opponent", "position"])
    )


def main() -> None:
    logger = setup_logging("build_wnba_features_today")
    dataset = pd.read_csv(DATASET_PATH, parse_dates=["game_date"])
    _, _, schedule_today, _, _, player_status = load_inputs_for_pipeline(logger)
    if schedule_today.empty:
        raise ValueError("Today's schedule is empty. Populate data/raw/wnba_schedule_today_raw.csv first.")

    team_map = build_today_team_map(schedule_today)
    latest = latest_player_rows(dataset)
    today_features = latest.merge(team_map, on="team", how="inner", suffixes=("", "_today"))
    today_features["game_date"] = today_features["game_date_today"]
    today_features["opponent"] = today_features["opponent_today"]
    today_features["is_home"] = today_features["is_home_today"]
    today_features["days_since_last_game"] = (today_features["game_date"] - pd.to_datetime(today_features["last_game_date"])).dt.days
    today_features["rest_days"] = today_features["days_since_last_game"].sub(1).fillna(3).clip(lower=0, upper=7)
    today_features["is_back_to_back"] = (today_features["rest_days"] <= 0).astype(int)

    # Use historical rolling features from the latest completed game as the input state for today's matchup.
    drop_cols = [column for column in today_features.columns if column.endswith("_today")]
    today_features = today_features.drop(columns=drop_cols)
    today_features = today_features.merge(latest_team_snapshot(dataset), on="team", how="left", suffixes=("", "_team_latest"))
    today_features = today_features.merge(latest_opponent_snapshot(dataset), on="opponent", how="left", suffixes=("", "_opp_latest"))
    today_features = today_features.merge(latest_position_snapshot(dataset), on=["opponent", "position"], how="left")
    for column in [
        "pace_last_10",
        "off_rating_last_10",
        "def_rating_last_10",
        "team_points_last_10",
        "opp_points_last_10",
        "opponent_points_allowed_last_10",
        "opponent_rebounds_allowed_last_10",
        "opponent_assists_allowed_last_10",
        "opponent_threes_made_allowed_last_10",
        "opponent_steals_allowed_last_10",
        "opponent_blocks_allowed_last_10",
    ]:
        latest_column = f"{column}_opp_latest" if f"{column}_opp_latest" in today_features.columns else f"{column}_team_latest"
        if latest_column in today_features.columns:
            today_features[column] = today_features[latest_column].combine_first(today_features[column])
    drop_snapshot_cols = [
        column
        for column in today_features.columns
        if column.endswith("_team_latest") or column.endswith("_opp_latest")
    ]
    today_features = today_features.drop(columns=drop_snapshot_cols)
    today_features = apply_status_filter(today_features, player_status)
    today_features = today_features[today_features["days_since_last_game"].fillna(999) <= 30].copy()
    today_features = today_features.drop_duplicates(subset=["player_key", "team", "opponent", "game_date"])

    numeric_fill_cols = [
        "minutes",
        "minutes_rolling_mean_3",
        "minutes_rolling_mean_5",
        "minutes_rolling_mean_10",
        "season_avg_minutes",
    ]
    for column in numeric_fill_cols:
        if column in today_features.columns:
            today_features[column] = today_features[column].fillna(today_features["season_avg_minutes"])

    today_features.to_csv(TODAY_FEATURES_PATH, index=False)
    logger.info("Saved today's features to %s for %s players", TODAY_FEATURES_PATH, len(today_features))


if __name__ == "__main__":
    main()
