from __future__ import annotations

import json
import numpy as np
import pandas as pd

from wnba_model_config import BETTING_RECORD_PATH, BEST_BETS_DIR, PROCESSED_DIR
from wnba_model_utils import setup_logging


CALIBRATION_REPORT_PATH = PROCESSED_DIR / "wnba_calibration_report.csv"
BEST_BETS_CALIBRATION_REPORT_PATH = BEST_BETS_DIR / "calibration_report.txt"
BEST_BETS_CALIBRATION_SUMMARY_PATH = BEST_BETS_DIR / "calibration_summary.csv"
CALIBRATION_FACTORS_PATH = BEST_BETS_DIR / "calibration_factors.json"


def bucket_probabilities(series: pd.Series) -> pd.Series:
    bins = [0.0, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 1.01]
    labels = ["50-55%", "55-60%", "60-65%", "65-70%", "70-75%", "75-80%", "80-100%", "80-100%+"]
    bucket = pd.cut(series.clip(lower=0, upper=1), bins=bins, labels=labels[: len(bins) - 1], right=False)
    return bucket.astype(str)


def smoothed_rate(wins: int, losses: int, alpha: int = 4, beta: int = 4) -> float:
    return (wins + alpha) / (wins + losses + alpha + beta)


def build_factors(graded: pd.DataFrame) -> dict:
    factors = {
        "metadata": {"graded_bets": int(len(graded))},
        "side": {},
        "stat_side": {},
        "confidence_label": {},
        "hit_rate_bucket": {},
    }
    for side, group in graded.groupby("side"):
        wins = int((group["bet_result"] == "win").sum())
        losses = int((group["bet_result"] == "loss").sum())
        factors["side"][str(side).upper()] = {
            "wins": wins,
            "losses": losses,
            "bets": wins + losses,
            "win_rate": round(smoothed_rate(wins, losses, 5, 5), 4),
        }
    for (stat, side), group in graded.groupby(["stat", "side"]):
        wins = int((group["bet_result"] == "win").sum())
        losses = int((group["bet_result"] == "loss").sum())
        factors["stat_side"][f"{str(stat).upper()}::{str(side).upper()}"] = {
            "wins": wins,
            "losses": losses,
            "bets": wins + losses,
            "win_rate": round(smoothed_rate(wins, losses, 3, 3), 4),
        }
    if "confidence" in graded.columns:
        for label, group in graded.groupby("confidence"):
            wins = int((group["bet_result"] == "win").sum())
            losses = int((group["bet_result"] == "loss").sum())
            factors["confidence_label"][str(label).title()] = {
                "wins": wins,
                "losses": losses,
                "bets": wins + losses,
                "win_rate": round(smoothed_rate(wins, losses, 4, 4), 4),
            }
    if "prob_bucket" in graded.columns:
        for bucket, group in graded.groupby("prob_bucket"):
            wins = int((group["bet_result"] == "win").sum())
            losses = int((group["bet_result"] == "loss").sum())
            factors["hit_rate_bucket"][str(bucket)] = {
                "wins": wins,
                "losses": losses,
                "bets": wins + losses,
                "win_rate": round(smoothed_rate(wins, losses, 4, 4), 4),
            }
    return factors


def main() -> None:
    logger = setup_logging("calibrate_wnba_model")
    if not BETTING_RECORD_PATH.exists():
        raise FileNotFoundError(f"Bet history not found: {BETTING_RECORD_PATH}")

    bets = pd.read_csv(BETTING_RECORD_PATH)
    graded = bets[bets["bet_result"].isin(["win", "loss"])].copy()
    if graded.empty:
        empty_report = pd.DataFrame(
            columns=[
                "stat",
                "prob_bucket",
                "bets",
                "avg_hit_rate",
                "actual_win_rate",
                "avg_edge",
                "avg_minutes",
                "calibration_gap",
            ]
        )
        empty_report.to_csv(CALIBRATION_REPORT_PATH, index=False)
        empty_report.to_csv(BEST_BETS_CALIBRATION_SUMMARY_PATH, index=False)
        with open(CALIBRATION_FACTORS_PATH, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "metadata": {"graded_bets": 0},
                    "side": {},
                    "stat_side": {},
                    "confidence_label": {},
                    "hit_rate_bucket": {},
                },
                handle,
                indent=2,
                sort_keys=True,
            )
        with open(BEST_BETS_CALIBRATION_REPORT_PATH, "w", encoding="utf-8") as handle:
            handle.write("WNBA Model Calibration Report\nNo graded bets available yet.\n")
        logger.info("No graded bets available yet. Wrote empty WNBA calibration artifacts.")
        return

    graded["won_flag"] = (graded["bet_result"] == "win").astype(int)
    graded["prob_bucket"] = bucket_probabilities(pd.to_numeric(graded["hit_rate"], errors="coerce"))
    report = (
        graded.groupby(["stat", "prob_bucket"], as_index=False)
        .agg(
            bets=("won_flag", "size"),
            avg_hit_rate=("hit_rate", "mean"),
            actual_win_rate=("won_flag", "mean"),
            avg_edge=("edge", "mean"),
            avg_minutes=("projected_minutes", "mean"),
        )
        .sort_values(["stat", "prob_bucket"])
    )
    report["calibration_gap"] = report["actual_win_rate"] - report["avg_hit_rate"]
    report.to_csv(CALIBRATION_REPORT_PATH, index=False)
    report.to_csv(BEST_BETS_CALIBRATION_SUMMARY_PATH, index=False)

    factors = build_factors(graded)
    with open(CALIBRATION_FACTORS_PATH, "w", encoding="utf-8") as handle:
        json.dump(factors, handle, indent=2, sort_keys=True)

    total_bets = len(graded)
    wins = int((graded["bet_result"] == "win").sum())
    losses = int((graded["bet_result"] == "loss").sum())
    win_rate = wins / total_bets if total_bets else 0.0
    lines = [
        "WNBA Model Calibration Report",
        f"Total graded bets: {total_bets}",
        f"Overall record: {wins}-{losses}",
        f"Overall win rate: {win_rate:.3f}",
        "",
        "By stat and probability bucket:",
        report.to_string(index=False),
    ]
    with open(BEST_BETS_CALIBRATION_REPORT_PATH, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")

    logger.info("Saved calibration report to %s with %s grouped rows", CALIBRATION_REPORT_PATH, len(report))


if __name__ == "__main__":
    main()
