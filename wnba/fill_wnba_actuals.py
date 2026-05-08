from __future__ import annotations

import numpy as np
import pandas as pd

from wnba_model_config import BETTING_RECORD_PATH, CANONICAL_PLAYER_GAMES_PATH
from wnba_model_utils import setup_logging


def main() -> None:
    logger = setup_logging("fill_wnba_actuals")
    if not BETTING_RECORD_PATH.exists():
        raise FileNotFoundError(f"Bet history not found: {BETTING_RECORD_PATH}")

    bet_history = pd.read_csv(BETTING_RECORD_PATH)
    actuals = pd.read_csv(CANONICAL_PLAYER_GAMES_PATH, parse_dates=["game_date"])
    actuals["bet_date"] = actuals["game_date"].dt.date.astype(str)

    stat_map = {
        "points": "points",
        "rebounds": "rebounds",
        "assists": "assists",
        "threes_made": "threes_made",
        "steals": "steals",
        "blocks": "blocks",
    }

    bet_history["actual_value"] = bet_history.get("actual_value", np.nan)
    for index, bet in bet_history[bet_history["actual_value"].isna()].iterrows():
        stat_column = stat_map.get(bet["stat"])
        if not stat_column:
            continue
        match = actuals[
            (actuals["bet_date"] == bet["bet_date"])
            & (actuals["player_name"].str.lower() == str(bet["player_name"]).lower())
        ]
        if not match.empty:
            bet_history.at[index, "actual_value"] = match.iloc[-1][stat_column]

    bet_history.to_csv(BETTING_RECORD_PATH, index=False)
    logger.info("Updated actual values in %s", BETTING_RECORD_PATH)


if __name__ == "__main__":
    main()
