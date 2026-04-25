import os
import sys
import subprocess
import pandas as pd
from pathlib import Path
from datetime import datetime

from nba_model.common import clean_name, find_player_col
from nba_model.settings import BASE_DIR, BEST_BETS_OUTPUT_PATH, GAME_LINES_PATH, LINES_PATH, PROJECTIONS_PATH, UNMATCHED_PLAYERS_PATH


RENDER_PUBLISH_SCRIPT = Path(BASE_DIR) / "scripts" / "publish_render_site.sh"
PROJECT_PYTHON = str(Path(BASE_DIR) / ".venv" / "bin" / "python")


def env_flag(name):
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "y"}


def run_step(label, cmd):
    print(f"\n===== {label} =====")
    print("Running:", " ".join(cmd))
    result = subprocess.run(cmd, cwd=BASE_DIR)

    if result.returncode != 0:
        print(f"ERROR: Step failed: {label}")
        sys.exit(result.returncode)


def validate_csv(path, label, allow_empty=False):
    if not os.path.exists(path):
        print(f"ERROR: Missing {label}: {path}")
        sys.exit(1)

    df = pd.read_csv(path)

    if df.empty and not allow_empty:
        print(f"ERROR: {label} exists but is empty: {path}")
        sys.exit(1)

    print(f"{label} rows: {len(df)}")
    return df


def today_et_date():
    return pd.Timestamp.now(tz="America/New_York").date()


def latest_game_lines_date():
    if not os.path.exists(GAME_LINES_PATH):
        return None
    try:
        df = pd.read_csv(GAME_LINES_PATH)
    except Exception:
        return None
    if df.empty or "GAME_DATE" not in df.columns:
        return None
    dates = pd.to_datetime(df["GAME_DATE"], errors="coerce").dropna()
    if dates.empty:
        return None
    return dates.max().date()


def latest_nba_lines_date():
    if not os.path.exists(LINES_PATH):
        return None
    try:
        df = pd.read_csv(LINES_PATH)
    except Exception:
        return None
    if df.empty or "UPDATED_AT_ET" not in df.columns:
        return None
    timestamps = pd.to_datetime(df["UPDATED_AT_ET"], errors="coerce").dropna()
    if timestamps.empty:
        return None
    return timestamps.max().date()


def ensure_market_game_lines_current():
    latest_date = latest_game_lines_date()
    today = today_et_date()
    if latest_date == today:
        return
    print(
        f"ERROR: game_lines_today.csv is stale or missing for today's slate. "
        f"Latest available date: {latest_date}. Expected: {today}."
    )
    sys.exit(1)


def ensure_nba_lines_current():
    latest_date = latest_nba_lines_date()
    today = today_et_date()
    if latest_date == today:
        return
    print(
        f"ERROR: lines_today.csv is stale or missing for today's slate. "
        f"Latest available date: {latest_date}. Expected: {today}."
    )
    sys.exit(1)


def should_fetch_lines():
    if env_flag("EDGERANKED_SKIP_NBA_LINES"):
        print("SKIPPING LINE REFRESH: EDGERANKED_SKIP_NBA_LINES=1")
        return False

    if os.environ.get("EDGERANKED_FORCE_NBA_LINES", "").strip() == "1":
        print("FORCING LINE REFRESH: EDGERANKED_FORCE_NBA_LINES=1")
        return True

    if not os.path.exists(LINES_PATH):
        print("No existing lines_today.csv found. Fetching fresh lines.")
        return True

    try:
        df = pd.read_csv(LINES_PATH)
    except Exception as exc:
        print(f"Could not read existing lines_today.csv ({exc}). Fetching fresh lines.")
        return True

    if df.empty:
        print("Existing lines_today.csv is empty. Fetching fresh lines.")
        return True

    if "UPDATED_AT_ET" not in df.columns:
        print("Existing lines_today.csv has no UPDATED_AT_ET column. Fetching fresh lines.")
        return True

    timestamps = pd.to_datetime(df["UPDATED_AT_ET"], errors="coerce")
    timestamps = timestamps.dropna()
    if timestamps.empty:
        print("Existing lines_today.csv has no valid timestamps. Fetching fresh lines.")
        return True

    latest_date = timestamps.max().date()
    today = datetime.now().date()

    if latest_date == today:
        print(f"Reusing existing lines_today.csv from {latest_date}. No new line pull needed.")
        return False

    print(f"Existing lines_today.csv is from {latest_date}. Fetching fresh lines for {today}.")
    return True


def should_fetch_market_game_lines():
    if env_flag("EDGERANKED_SKIP_GAME_LINES"):
        print("SKIPPING GAME LINE REFRESH: EDGERANKED_SKIP_GAME_LINES=1")
        return False

    if os.environ.get("EDGERANKED_FORCE_GAME_LINES", "").strip() == "1":
        print("FORCING GAME LINE REFRESH: EDGERANKED_FORCE_GAME_LINES=1")
        return True

    if not os.path.exists(GAME_LINES_PATH):
        print("No existing game_lines_today.csv found. Fetching fresh game lines.")
        return True

    try:
        df = pd.read_csv(GAME_LINES_PATH)
    except Exception as exc:
        print(f"Could not read existing game_lines_today.csv ({exc}). Fetching fresh game lines.")
        return True

    if df.empty:
        print("Existing game_lines_today.csv is empty. Fetching fresh game lines.")
        return True

    if "GAME_DATE" not in df.columns:
        print("Existing game_lines_today.csv has no GAME_DATE column. Fetching fresh game lines.")
        return True

    dates = pd.to_datetime(df["GAME_DATE"], errors="coerce").dropna()
    if dates.empty:
        print("Existing game_lines_today.csv has no valid GAME_DATE values. Fetching fresh game lines.")
        return True

    latest_date = dates.max().date()
    today = today_et_date()

    if latest_date == today:
        print(f"Reusing existing game_lines_today.csv from {latest_date}. No new odds API pull needed.")
        return False

    print(f"Existing game_lines_today.csv is from {latest_date}. Fetching fresh game lines for {today}.")
    return True


def sanitize_lines_against_projections():
    lines = pd.read_csv(LINES_PATH)
    projections = pd.read_csv(PROJECTIONS_PATH)

    if lines.empty:
        print("WARNING: lines_today.csv is empty before sanitize step.")
        return []

    if projections.empty:
        raise ValueError("projections.csv is empty before sanitize step.")

    line_player_col = find_player_col(lines)
    proj_player_col = find_player_col(projections)

    lines = lines.copy()
    projections = projections.copy()

    lines["_PLAYER_KEY"] = lines[line_player_col].astype(str).map(clean_name)
    projections["_PLAYER_KEY"] = projections[proj_player_col].astype(str).map(clean_name)

    valid_projection_players = set(projections["_PLAYER_KEY"].dropna().tolist())

    removed = lines[~lines["_PLAYER_KEY"].isin(valid_projection_players)].copy()
    kept = lines[lines["_PLAYER_KEY"].isin(valid_projection_players)].copy()

    removed_names = (
        removed[line_player_col].astype(str).drop_duplicates().tolist()
        if not removed.empty else []
    )

    kept = kept.drop(columns=["_PLAYER_KEY"], errors="ignore")
    kept.to_csv(LINES_PATH, index=False)

    print(f"\nSanitized lines_today.csv")
    print(f"Kept rows: {len(kept)}")
    print(f"Removed stale/unmatched rows: {len(removed)}")

    if removed_names:
        print("Removed players:")
        for name in removed_names:
            print(f"- {name}")

    return removed_names


def publish_render_site():
    if not RENDER_PUBLISH_SCRIPT.exists():
        print("SKIPPING RENDER PUBLISH: publish_render_site.sh not found.")
        sys.exit(1)

    print("\n===== Publish Render site =====")
    env = os.environ.copy()
    env.setdefault("EDGERANKED_PUBLISH_SPORTS", "nba")
    result = subprocess.run([str(RENDER_PUBLISH_SCRIPT)], cwd=BASE_DIR, env=env)
    if result.returncode != 0:
        print("ERROR: Render publish step failed.")
        sys.exit(result.returncode or 1)

    print("Render publish finished.")


def refresh_official_injuries():
    print("\n===== Refresh official NBA injuries =====")
    result = subprocess.run([PROJECT_PYTHON, "fetch_official_nba_injuries.py"], cwd=BASE_DIR)
    if result.returncode != 0:
        print("WARNING: Official NBA injury refresh failed. Reusing existing injury file.")
        return

    print("Official NBA injuries refreshed.")


def refresh_market_game_lines():
    print("\n===== Refresh NBA market game lines =====")
    if not should_fetch_market_game_lines():
        print("Skipping fetch_nba_game_lines.py and reusing the saved game-line board.")
        ensure_market_game_lines_current()
        return

    result = subprocess.run([PROJECT_PYTHON, "fetch_nba_game_lines.py"], cwd=BASE_DIR)
    if result.returncode != 0:
        print("ERROR: NBA market game-line refresh failed.")
        ensure_market_game_lines_current()
        return

    ensure_market_game_lines_current()
    print("NBA market game-line refresh finished.")


def main():
    refresh_official_injuries()
    refresh_market_game_lines()

    if should_fetch_lines():
        run_step("Fetch PrizePicks lines", [PROJECT_PYTHON, "fetch_lines.py"])
    else:
        print("\n===== Fetch PrizePicks lines =====")
        print("Skipping fetch_lines.py and using the existing saved line board.")

    lines_df = validate_csv(LINES_PATH, "lines_today.csv")
    ensure_nba_lines_current()

    player_col = find_player_col(lines_df)
    unique_players = lines_df[player_col].astype(str).str.strip().nunique()
    print(f"Unique players in lines_today.csv before sanitize: {unique_players}")

    if unique_players < 10:
        print("\nERROR: fetch_lines.py only produced a tiny slate.")
        sys.exit(1)

    run_step("Run NBA projection model", [PROJECT_PYTHON, "run_model.py"])
    validate_csv(PROJECTIONS_PATH, "projections.csv")

    sanitize_lines_against_projections()

    if env_flag("EDGERANKED_SKIP_BEST_BETS"):
        print("\n===== Build best bets =====")
        print("Skipping build_best_bets.py and reusing the saved best-bets outputs.")
    else:
        run_step("Build best bets", [PROJECT_PYTHON, "build_best_bets.py"])
        validate_csv(BEST_BETS_OUTPUT_PATH, "nba_best_bets_today.csv", allow_empty=True)

        unmatched = validate_csv(
            UNMATCHED_PLAYERS_PATH,
            "unmatched_players_today.csv",
            allow_empty=True
        )

        if len(unmatched) > 0:
            print("\nERROR: Unmatched players still exist.")
            print(unmatched.head(25).to_string(index=False))

    publish_render_site()
    print("\nPipeline finished successfully.")


if __name__ == "__main__":
    main()
