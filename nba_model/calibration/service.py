import os
import json
import pandas as pd

from nba_model.settings import (
    CALIBRATION_FACTORS_PATH,
    CALIBRATION_REPORT_PATH,
    HISTORY_PATH,
)


def bucket_hit_rate(value):
    if pd.isna(value):
        return "unknown"
    if value <= 0.55:
        return "<=55%"
    if value <= 0.60:
        return "55-60%"
    if value <= 0.65:
        return "60-65%"
    if value <= 0.70:
        return "65-70%"
    return "70%+"


def summarize(df, group_col):
    grouped = (
        df.groupby(group_col, dropna=False)
        .agg(
            bets=("result", "size"),
            wins=("result", lambda s: int((s == "WIN").sum())),
            losses=("result", lambda s: int((s == "LOSS").sum())),
        )
        .reset_index()
    )
    grouped["win_pct"] = (grouped["wins"] / grouped["bets"]).round(3)
    return grouped.sort_values("bets", ascending=False)


def smoothed_rate(wins, losses, alpha=5, beta=5):
    return (wins + alpha) / (wins + losses + alpha + beta)


def build_factors(df):
    factors = {
        "metadata": {"graded_bets": int(len(df))},
        "side": {},
        "stat_side": {},
        "confidence_label": {},
        "hit_rate_bucket": {},
    }

    if "prediction" in df.columns:
        for side, group in df.groupby("prediction"):
            if pd.isna(side) or side == "":
                continue
            wins = int((group["result"] == "WIN").sum())
            losses = int((group["result"] == "LOSS").sum())
            factors["side"][str(side).upper()] = {
                "wins": wins,
                "losses": losses,
                "bets": wins + losses,
                "win_rate": round(smoothed_rate(wins, losses, 5, 5), 4),
            }

    if {"stat", "prediction"}.issubset(df.columns):
        for (stat, side), group in df.groupby(["stat", "prediction"]):
            if pd.isna(stat) or pd.isna(side) or side == "":
                continue
            wins = int((group["result"] == "WIN").sum())
            losses = int((group["result"] == "LOSS").sum())
            factors["stat_side"][f"{str(stat).upper()}::{str(side).upper()}"] = {
                "wins": wins,
                "losses": losses,
                "bets": wins + losses,
                "win_rate": round(smoothed_rate(wins, losses, 3, 3), 4),
            }

    if "confidence_label" in df.columns:
        for label, group in df.groupby("confidence_label"):
            if pd.isna(label) or label == "":
                continue
            wins = int((group["result"] == "WIN").sum())
            losses = int((group["result"] == "LOSS").sum())
            factors["confidence_label"][str(label).title()] = {
                "wins": wins,
                "losses": losses,
                "bets": wins + losses,
                "win_rate": round(smoothed_rate(wins, losses, 4, 4), 4),
            }

    if "hit_rate_bucket" in df.columns:
        for bucket, group in df.groupby("hit_rate_bucket"):
            if pd.isna(bucket) or bucket == "":
                continue
            wins = int((group["result"] == "WIN").sum())
            losses = int((group["result"] == "LOSS").sum())
            factors["hit_rate_bucket"][str(bucket)] = {
                "wins": wins,
                "losses": losses,
                "bets": wins + losses,
                "win_rate": round(smoothed_rate(wins, losses, 4, 4), 4),
            }

    return factors


def main():
    if not os.path.exists(HISTORY_PATH):
        raise FileNotFoundError(HISTORY_PATH)

    df = pd.read_csv(HISTORY_PATH)
    df.columns = [str(c).strip().lower() for c in df.columns]
    df = df[df["result"].isin(["WIN", "LOSS"])].copy()

    if df.empty:
        report = "No graded bets available yet."
        with open(CALIBRATION_REPORT_PATH, "w", encoding="utf-8") as handle:
            handle.write(report + "\n")
        print(report)
        return

    if "hit_rate" in df.columns:
        df["hit_rate"] = pd.to_numeric(df["hit_rate"], errors="coerce")
        df["hit_rate_bucket"] = df["hit_rate"].apply(bucket_hit_rate)

    factors = build_factors(df)

    overall_bets = len(df)
    overall_wins = int((df["result"] == "WIN").sum())
    overall_losses = int((df["result"] == "LOSS").sum())
    overall_win_pct = round(overall_wins / overall_bets, 3)

    lines = [
        "NBA Model Calibration Report",
        f"Total graded bets: {overall_bets}",
        f"Overall record: {overall_wins}-{overall_losses}",
        f"Overall win rate: {overall_win_pct}",
        "",
        "By confidence label:",
        summarize(df, "confidence_label").to_string(index=False) if "confidence_label" in df.columns else "n/a",
        "",
        "By stat:",
        summarize(df, "stat").to_string(index=False) if "stat" in df.columns else "n/a",
        "",
        "By side:",
        summarize(df, "prediction").to_string(index=False) if "prediction" in df.columns else "n/a",
    ]

    if "hit_rate_bucket" in df.columns and df["hit_rate_bucket"].notna().any():
        lines.extend([
            "",
            "By hit-rate bucket:",
            summarize(df.dropna(subset=["hit_rate_bucket"]), "hit_rate_bucket").to_string(index=False),
        ])

    report = "\n".join(lines)

    with open(CALIBRATION_REPORT_PATH, "w", encoding="utf-8") as handle:
        handle.write(report + "\n")

    with open(CALIBRATION_FACTORS_PATH, "w", encoding="utf-8") as handle:
        json.dump(factors, handle, indent=2, sort_keys=True)

    print(report)
    print(f"\nSaved calibration report: {CALIBRATION_REPORT_PATH}")
    print(f"Saved calibration factors: {CALIBRATION_FACTORS_PATH}")


if __name__ == "__main__":
    main()
