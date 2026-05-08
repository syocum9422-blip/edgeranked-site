from __future__ import annotations

from pathlib import Path

import pandas as pd

from wnba_model_config import (
    RAW_PLAYER_GAMES_PATH,
    RAW_PLAYER_POSITIONS_PATH,
    RAW_TEAM_CONTEXT_PATH,
)
from wnba_model_utils import setup_logging


# Drop a downloaded WNBA CSV here, then run:
# python3 import_wnba_csv.py
SOURCE_CSV_PATH = Path("/Users/steveyocum/WNBA_Model/data/raw/source_wnba_dataset.csv")


PLAYER_GAME_COLUMN_MAP = {
    "date": "game_date",
    "game_date": "game_date",
    "season": "season",
    "player_name": "player_name",
    "player": "player_name",
    "name": "player_name",
    "team": "team",
    "team_abbrev": "team",
    "opponent": "opponent",
    "opp": "opponent",
    "home_away": "home_away",
    "venue": "home_away",
    "minutes": "minutes",
    "min": "minutes",
    "points": "points",
    "pts": "points",
    "rebounds": "rebounds",
    "reb": "rebounds",
    "assists": "assists",
    "ast": "assists",
    "threes_made": "threes_made",
    "fg3m": "threes_made",
    "3pm": "threes_made",
    "steals": "steals",
    "stl": "steals",
    "blocks": "blocks",
    "blk": "blocks",
}


POSITION_COLUMN_MAP = {
    "player_name": "player_name",
    "player": "player_name",
    "name": "player_name",
    "team": "team",
    "team_abbrev": "team",
    "position": "position",
    "pos": "position",
}


def _normalize_columns(df: pd.DataFrame, column_map: dict[str, str]) -> pd.DataFrame:
    rename = {}
    for column in df.columns:
        key = str(column).strip().lower()
        if key in column_map:
            rename[column] = column_map[key]
    return df.rename(columns=rename)


def import_player_games(df: pd.DataFrame, logger) -> None:
    frame = _normalize_columns(df, PLAYER_GAME_COLUMN_MAP)
    required = ["game_date", "player_name", "team", "opponent", "minutes", "points", "rebounds", "assists"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"Source CSV is missing required player game columns: {missing}")

    keep = [
        "game_date",
        "season",
        "player_name",
        "team",
        "opponent",
        "home_away",
        "minutes",
        "points",
        "rebounds",
        "assists",
        "threes_made",
        "steals",
        "blocks",
    ]
    for column in keep:
        if column not in frame.columns:
            frame[column] = pd.NA
    frame = frame[keep].copy()
    frame.to_csv(RAW_PLAYER_GAMES_PATH, index=False)
    logger.info("Wrote player games import to %s with %s rows", RAW_PLAYER_GAMES_PATH, len(frame))


def import_positions_if_available(df: pd.DataFrame, logger) -> None:
    frame = _normalize_columns(df, POSITION_COLUMN_MAP)
    if not {"player_name", "position"}.issubset(frame.columns):
        logger.info("No position columns found in source CSV; skipping position export.")
        return
    keep = ["player_name", "team", "position"]
    for column in keep:
        if column not in frame.columns:
            frame[column] = pd.NA
    positions = frame[keep].dropna(subset=["player_name", "position"]).drop_duplicates()
    if positions.empty:
        logger.info("Source CSV did not yield any position rows.")
        return
    positions.to_csv(RAW_PLAYER_POSITIONS_PATH, index=False)
    logger.info("Wrote player positions import to %s with %s rows", RAW_PLAYER_POSITIONS_PATH, len(positions))


def main() -> None:
    logger = setup_logging("import_wnba_csv")
    if not SOURCE_CSV_PATH.exists():
        raise FileNotFoundError(
            f"Put your downloaded WNBA CSV at {SOURCE_CSV_PATH} and rerun this script."
        )
    source = pd.read_csv(SOURCE_CSV_PATH)
    import_player_games(source, logger)
    import_positions_if_available(source, logger)

    if not RAW_TEAM_CONTEXT_PATH.exists():
        pd.DataFrame(
            columns=["game_date", "team", "opponent", "pace", "off_rating", "def_rating", "team_points", "opp_points"]
        ).to_csv(RAW_TEAM_CONTEXT_PATH, index=False)
        logger.info("Created empty team context template at %s", RAW_TEAM_CONTEXT_PATH)


if __name__ == "__main__":
    main()
