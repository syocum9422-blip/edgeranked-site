import os
import pandas as pd
from nba_api.stats.endpoints import leaguegamelog

# NBA production source of truth: /home/ubuntu/EdgeRanked/site
BASE_DIR = os.environ.get("EDGERANKED_NBA_BASE_DIR", os.path.dirname(os.path.abspath(__file__)))

def get_logs(season, season_type):
    """Fetch game logs for a specific season and season type.
    
    Args:
        season: NBA season string (e.g., "2024-25")
        season_type: One of "Regular Season", "Playoffs", "PlayIn"
    
    Returns:
        DataFrame with game logs and SEASON_TYPE column
    """
    try:
        df = leaguegamelog.LeagueGameLog(
            season=season,
            season_type_all_star=season_type,
            player_or_team_abbreviation="P"
        ).get_data_frames()[0]
        df["SEASON_TYPE"] = season_type
        # Ensure GAME_ID is stored as string to preserve leading zeros
        df["GAME_ID"] = df["GAME_ID"].astype(str)
        return df
    except Exception as e:
        print(f"Could not fetch {season} {season_type}: {e}")
        return pd.DataFrame()

# Fetch current season (2025-26) Regular Season, Playoffs, and PlayIn
df_reg = get_logs("2025-26", "Regular Season")
df_playoff = get_logs("2025-26", "Playoffs")
df_playin = get_logs("2025-26", "PlayIn")

# Combine all dataframes
dfs = [d for d in [df_reg, df_playoff, df_playin] if not d.empty]
df = pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()

# NBA production source of truth: /home/ubuntu/EdgeRanked/site
df.to_csv(os.path.join(BASE_DIR, "raw_games.csv"), index=False)

print(f"Saved raw_games.csv with {len(df)} rows")
print(f"  - Regular Season rows: {len(df[df['SEASON_TYPE'] == 'Regular Season'])}")
print(f"  - Playoffs rows: {len(df[df['SEASON_TYPE'] == 'Playoffs'])}")
print(f"  - PlayIn rows: {len(df[df['SEASON_TYPE'] == 'PlayIn'])}")
print()
print(df[["PLAYER_ID", "TEAM_ID", "TEAM_ABBREVIATION", "GAME_DATE", "GAME_ID", "MATCHUP", "MIN", "PTS", "REB", "AST", "SEASON_TYPE"]].head(10))
print()
print("Min date:", df["GAME_DATE"].min() if not df.empty else "N/A")
print("Max date:", df["GAME_DATE"].max() if not df.empty else "N/A")
print()
# Verify playoff data was fetched
playoff_sample = df[df["SEASON_TYPE"] == "Playoffs"]
if not playoff_sample.empty:
    print("Sample playoff GAME_IDs (should start with 004):")
    print(playoff_sample["GAME_ID"].head().tolist())
else:
    print("WARNING: No playoff rows found in raw_games.csv!")
