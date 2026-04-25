import pandas as pd

projections = pd.read_csv("projections.csv")
lines = pd.read_csv("lines_today.csv")

stat_map = {
    "PTS": "PRED_PTS",
    "REB": "PRED_REB",
    "AST": "PRED_AST",
    "STL": "PRED_STL",
    "BLK": "PRED_BLK",
    "FG3M": "PRED_FG3M",
    "PRA": "PRA",
    "PR": "PR",
    "PA": "PA",
    "RA": "RA"
}

rows = []

for _, proj in projections.iterrows():

    for stat in stat_map:

        column = stat_map[stat]

        rows.append({
            "PLAYER_NAME": proj["PLAYER_NAME"],
            "TEAM_ABBREVIATION": proj["TEAM_ABBREVIATION"],
            "STAT": stat,
            "PROJECTION": proj[column],
            "MODEL_CONFIDENCE": proj["CONFIDENCE"],
            "PRED_MIN": proj["PRED_MIN"]
        })

proj_df = pd.DataFrame(rows)

merged = pd.merge(
    lines,
    proj_df,
    on=["PLAYER_NAME", "STAT"],
    how="left"
)

merged["EDGE"] = merged["PROJECTION"] - merged["LINE"]

merged["ABS_EDGE"] = merged["EDGE"].abs()

def pick_side(edge):

    if pd.isna(edge):
        return "NO_DATA"

    if edge > 0:
        return "OVER"

    if edge < 0:
        return "UNDER"

    return "PASS"

merged["BET_SIDE"] = merged["EDGE"].apply(pick_side)


def bet_confidence(row):

    if pd.isna(row["EDGE"]):
        return "NO_DATA"

    if row["MODEL_CONFIDENCE"] == "LOW":
        return "LOW"

    if row["PRED_MIN"] < 24:
        return "LOW"

    if row["ABS_EDGE"] >= 3:
        return "HIGH"

    if row["ABS_EDGE"] >= 1.5:
        return "MEDIUM"

    return "LOW"

merged["BET_CONFIDENCE"] = merged.apply(bet_confidence, axis=1)

merged = merged.sort_values(
    ["BET_CONFIDENCE","ABS_EDGE"],
    ascending=[True,False]
)

merged.to_csv("edges_today.csv", index=False)

print("Saved edges_today.csv")
print(merged.head(25))