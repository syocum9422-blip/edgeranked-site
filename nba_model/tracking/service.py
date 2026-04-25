import os
import pandas as pd

from nba_model.settings import (
    CALIBRATION_SUMMARY_PATH,
    HISTORY_PATH,
    RECORD_SUMMARY_PATH,
)


def summarize_group(df, group_cols, label):
    grouped = (
        df.groupby(group_cols, dropna=False)
        .agg(
            bets=("result", "size"),
            wins=("result", lambda s: int((s == "WIN").sum())),
            losses=("result", lambda s: int((s == "LOSS").sum())),
        )
        .reset_index()
    )
    grouped["win_pct"] = (grouped["wins"] / grouped["bets"]).round(3)
    grouped["section"] = label
    return grouped


def main():
    print("=== BUILDING RECORD SUMMARY ===")

    if not os.path.exists(HISTORY_PATH):
        print("❌ No history file found.")
        return

    df = pd.read_csv(HISTORY_PATH)

    if df.empty:
        print("No data.")
        return

    df.columns = [c.lower() for c in df.columns]

    df = df[df["result"].isin(["WIN", "LOSS"])]

    if df.empty:
        print("No graded bets yet.")
        return

    daily = df.groupby("date")["result"].value_counts().unstack(fill_value=0)

    daily["wins"] = daily.get("WIN", 0)
    daily["losses"] = daily.get("LOSS", 0)
    daily["total"] = daily["wins"] + daily["losses"]
    daily["win_pct"] = (daily["wins"] / daily["total"]).round(3)

    daily = daily.reset_index()

    total_wins = daily["wins"].sum()
    total_losses = daily["losses"].sum()
    total_bets = total_wins + total_losses

    overall_pct = round(total_wins / total_bets, 3) if total_bets > 0 else 0

    print("\n=== OVERALL RECORD ===")
    print(f"{total_wins}-{total_losses}")
    print(f"Win %: {overall_pct}")

    daily.to_csv(RECORD_SUMMARY_PATH, index=False)

    print(f"\nSaved record file: {RECORD_SUMMARY_PATH}")

    calibration_frames = []

    if "stat" in df.columns:
        calibration_frames.append(summarize_group(df, ["stat"], "by_stat"))

    if "confidence_label" in df.columns:
        calibration_frames.append(summarize_group(df, ["confidence_label"], "by_confidence"))

    if "prediction" in df.columns:
        calibration_frames.append(summarize_group(df, ["prediction"], "by_side"))

    if "hit_rate" in df.columns:
        hit_rate_df = df.copy()
        hit_rate_df["hit_rate"] = pd.to_numeric(hit_rate_df["hit_rate"], errors="coerce")
        hit_rate_df = hit_rate_df.dropna(subset=["hit_rate"])
        if not hit_rate_df.empty:
            hit_rate_df["hit_rate_bucket"] = pd.cut(
                hit_rate_df["hit_rate"],
                bins=[0.0, 0.55, 0.60, 0.65, 0.70, 1.0],
                labels=["<=55%", "55-60%", "60-65%", "65-70%", "70%+"],
                include_lowest=True,
            )
            calibration_frames.append(summarize_group(hit_rate_df, ["hit_rate_bucket"], "by_hit_rate"))

    if calibration_frames:
        calibration_df = pd.concat(calibration_frames, ignore_index=True)
        calibration_df.to_csv(CALIBRATION_SUMMARY_PATH, index=False)
        print(f"Saved calibration summary: {CALIBRATION_SUMMARY_PATH}")


if __name__ == "__main__":
    main()
