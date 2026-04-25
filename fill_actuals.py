import os
import re
import time
import unicodedata
from datetime import datetime, timedelta

import pandas as pd
from nba_api.stats.static import players
from nba_api.stats.endpoints import playergamelog

BASE_DIR = os.environ.get("EDGERANKED_NBA_BASE_DIR", os.path.dirname(os.path.abspath(__file__)))
BEST_BETS_PATH = os.environ.get(
    "NBA_BETS_INPUT_PATH",
    os.path.join(BASE_DIR, "Best_Bets", "nba_best_bets_today.csv"),
)


def normalize_name(name):
    name = str(name).strip()
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    name = name.lower()
    name = re.sub(r"[^a-z0-9\s]", "", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def normalize_columns(df):
    df = df.copy()
    df.columns = [str(c).strip().upper() for c in df.columns]
    return df


def parse_prediction_from_bet(bet_value):
    if pd.isna(bet_value):
        return None
    bet_str = str(bet_value).strip().upper()
    if "OVER" in bet_str:
        return "OVER"
    if "UNDER" in bet_str:
        return "UNDER"
    return None


def safe_float(value):
    try:
        if pd.isna(value) or value == "":
            return None
        return float(value)
    except Exception:
        return None


def compute_result(prediction, line, actual):
    if prediction is None or line is None or actual is None:
        return "PENDING"

    if prediction == "OVER":
        return "WIN" if actual > line else "LOSS"
    if prediction == "UNDER":
        return "WIN" if actual < line else "LOSS"

    return "UNKNOWN"


def get_stat_value_from_log_row(log_row, stat_name):
    stat_name = str(stat_name).strip().upper()

    if stat_name == "PTS":
        return safe_float(log_row.get("PTS"))
    if stat_name == "REB":
        return safe_float(log_row.get("REB"))
    if stat_name == "AST":
        return safe_float(log_row.get("AST"))
    if stat_name == "STL":
        return safe_float(log_row.get("STL"))
    if stat_name == "BLK":
        return safe_float(log_row.get("BLK"))
    if stat_name in ["FG3M", "3PM", "THREES"]:
        return safe_float(log_row.get("FG3M"))

    return None


def load_best_bets():
    if not os.path.exists(BEST_BETS_PATH):
        raise FileNotFoundError(f"Missing file: {BEST_BETS_PATH}")

    df = pd.read_csv(BEST_BETS_PATH)
    if df.empty:
        return normalize_columns(df)

    df = normalize_columns(df)

    if "ACTUAL" not in df.columns:
        df["ACTUAL"] = ""
    if "RESULT" not in df.columns:
        df["RESULT"] = ""

    return df


def build_player_lookup():
    lookup = {}
    all_players = players.get_players()

    for p in all_players:
        full_name = p.get("full_name", "")
        pid = p.get("id")
        key = normalize_name(full_name)
        lookup[key] = pid

    manual_aliases = {
        "luka doncic": "Luka Doncic",
        "kristaps porzingis": "Kristaps Porzingis",
        "nikola jokic": "Nikola Jokic",
        "bogdan bogdanovic": "Bogdan Bogdanovic",
    }

    for alias_key, official_name in manual_aliases.items():
        match = players.find_players_by_full_name(official_name)
        if match:
            lookup[alias_key] = match[0]["id"]

    return lookup


def fetch_player_gamelog(player_id, season_string):
    endpoint = playergamelog.PlayerGameLog(
        player_id=player_id,
        season=season_string
    )
    df = endpoint.get_data_frames()[0]
    if df.empty:
        return df

    df = df.copy()
    df["GAME_DATE"] = pd.to_datetime(df["GAME_DATE"], errors="coerce")
    return df


def find_matching_game_row(gamelog_df, target_date):
    """
    Finds the most likely row for the slate date.
    Because late-night grading can happen after midnight, we allow +/- 1 day.
    Preference:
    1) exact date
    2) previous day
    3) next day
    """
    if gamelog_df.empty:
        return None

    target_ts = pd.to_datetime(target_date)

    exact = gamelog_df[gamelog_df["GAME_DATE"].dt.date == target_ts.date()]
    if not exact.empty:
        return exact.sort_values("GAME_DATE", ascending=False).iloc[0]

    prev_day = target_ts - timedelta(days=1)
    prev_match = gamelog_df[gamelog_df["GAME_DATE"].dt.date == prev_day.date()]
    if not prev_match.empty:
        return prev_match.sort_values("GAME_DATE", ascending=False).iloc[0]

    next_day = target_ts + timedelta(days=1)
    next_match = gamelog_df[gamelog_df["GAME_DATE"].dt.date == next_day.date()]
    if not next_match.empty:
        return next_match.sort_values("GAME_DATE", ascending=False).iloc[0]

    return None


def season_from_date(date_str):
    dt = pd.to_datetime(date_str)
    year = dt.year
    month = dt.month

    if month >= 10:
        start_year = year
        end_year = year + 1
    else:
        start_year = year - 1
        end_year = year

    return f"{start_year}-{str(end_year)[-2:]}"


def main():
    print("=== FILLING ACTUALS ===")

    try:
        df = load_best_bets()
    except FileNotFoundError as e:
        print(f"❌ {e}")
        raise SystemExit(1)

    if df.empty:
        print("No bets found in file.")
        raise SystemExit(0)

    required_cols = ["DATE", "PLAYER", "STAT", "BET", "LINE"]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        print(f"❌ Missing required columns: {missing}")
        print(f"Columns found: {list(df.columns)}")
        raise SystemExit(1)

    df["DATE"] = df["DATE"].astype(str).str[:10]

    target_dates = sorted(df["DATE"].dropna().unique().tolist())
    target_date = max(target_dates)

    print(f"Loaded bets: {len(df)}")
    print(f"Dates in file: {target_dates}")
    print(f"Target grading date: {target_date}")

    player_lookup = build_player_lookup()
    season_string = season_from_date(target_date)

    print(f"Using NBA season: {season_string}")

    gamelog_cache = {}
    updated_rows = 0
    pending_rows = 0
    missing_players = []

    for idx, row in df.iterrows():
        row_date = str(row.get("DATE", ""))[:10]
        if row_date != target_date:
            continue

        player_name = row.get("PLAYER")
        stat_name = row.get("STAT")
        bet_value = row.get("BET")
        line_value = safe_float(row.get("LINE"))

        player_key = normalize_name(player_name)
        player_id = player_lookup.get(player_key)

        if not player_id:
            missing_players.append(str(player_name))
            df.at[idx, "RESULT"] = "PENDING"
            continue

        if player_id not in gamelog_cache:
            try:
                gamelog_cache[player_id] = fetch_player_gamelog(player_id, season_string)
                time.sleep(0.6)
            except Exception as e:
                print(f"Warning: could not fetch gamelog for {player_name}: {e}")
                gamelog_cache[player_id] = pd.DataFrame()

        player_log = gamelog_cache[player_id]
        game_row = find_matching_game_row(player_log, target_date)

        if game_row is None:
            df.at[idx, "RESULT"] = "PENDING"
            pending_rows += 1
            continue

        actual = get_stat_value_from_log_row(game_row, stat_name)
        prediction = parse_prediction_from_bet(bet_value)
        result = compute_result(prediction, line_value, actual)

        if actual is None:
            df.at[idx, "ACTUAL"] = ""
            df.at[idx, "RESULT"] = "PENDING"
            pending_rows += 1
        else:
            df.at[idx, "ACTUAL"] = actual
            df.at[idx, "RESULT"] = result
            updated_rows += 1

    df.to_csv(BEST_BETS_PATH, index=False)
    print(f"Saved updated bets file: {BEST_BETS_PATH}")

    if missing_players:
        unique_missing = sorted(set(missing_players))
        print("\nPlayers not matched in nba_api lookup:")
        for name in unique_missing:
            print(f"- {name}")

    print("\n=== FILL ACTUALS SUMMARY ===")
    print(f"Updated rows: {updated_rows}")
    print(f"Still pending: {pending_rows}")
    print("=== DONE ===")


if __name__ == "__main__":
    main()
