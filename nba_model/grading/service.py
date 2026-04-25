import os
import sys
import pandas as pd

from nba_model.common import normalize_columns
from nba_model.settings import BEST_BETS_DIR, HISTORY_PATH
LOCAL_TODAYS_BETS_CSV = os.path.join(BEST_BETS_DIR, "nba_best_bets_today.csv")
LOCAL_TODAYS_BETS_NOEXT = os.path.join(BEST_BETS_DIR, "nba_best_bets_today")
GRADED_OUTPUT_PATH = os.path.join(BEST_BETS_DIR, "graded_bets.csv")


def ensure_dirs():
    os.makedirs(BEST_BETS_DIR, exist_ok=True)


def parse_prediction(bet_value):
    if pd.isna(bet_value):
        return None
    bet_str = str(bet_value).strip().upper()
    if "OVER" in bet_str:
        return "OVER"
    if "UNDER" in bet_str:
        return "UNDER"
    return None


def coerce_float(value):
    try:
        if pd.isna(value) or value == "":
            return None
        return float(value)
    except Exception:
        return None


def resolve_bets_file():
    explicit_path = os.environ.get("NBA_BETS_INPUT_PATH")
    if explicit_path:
        return explicit_path if os.path.exists(explicit_path) else None

    candidates = [
        LOCAL_TODAYS_BETS_CSV,
        LOCAL_TODAYS_BETS_NOEXT,
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def copy_to_local_csv(source_path):
    explicit_path = os.environ.get("NBA_BETS_INPUT_PATH")
    if explicit_path:
        return explicit_path
    return source_path


def load_history():
    if os.path.exists(HISTORY_PATH):
        try:
            df = pd.read_csv(HISTORY_PATH)
            df.columns = [str(c).strip().lower() for c in df.columns]
            return df
        except Exception as e:
            print(f"Warning: could not read local history, starting fresh: {e}")

    return pd.DataFrame(columns=[
        "date", "player", "team", "matchup", "stat", "bet",
        "line", "projection", "edge", "model_confidence",
        "bet_confidence", "confidence_label", "stddev", "hit_rate",
        "raw_stat", "result", "actual", "prediction"
    ])


def main():
    print("=== STARTING GRADING ===")
    ensure_dirs()

    source_bets_file = resolve_bets_file()
    if not source_bets_file:
        print("❌ Bets file not found in the local Best_Bets folder.")
        print("Checked:")
        print(f"  {LOCAL_TODAYS_BETS_CSV}")
        print(f"  {LOCAL_TODAYS_BETS_NOEXT}")
        sys.exit(1)

    print(f"Found bets file: {source_bets_file}")

    try:
        local_bets_file = copy_to_local_csv(source_bets_file)
    except Exception as e:
        print(f"❌ Could not copy bets file locally: {e}")
        sys.exit(1)

    print(f"Using local bets file: {local_bets_file}")

    df = pd.read_csv(local_bets_file)
    df = normalize_columns(df)

    required_cols = ["DATE", "PLAYER", "STAT", "BET", "LINE"]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        print(f"❌ Missing required columns: {missing}")
        print(f"Columns found: {list(df.columns)}")
        sys.exit(1)

    if df.empty:
        print("No bets in file. Exiting cleanly.")
        sys.exit(0)

    df["DATE"] = df["DATE"].astype(str).str[:10]
    file_dates = sorted(df["DATE"].dropna().unique().tolist())
    target_date = max(file_dates)

    print(f"Dates found in file: {file_dates}")
    print(f"Grading target date: {target_date}")

    graded_source_df = df[df["DATE"] == target_date].copy()

    if graded_source_df.empty:
        print("❌ No rows found for target grading date.")
        sys.exit(1)

    graded_rows = []

    for _, row in graded_source_df.iterrows():
        prediction = parse_prediction(row.get("BET"))
        line = coerce_float(row.get("LINE"))
        actual = coerce_float(row.get("ACTUAL"))
        existing_result = row.get("RESULT")

        result = "PENDING"

        if isinstance(existing_result, str) and existing_result.strip():
            result = existing_result.strip().upper()
        elif actual is not None and line is not None and prediction is not None:
            if prediction == "OVER":
                result = "WIN" if actual > line else "LOSS"
            elif prediction == "UNDER":
                result = "WIN" if actual < line else "LOSS"

        graded_rows.append({
            "date": str(row.get("DATE")),
            "player": row.get("PLAYER"),
            "team": row.get("TEAM"),
            "matchup": row.get("MATCHUP"),
            "stat": row.get("STAT"),
            "bet": row.get("BET"),
            "line": line,
            "projection": coerce_float(row.get("PROJECTION")),
            "edge": coerce_float(row.get("EDGE")),
            "model_confidence": row.get("MODEL_CONFIDENCE"),
            "bet_confidence": coerce_float(row.get("BET_CONFIDENCE")),
            "confidence_label": row.get("CONFIDENCE_LABEL"),
            "stddev": coerce_float(row.get("STDDEV")),
            "hit_rate": coerce_float(row.get("HIT_RATE")),
            "raw_stat": row.get("RAW_STAT"),
            "result": result,
            "actual": actual,
            "prediction": prediction,
        })

    graded_df = pd.DataFrame(graded_rows)

    history_df = load_history()
    replace_dates = set(graded_df["date"].astype(str).unique().tolist())

    if not history_df.empty and "date" in history_df.columns:
        history_df["date"] = history_df["date"].astype(str)
        history_df = history_df[~history_df["date"].isin(replace_dates)]

    final_df = pd.concat([history_df, graded_df], ignore_index=True)
    final_df.to_csv(HISTORY_PATH, index=False)
    print(f"Saved updated history locally: {HISTORY_PATH}")

    graded_df.to_csv(GRADED_OUTPUT_PATH, index=False)
    print(f"Saved graded bets locally: {GRADED_OUTPUT_PATH}")

    counts = graded_df["result"].value_counts(dropna=False).to_dict()

    print("\n=== SUMMARY ===")
    print(f"Date graded: {target_date}")
    print(f"Wins: {counts.get('WIN', 0)}")
    print(f"Losses: {counts.get('LOSS', 0)}")
    print(f"Pending: {counts.get('PENDING', 0)}")
    print(f"Unknown: {counts.get('UNKNOWN', 0)}")
    print("=== DONE ===")


if __name__ == "__main__":
    main()
