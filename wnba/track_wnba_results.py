from __future__ import annotations

import pandas as pd

from wnba_model_config import BETTING_RECORD_PATH, BEST_BETS_DIR
from wnba_model_utils import setup_logging


RECORD_SUMMARY_PATH = BEST_BETS_DIR / "record_summary.csv"
CALIBRATION_SUMMARY_PATH = BEST_BETS_DIR / "calibration_summary.csv"


def write_empty_outputs() -> None:
    pd.DataFrame(columns=["date", "wins", "losses", "total", "win_pct"]).to_csv(RECORD_SUMMARY_PATH, index=False)
    pd.DataFrame(columns=["section", "bets", "wins", "losses", "win_pct"]).to_csv(CALIBRATION_SUMMARY_PATH, index=False)


def summarize_group(df: pd.DataFrame, group_cols: list[str], label: str) -> pd.DataFrame:
    grouped = (
        df.groupby(group_cols, dropna=False)
        .agg(
            bets=("bet_result", "size"),
            wins=("bet_result", lambda s: int((s == "win").sum())),
            losses=("bet_result", lambda s: int((s == "loss").sum())),
        )
        .reset_index()
    )
    grouped["win_pct"] = (grouped["wins"] / grouped["bets"]).round(3)
    grouped["section"] = label
    return grouped


def main() -> None:
    logger = setup_logging("track_wnba_results")
    if not BETTING_RECORD_PATH.exists():
        logger.warning("No WNBA bet history found at %s", BETTING_RECORD_PATH)
        write_empty_outputs()
        return

    history = pd.read_csv(BETTING_RECORD_PATH)
    if history.empty or "bet_result" not in history.columns:
        logger.info("No WNBA graded history rows available yet.")
        write_empty_outputs()
        return

    history["bet_result"] = history["bet_result"].astype(str).str.lower()
    graded = history[history["bet_result"].isin(["win", "loss"])].copy()
    if graded.empty:
        logger.info("No WNBA win/loss rows available yet.")
        write_empty_outputs()
        return

    date_col = "bet_date" if "bet_date" in graded.columns else "DATE"
    daily = graded.groupby(date_col)["bet_result"].value_counts().unstack(fill_value=0)
    daily["wins"] = daily.get("win", 0)
    daily["losses"] = daily.get("loss", 0)
    daily["total"] = daily["wins"] + daily["losses"]
    daily["win_pct"] = (daily["wins"] / daily["total"]).round(3)
    daily = daily.reset_index().rename(columns={date_col: "date"})
    daily.to_csv(RECORD_SUMMARY_PATH, index=False)

    frames = []
    if "stat" in graded.columns:
        frames.append(summarize_group(graded, ["stat"], "by_stat"))
    if "confidence" in graded.columns:
        frames.append(summarize_group(graded, ["confidence"], "by_confidence"))
    if "side" in graded.columns:
        frames.append(summarize_group(graded, ["side"], "by_side"))
    if "hit_rate" in graded.columns:
        hit_rate_df = graded.copy()
        hit_rate_df["hit_rate"] = pd.to_numeric(hit_rate_df["hit_rate"], errors="coerce")
        hit_rate_df = hit_rate_df.dropna(subset=["hit_rate"])
        if not hit_rate_df.empty:
            hit_rate_df["hit_rate_bucket"] = pd.cut(
                hit_rate_df["hit_rate"],
                bins=[0.0, 0.55, 0.60, 0.65, 0.70, 1.0],
                labels=["<=55%", "55-60%", "60-65%", "65-70%", "70%+"],
                include_lowest=True,
            )
            frames.append(summarize_group(hit_rate_df, ["hit_rate_bucket"], "by_hit_rate"))

    if frames:
        pd.concat(frames, ignore_index=True).to_csv(CALIBRATION_SUMMARY_PATH, index=False)

    logger.info("Saved WNBA record summary to %s", RECORD_SUMMARY_PATH)


if __name__ == "__main__":
    main()
