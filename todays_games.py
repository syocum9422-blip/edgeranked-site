import pandas as pd
from nba_api.stats.endpoints import scoreboardv2

games = scoreboardv2.ScoreboardV2().get_data_frames()[0]

teams_today = set(games["HOME_TEAM_ID"]).union(set(games["VISITOR_TEAM_ID"]))

pd.Series(list(teams_today)).to_csv("teams_today.csv", index=False)

print("Teams playing today:")
print(teams_today)