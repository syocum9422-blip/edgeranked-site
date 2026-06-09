import pandas as pd

df = pd.read_csv("raw_games.csv")

df["GAME_DATE"] = pd.to_datetime(df["GAME_DATE"], errors="coerce")
df = df.dropna(subset=["GAME_DATE", "PLAYER_ID", "MATCHUP"]).copy()
df = df[df["GAME_DATE"] >= "2023-10-01"].copy()

num_cols = ["PTS", "REB", "AST", "STL", "BLK", "FG3M", "MIN"]
for col in num_cols:
    df[col] = pd.to_numeric(df[col], errors="coerce")

df = df.dropna(subset=num_cols).copy()

df["PTS"] = df["PTS"].clip(lower=0, upper=60)
df["REB"] = df["REB"].clip(lower=0, upper=25)
df["AST"] = df["AST"].clip(lower=0, upper=18)
df["STL"] = df["STL"].clip(lower=0, upper=10)
df["BLK"] = df["BLK"].clip(lower=0, upper=10)
df["FG3M"] = df["FG3M"].clip(lower=0, upper=15)
df["MIN"] = df["MIN"].clip(lower=0, upper=60)

name_col = None
for candidate in ["PLAYER_NAME", "PLAYER", "NAME"]:
    if candidate in df.columns:
        name_col = candidate
        break

if name_col is None:
    df["PLAYER_NAME"] = df["PLAYER_ID"].astype(str)
else:
    df["PLAYER_NAME"] = df[name_col].astype(str)

df = df.sort_values(["PLAYER_ID", "GAME_DATE"]).copy()

stats = ["PTS", "REB", "AST", "STL", "BLK", "FG3M", "MIN"]

for stat in stats:
    df[f"{stat}_LAST3"] = (
        df.groupby("PLAYER_ID")[stat]
        .transform(lambda s: s.shift(1).rolling(3).mean())
    )
    df[f"{stat}_LAST5"] = (
        df.groupby("PLAYER_ID")[stat]
        .transform(lambda s: s.shift(1).rolling(5).mean())
    )
    df[f"{stat}_LAST10"] = (
        df.groupby("PLAYER_ID")[stat]
        .transform(lambda s: s.shift(1).rolling(10).mean())
    )

df["MIN_STD5"] = (
    df.groupby("PLAYER_ID")["MIN"]
    .transform(lambda s: s.shift(1).rolling(5).std())
)

df["PTS_STD5"] = (
    df.groupby("PLAYER_ID")["PTS"]
    .transform(lambda s: s.shift(1).rolling(5).std())
)

df["REB_STD5"] = (
    df.groupby("PLAYER_ID")["REB"]
    .transform(lambda s: s.shift(1).rolling(5).std())
)

df["AST_STD5"] = (
    df.groupby("PLAYER_ID")["AST"]
    .transform(lambda s: s.shift(1).rolling(5).std())
)

df["HOME"] = df["MATCHUP"].astype(str).apply(lambda x: 1 if "vs." in x else 0)

df["REST_DAYS"] = (
    df.groupby("PLAYER_ID")["GAME_DATE"]
    .diff()
    .dt.days
)

df["B2B"] = (df["REST_DAYS"] == 1).astype(int)
df["LOW_MIN_ROLE"] = (df["MIN_LAST5"] < 20).astype(int)
df["VOLATILE_MINUTES"] = (df["MIN_STD5"] > 6).astype(int)
df["PTS_TREND"] = df["PTS_LAST3"] - df["PTS_LAST10"]
df["MIN_TREND"] = df["MIN_LAST3"] - df["MIN_LAST10"]

df["OPP_TEAM_ABBREVIATION"] = df["MATCHUP"].astype(str).str.split().str[-1]

# Opponent defensive context:
# For each player-game row, aggregate the opposing team's player stats in that same GAME_ID.
# Then use only games before the current row's GAME_DATE to avoid future leakage.
team_game_allowed = (
    df.groupby(["GAME_ID", "OPP_TEAM_ABBREVIATION", "GAME_DATE"])[["PTS", "REB", "AST"]]
    .sum()
    .reset_index()
    .rename(
        columns={
            "OPP_TEAM_ABBREVIATION": "TEAM_ABBREVIATION",
            "PTS": "TEAM_PTS_ALLOWED_GAME",
            "REB": "TEAM_REB_ALLOWED_GAME",
            "AST": "TEAM_AST_ALLOWED_GAME",
        }
    )
    .sort_values(["TEAM_ABBREVIATION", "GAME_DATE"])
)

for src, out in [
    ("TEAM_PTS_ALLOWED_GAME", "OPP_PTS_ALLOWED"),
    ("TEAM_REB_ALLOWED_GAME", "OPP_REB_ALLOWED"),
    ("TEAM_AST_ALLOWED_GAME", "OPP_AST_ALLOWED"),
]:
    team_game_allowed[out] = (
        team_game_allowed.groupby("TEAM_ABBREVIATION")[src]
        .transform(lambda x: x.shift(1).expanding(min_periods=3).mean())
    )

league_defaults = {
    "OPP_PTS_ALLOWED": float(team_game_allowed["TEAM_PTS_ALLOWED_GAME"].mean()),
    "OPP_REB_ALLOWED": float(team_game_allowed["TEAM_REB_ALLOWED_GAME"].mean()),
    "OPP_AST_ALLOWED": float(team_game_allowed["TEAM_AST_ALLOWED_GAME"].mean()),
}

team_defense = team_game_allowed[
    ["GAME_ID", "TEAM_ABBREVIATION", "OPP_PTS_ALLOWED", "OPP_REB_ALLOWED", "OPP_AST_ALLOWED"]
].rename(columns={"TEAM_ABBREVIATION": "OPP_TEAM_ABBREVIATION"})

df = df.merge(team_defense, on=["GAME_ID", "OPP_TEAM_ABBREVIATION"], how="left")

for col, default in league_defaults.items():
    df[col] = df[col].fillna(default)

keep_cols = [
    "PLAYER_ID", "PLAYER_NAME", "TEAM_ID", "TEAM_ABBREVIATION", "GAME_ID",
    "GAME_DATE", "MATCHUP", "OPP_TEAM_ABBREVIATION", "HOME", "REST_DAYS",
    "B2B", "LOW_MIN_ROLE", "VOLATILE_MINUTES",
    "PTS", "REB", "AST", "STL", "BLK", "FG3M", "MIN",
    "PTS_LAST3", "PTS_LAST5", "PTS_LAST10",
    "REB_LAST3", "REB_LAST5", "REB_LAST10",
    "AST_LAST3", "AST_LAST5", "AST_LAST10",
    "STL_LAST3", "STL_LAST5", "STL_LAST10",
    "BLK_LAST3", "BLK_LAST5", "BLK_LAST10",
    "FG3M_LAST3", "FG3M_LAST5", "FG3M_LAST10",
    "MIN_LAST3", "MIN_LAST5", "MIN_LAST10",
    "MIN_STD5", "PTS_STD5", "REB_STD5", "AST_STD5",
    "PTS_TREND", "MIN_TREND",
    "OPP_PTS_ALLOWED", "OPP_REB_ALLOWED", "OPP_AST_ALLOWED"
]

model_df = df[keep_cols].dropna().copy()
model_df.to_csv("model_dataset.csv", index=False)

print("Saved model_dataset.csv with", len(model_df), "rows")
