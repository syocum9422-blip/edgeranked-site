import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import requests

BASE_DIR = os.environ.get("EDGERANKED_NBA_BASE_DIR", os.path.dirname(os.path.abspath(__file__)))
OUTPUT_PATH = os.path.join(BASE_DIR, "lines_today.csv")

NBA_LEAGUE_ID = 7
EASTERN = ZoneInfo("America/New_York")


def get_today_et():
    return datetime.now(EASTERN).date()


def parse_iso_to_et(value):
    if not value:
        return pd.NaT

    try:
        dt = pd.to_datetime(value, utc=True, errors="coerce")
        if pd.isna(dt):
            return pd.NaT
        return dt.tz_convert(EASTERN)
    except Exception:
        return pd.NaT


def build_headers():
    return {
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://app.prizepicks.com/",
        "Origin": "https://app.prizepicks.com",
    }


def fetch_payload():
    session = requests.Session()
    session.headers.update(build_headers())

    endpoints = [
        "https://partner-api.prizepicks.com/projections",
        "https://api.prizepicks.com/projections",
    ]

    params = {
        "league_id": NBA_LEAGUE_ID,
        "per_page": 1000,
        "single_stat": "true",
    }

    last_error = None

    for url in endpoints:
        try:
            resp = session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict) and data.get("data"):
                print(f"Fetched PrizePicks data from: {url}")
                return data
        except Exception as e:
            last_error = e
            print(f"WARNING: failed endpoint {url}: {e}")

    raise RuntimeError(f"Could not fetch PrizePicks projections payload. Last error: {last_error}")


def build_player_lookup(included):
    player_lookup = {}

    for item in included:
        item_type = str(item.get("type", "")).lower()
        item_id = str(item.get("id", ""))
        attrs = item.get("attributes", {}) or {}

        if item_type in {"new_player", "player"}:
            name = (
                attrs.get("name")
                or attrs.get("display_name")
                or attrs.get("full_name")
                or ""
            )
            team = attrs.get("team") or attrs.get("team_abbreviation") or ""
            league_name = attrs.get("league_name") or ""

            player_lookup[item_id] = {
                "PLAYER_NAME": name,
                "TEAM": team,
                "LEAGUE_NAME": league_name,
            }

    return player_lookup


def get_related_player_id(proj):
    rel = proj.get("relationships", {}) or {}

    for key in ["new_player", "player"]:
        node = rel.get(key, {}) or {}
        data = node.get("data")

        if isinstance(data, dict) and data.get("id") is not None:
            return str(data["id"])

    return None


def truthy_flag(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False

    s = str(value).strip().lower()
    return s in {"true", "1", "yes", "y"}


def looks_like_goblin(attrs):
    candidates = [
        attrs.get("is_goblin"),
        attrs.get("goblin"),
        attrs.get("board_projection_type"),
        attrs.get("projection_type"),
        attrs.get("pick_type"),
    ]
    for v in candidates:
        if v is None:
            continue
        s = str(v).strip().lower()
        if s == "goblin" or truthy_flag(v) and "goblin" in s:
            return True
    return False


def looks_like_demon(attrs):
    candidates = [
        attrs.get("is_demon"),
        attrs.get("demon"),
        attrs.get("board_projection_type"),
        attrs.get("projection_type"),
        attrs.get("pick_type"),
    ]
    for v in candidates:
        if v is None:
            continue
        s = str(v).strip().lower()
        if s == "demon" or truthy_flag(v) and "demon" in s:
            return True
    return False


def looks_like_regular(attrs):
    candidates = [
        attrs.get("is_default"),
        attrs.get("default"),
        attrs.get("is_main"),
        attrs.get("main"),
        attrs.get("board_projection_type"),
        attrs.get("projection_type"),
        attrs.get("pick_type"),
        attrs.get("odds_type"),
    ]
    for v in candidates:
        if v is None:
            continue
        if truthy_flag(v):
            return True
        s = str(v).strip().lower()
        if s in {"regular", "standard", "default", "core", "main"}:
            return True
    return False


def extract_rows(payload):
    data = payload.get("data", []) or []
    included = payload.get("included", []) or []

    player_lookup = build_player_lookup(included)

    rows = []
    for proj in data:
        attrs = proj.get("attributes", {}) or {}
        player_id = get_related_player_id(proj)
        player_info = player_lookup.get(player_id, {})

        player_name = str(player_info.get("PLAYER_NAME", "")).strip()
        if not player_name:
            continue

        stat = (
            attrs.get("stat_type")
            or attrs.get("market")
            or attrs.get("prop_type")
            or ""
        )

        line = attrs.get("line_score")
        if line is None:
            line = attrs.get("line")

        start_time_raw = attrs.get("start_time")
        board_time_raw = attrs.get("board_time")
        updated_at_raw = attrs.get("updated_at")

        rows.append({
            "PLAYER_NAME": player_name,
            "TEAM": player_info.get("TEAM", ""),
            "STAT": str(stat).strip(),
            "LINE": pd.to_numeric(line, errors="coerce"),
            "START_TIME_ET": parse_iso_to_et(start_time_raw),
            "BOARD_TIME_ET": parse_iso_to_et(board_time_raw),
            "UPDATED_AT_ET": parse_iso_to_et(updated_at_raw),
            "IS_GOBLIN": looks_like_goblin(attrs),
            "IS_DEMON": looks_like_demon(attrs),
            "IS_REGULAR_HINT": looks_like_regular(attrs),
            "RAW_START_TIME": start_time_raw or "",
            "RAW_BOARD_TIME": board_time_raw or "",
            "RAW_UPDATED_AT": updated_at_raw or "",
        })

    df = pd.DataFrame(rows)

    if df.empty:
        raise ValueError("PrizePicks payload returned no usable projection rows")

    return df


def filter_to_today(df):
    today_et = get_today_et()
    df = df.copy()

    df["START_TIME_ET"] = pd.to_datetime(df["START_TIME_ET"], errors="coerce")
    df["BOARD_TIME_ET"] = pd.to_datetime(df["BOARD_TIME_ET"], errors="coerce")
    df["UPDATED_AT_ET"] = pd.to_datetime(df["UPDATED_AT_ET"], errors="coerce")

    same_day_start = df["START_TIME_ET"].notna() & (df["START_TIME_ET"].dt.date == today_et)
    same_day_board = df["BOARD_TIME_ET"].notna() & (df["BOARD_TIME_ET"].dt.date == today_et)

    filtered = df[same_day_start | same_day_board].copy()

    if not filtered.empty:
        return filtered

    df["_SORT_TIME"] = df["START_TIME_ET"]
    future_rows = df[df["_SORT_TIME"].notna()].sort_values("_SORT_TIME")

    if future_rows.empty:
        return filtered

    nearest_date = future_rows.iloc[0]["_SORT_TIME"].date()
    fallback = future_rows[future_rows["_SORT_TIME"].dt.date == nearest_date].copy()
    fallback.drop(columns=["_SORT_TIME"], inplace=True, errors="ignore")

    print(f"WARNING: no exact ET-today rows found; falling back to nearest slate date: {nearest_date}")
    return fallback


def choose_regular_line(group):
    group = group.copy()

    # freshest timestamps first
    group = group.sort_values(
        by=["UPDATED_AT_ET", "BOARD_TIME_ET", "START_TIME_ET"],
        ascending=False,
        na_position="last"
    )

    # 1) Prefer rows explicitly hinted as regular
    regular_hint_rows = group[group["IS_REGULAR_HINT"] == True]
    if not regular_hint_rows.empty:
        return regular_hint_rows.iloc[0]

    # 2) Prefer rows that are NOT marked goblin/demon
    normal_rows = group[(group["IS_GOBLIN"] == False) & (group["IS_DEMON"] == False)]
    if not normal_rows.empty:
        return normal_rows.iloc[0]

    # 3) No trustworthy main line exists in this group.
    # Return None so downstream consumers can keep the player visible
    # without attaching an alternate line as if it were the standard market.
    return None


def clean_and_dedupe(df):
    df = df.copy()

    df = df.dropna(subset=["PLAYER_NAME", "STAT", "LINE"])
    df["PLAYER_NAME"] = df["PLAYER_NAME"].astype(str).str.strip()
    df["STAT"] = df["STAT"].astype(str).str.strip()

    selected_rows = []
    for (_, _), group in df.groupby(["PLAYER_NAME", "STAT"], dropna=False):
        chosen = choose_regular_line(group)
        if chosen is not None:
            selected_rows.append(chosen)

    final_df = pd.DataFrame(selected_rows).copy()

    for col in ["START_TIME_ET", "BOARD_TIME_ET", "UPDATED_AT_ET"]:
        final_df[col] = final_df[col].apply(lambda x: x.isoformat() if pd.notna(x) else "")

    final_df = final_df[
        [
            "PLAYER_NAME",
            "TEAM",
            "STAT",
            "LINE",
            "IS_REGULAR_HINT",
            "IS_GOBLIN",
            "IS_DEMON",
            "START_TIME_ET",
            "BOARD_TIME_ET",
            "UPDATED_AT_ET",
        ]
    ].copy()

    final_df = final_df.sort_values(["PLAYER_NAME", "STAT"]).reset_index(drop=True)

    return final_df


def main():
    payload = fetch_payload()
    raw_df = extract_rows(payload)
    filtered_df = filter_to_today(raw_df)
    final_df = clean_and_dedupe(filtered_df)

    if final_df.empty:
        raise ValueError("lines_today.csv would be empty after filtering to today's slate")

    final_df.to_csv(OUTPUT_PATH, index=False)

    unique_players = final_df["PLAYER_NAME"].nunique()
    unique_stats = final_df["STAT"].nunique()

    print(f"Saved lines file: {OUTPUT_PATH}")
    print(f"Rows saved: {len(final_df)}")
    print(f"Unique players: {unique_players}")
    print(f"Unique stats: {unique_stats}")

    print("\nSample rows:")
    print(final_df.head(20).to_string(index=False))

    if unique_players < 10:
        print("\nERROR: Tiny slate detected after fetch/filter.")
        sys.exit(1)


if __name__ == "__main__":
    main()
