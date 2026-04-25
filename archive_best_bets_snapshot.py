import os
import shutil

import pandas as pd

from nba_model.settings import BEST_BETS_ARCHIVE_DIR, BEST_BETS_OUTPUT_PATH


def main():
    if not os.path.exists(BEST_BETS_OUTPUT_PATH):
        print(f"No current best bets file to archive: {BEST_BETS_OUTPUT_PATH}")
        return

    df = pd.read_csv(BEST_BETS_OUTPUT_PATH)
    if df.empty or "DATE" not in df.columns:
        print("Best bets file missing DATE column or empty. Skipping archive.")
        return

    bet_date = str(df["DATE"].dropna().astype(str).iloc[0])[:10]
    if not bet_date:
        print("Could not determine bet date. Skipping archive.")
        return

    os.makedirs(BEST_BETS_ARCHIVE_DIR, exist_ok=True)
    archive_path = os.path.join(BEST_BETS_ARCHIVE_DIR, f"nba_best_bets_{bet_date}.csv")

    if os.path.exists(archive_path):
        print(f"Archive already exists: {archive_path}")
        return

    shutil.copy2(BEST_BETS_OUTPUT_PATH, archive_path)
    print(f"Archived prior best bets file to: {archive_path}")


if __name__ == "__main__":
    main()
