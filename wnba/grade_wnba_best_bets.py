from __future__ import annotations

import numpy as np
import pandas as pd

from wnba_model_config import BETTING_RECORD_PATH, GRADED_BETS_PATH
from wnba_model_utils import setup_logging


def grade_bet(side: str, line: float, actual_value: float) -> str:
    if pd.isna(actual_value):
        return ""
    if actual_value == line:
        return "push"
    if side == "over":
        return "win" if actual_value > line else "loss"
    return "win" if actual_value < line else "loss"


def main() -> None:
    logger = setup_logging("grade_wnba_best_bets")
    if not BETTING_RECORD_PATH.exists():
        raise FileNotFoundError(f"Bet history not found: {BETTING_RECORD_PATH}")

    bet_history = pd.read_csv(BETTING_RECORD_PATH)
    bet_history["bet_result"] = [
        grade_bet(side, line, actual)
        for side, line, actual in zip(
            bet_history["side"],
            pd.to_numeric(bet_history["line"], errors="coerce"),
            pd.to_numeric(bet_history["actual_value"], errors="coerce"),
        )
    ]

    graded = bet_history[bet_history["bet_result"] != ""].copy()
    graded["won_flag"] = (graded["bet_result"] == "win").astype(int)
    graded["lost_flag"] = (graded["bet_result"] == "loss").astype(int)
    graded.to_csv(GRADED_BETS_PATH, index=False)
    bet_history.to_csv(BETTING_RECORD_PATH, index=False)
    logger.info("Saved graded bets to %s", GRADED_BETS_PATH)


if __name__ == "__main__":
    main()
