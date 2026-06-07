from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from wnba_model_config import BETTING_RECORD_PATH, BEST_BETS_DIR, PROCESSED_DIR
from wnba_model_utils import setup_logging


CALIBRATION_REPORT_PATH = PROCESSED_DIR / "wnba_calibration_report.csv"
BEST_BETS_CALIBRATION_REPORT_PATH = BEST_BETS_DIR / "calibration_report.txt"
BEST_BETS_CALIBRATION_SUMMARY_PATH = BEST_BETS_DIR / "calibration_summary.csv"
CALIBRATION_FACTORS_PATH = BEST_BETS_DIR / "calibration_factors.json"
LEARNING_DIR = BEST_BETS_DIR.parent / "learning"
CONFIDENCE_CALIBRATION_SUMMARY_PATH = LEARNING_DIR / "confidence_calibration_summary.csv"


def created_at_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def bucket_probabilities(series: pd.Series) -> pd.Series:
    bins = [0.0, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 1.01]
    labels = ["50-55%", "55-60%", "60-65%", "65-70%", "70-75%", "75-80%", "80-100%", "80-100%+"]
    bucket = pd.cut(series.clip(lower=0, upper=1), bins=bins, labels=labels[: len(bins) - 1], right=False)
    return bucket.astype(str)


def smoothed_rate(wins: int, losses: int, alpha: int = 4, beta: int = 4) -> float:
    return (wins + alpha) / (wins + losses + alpha + beta)


def build_factors(graded: pd.DataFrame) -> dict:
    timestamp = created_at_utc()
    wins_total = int((graded["bet_result"] == "win").sum())
    losses_total = int((graded["bet_result"] == "loss").sum())
    factors = {
        "metadata": {
            "graded_bets": int(len(graded)),
            "wins": wins_total,
            "losses": losses_total,
            "overall_win_rate": round(smoothed_rate(wins_total, losses_total, 5, 5), 4) if len(graded) else None,
            "created_at_utc": timestamp,
        },
        "global": {},
        "side": {},
        "stat_side": {},
        "stat_side_confidence_bucket": {},
        "confidence_label": {},
        "hit_rate_bucket": {},
    }
    factors["global"]["ALL"] = {
        "wins": wins_total,
        "losses": losses_total,
        "bets": wins_total + losses_total,
        "win_rate": round(smoothed_rate(wins_total, losses_total, 5, 5), 4) if len(graded) else None,
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
    if "confidence_label" not in graded.columns:
        if "CONFIDENCE_LABEL" in graded.columns:
            graded["confidence_label"] = graded["CONFIDENCE_LABEL"]
        elif "confidence" in graded.columns:
            graded["confidence_label"] = graded["confidence"].astype(str).str.title()

    if {"confidence_label", "prob_bucket"}.issubset(graded.columns):
        grouped = graded.dropna(subset=["confidence_label", "prob_bucket"])
        for (stat, side, label, bucket), group in grouped.groupby(["stat", "side", "confidence_label", "prob_bucket"]):
            wins = int((group["bet_result"] == "win").sum())
            losses = int((group["bet_result"] == "loss").sum())
            factors["stat_side_confidence_bucket"][
                f"{str(stat).upper()}::{str(side).upper()}::{str(label).title()}::{str(bucket)}"
            ] = {
                "wins": wins,
                "losses": losses,
                "bets": wins + losses,
                "win_rate": round(smoothed_rate(wins, losses, 3, 3), 4),
            }
    return factors


def build_confidence_calibration_summary(bets: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "confidence_label",
        "stat",
        "side",
        "total_bets",
        "wins",
        "losses",
        "pushes",
        "win_rate",
        "avg_predicted_hit_rate",
        "calibration_gap",
        "created_at_utc",
    ]
    if bets.empty:
        return pd.DataFrame(columns=columns)

    summary_frame = bets[bets["bet_result"].isin(["win", "loss", "push"])].copy()
    if summary_frame.empty:
        return pd.DataFrame(columns=columns)

    if "CONFIDENCE_LABEL" in summary_frame.columns:
        confidence_series = summary_frame["CONFIDENCE_LABEL"]
    elif "confidence" in summary_frame.columns:
        confidence_series = summary_frame["confidence"]
    else:
        confidence_series = pd.Series(["Unknown"] * len(summary_frame), index=summary_frame.index)
    summary_frame["confidence_label"] = confidence_series.fillna("Unknown").astype(str).str.title()
    summary_frame["hit_rate"] = pd.to_numeric(summary_frame.get("hit_rate"), errors="coerce")

    rows = []
    timestamp = created_at_utc()
    for (confidence_label, stat, side), group in summary_frame.groupby(["confidence_label", "stat", "side"], dropna=False):
        wins = int((group["bet_result"] == "win").sum())
        losses = int((group["bet_result"] == "loss").sum())
        pushes = int((group["bet_result"] == "push").sum())
        decisions = wins + losses
        avg_predicted_hit_rate = pd.to_numeric(group["hit_rate"], errors="coerce").mean()
        win_rate = (wins / decisions) if decisions else np.nan
        rows.append(
            {
                "confidence_label": str(confidence_label),
                "stat": str(stat),
                "side": str(side),
                "total_bets": int(len(group)),
                "wins": wins,
                "losses": losses,
                "pushes": pushes,
                "win_rate": win_rate,
                "avg_predicted_hit_rate": avg_predicted_hit_rate,
                "calibration_gap": win_rate - avg_predicted_hit_rate if pd.notna(win_rate) and pd.notna(avg_predicted_hit_rate) else np.nan,
                "created_at_utc": timestamp,
            }
        )
    return pd.DataFrame(rows, columns=columns).sort_values(
        ["confidence_label", "stat", "side"],
        kind="stable",
    ).reset_index(drop=True)


def main() -> None:
    logger = setup_logging("calibrate_wnba_model")
    LEARNING_DIR.mkdir(parents=True, exist_ok=True)
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
        build_confidence_calibration_summary(bets).to_csv(CONFIDENCE_CALIBRATION_SUMMARY_PATH, index=False)
        with open(CALIBRATION_FACTORS_PATH, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "metadata": {"graded_bets": 0, "created_at_utc": created_at_utc()},
                    "global": {},
                    "side": {},
                    "stat_side": {},
                    "stat_side_confidence_bucket": {},
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
    build_confidence_calibration_summary(bets).to_csv(CONFIDENCE_CALIBRATION_SUMMARY_PATH, index=False)

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
