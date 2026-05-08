from __future__ import annotations

import numpy as np
import pandas as pd

from wnba_model_config import DATASET_PATH, STAT_TARGETS
from wnba_model_utils import (
    add_group_rolling_features,
    load_inputs_for_pipeline,
    setup_logging,
)


def build_team_game_aggregates(games: pd.DataFrame) -> pd.DataFrame:
    team_game = (
        games.groupby(["game_date", "team", "opponent"], as_index=False)
        .agg(
            team_points=("points", "sum"),
            team_rebounds=("rebounds", "sum"),
            team_assists=("assists", "sum"),
            team_threes_made=("threes_made", "sum"),
            team_steals=("steals", "sum"),
            team_blocks=("blocks", "sum"),
            team_minutes=("minutes", "sum"),
        )
        .sort_values(["team", "game_date"])
        .reset_index(drop=True)
    )
    for column in ["team_points", "team_rebounds", "team_assists", "team_threes_made", "team_steals", "team_blocks"]:
        team_game[f"{column}_last_10"] = team_game.groupby("team")[column].transform(
            lambda s: s.shift(1).rolling(10, min_periods=1).mean()
        )
    return team_game


def build_opponent_allowance(games: pd.DataFrame, positions: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    player_games = games.copy()
    if "position" not in player_games.columns:
        player_games = player_games.merge(
            positions[["player_key", "position"]].drop_duplicates(),
            on="player_key",
            how="left",
        )
    player_games["position"] = player_games.get("position", "UNK")
    player_games["position"] = player_games["position"].fillna("UNK")

    team_allowed = (
        player_games.groupby(["game_date", "opponent"], as_index=False)
        .agg(
            opponent_points_allowed=("points", "sum"),
            opponent_rebounds_allowed=("rebounds", "sum"),
            opponent_assists_allowed=("assists", "sum"),
            opponent_threes_made_allowed=("threes_made", "sum"),
            opponent_steals_allowed=("steals", "sum"),
            opponent_blocks_allowed=("blocks", "sum"),
        )
        .rename(columns={"opponent": "team"})
        .sort_values(["team", "game_date"])
        .reset_index(drop=True)
    )
    for column in [c for c in team_allowed.columns if c.startswith("opponent_")]:
        team_allowed[f"{column}_last_10"] = team_allowed.groupby("team")[column].transform(
            lambda s: s.shift(1).rolling(10, min_periods=1).mean()
        )

    position_allowed = (
        player_games.groupby(["game_date", "opponent", "position"], as_index=False)
        .agg(
            pos_points_allowed=("points", "sum"),
            pos_rebounds_allowed=("rebounds", "sum"),
            pos_assists_allowed=("assists", "sum"),
            pos_threes_made_allowed=("threes_made", "sum"),
            pos_steals_allowed=("steals", "sum"),
            pos_blocks_allowed=("blocks", "sum"),
        )
        .rename(columns={"opponent": "team"})
        .sort_values(["team", "position", "game_date"])
        .reset_index(drop=True)
    )
    for column in [c for c in position_allowed.columns if c.startswith("pos_")]:
        position_allowed[f"{column}_last_10"] = position_allowed.groupby(["team", "position"])[column].transform(
            lambda s: s.shift(1).rolling(10, min_periods=1).mean()
        )
    return team_allowed, position_allowed


def add_schedule_features(games: pd.DataFrame) -> pd.DataFrame:
    games = games.sort_values(["player_key", "game_date"]).copy()
    games["prev_game_date"] = games.groupby("player_key")["game_date"].shift(1)
    games["rest_days"] = (games["game_date"] - games["prev_game_date"]).dt.days.sub(1)
    games["rest_days"] = games["rest_days"].fillna(3).clip(lower=0, upper=7)
    games["is_back_to_back"] = (games["rest_days"] <= 0).astype(int)
    games["games_played_season"] = games.groupby(["player_key", "season"]).cumcount()
    return games


def add_usage_features(games: pd.DataFrame, team_game: pd.DataFrame) -> pd.DataFrame:
    merged = games.merge(team_game, on=["game_date", "team", "opponent"], how="left")
    merged["usage_proxy"] = (
        merged["points"].fillna(0)
        + 1.2 * merged["assists"].fillna(0)
        + 0.7 * merged["rebounds"].fillna(0)
        + 0.6 * merged["threes_made"].fillna(0)
    ) / merged["minutes"].replace(0, np.nan)
    merged["usage_proxy"] = merged["usage_proxy"].replace([np.inf, -np.inf], np.nan).fillna(0)
    merged["usage_proxy_last_5"] = merged.groupby("player_key")["usage_proxy"].transform(
        lambda s: s.shift(1).rolling(5, min_periods=1).mean()
    )
    merged["usage_proxy_last_10"] = merged.groupby("player_key")["usage_proxy"].transform(
        lambda s: s.shift(1).rolling(10, min_periods=1).mean()
    )
    return merged


def add_player_trend_features(games: pd.DataFrame) -> pd.DataFrame:
    frame = add_group_rolling_features(games, "player_key", ["minutes", *STAT_TARGETS])
    frame["minutes_trend_3_over_10"] = frame["minutes_rolling_mean_3"] - frame["minutes_rolling_mean_10"]

    for stat in ["minutes", *STAT_TARGETS]:
        rate_col = f"rate_{stat}_last_10"
        if stat == "minutes":
            continue
        frame[rate_col] = frame[f"{stat}_rolling_mean_10"] / frame["minutes_rolling_mean_10"].replace(0, np.nan)
        frame[rate_col] = frame[rate_col].replace([np.inf, -np.inf], np.nan).fillna(0)
        frame[f"player_{stat}_std_10"] = frame[f"{stat}_rolling_std_10"].fillna(frame[f"{stat}_rolling_std_5"]).fillna(0)

    frame["player_minutes_std_10"] = frame["minutes_rolling_std_10"].fillna(frame["minutes_rolling_std_5"]).fillna(0)
    for stat in ["minutes", *STAT_TARGETS]:
        if stat == "minutes":
            prefix = "season_avg_minutes"
        else:
            prefix = f"season_avg_{stat}"
        frame[prefix] = frame.groupby(["player_key", "season"])[stat].transform(lambda s: s.shift(1).expanding().mean())
    return frame


def enrich_with_team_context(frame: pd.DataFrame, team_context: pd.DataFrame) -> pd.DataFrame:
    if team_context.empty:
        for column in ["pace_last_10", "off_rating_last_10", "def_rating_last_10", "opp_points_last_10"]:
            frame[column] = np.nan
        return frame

    context = team_context.sort_values(["team", "game_date"]).copy()
    for column in ["pace", "off_rating", "def_rating", "team_points", "opp_points"]:
        context[f"{column}_last_10"] = context.groupby("team")[column].transform(
            lambda s: s.shift(1).rolling(10, min_periods=1).mean()
        )
    return frame.merge(
        context[
            [
                "game_date",
                "team",
                "opponent",
                "pace_last_10",
                "off_rating_last_10",
                "def_rating_last_10",
                "opp_points_last_10",
            ]
        ],
        on=["game_date", "team", "opponent"],
        how="left",
    )


def main() -> None:
    logger = setup_logging("build_wnba_dataset")
    games, team_context, _, _, positions, _ = load_inputs_for_pipeline(logger)

    dataset = games.copy()
    dataset = add_schedule_features(dataset)
    dataset = dataset.merge(positions[["player_key", "position"]], on="player_key", how="left")
    dataset["position"] = dataset["position"].fillna("UNK")

    team_game = build_team_game_aggregates(dataset)
    dataset = add_usage_features(dataset, team_game)
    dataset = add_player_trend_features(dataset)
    dataset = enrich_with_team_context(dataset, team_context)

    team_allowed, position_allowed = build_opponent_allowance(dataset, positions)
    dataset = dataset.merge(
        team_allowed[
            [
                "game_date",
                "team",
                "opponent_points_allowed_last_10",
                "opponent_rebounds_allowed_last_10",
                "opponent_assists_allowed_last_10",
                "opponent_threes_made_allowed_last_10",
                "opponent_steals_allowed_last_10",
                "opponent_blocks_allowed_last_10",
            ]
        ].rename(columns={"team": "opponent"}),
        on=["game_date", "opponent"],
        how="left",
    )
    dataset = dataset.merge(
        position_allowed[
            [
                "game_date",
                "team",
                "position",
                "pos_points_allowed_last_10",
                "pos_rebounds_allowed_last_10",
                "pos_assists_allowed_last_10",
                "pos_threes_made_allowed_last_10",
                "pos_steals_allowed_last_10",
                "pos_blocks_allowed_last_10",
            ]
        ].rename(columns={"team": "opponent"}),
        on=["game_date", "opponent", "position"],
        how="left",
    )

    dataset["minutes"] = dataset["minutes"].fillna(dataset["minutes_rolling_mean_5"]).fillna(dataset["season_avg_minutes"])
    dataset["opp_points_allowed_last_10"] = dataset["opp_points_last_10"]
    dataset = dataset.sort_values(["game_date", "team", "player_name"]).reset_index(drop=True)
    dataset.to_csv(DATASET_PATH, index=False)
    logger.info("Saved training dataset to %s with %s rows", DATASET_PATH, len(dataset))


if __name__ == "__main__":
    main()
