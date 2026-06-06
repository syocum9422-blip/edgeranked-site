from __future__ import annotations

import os
import shutil
import time
import unicodedata
from json import JSONDecodeError
from pathlib import Path

import pandas as pd
import requests

from wnba_model_config import (
    CANONICAL_PLAYER_GAMES_PATH,
    CANONICAL_SCHEDULE_TODAY_PATH,
    RAW_PLAYER_GAMES_PATH,
    RAW_SPORTSBOOK_LINES_PATH,
)
from wnba_model.settings import BASE_DIR, RAW_DIR, TODAY_OVERRIDE
from wnba_model_utils import canonicalize_name, setup_logging, standardize_team_abbrev

SEASONS = (2025, 2024, 2023)
SOURCE_TO_LEAGUE = {
    "api:espn:wnba:gamelog": "wnba",
    "api:espn:womens-college-basketball:gamelog": "womens-college-basketball",
}
REQUEST_SLEEP_SECONDS = 0.08
REPORT_COLUMNS = [
    "player_name",
    "team",
    "had_history_before",
    "rows_added",
    "source",
    "league_used",
    "athlete_id",
    "resolution_status",
]
PLAYER_GAME_COLUMNS = [
    "game_date",
    "season",
    "player_name",
    "team",
    "opponent",
    "home_away",
    "minutes",
    "points",
    "rebounds",
    "assists",
    "threes_made",
    "steals",
    "blocks",
    "turnovers",
    "fga",
    "fgm",
    "fta",
    "ftm",
    "offensive_rebounds",
    "defensive_rebounds",
    "plus_minus",
    "player_key",
    "is_home",
    "_data_source",
]

REQUEST_FAILURES = (
    requests.exceptions.HTTPError,
    requests.exceptions.Timeout,
    requests.exceptions.ConnectionError,
    requests.exceptions.RequestException,
    JSONDecodeError,
    ValueError,
)


class PlayerHistoryApiError(RuntimeError):
    pass


def et_today() -> pd.Timestamp:
    if os.environ.get("WNBA_SELECTED_SLATE_DATE"):
        return pd.Timestamp(os.environ["WNBA_SELECTED_SLATE_DATE"]).tz_localize("America/New_York").normalize()
    if TODAY_OVERRIDE:
        return pd.Timestamp(TODAY_OVERRIDE).tz_localize("America/New_York").normalize()
    return pd.Timestamp.now(tz="America/New_York").normalize()


def date_tag() -> str:
    return et_today().strftime("%Y%m%d")


def report_path() -> Path:
    return RAW_DIR / f"wnba_history_backfill_report_{date_tag()}.csv"


def backup_path() -> Path:
    return RAW_DIR / f"wnba_player_games_backfilled_{date_tag()}.csv"


def strip_accents(value: object) -> str:
    text = "".join(c for c in unicodedata.normalize("NFKD", str(value)) if not unicodedata.combining(c))
    return canonicalize_name(text)


def parse_numeric(value: object) -> float:
    return pd.to_numeric(value, errors="coerce")


def parse_made_attempted(value: object) -> tuple[float, float]:
    text = str(value or "").strip()
    if "-" not in text:
        return float("nan"), float("nan")
    made, attempted = text.split("-", 1)
    return parse_numeric(made), parse_numeric(attempted)


def fetch_json(session: requests.Session, url: str) -> dict:
    try:
        response = session.get(url, timeout=30)
        response.raise_for_status()
        time.sleep(REQUEST_SLEEP_SECONDS)
        return response.json()
    except REQUEST_FAILURES as exc:
        raise PlayerHistoryApiError(f"{type(exc).__name__}: {exc}") from exc


def regular_categories(payload: dict) -> list[dict]:
    categories: list[dict] = []
    for season_type in payload.get("seasonTypes", []) or []:
        display = str(season_type.get("displayName", ""))
        if "Postseason" in display or "Preseason" in display:
            continue
        if "Regular Season" not in display and not display.endswith("Season"):
            continue
        categories.extend(season_type.get("categories", []) or [])
    return categories


def source_league(payload: dict, default: str) -> str:
    for item in payload.get("filters", []) or []:
        if item.get("name") == "league" and item.get("value"):
            return str(item["value"])
    return default


def stat_value(stats: list[object], label_index: dict[str, int], label: str) -> float:
    index = label_index.get(label)
    if index is None or index >= len(stats):
        return float("nan")
    return parse_numeric(stats[index])


def pair_value(stats: list[object], label_index: dict[str, int], label: str) -> tuple[float, float]:
    index = label_index.get(label)
    if index is None or index >= len(stats):
        return float("nan"), float("nan")
    return parse_made_attempted(stats[index])


def canonical_slate_teams(schedule: pd.DataFrame) -> tuple[pd.Timestamp, set[str]]:
    if schedule.empty:
        raise RuntimeError("Canonical schedule is empty; cannot auto-backfill live players.")
    date_col = next((col for col in schedule.columns if str(col).lower() in {"game_date", "date"}), None)
    if not date_col:
        raise RuntimeError(f"Canonical schedule missing game_date/date column: {list(schedule.columns)}")
    dates = pd.to_datetime(schedule[date_col], errors="coerce").dropna()
    if dates.empty:
        raise RuntimeError("Canonical schedule has no valid dates.")
    slate_date = dates.min().normalize()
    teams: set[str] = set()
    for col in ["home_team", "away_team"]:
        if col in schedule.columns:
            teams.update(schedule[col].dropna().astype(str).map(standardize_team_abbrev))
    teams = {team for team in teams if team}
    if not teams:
        raise RuntimeError("Canonical schedule has no teams.")
    return slate_date, teams


def live_line_players_on_slate(lines: pd.DataFrame, slate_teams: set[str]) -> pd.DataFrame:
    if lines.empty:
        return pd.DataFrame(columns=["player_name", "team", "player_key", "source"])
    frame = lines.copy()
    if "team" not in frame.columns or "player_name" not in frame.columns:
        return pd.DataFrame(columns=["player_name", "team", "player_key", "source"])
    if "_data_source" in frame.columns:
        frame = frame[frame["_data_source"].astype(str).str.lower() == "api:prizepicks"].copy()
    frame["team"] = frame["team"].map(standardize_team_abbrev)
    frame["player_name"] = frame["player_name"].astype(str).str.strip()
    frame["player_key"] = frame["player_name"].map(canonicalize_name)
    frame = frame[frame["team"].isin(slate_teams)].copy()
    frame["source"] = "api:espn:wnba:gamelog"
    return frame[["player_name", "team", "player_key", "source"]].drop_duplicates().reset_index(drop=True)


def existing_history_keys(history: pd.DataFrame) -> set[str]:
    if history.empty:
        return set()
    if "player_key" in history.columns:
        return set(history["player_key"].dropna().astype(str))
    if "player_name" in history.columns:
        return set(history["player_name"].map(canonicalize_name))
    return set()


def fetch_team_id_map(session: requests.Session, slate_date: pd.Timestamp) -> dict[str, str]:
    url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard?dates={slate_date.strftime('%Y%m%d')}"
    try:
        data = fetch_json(session, url)
    except PlayerHistoryApiError:
        return {}
    mapping: dict[str, str] = {}
    for event in data.get("events", []) or []:
        comp = (event.get("competitions") or [{}])[0]
        for competitor in comp.get("competitors", []) or []:
            team = competitor.get("team", {}) or {}
            abbrev = standardize_team_abbrev(team.get("abbreviation", ""))
            team_id = str(team.get("id", "")).strip()
            if abbrev and team_id:
                mapping[abbrev] = team_id
    return mapping


def build_roster_lookup(session: requests.Session, team_ids: dict[str, str]) -> dict[tuple[str, str], dict]:
    lookup: dict[tuple[str, str], dict] = {}
    for team, team_id in sorted(team_ids.items()):
        url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/teams/{team_id}/roster"
        try:
            data = fetch_json(session, url)
        except PlayerHistoryApiError:
            continue
        for athlete in data.get("athletes", []) or []:
            name = str(athlete.get("displayName", "")).strip()
            if not name:
                continue
            payload = {
                "athlete_id": str(athlete.get("id", "")).strip(),
                "player_name": name,
                "position": ((athlete.get("position") or {}).get("abbreviation") or "").strip(),
            }
            lookup[(team, canonicalize_name(name))] = payload
            lookup[(team, strip_accents(name))] = payload
    return lookup


def fetch_game_logs_for_league(
    session: requests.Session,
    player_name: str,
    current_team: str,
    league: str,
    athlete_id: str,
) -> list[dict]:
    rows: list[dict] = []
    for season in SEASONS:
        url = (
            "https://site.web.api.espn.com/apis/common/v3/sports/basketball/"
            f"{league}/athletes/{athlete_id}/gamelog?season={season}"
        )
        payload = fetch_json(session, url)
        labels = [str(label).upper() for label in payload.get("labels", []) or []]
        if not labels:
            continue

        label_index = {label: index for index, label in enumerate(labels)}
        events = payload.get("events", {}) or {}
        actual_source = f"api:espn:{source_league(payload, league)}:gamelog"
        for category in regular_categories(payload):
            for event_row in category.get("events", []) or []:
                stats = event_row.get("stats", []) or []
                event_id = str(event_row.get("eventId", ""))
                event = events.get(event_id, {}) or {}
                game_date = pd.to_datetime(event.get("gameDate"), errors="coerce")
                if pd.isna(game_date):
                    continue

                fgm, fga = pair_value(stats, label_index, "FG")
                threes_made, _threes_attempted = pair_value(stats, label_index, "3PT")
                ftm, fta = pair_value(stats, label_index, "FT")
                at_vs = str(event.get("atVs", "@"))

                rows.append(
                    {
                        "game_date": game_date.date().isoformat(),
                        "season": int(season),
                        "player_name": player_name,
                        "team": standardize_team_abbrev(current_team),
                        "opponent": standardize_team_abbrev((event.get("opponent") or {}).get("abbreviation", "")),
                        "home_away": "A" if at_vs == "@" else "H",
                        "minutes": stat_value(stats, label_index, "MIN"),
                        "points": stat_value(stats, label_index, "PTS"),
                        "rebounds": stat_value(stats, label_index, "REB"),
                        "assists": stat_value(stats, label_index, "AST"),
                        "threes_made": threes_made,
                        "steals": stat_value(stats, label_index, "STL"),
                        "blocks": stat_value(stats, label_index, "BLK"),
                        "turnovers": stat_value(stats, label_index, "TO"),
                        "fga": fga,
                        "fgm": fgm,
                        "fta": fta,
                        "ftm": ftm,
                        "offensive_rebounds": float("nan"),
                        "defensive_rebounds": float("nan"),
                        "plus_minus": float("nan"),
                        "player_key": canonicalize_name(player_name),
                        "is_home": 0 if at_vs == "@" else 1,
                        "_data_source": actual_source,
                    }
                )
    return rows


def fetch_game_logs(session: requests.Session, player_name: str, current_team: str, athlete_id: str) -> tuple[list[dict], str, str]:
    try:
        rows = fetch_game_logs_for_league(session, player_name, current_team, "wnba", athlete_id)
    except PlayerHistoryApiError as exc:
        return [], "wnba", f"api_error:{exc}"
    if rows:
        return rows, "wnba", "backfilled"
    try:
        fallback_rows = fetch_game_logs_for_league(session, player_name, current_team, "womens-college-basketball", athlete_id)
    except PlayerHistoryApiError as exc:
        return [], "womens-college-basketball", f"api_error:{exc}"
    if fallback_rows:
        return fallback_rows, "womens-college-basketball", "backfilled"
    return [], "none", "no_history_found"


def rebuild_history(existing: pd.DataFrame, fetched: pd.DataFrame) -> pd.DataFrame:
    if fetched.empty:
        return existing.copy()
    fetched_keys = set(fetched["player_key"].dropna().astype(str))
    if "player_key" in existing.columns:
        kept = existing[~existing["player_key"].astype(str).isin(fetched_keys)].copy()
    else:
        kept = existing[~existing["player_name"].map(canonicalize_name).isin(fetched_keys)].copy()
    rebuilt = pd.concat([kept, fetched.reindex(columns=existing.columns)], ignore_index=True)
    dedupe_columns = [column for column in ["game_date", "player_key", "player_name", "team", "opponent"] if column in rebuilt.columns]
    sort_columns = [column for column in ["player_key", "player_name", "game_date", "team", "opponent"] if column in rebuilt.columns]
    rebuilt = rebuilt.drop_duplicates(subset=dedupe_columns, keep="last")
    return rebuilt.sort_values(sort_columns).reset_index(drop=True)


def ensure_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    frame = df.copy()
    for column in columns:
        if column not in frame.columns:
            frame[column] = pd.NA
    return frame[columns]


def main() -> None:
    logger = setup_logging("auto_backfill_wnba_live_players")

    schedule = pd.read_csv(CANONICAL_SCHEDULE_TODAY_PATH)
    slate_date, slate_teams = canonical_slate_teams(schedule)

    raw_lines = pd.read_csv(RAW_SPORTSBOOK_LINES_PATH)
    live_players = live_line_players_on_slate(raw_lines, slate_teams)
    if live_players.empty:
        report = pd.DataFrame(columns=REPORT_COLUMNS)
        report.to_csv(report_path(), index=False)
        logger.info("No canonical-slate live-line players to auto-backfill.")
        print("No canonical-slate live-line players to auto-backfill.")
        return

    history = pd.read_csv(CANONICAL_PLAYER_GAMES_PATH)
    history_raw = pd.read_csv(RAW_PLAYER_GAMES_PATH)
    known_keys = existing_history_keys(history)
    missing = live_players[~live_players["player_key"].isin(known_keys)].copy()

    if missing.empty:
        report = live_players.assign(
            had_history_before=True,
            rows_added=0,
            league_used="existing_history",
            athlete_id="",
            resolution_status="already_present",
        )
        report = ensure_columns(report, REPORT_COLUMNS)
        report.to_csv(report_path(), index=False)
        logger.info("Auto-backfill: all %d canonical-slate live-line players already have history.", len(live_players))
        print(f"Auto-backfill: all {len(live_players)} canonical-slate live-line players already have history.")
        return

    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    team_ids = fetch_team_id_map(session, slate_date)
    unresolved_team_ids = sorted(team for team in slate_teams if team not in team_ids)
    if unresolved_team_ids:
        logger.warning("Auto-backfill could not resolve ESPN team ids; continuing where history already exists: %s", unresolved_team_ids)
    roster_lookup = build_roster_lookup(session, {team: team_ids[team] for team in slate_teams})

    report_rows: list[dict] = []
    fetched_rows: list[dict] = []
    unresolved_names: list[str] = []

    for _, player in missing.sort_values(["team", "player_name"]).iterrows():
        player_name = str(player["player_name"])
        team = str(player["team"])
        player_key = str(player["player_key"])
        roster_match = roster_lookup.get((team, player_key)) or roster_lookup.get((team, strip_accents(player_name)))
        athlete_id = roster_match.get("athlete_id", "") if roster_match else ""
        if not athlete_id:
            unresolved_names.append(player_name)
            report_rows.append(
                {
                    "player_name": player_name,
                    "team": team,
                    "had_history_before": False,
                    "rows_added": 0,
                    "source": "api:espn:wnba:gamelog",
                    "league_used": "none",
                    "athlete_id": "",
                    "resolution_status": "api_error" if team in unresolved_team_ids else "no_history_found",
                }
            )
            continue

        rows, league_used, resolution_status = fetch_game_logs(session, player_name, team, athlete_id)
        if not rows:
            unresolved_names.append(player_name)
            report_rows.append(
                {
                    "player_name": player_name,
                    "team": team,
                    "had_history_before": False,
                    "rows_added": 0,
                    "source": "api:espn:wnba:gamelog",
                    "league_used": league_used,
                    "athlete_id": athlete_id,
                    "resolution_status": "api_error" if resolution_status.startswith("api_error") else "no_history_found",
                }
            )
            continue

        fetched_rows.extend(rows)
        report_rows.append(
            {
                "player_name": player_name,
                "team": team,
                "had_history_before": False,
                "rows_added": len(rows),
                "source": "api:espn:wnba:gamelog",
                "league_used": league_used,
                "athlete_id": athlete_id,
                "resolution_status": "backfilled",
            }
        )

    report = ensure_columns(pd.DataFrame(report_rows), REPORT_COLUMNS)
    report.to_csv(report_path(), index=False)

    fetched = ensure_columns(pd.DataFrame(fetched_rows), PLAYER_GAME_COLUMNS)
    rebuilt = rebuild_history(history, fetched)
    rebuilt_raw = rebuild_history(history_raw, fetched)

    rebuilt.to_csv(CANONICAL_PLAYER_GAMES_PATH, index=False)
    rebuilt_raw.to_csv(RAW_PLAYER_GAMES_PATH, index=False)
    shutil.copy2(CANONICAL_PLAYER_GAMES_PATH, backup_path())

    refreshed_keys = existing_history_keys(pd.read_csv(CANONICAL_PLAYER_GAMES_PATH))
    remaining = missing[~missing["player_key"].isin(refreshed_keys)].copy()
    supportable = live_players[live_players["player_key"].isin(refreshed_keys)].copy()
    supportable_teams = set(supportable["team"].dropna().astype(str))
    unsupported_teams = sorted(slate_teams - supportable_teams)

    if unsupported_teams:
        logger.warning("Auto-backfill has no supportable live-line history for scheduled teams: %s", unsupported_teams)
        print(f"Auto-backfill warning: missing_supportable_teams={unsupported_teams}")

    if not remaining.empty:
        missing_list = remaining[["player_name", "team"]].drop_duplicates().to_dict("records")
        logger.warning("Auto-backfill could not resolve some players; continuing with exclusions: %s", missing_list)
        print(f"Auto-backfill unresolved players excluded: {missing_list}")

    logger.info(
        "Auto-backfill complete for %d missing canonical-slate live-line players. rows_added=%d unresolved=%d backup=%s report=%s",
        len(missing),
        len(fetched),
        len(remaining),
        backup_path(),
        report_path(),
    )
    print(
        f"Auto-backfill complete. missing_players={len(missing)} rows_added={len(fetched)} unresolved={len(remaining)} "
        f"backup={backup_path().name} report={report_path().name}"
    )


if __name__ == "__main__":
    main()
