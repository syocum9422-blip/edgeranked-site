from __future__ import annotations

import os
import subprocess
import sys

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


def learning_audit_enabled() -> bool:
    return os.environ.get("WNBA_ENABLE_LEARNING_AUDIT", "").strip().lower() in {"1", "true", "yes", "on"}


def run_learning_audit(logger) -> None:
    if not learning_audit_enabled():
        return
    script_path = GRADED_BETS_PATH.parents[1] / "wnba_learning_audit.py"
    result = subprocess.run([sys.executable, str(script_path)], cwd=script_path.parent)
    if result.returncode != 0:
        raise RuntimeError(f"WNBA learning audit failed with exit code {result.returncode}")
    logger.info("WNBA learning audit completed via WNBA_ENABLE_LEARNING_AUDIT")


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
    run_learning_audit(logger)


if __name__ == "__main__":
    main()
