import os
import re
import time
from typing import Dict, List

import pandas as pd
from nba_api.stats.endpoints import boxscoretraditionalv3, playbyplayv3

from nba_model.settings import LINEUP_STINTS_PATH, RAW_GAMES_PATH


SECONDS_PER_PERIOD = 12 * 60
DEFAULT_MAX_GAMES = 60
DEFAULT_MAX_NEW_GAMES = 8
DEFAULT_RETRY_ATTEMPTS = 3
DEFAULT_RETRY_SLEEP = 2.5
DEFAULT_SAVE_EVERY = 2


def clock_to_seconds_remaining(clock_value):
    raw = str(clock_value or "").strip()
    if not raw or raw in {"nan", "None"}:
        return 0
    match = re.match(r"PT(?:(\d+)M)?([\d\.]+)S", raw)
    if match:
        minutes = int(match.group(1) or 0)
        seconds = float(match.group(2) or 0)
        return int(round((minutes * 60) + seconds))
    parts = raw.split(":", 1)
    if len(parts) == 2:
        minutes = int(float(parts[0] or 0))
        seconds = float(parts[1] or 0)
        return int(round((minutes * 60) + seconds))
    try:
        return int(round(float(raw)))
    except Exception:
        return 0


def normalize_name(value):
    text = str(value or "").strip().lower()
    text = text.replace(".", "").replace("'", "")
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def stint_row(game_id, team_id, team_code, period, stint_index, start_sec, end_sec, lineup):
    start_sec = 0 if start_sec is None else int(start_sec)
    end_sec = 0 if end_sec is None else int(end_sec)
    ordered = sorted(lineup)
    return {
        "GAME_ID": game_id,
        "TEAM_ID": team_id,
        "TEAM_ABBREVIATION": team_code,
        "PERIOD": int(period),
        "STINT_INDEX": int(stint_index),
        "START_SEC_REMAINING": start_sec,
        "END_SEC_REMAINING": end_sec,
        "SECONDS_PLAYED": max(start_sec - end_sec, 0),
        "LINEUP_PLAYER_IDS": "|".join(str(pid) for pid in ordered),
    }


def infer_starting_lineups(player_stats_df):
    starters = {}
    for team_id, team_df in player_stats_df.groupby("teamId"):
        team_sorted = team_df.copy()
        team_sorted = team_sorted.dropna(subset=["personId"]).copy()
        if team_sorted.empty:
            continue
        team_sorted["minutes_num"] = pd.to_numeric(
            team_sorted["minutes"].astype(str).str.split(":").str[0],
            errors="coerce",
        ).fillna(0)
        top_five = team_sorted.sort_values("minutes_num", ascending=False).head(5)
        starters[int(team_id)] = {
            "team_code": str(top_five["teamTricode"].iloc[0]).strip().upper(),
            "lineup": {int(pid) for pid in top_five["personId"].dropna().tolist()},
        }
    return starters


def build_team_name_lookup(player_stats_df, team_id):
    lookup = {}
    team_df = player_stats_df[pd.to_numeric(player_stats_df["teamId"], errors="coerce") == team_id].copy()
    for _, row in team_df.iterrows():
        if pd.isna(row.get("personId")):
            continue
        person_id = int(row["personId"])
        candidates = {
            normalize_name(f"{row.get('firstName', '')} {row.get('familyName', '')}"),
            normalize_name(row.get("nameI", "")),
            normalize_name(row.get("familyName", "")),
        }
        for candidate in candidates:
            if candidate:
                lookup[candidate] = person_id
    return lookup


def extract_lineup_stints_for_game(game_id):
    box = boxscoretraditionalv3.BoxScoreTraditionalV3(game_id=game_id)
    player_stats = box.get_data_frames()[0]
    if player_stats.empty:
        return []

    pbp = playbyplayv3.PlayByPlayV3(game_id=game_id)
    play_df = pbp.get_data_frames()[0]
    if play_df.empty:
        return []

    starters = infer_starting_lineups(player_stats)
    team_name_lookups = {team_id: build_team_name_lookup(player_stats, team_id) for team_id in starters}
    stints = []

    for team_id, starter_info in starters.items():
        lineup = set(starter_info["lineup"])
        team_code = starter_info["team_code"]
        stint_index = 0
        current_period = 1
        current_start = SECONDS_PER_PERIOD

        team_plays = play_df[pd.to_numeric(play_df["teamId"], errors="coerce") == team_id].copy()
        team_plays["period"] = pd.to_numeric(team_plays["period"], errors="coerce").fillna(0).astype(int)
        team_plays = team_plays.sort_values(["period", "actionNumber"])

        for _, play in team_plays.iterrows():
            period = int(play["period"])
            if period <= 0 or period > 4:
                continue

            if period != current_period:
                stints.append(stint_row(game_id, team_id, team_code, current_period, stint_index, current_start, 0, lineup))
                current_period = period
                current_start = SECONDS_PER_PERIOD
                stint_index = 0

            if str(play.get("actionType", "")).strip().lower() != "substitution":
                continue

            sec_remaining = clock_to_seconds_remaining(play.get("clock"))
            stints.append(stint_row(game_id, team_id, team_code, current_period, stint_index, current_start, sec_remaining, lineup))
            stint_index += 1
            current_start = sec_remaining

            description = str(play.get("description", ""))
            person_id = int(play.get("personId")) if pd.notna(play.get("personId")) else None

            if person_id is not None and person_id in lineup:
                lineup.remove(person_id)

            entering_name = None
            if "SUB:" in description:
                tail = description.split("SUB:", 1)[1]
                entering_name = tail.split("FOR", 1)[0].strip().strip(".")

            if entering_name:
                entering_id = team_name_lookups.get(team_id, {}).get(normalize_name(entering_name))
                if entering_id is not None:
                    lineup.add(int(entering_id))

        stints.append(stint_row(game_id, team_id, team_code, current_period, stint_index, current_start, 0, lineup))

    return stints


def read_existing_stints():
    if not os.path.exists(LINEUP_STINTS_PATH):
        return pd.DataFrame()
    try:
        return pd.read_csv(LINEUP_STINTS_PATH)
    except Exception:
        return pd.DataFrame()


def save_stints(stints_df):
    if stints_df.empty:
        return
    stints_df = stints_df[stints_df["SECONDS_PLAYED"] > 0].copy()
    stints_df = stints_df.drop_duplicates(
        subset=["GAME_ID", "TEAM_ID", "PERIOD", "STINT_INDEX", "START_SEC_REMAINING", "END_SEC_REMAINING", "LINEUP_PLAYER_IDS"]
    )
    stints_df = stints_df.sort_values(["GAME_ID", "TEAM_ID", "PERIOD", "STINT_INDEX"]).reset_index(drop=True)
    stints_df.to_csv(LINEUP_STINTS_PATH, index=False)


def extract_with_retries(game_id, retry_attempts, retry_sleep):
    last_exc = None
    for attempt in range(1, retry_attempts + 1):
        try:
            return extract_lineup_stints_for_game(game_id)
        except Exception as exc:
            last_exc = exc
            if attempt < retry_attempts:
                wait_seconds = retry_sleep * attempt
                print(f"Retrying lineup stints for game {game_id} ({attempt}/{retry_attempts}) after {wait_seconds:.1f}s: {exc}")
                time.sleep(wait_seconds)
    raise last_exc


def main():
    if not os.path.exists(RAW_GAMES_PATH):
        raise FileNotFoundError(f"Missing raw games file: {RAW_GAMES_PATH}")

    raw_games = pd.read_csv(RAW_GAMES_PATH, usecols=["GAME_ID", "GAME_DATE"])
    raw_games["GAME_DATE"] = pd.to_datetime(raw_games["GAME_DATE"], errors="coerce")
    raw_games = raw_games.dropna(subset=["GAME_ID", "GAME_DATE"]).copy()
    raw_games["GAME_ID"] = raw_games["GAME_ID"].astype(str).str.zfill(10)
    raw_games = raw_games.sort_values("GAME_DATE", ascending=False)
    max_games = int(os.environ.get("NBA_LINEUP_STINT_MAX_GAMES", str(DEFAULT_MAX_GAMES)) or str(DEFAULT_MAX_GAMES))
    max_new_games = int(os.environ.get("NBA_LINEUP_STINT_MAX_NEW_GAMES", str(DEFAULT_MAX_NEW_GAMES)) or str(DEFAULT_MAX_NEW_GAMES))
    retry_attempts = int(os.environ.get("NBA_LINEUP_STINT_RETRY_ATTEMPTS", str(DEFAULT_RETRY_ATTEMPTS)) or str(DEFAULT_RETRY_ATTEMPTS))
    retry_sleep = float(os.environ.get("NBA_LINEUP_STINT_RETRY_SLEEP", str(DEFAULT_RETRY_SLEEP)) or str(DEFAULT_RETRY_SLEEP))
    save_every = int(os.environ.get("NBA_LINEUP_STINT_SAVE_EVERY", str(DEFAULT_SAVE_EVERY)) or str(DEFAULT_SAVE_EVERY))
    recent_games = raw_games.drop_duplicates(subset=["GAME_ID"]).head(max_games)
    game_ids = recent_games["GAME_ID"].tolist()

    existing = read_existing_stints()
    existing_game_ids = set()
    if not existing.empty and "GAME_ID" in existing.columns:
        existing_game_ids = {str(game_id).zfill(10) for game_id in existing["GAME_ID"].dropna().tolist()}

    game_ids = [game_id for game_id in game_ids if game_id not in existing_game_ids]
    game_ids = game_ids[:max_new_games]
    if not game_ids:
        print("Lineup stints already cover the targeted recent games. Nothing new to fetch.")
        return

    all_stints: List[Dict] = []
    successful_games = 0
    failed_games = []

    print(
        f"Fetching lineup stints for up to {len(game_ids)} new games "
        f"(recent pool={max_games}, retries={retry_attempts}, save_every={save_every})"
    )

    for idx, game_id in enumerate(game_ids, start=1):
        try:
            game_stints = extract_with_retries(game_id, retry_attempts=retry_attempts, retry_sleep=retry_sleep)
            if game_stints:
                all_stints.extend(game_stints)
                successful_games += 1
        except Exception as exc:
            print(f"WARNING: lineup stints failed for game {game_id}: {exc}")
            failed_games.append(game_id)

        if all_stints and (successful_games % max(save_every, 1) == 0):
            pending_df = pd.DataFrame(all_stints)
            merged = pd.concat([existing, pending_df], ignore_index=True) if not existing.empty else pending_df
            save_stints(merged)
            existing = read_existing_stints()
            all_stints = []

        if idx % 5 == 0 or idx == len(game_ids):
            print(f"Processed {idx}/{len(game_ids)} games")

    if not all_stints and successful_games == 0:
        print("No lineup stints were created.")
        return

    if all_stints:
        pending_df = pd.DataFrame(all_stints)
        stints_df = pd.concat([existing, pending_df], ignore_index=True) if not existing.empty else pending_df
    else:
        stints_df = existing

    save_stints(stints_df)
    stints_df = read_existing_stints()
    print(f"Saved lineup stints: {LINEUP_STINTS_PATH}")
    print(f"Rows saved: {len(stints_df)}")
    print(f"Successful new games: {successful_games}")
    if failed_games:
        print(f"Failed new games: {len(failed_games)}")


if __name__ == "__main__":
    main()
