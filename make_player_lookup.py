from nba_api.stats.static import players
import pandas as pd

all_players = players.get_players()

df = pd.DataFrame(all_players)
df = df.rename(columns={"id": "PLAYER_ID", "full_name": "PLAYER_NAME"})
df = df[["PLAYER_ID", "PLAYER_NAME"]].drop_duplicates()

df.to_csv("player_lookup.csv", index=False)
print("Saved player_lookup.csv with", len(df), "players")
