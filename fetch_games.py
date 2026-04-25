import pandas as pd
from nba_api.stats.endpoints import leaguegamelog

df = leaguegamelog.LeagueGameLog(
    season="2025-26",
    season_type_all_star="Regular Season",
    player_or_team_abbreviation="P"
).get_data_frames()[0]

df.to_csv("raw_games.csv", index=False)

print(f"Saved raw_games.csv with {len(df)} rows")
print(df[["PLAYER_ID", "TEAM_ID", "TEAM_ABBREVIATION", "GAME_DATE", "MATCHUP", "MIN", "PTS", "REB", "AST"]].head())
print("Min date:", df["GAME_DATE"].min())
print("Max date:", df["GAME_DATE"].max())
