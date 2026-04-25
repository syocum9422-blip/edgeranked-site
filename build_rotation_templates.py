import pandas as pd

from nba_model.settings import LINEUP_STINTS_PATH, ROTATION_TEMPLATES_PATH


def main():
    stints = pd.read_csv(LINEUP_STINTS_PATH)
    if stints.empty:
        raise ValueError("lineup_stints.csv is empty")

    rows = []
    for _, row in stints.iterrows():
        lineup_ids = str(row.get("LINEUP_PLAYER_IDS", "")).strip()
        if not lineup_ids:
            continue
        player_ids = [pid for pid in lineup_ids.split("|") if pid]
        if not player_ids:
            continue
        seconds_played = float(row.get("SECONDS_PLAYED", 0) or 0)
        if seconds_played <= 0:
            continue
        for player_id in player_ids:
            rows.append(
                {
                    "GAME_ID": row["GAME_ID"],
                    "TEAM_ID": row["TEAM_ID"],
                    "TEAM_ABBREVIATION": row["TEAM_ABBREVIATION"],
                    "PERIOD": row["PERIOD"],
                    "PLAYER_ID": str(player_id),
                    "SECONDS_PLAYED": seconds_played,
                }
            )

    player_seconds = pd.DataFrame(rows)
    if player_seconds.empty:
        raise ValueError("No player-level rotation rows were created from lineup stints")

    player_periods = (
        player_seconds.groupby(
            ["GAME_ID", "TEAM_ID", "TEAM_ABBREVIATION", "PLAYER_ID", "PERIOD"],
            as_index=False,
        )["SECONDS_PLAYED"]
        .sum()
    )

    summary = (
        player_periods.groupby(["TEAM_ABBREVIATION", "PLAYER_ID", "PERIOD"], as_index=False)["SECONDS_PLAYED"]
        .mean()
    )
    summary["MINUTES_ALLOCATED"] = summary["SECONDS_PLAYED"] / 60.0

    overall = (
        player_seconds.groupby(["GAME_ID", "TEAM_ABBREVIATION", "PLAYER_ID"], as_index=False)["SECONDS_PLAYED"]
        .sum()
        .groupby(["TEAM_ABBREVIATION", "PLAYER_ID"], as_index=False)["SECONDS_PLAYED"]
        .mean()
    )
    games_played = (
        player_seconds.groupby(["TEAM_ABBREVIATION", "PLAYER_ID"], as_index=False)["GAME_ID"]
        .nunique()
        .rename(columns={"GAME_ID": "GAMES_IN_SAMPLE"})
    )
    overall = overall.merge(games_played, on=["TEAM_ABBREVIATION", "PLAYER_ID"], how="left")
    overall["AVG_MINUTES_TOTAL"] = overall["SECONDS_PLAYED"] / 60.0

    pivot = (
        summary.pivot_table(
            index=["TEAM_ABBREVIATION", "PLAYER_ID"],
            columns="PERIOD",
            values="MINUTES_ALLOCATED",
            aggfunc="mean",
            fill_value=0.0,
        )
        .reset_index()
    )
    pivot.columns = [
        "TEAM_ABBREVIATION" if col == "TEAM_ABBREVIATION" else
        "PLAYER_ID" if col == "PLAYER_ID" else
        f"Q{int(col)}_MINUTES"
        for col in pivot.columns
    ]

    output = overall.merge(pivot, on=["TEAM_ABBREVIATION", "PLAYER_ID"], how="left")
    for col in ["Q1_MINUTES", "Q2_MINUTES", "Q3_MINUTES", "Q4_MINUTES"]:
        if col not in output.columns:
            output[col] = 0.0
    quarter_total = output[["Q1_MINUTES", "Q2_MINUTES", "Q3_MINUTES", "Q4_MINUTES"]].sum(axis=1).clip(lower=1e-6)
    output["Q1_SHARE"] = output["Q1_MINUTES"] / quarter_total
    output["Q2_SHARE"] = output["Q2_MINUTES"] / quarter_total
    output["Q3_SHARE"] = output["Q3_MINUTES"] / quarter_total
    output["Q4_SHARE"] = output["Q4_MINUTES"] / quarter_total
    output = output.sort_values(["TEAM_ABBREVIATION", "AVG_MINUTES_TOTAL"], ascending=[True, False]).reset_index(drop=True)
    output.to_csv(ROTATION_TEMPLATES_PATH, index=False)
    print(f"Saved rotation templates: {ROTATION_TEMPLATES_PATH}")
    print(f"Rows saved: {len(output)}")


if __name__ == "__main__":
    main()
