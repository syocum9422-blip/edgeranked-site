from __future__ import annotations

import pandas as pd

from wnba_model_config import (
    BEST_BETS_ARCHIVE_DIR_DATED,
    BEST_BETS_PATH,
    PROJECTIONS_ARCHIVE_DIR,
    PROJECTIONS_PATH,
)
from wnba_model_utils import archive_dataframe, setup_logging


def main() -> None:
    logger = setup_logging("archive_wnba_outputs")
    if PROJECTIONS_PATH.exists():
        projections = pd.read_csv(PROJECTIONS_PATH)
        archive_path = archive_dataframe(projections, PROJECTIONS_ARCHIVE_DIR, "wnba_projections")
        logger.info("Archived projections to %s", archive_path)
    if BEST_BETS_PATH.exists():
        best_bets = pd.read_csv(BEST_BETS_PATH)
        archive_path = archive_dataframe(best_bets, BEST_BETS_ARCHIVE_DIR_DATED, "wnba_best_bets")
        logger.info("Archived best bets to %s", archive_path)


if __name__ == "__main__":
    main()
