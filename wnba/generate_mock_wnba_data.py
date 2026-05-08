from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from wnba_model_config import (
    RAW_PLAYER_GAMES_PATH,
    RAW_PLAYER_POSITIONS_PATH,
    RAW_PLAYER_STATUS_PATH,
    RAW_SCHEDULE_TODAY_PATH,
    RAW_SPORTSBOOK_LINES_PATH,
    RAW_TEAM_CONTEXT_PATH,
)
from wnba_model_utils import setup_logging


RNG = np.random.default_rng(42)
SEASON_START = pd.Timestamp("2025-05-16")
TODAY_DATE = pd.Timestamp("2025-07-05")

TEAM_ROSTERS = {
    "NYL": [
        ("Sabrina Ionescu", "G", 32, 19.0, 5.8, 6.4, 2.7, 1.4, 0.3),
        ("Breanna Stewart", "F", 33, 21.8, 8.7, 3.9, 1.8, 1.5, 1.3),
        ("Jonquel Jones", "C", 30, 15.4, 9.1, 2.4, 1.2, 0.8, 1.4),
        ("Betnijah Laney-Hamilton", "G", 29, 12.8, 4.4, 3.0, 1.7, 1.0, 0.2),
        ("Courtney Vandersloot", "G", 27, 10.1, 3.1, 6.2, 1.2, 1.1, 0.1),
    ],
    "LVA": [
        ("A'ja Wilson", "C", 34, 24.4, 10.7, 2.6, 0.4, 1.7, 2.4),
        ("Jackie Young", "G", 32, 18.1, 4.8, 5.2, 2.1, 1.4, 0.3),
        ("Chelsea Gray", "G", 30, 15.0, 4.0, 6.4, 1.8, 1.2, 0.2),
        ("Kelsey Plum", "G", 31, 20.2, 2.7, 4.6, 2.8, 0.9, 0.1),
        ("Alysha Clark", "F", 25, 8.7, 4.9, 2.0, 1.5, 0.8, 0.4),
    ],
    "CON": [
        ("Alyssa Thomas", "F", 34, 15.7, 9.4, 8.1, 0.2, 1.7, 0.5),
        ("DeWanna Bonner", "F", 31, 17.0, 6.4, 2.5, 1.8, 1.1, 0.6),
        ("Brionna Jones", "C", 28, 13.6, 7.6, 1.8, 0.1, 0.8, 1.0),
        ("DiJonai Carrington", "G", 29, 12.2, 5.3, 2.7, 1.1, 1.5, 0.4),
        ("Marina Mabrey", "G", 30, 15.3, 4.1, 4.2, 2.5, 1.1, 0.2),
    ],
    "IND": [
        ("Caitlin Clark", "G", 34, 22.5, 5.9, 8.8, 3.3, 1.4, 0.6),
        ("Aliyah Boston", "C", 31, 15.1, 8.4, 3.2, 0.1, 0.8, 1.4),
        ("Kelsey Mitchell", "G", 32, 18.7, 2.5, 3.1, 2.6, 0.9, 0.1),
        ("NaLyssa Smith", "F", 27, 12.0, 7.1, 1.8, 0.4, 0.7, 0.6),
        ("Erica Wheeler", "G", 25, 8.8, 2.6, 4.4, 1.2, 1.0, 0.2),
    ],
}

MATCHUPS = [("NYL", "LVA"), ("CON", "IND")]


def stat_line(mean: float, noise: float, low: float = 0.0) -> float:
    return round(max(low, RNG.normal(mean, noise)), 1)


def build_mock_history() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    player_rows = []
    team_rows = []
    schedule_rows = []

    for game_idx in range(24):
        game_date = SEASON_START + pd.Timedelta(days=game_idx * 2)
        for away_team, home_team in MATCHUPS:
            schedule_rows.append(
                {
                    "game_date": TODAY_DATE.date().isoformat(),
                    "away_team": away_team,
                    "home_team": home_team,
                    "game_id": f"{TODAY_DATE:%Y%m%d}_{away_team}_{home_team}",
                    "start_time": "7:00 PM ET",
                }
            )
            team_totals = {}
            for team, opponent, home_away in [
                (away_team, home_team, "A"),
                (home_team, away_team, "H"),
            ]:
                totals = {
                    "points": 0.0,
                    "rebounds": 0.0,
                    "assists": 0.0,
                    "threes_made": 0.0,
                    "steals": 0.0,
                    "blocks": 0.0,
                }
                for player_name, position, base_minutes, pts, reb, ast, fg3m, stl, blk in TEAM_ROSTERS[team]:
                    minutes = stat_line(base_minutes, 2.2, 18)
                    points = stat_line(pts, 4.0)
                    rebounds = stat_line(reb, 2.0)
                    assists = stat_line(ast, 1.8)
                    threes_made = stat_line(fg3m, 1.0)
                    steals = stat_line(stl, 0.6)
                    blocks = stat_line(blk, 0.5)
                    player_rows.append(
                        {
                            "game_date": game_date.date().isoformat(),
                            "season": 2025,
                            "player_name": player_name,
                            "team": team,
                            "opponent": opponent,
                            "home_away": home_away,
                            "minutes": minutes,
                            "points": points,
                            "rebounds": rebounds,
                            "assists": assists,
                            "threes_made": threes_made,
                            "steals": steals,
                            "blocks": blocks,
                        }
                    )
                    totals["points"] += points
                    totals["rebounds"] += rebounds
                    totals["assists"] += assists
                    totals["threes_made"] += threes_made
                    totals["steals"] += steals
                    totals["blocks"] += blocks
                team_totals[team] = totals

            for team, opponent in [(away_team, home_team), (home_team, away_team)]:
                team_rows.append(
                    {
                        "game_date": game_date.date().isoformat(),
                        "team": team,
                        "opponent": opponent,
                        "pace": stat_line(79.5, 2.0, 72),
                        "off_rating": stat_line(104.0, 5.0, 90),
                        "def_rating": stat_line(101.0, 5.0, 88),
                        "team_points": round(team_totals[team]["points"], 1),
                        "opp_points": round(team_totals[opponent]["points"], 1),
                    }
                )

    positions_rows = []
    for team, roster in TEAM_ROSTERS.items():
        for player_name, position, *_ in roster:
            positions_rows.append({"player_name": player_name, "team": team, "position": position})

    return pd.DataFrame(player_rows), pd.DataFrame(team_rows), pd.DataFrame(schedule_rows), pd.DataFrame(positions_rows)


def build_mock_lines() -> pd.DataFrame:
    rows = []
    todays_games = {
        "NYL": "LVA",
        "LVA": "NYL",
        "CON": "IND",
        "IND": "CON",
    }
    for team, roster in TEAM_ROSTERS.items():
        opponent = todays_games[team]
        for player_name, _, _, pts, reb, ast, fg3m, stl, blk in roster:
            for stat, line in [
                ("points", round(pts - 0.5, 1)),
                ("rebounds", round(reb - 0.5, 1)),
                ("assists", round(ast - 0.5, 1)),
                ("threes_made", round(max(0.5, fg3m - 0.5), 1)),
                ("steals", round(max(0.5, stl), 1)),
                ("blocks", round(max(0.5, blk), 1)),
            ]:
                rows.append(
                    {
                        "player_name": player_name,
                        "team": team,
                        "opponent": opponent,
                        "stat": stat,
                        "line": line,
                        "over_odds": -115,
                        "under_odds": -115,
                        "sportsbook": "mockbook",
                    }
                )
    return pd.DataFrame(rows)


def main() -> None:
    logger = setup_logging("generate_mock_wnba_data")
    RAW_PLAYER_GAMES_PATH.parent.mkdir(parents=True, exist_ok=True)
    RAW_TEAM_CONTEXT_PATH.parent.mkdir(parents=True, exist_ok=True)

    player_games, team_context, schedule_today, positions = build_mock_history()
    sportsbook_lines = build_mock_lines()
    player_status = pd.DataFrame(columns=["player_name", "team", "status"])

    player_games.to_csv(RAW_PLAYER_GAMES_PATH, index=False)
    team_context.to_csv(RAW_TEAM_CONTEXT_PATH, index=False)
    schedule_today.to_csv(RAW_SCHEDULE_TODAY_PATH, index=False)
    positions.to_csv(RAW_PLAYER_POSITIONS_PATH, index=False)
    sportsbook_lines.to_csv(RAW_SPORTSBOOK_LINES_PATH, index=False)
    player_status.to_csv(RAW_PLAYER_STATUS_PATH, index=False)

    logger.info("Mock raw player games written: %s", len(player_games))
    logger.info("Mock raw team context written: %s", len(team_context))
    logger.info("Mock raw schedule written: %s", len(schedule_today))
    logger.info("Mock raw positions written: %s", len(positions))
    logger.info("Mock raw sportsbook lines written: %s", len(sportsbook_lines))


if __name__ == "__main__":
    main()
