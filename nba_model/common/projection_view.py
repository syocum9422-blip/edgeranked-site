import pandas as pd


NON_PLAYING_STATUSES = {
    "OUT",
    "DOUBTFUL",
    "INACTIVE",
    "SUSPENDED",
    "NOT WITH TEAM",
    "OFS",
}


def filter_displayable_projections(df):
    if df is None or df.empty:
        return df

    work = df.copy()

    if "INJURY_STATUS" in work.columns:
        statuses = work["INJURY_STATUS"].fillna("").astype(str).str.strip().str.upper()
        work = work[~statuses.isin(NON_PLAYING_STATUSES)]

    if "ACTIVE_PROB" in work.columns:
        active_prob = pd.to_numeric(work["ACTIVE_PROB"], errors="coerce")
        work = work[active_prob.isna() | (active_prob > 0)]

    return work.reset_index(drop=True)


def build_projection_app_view(df):
    if df is None or df.empty:
        return pd.DataFrame(
            columns=[
                "PLAYER",
                "TEAM",
                "MATCHUP",
                "CONFIDENCE",
                "MIN",
                "PTS",
                "REB",
                "AST",
                "STL",
                "BLK",
                "3PM",
                "TOV",
                "PRA",
                "PR",
                "PA",
                "RA",
                "SB",
                "FANTASY",
            ]
        )

    df = filter_displayable_projections(df)
    if df.empty:
        return pd.DataFrame(
            columns=[
                "PLAYER",
                "TEAM",
                "MATCHUP",
                "CONFIDENCE",
                "MIN",
                "PTS",
                "REB",
                "AST",
                "STL",
                "BLK",
                "3PM",
                "TOV",
                "PRA",
                "PR",
                "PA",
                "RA",
                "SB",
                "FANTASY",
            ]
        )

    for col in ["PLAYER_NAME", "TEAM_ABBREVIATION", "MATCHUP", "CONFIDENCE_LABEL"]:
        if col not in df.columns:
            df[col] = None

    confidence = (
        df["CONFIDENCE_LABEL"]
        .fillna(df.get("MODEL_CONFIDENCE"))
        .fillna(df.get("BET_CONFIDENCE"))
        .astype(str)
        .str.strip()
        .replace({"": "Medium"})
        .str.title()
    )

    view = pd.DataFrame({
        "PLAYER": df["PLAYER_NAME"],
        "TEAM": df["TEAM_ABBREVIATION"],
        "MATCHUP": df["MATCHUP"],
        "CONFIDENCE": confidence,
        "MIN": pd.to_numeric(df.get("MIN_PROJ"), errors="coerce").round(1),
        "PTS": pd.to_numeric(df.get("PTS_PROJ"), errors="coerce").round(1),
        "REB": pd.to_numeric(df.get("REB_PROJ"), errors="coerce").round(1),
        "AST": pd.to_numeric(df.get("AST_PROJ"), errors="coerce").round(1),
        "STL": pd.to_numeric(df.get("STL_PROJ"), errors="coerce").round(1),
        "BLK": pd.to_numeric(df.get("BLK_PROJ"), errors="coerce").round(1),
        "3PM": pd.to_numeric(df.get("FG3M_PROJ"), errors="coerce").round(1),
        "TOV": pd.to_numeric(df.get("TOV_PROJ"), errors="coerce").round(1),
        "PRA": pd.to_numeric(df.get("PRA_PROJ"), errors="coerce").round(1),
        "PR": pd.to_numeric(df.get("PR_PROJ"), errors="coerce").round(1),
        "PA": pd.to_numeric(df.get("PA_PROJ"), errors="coerce").round(1),
        "RA": pd.to_numeric(df.get("RA_PROJ"), errors="coerce").round(1),
        "SB": pd.to_numeric(df.get("SB_PROJ"), errors="coerce").round(1),
        "FANTASY": pd.to_numeric(df.get("FANTASY_PROJ"), errors="coerce").round(1),
    })

    return view.sort_values(["FANTASY", "PTS", "PRA", "PLAYER"], ascending=[False, False, False, True], kind="stable").reset_index(drop=True)
