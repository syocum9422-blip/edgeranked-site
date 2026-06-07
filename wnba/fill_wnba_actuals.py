from __future__ import annotations

import numpy as np
import pandas as pd

from fetch_wnba_espn_actuals import fetch_recent_actuals
from wnba_model_config import BETTING_RECORD_PATH, CANONICAL_PLAYER_GAMES_PATH
from wnba_model_utils import canonicalize_name, setup_logging, standardize_team_abbrev


def stat_actual(row: pd.Series, stat: str) -> float:
    stat = str(stat or "").lower().strip()
    values = {
        "points": row.get("points"),
        "rebounds": row.get("rebounds"),
        "assists": row.get("assists"),
        "threes_made": row.get("threes_made"),
        "steals": row.get("steals"),
        "blocks": row.get("blocks"),
    }
    if stat in values:
        return pd.to_numeric(values[stat], errors="coerce")
    points = pd.to_numeric(row.get("points"), errors="coerce")
    rebounds = pd.to_numeric(row.get("rebounds"), errors="coerce")
    assists = pd.to_numeric(row.get("assists"), errors="coerce")
    steals = pd.to_numeric(row.get("steals"), errors="coerce")
    blocks = pd.to_numeric(row.get("blocks"), errors="coerce")
    if stat == "pra":
        return points + rebounds + assists
    if stat == "pr":
        return points + rebounds
    if stat == "pa":
        return points + assists
    if stat == "ra":
        return rebounds + assists
    if stat == "sb":
        return steals + blocks
    return np.nan


def main() -> None:
    logger = setup_logging("fill_wnba_actuals")
    if not BETTING_RECORD_PATH.exists():
        raise FileNotFoundError(f"Bet history not found: {BETTING_RECORD_PATH}")

    fetch_recent_actuals()
    bet_history = pd.read_csv(BETTING_RECORD_PATH)
    actuals = pd.read_csv(CANONICAL_PLAYER_GAMES_PATH, parse_dates=["game_date"])
    actuals["bet_date"] = actuals["game_date"].dt.date.astype(str)
    actuals["player_key"] = actuals["player_name"].map(canonicalize_name)
    actuals["team"] = actuals["team"].map(standardize_team_abbrev)
    actuals["opponent"] = actuals["opponent"].map(standardize_team_abbrev)

    bet_history["actual_value"] = bet_history.get("actual_value", np.nan)
    matched = 0
    for index, bet in bet_history[bet_history["actual_value"].isna()].iterrows():
        player_key = canonicalize_name(bet.get("player_name"))
        team = standardize_team_abbrev(bet.get("team"))
        opponent = standardize_team_abbrev(bet.get("opponent"))
        match = actuals[
            (actuals["bet_date"] == str(bet.get("bet_date")))
            & (actuals["player_key"] == player_key)
        ].copy()
        if len(match) > 1 and team:
            narrowed = match[match["team"] == team]
            if not narrowed.empty:
                match = narrowed
        if len(match) > 1 and opponent:
            narrowed = match[match["opponent"] == opponent]
            if not narrowed.empty:
                match = narrowed
        if not match.empty:
            value = stat_actual(match.iloc[-1], bet.get("stat"))
            if pd.notna(value):
                bet_history.at[index, "actual_value"] = value
                matched += 1

    bet_history.to_csv(BETTING_RECORD_PATH, index=False)
    logger.info("Updated actual values in %s; matched=%s", BETTING_RECORD_PATH, matched)


if __name__ == "__main__":
    main()
