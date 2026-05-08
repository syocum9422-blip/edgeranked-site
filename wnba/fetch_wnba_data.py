from __future__ import annotations

import json
import os
import re
import ssl
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
from bs4 import BeautifulSoup

from wnba_model_config import (
    CANONICAL_PLAYER_GAMES_PATH,
    CANONICAL_PLAYER_POSITIONS_PATH,
    CANONICAL_PLAYER_STATUS_PATH,
    CANONICAL_SCHEDULE_TODAY_PATH,
    CANONICAL_SPORTSBOOK_LINES_PATH,
    CANONICAL_TEAM_CONTEXT_PATH,
    RAW_PLAYER_GAMES_PATH,
    RAW_PLAYER_POSITIONS_PATH,
    RAW_PLAYER_STATUS_PATH,
    RAW_SCHEDULE_TODAY_PATH,
    RAW_SPORTSBOOK_LINES_PATH,
    RAW_TEAM_CONTEXT_PATH,
    TODAY_OVERRIDE,
)
from wnba_model_utils import (
    normalize_player_games,
    normalize_player_status,
    normalize_positions,
    normalize_schedule,
    normalize_sportsbook_lines,
    normalize_team_context,
    setup_logging,
    today_timestamp,
)


# Source mode:
# - auto: try official WNBA stats endpoints first, then fall back to local CSVs
# - api: only use official WNBA stats endpoints
# - csv: only use local CSVs / remote CSV URLs below
SOURCE_MODE = os.getenv("WNBA_SOURCE_MODE", "auto").strip().lower()

# Historical seasons to pull before the 2026 season begins.
# Practical default: use the most recent three completed seasons.
HISTORICAL_SEASONS = ["2023", "2024", "2025"]
SEASON_TYPE = "Regular Season"
LEAGUE_ID = "10"

# Optional remote CSV sources. Keep as None unless you have a direct file URL.
PLAYER_GAMES_URL: Optional[str] = None
TEAM_CONTEXT_URL: Optional[str] = None
SCHEDULE_TODAY_URL: Optional[str] = None
SPORTSBOOK_LINES_URL: Optional[str] = None
PLAYER_POSITIONS_URL: Optional[str] = None
PLAYER_STATUS_URL: Optional[str] = None

API_BASE = "https://stats.wnba.com/stats"
API_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://www.wnba.com/",
    "Origin": "https://www.wnba.com",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}
REQUEST_TIMEOUT_SECONDS = 30
REQUEST_SLEEP_SECONDS = 0.6

# Connectivity check timeout (shorter than request timeout)
CONNECTIVITY_CHECK_TIMEOUT = 5


def _http_get_json(url: str, logger) -> dict:
    request = urllib.request.Request(url, headers=API_HEADERS)
    context = ssl.create_default_context()
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS, context=context) as response:
        payload = response.read().decode("utf-8")
    logger.info("Fetched %s", url)
    time.sleep(REQUEST_SLEEP_SECONDS)
    return json.loads(payload)


def _check_api_reachable(logger) -> bool:
    """Quick connectivity check for stats.wnba.com API endpoint. Returns True if reachable."""
    try:
        # Test a lightweight endpoint: leaguegamelog with minimal params
        params = {
            "Counter": 0,
            "Direction": "ASC",
            "LeagueID": LEAGUE_ID,
            "PlayerOrTeam": "P",
            "Season": "2025",
            "SeasonType": SEASON_TYPE,
            "Sorter": "DATE",
        }
        url = _build_url("leaguegamelog", params)
        request = urllib.request.Request(url, headers=API_HEADERS)
        context = ssl.create_default_context()
        with urllib.request.urlopen(request, timeout=CONNECTIVITY_CHECK_TIMEOUT, context=context) as response:
            return response.status == 200
    except Exception as exc:
        logger.debug("stats.wnba.com API not reachable: %s", exc)
        return False


def _result_set_to_frame(payload: dict, desired_name: Optional[str] = None) -> pd.DataFrame:
    if "resultSets" in payload:
        result_sets = payload["resultSets"]
        if isinstance(result_sets, dict):
            result_sets = [result_sets]
        for result in result_sets:
            if desired_name is None or result.get("name") == desired_name:
                return pd.DataFrame(result.get("rowSet", []), columns=result.get("headers", []))
    if "resultSet" in payload:
        result = payload["resultSet"]
        return pd.DataFrame(result.get("rowSet", []), columns=result.get("headers", []))
    return pd.DataFrame()


def _build_url(endpoint: str, params: dict) -> str:
    return f"{API_BASE}/{endpoint}?{urllib.parse.urlencode(params)}"


def fetch_api_player_games(logger) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for season in HISTORICAL_SEASONS:
        params = {
            "Counter": 0,
            "Direction": "DESC",
            "LeagueID": LEAGUE_ID,
            "PlayerOrTeam": "P",
            "Season": season,
            "SeasonType": SEASON_TYPE,
            "Sorter": "DATE",
        }
        url = _build_url("leaguegamelog", params)
        payload = _http_get_json(url, logger)
        frame = _result_set_to_frame(payload)
        if frame.empty:
            logger.warning("No player game logs returned for season %s", season)
            continue
        frame["season"] = season
        frames.append(frame)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def fetch_api_team_context(logger) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for season in HISTORICAL_SEASONS:
        params = {
            "Counter": 0,
            "Direction": "DESC",
            "LeagueID": LEAGUE_ID,
            "PlayerOrTeam": "T",
            "Season": season,
            "SeasonType": SEASON_TYPE,
            "Sorter": "DATE",
        }
        url = _build_url("leaguegamelog", params)
        payload = _http_get_json(url, logger)
        frame = _result_set_to_frame(payload)
        if frame.empty:
            logger.warning("No team logs returned for season %s", season)
            continue
        frame["season"] = season
        frames.append(frame)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def fetch_api_schedule_today(logger) -> pd.DataFrame:
    target_date = today_timestamp()
    params = {
        "DayOffset": 0,
        "GameDate": target_date.strftime("%m/%d/%Y"),
        "LeagueID": LEAGUE_ID,
    }
    url = _build_url("scoreboardv2", params)
    payload = _http_get_json(url, logger)
    game_header = _result_set_to_frame(payload, desired_name="GameHeader")
    if game_header.empty:
        logger.warning("No schedule returned for %s", target_date.date())
        return pd.DataFrame(columns=["game_date", "home_team", "away_team", "game_id", "start_time"])

    line_score = _result_set_to_frame(payload, desired_name="LineScore")
    home = line_score[line_score.get("TEAM_CITY_NAME", pd.Series(dtype=str)).notna()].copy() if not line_score.empty else pd.DataFrame()
    if home.empty:
        schedule = pd.DataFrame(
            {
                "game_date": game_header["GAME_DATE_EST"],
                "game_id": game_header["GAME_ID"],
                "home_team": game_header.get("HOME_TEAM_ABBREVIATION"),
                "away_team": game_header.get("VISITOR_TEAM_ABBREVIATION"),
                "start_time": game_header.get("GAME_STATUS_TEXT"),
            }
        )
        return schedule

    lines = line_score[["GAME_ID", "TEAM_ABBREVIATION", "TEAM_ID"]].drop_duplicates()
    schedule_rows = []
    for game_id, group in lines.groupby("GAME_ID"):
        if len(group) != 2:
            continue
        team_abbrevs = list(group["TEAM_ABBREVIATION"])
        header_row = game_header.loc[game_header["GAME_ID"] == game_id].iloc[0]
        schedule_rows.append(
            {
                "game_date": header_row["GAME_DATE_EST"],
                "game_id": game_id,
                "home_team": team_abbrevs[0],
                "away_team": team_abbrevs[1],
                "start_time": header_row.get("GAME_STATUS_TEXT"),
            }
        )
    return pd.DataFrame(schedule_rows)


def fetch_espn_schedule(logger) -> pd.DataFrame:
    """Fetch WNBA schedule from ESPN API as fallback."""
    import requests as req

    url = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard"
    try:
        resp = req.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("ESPN schedule fetch failed: %s", exc)
        return pd.DataFrame()

    events = data.get("events", [])
    if not events:
        logger.warning("ESPN returned no WNBA events for today")
        return pd.DataFrame()

    rows = []
    for event in events:
        event_id = str(event.get("id", ""))
        date_raw = event.get("date", "")

        competitions = event.get("competitions", [])
        if not competitions:
            continue

        # Get competitors from the first (and usually only) competition
        comp = competitions[0]
        competitors = comp.get("competitors", [])
        if len(competitors) < 2:
            continue

        home_abbrev = ""
        away_abbrev = ""
        for c in competitors:
            home_away = c.get("homeAway", "")
            team = c.get("team", {})
            abbrev = team.get("abbreviation", "")
            if home_away == "home":
                home_abbrev = abbrev
            elif home_away == "away":
                away_abbrev = abbrev

        if not home_abbrev or not away_abbrev:
            continue

        # Parse date to YYYY-MM-DD format
        game_date = ""
        try:
            dt = pd.to_datetime(date_raw, utc=True)
            game_date = dt.strftime("%Y-%m-%d")
        except Exception:
            pass

        rows.append({
            "game_date": game_date,
            "home_team": home_abbrev,
            "away_team": away_abbrev,
            "game_id": event_id,
            "start_time": date_raw,
        })

    if not rows:
        logger.warning("ESPN returned WNBA events but could not parse them")
        return pd.DataFrame()

    logger.info("Fetched %d games from ESPN API", len(rows))
    return pd.DataFrame(rows)


ESPN_INJURIES_URL = "https://www.espn.com/wnba/injuries"
ESPN_INJURIES_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _normalize_status_from_css_class(css_class: str) -> str:
    """Map ESPN TextStatus CSS class to model-safe status values."""
    class_lower = css_class.lower()
    if "red" in class_lower:
        return "out"
    if "yellow" in class_lower:
        return "day-to-day"
    if "orange" in class_lower:
        return "doubtful"
    if "green" in class_lower:
        return "probable"
    if "blue" in class_lower:
        return "questionable"
    return "unknown"


def _parse_status_cell(cell_html: str) -> tuple[str, str]:
    """Extract status text and CSS class from a status cell's HTML."""
    # Match TextStatus--xxx pattern
    match = re.search(r'TextStatus--(\w+)', cell_html)
    css_class = match.group(1) if match else ""
    # Extract the text content (status label)
    text_match = re.search(r'plain">([^<]+)<', cell_html)
    status_text = text_match.group(1) if text_match else "unknown"
    return status_text, css_class


def fetch_espn_injuries(logger) -> pd.DataFrame:
    """Fetch WNBA injury data from ESPN.com injuries page via HTML scraping."""
    logger.info("Fetching WNBA injuries from ESPN: %s", ESPN_INJURIES_URL)
    request = urllib.request.Request(ESPN_INJURIES_URL, headers=ESPN_INJURIES_HEADERS)
    context = ssl.create_default_context()
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS, context=context) as response:
        html = response.read().decode("utf-8")
    logger.info("Fetched ESPN injuries page (%d bytes)", len(html))

    soup = BeautifulSoup(html, "html.parser")
    rows = []

    # Find each team section: <div class="Table__league-injuries">...</div>
    for section in soup.find_all("div", class_="Table__league-injuries"):
        # Extract team name from .injuries__teamName span
        team_elem = section.find("span", class_="injuries__teamName")
        team_name = team_elem.get_text(strip=True) if team_elem else ""
        if not team_name:
            continue

        # Find the table within this section
        table = section.find("table", class_="Table")
        if not table:
            continue

        tbody = table.find("tbody")
        if not tbody:
            continue

        for tr in tbody.find_all("tr", recursive=False):
            cells = tr.find_all("td")
            if len(cells) < 4:
                continue

            # Cell 0: player name (may contain <a> tag)
            name_cell = cells[0]
            player_link = name_cell.find("a")
            player_name = player_link.get_text(strip=True) if player_link else name_cell.get_text(strip=True)

            # Cell 1: position
            position = cells[1].get_text(strip=True)

            # Cell 2: estimated return date
            est_return = cells[2].get_text(strip=True)

            # Cell 3: status (contains span with TextStatus class)
            status_cell_html = str(cells[3])
            status_text, css_class = _parse_status_cell(status_cell_html)
            normalized_status = _normalize_status_from_css_class(css_class)

            # Cell 4: comment (optional)
            comment = cells[4].get_text(strip=True) if len(cells) > 4 else ""

            rows.append({
                "player_name": player_name,
                "team": team_name,
                "position": position,
                "est_return_date": est_return,
                "status": normalized_status,
                "status_text": status_text,
                "comment": comment,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "_data_source": "api:espn_injuries",
            })

    logger.info("Parsed %d injury entries from ESPN page", len(rows))
    return pd.DataFrame(rows)


def load_csv_or_url(local_path: Path, remote_url: Optional[str], logger) -> pd.DataFrame:
    if local_path.exists():
        logger.info("Loading local source: %s", local_path)
        return pd.read_csv(local_path)
    if remote_url:
        logger.info("Loading remote CSV source: %s", remote_url)
        return pd.read_csv(remote_url)
    logger.warning("No CSV source configured for %s", local_path.name)
    return pd.DataFrame()


def write_template_if_missing(path: Path, columns: list[str], logger) -> None:
    if path.exists():
        return
    logger.info("Creating template file: %s", path)
    pd.DataFrame(columns=columns).to_csv(path, index=False)


def resolve_player_games(logger) -> tuple[pd.DataFrame, str]:
    """Returns (DataFrame, source_label) where source_label is 'api' or 'csv'."""
    if SOURCE_MODE in {"auto", "api"}:
        if not _check_api_reachable(logger):
            logger.warning("stats.wnba.com is not reachable; skipping API fetch for player games")
            if SOURCE_MODE == "api":
                raise ConnectionError(
                    "WNBA_SOURCE_MODE=api but stats.wnba.com is not reachable. "
                    "Check network connectivity or use WNBA_SOURCE_MODE=csv for offline mode."
                )
        try:
            frame = fetch_api_player_games(logger)
            if not frame.empty:
                logger.info("Player games: fetched %d rows from stats.wnba.com API", len(frame))
                return frame, "api"
        except Exception as exc:
            logger.warning("Official API player log fetch failed: %s", exc)
            if SOURCE_MODE == "api":
                raise
    frame = load_csv_or_url(RAW_PLAYER_GAMES_PATH, PLAYER_GAMES_URL, logger)
    source = "csv"
    if not frame.empty and RAW_PLAYER_GAMES_PATH.exists():
        try:
            with open(RAW_PLAYER_GAMES_PATH) as f:
                first_line = f.readline()
            if "mockbook" in first_line or "generate_mock" in first_line:
                source = "csv:mock"
                logger.warning("Player games loaded from CSV but data appears to be mock/generated")
        except Exception:
            pass
    logger.info("Player games: loaded %d rows from CSV (%s)", len(frame), source)
    return frame, source


def resolve_team_context(logger) -> tuple[pd.DataFrame, str]:
    """Returns (DataFrame, source_label) where source_label is 'api' or 'csv'."""
    if SOURCE_MODE in {"auto", "api"}:
        if not _check_api_reachable(logger):
            logger.warning("stats.wnba.com is not reachable; skipping API fetch for team context")
            if SOURCE_MODE == "api":
                raise ConnectionError(
                    "WNBA_SOURCE_MODE=api but stats.wnba.com is not reachable. "
                    "Check network connectivity or use WNBA_SOURCE_MODE=csv for offline mode."
                )
        try:
            frame = fetch_api_team_context(logger)
            if not frame.empty:
                logger.info("Team context: fetched %d rows from stats.wnba.com API", len(frame))
                return frame, "api"
        except Exception as exc:
            logger.warning("Official API team log fetch failed: %s", exc)
            if SOURCE_MODE == "api":
                raise
    frame = load_csv_or_url(RAW_TEAM_CONTEXT_PATH, TEAM_CONTEXT_URL, logger)
    source = "csv"
    logger.info("Team context: loaded %d rows from CSV (%s)", len(frame), source)
    return frame, source


def resolve_schedule_today(logger) -> tuple[pd.DataFrame, str]:
    """Returns (DataFrame, source_label) where source_label is 'api:stats_wnba', 'api:espn', or 'csv:*'."""
    if SOURCE_MODE in {"auto", "api"}:
        stats_api_reachable = _check_api_reachable(logger)

        if stats_api_reachable:
            try:
                frame = fetch_api_schedule_today(logger)
                if not frame.empty:
                    logger.info("Schedule today: fetched %d rows from stats.wnba.com API", len(frame))
                    return frame, "api:stats_wnba"
            except Exception as exc:
                logger.warning("Official API schedule fetch failed: %s", exc)
                if SOURCE_MODE == "api":
                    raise
        else:
            logger.warning("stats.wnba.com is not reachable; trying ESPN as fallback for schedule")

        # Try ESPN as fallback (both auto and api modes)
        try:
            frame = fetch_espn_schedule(logger)
            if not frame.empty:
                logger.info("Schedule today: fetched %d rows from ESPN API", len(frame))
                return frame, "api:espn"
        except Exception as exc:
            logger.warning("ESPN schedule fetch also failed: %s", exc)
            if SOURCE_MODE == "api":
                raise ConnectionError(
                    "WNBA_SOURCE_MODE=api but both stats.wnba.com and ESPN failed. "
                    "Check network connectivity or use WNBA_SOURCE_MODE=csv for offline mode."
                )

    frame = load_csv_or_url(RAW_SCHEDULE_TODAY_PATH, SCHEDULE_TODAY_URL, logger)
    source = "csv"
    if not frame.empty:
        try:
            with open(RAW_SCHEDULE_TODAY_PATH) as f:
                first_data_line = f.readline()
                for line in f:
                    if "2025-07-05" in line:
                        source = "csv:test_date"
                        logger.warning("Schedule loaded from CSV but contains test date 2025-07-05 (not today's schedule)")
                        break
        except Exception:
            pass
    logger.info("Schedule today: loaded %d rows from CSV (%s)", len(frame), source)
    return frame, source


def resolve_player_status(logger) -> tuple[pd.DataFrame, str]:
    """Returns (DataFrame, source_label) where source_label is 'api:espn_injuries', 'csv:manual', or 'missing:empty_rows'."""
    if SOURCE_MODE in {"auto", "api"}:
        try:
            frame = fetch_espn_injuries(logger)
            if not frame.empty:
                logger.info("Player status: fetched %d rows from ESPN injuries page", len(frame))
                return frame, "api:espn_injuries"
            # Empty response from ESPN is still a valid source (no injuries currently)
            logger.info("Player status: ESPN returned 0 injury entries (off-season or truly no injuries)")
            return frame, "api:espn_injuries"
        except Exception as exc:
            logger.warning("ESPN injuries fetch failed: %s", exc)
            if SOURCE_MODE == "api":
                raise ConnectionError(
                    f"WNBA_SOURCE_MODE=api but ESPN injuries fetch failed: {exc}. "
                    "Check network connectivity or use WNBA_SOURCE_MODE=csv for offline mode."
                )

    # Fall back to CSV
    frame = load_csv_or_url(RAW_PLAYER_STATUS_PATH, PLAYER_STATUS_URL, logger)
    if not frame.empty:
        logger.info("Player status: loaded %d rows from CSV (csv:manual)", len(frame))
        return frame, "csv:manual"

    # Empty CSV - return empty with explicit source label
    logger.warning("Player status: no live source and no CSV data; returning empty frame with source=missing:empty_rows")
    return frame, "missing:empty_rows"


def main() -> None:
    logger = setup_logging("fetch_wnba_data")

    player_games_raw, pg_source = resolve_player_games(logger)
    if player_games_raw.empty:
        raise FileNotFoundError(
            "No WNBA player game log source found. Either leave SOURCE_MODE as 'auto' and allow the official "
            "WNBA stats endpoint to work, or place a file at "
            f"{RAW_PLAYER_GAMES_PATH}."
        )
    player_games = normalize_player_games(player_games_raw)
    player_games["_data_source"] = pg_source
    player_games.to_csv(CANONICAL_PLAYER_GAMES_PATH, index=False)
    logger.info("Saved canonical player games: %s rows [source=%s]", len(player_games), pg_source)

    team_context_raw, tc_source = resolve_team_context(logger)
    team_context = normalize_team_context(team_context_raw)
    team_context["_data_source"] = tc_source
    team_context.to_csv(CANONICAL_TEAM_CONTEXT_PATH, index=False)
    logger.info("Saved canonical team context: %s rows [source=%s]", len(team_context), tc_source)

    schedule_today_raw, st_source = resolve_schedule_today(logger)
    schedule_today = normalize_schedule(schedule_today_raw) if not schedule_today_raw.empty else schedule_today_raw
    if not schedule_today.empty:
        schedule_today["_data_source"] = st_source
    schedule_today.to_csv(CANONICAL_SCHEDULE_TODAY_PATH, index=False)
    logger.info("Saved canonical schedule today: %s rows [source=%s]", len(schedule_today), st_source)

    # Sportsbook lines and player status have no live API fetcher yet; mark as csv:manual
    sportsbook_lines = normalize_sportsbook_lines(load_csv_or_url(RAW_SPORTSBOOK_LINES_PATH, SPORTSBOOK_LINES_URL, logger))
    sportsbook_lines["_data_source"] = "csv:manual"
    sportsbook_lines.to_csv(CANONICAL_SPORTSBOOK_LINES_PATH, index=False)

    player_positions = normalize_positions(load_csv_or_url(RAW_PLAYER_POSITIONS_PATH, PLAYER_POSITIONS_URL, logger))
    player_positions["_data_source"] = "csv:manual"
    player_positions.to_csv(CANONICAL_PLAYER_POSITIONS_PATH, index=False)

    player_status_raw, ps_source = resolve_player_status(logger)
    # Only normalize if we have columns that need renaming; the ESPN fetcher already produces
    # player_name, team, status columns so normalize_player_status handles both cases
    player_status = normalize_player_status(player_status_raw)
    player_status["_data_source"] = ps_source
    player_status.to_csv(CANONICAL_PLAYER_STATUS_PATH, index=False)
    logger.info("Saved canonical player status: %d rows [source=%s]", len(player_status), ps_source)

    write_template_if_missing(
        RAW_PLAYER_GAMES_PATH,
        [
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
        ],
        logger,
    )
    write_template_if_missing(
        RAW_TEAM_CONTEXT_PATH,
        ["game_date", "team", "opponent", "pace", "off_rating", "def_rating", "team_points", "opp_points"],
        logger,
    )
    write_template_if_missing(RAW_SCHEDULE_TODAY_PATH, ["game_date", "home_team", "away_team", "game_id", "start_time"], logger)
    write_template_if_missing(
        RAW_SPORTSBOOK_LINES_PATH,
        ["player_name", "team", "opponent", "stat", "line", "over_odds", "under_odds", "sportsbook"],
        logger,
    )
    write_template_if_missing(RAW_PLAYER_POSITIONS_PATH, ["player_name", "team", "position"], logger)
    write_template_if_missing(RAW_PLAYER_STATUS_PATH, ["player_name", "team", "status"], logger)

    logger.info(
        "Fetch completed. As of %s, the 2026 WNBA regular season has not started yet; official key dates say opening night is May 8, 2026.",
        today_timestamp().date(),
    )


if __name__ == "__main__":
    main()
