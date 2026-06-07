from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from wnba_model_config import (
    CANONICAL_PLAYER_GAMES_PATH,
    CANONICAL_TEAM_CONTEXT_PATH,
    RAW_PLAYER_GAMES_PATH,
    RAW_TEAM_CONTEXT_PATH,
)
from wnba_model_utils import canonicalize_name, setup_logging, standardize_team_abbrev


ET = ZoneInfo("America/New_York")
SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard"
SUMMARY_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/summary?event={event_id}"
REQUEST_HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
PLAYER_COLUMNS = [
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
TEAM_COLUMNS = [
    "game_date",
    "team",
    "opponent",
    "pace",
    "off_rating",
    "def_rating",
    "team_points",
    "opp_points",
    "team_rebounds",
    "team_assists",
    "team_threes_made",
    "_data_source",
]


def fetch_json(url: str) -> dict:
    request = urllib.request.Request(url, headers=REQUEST_HEADERS)
    with urllib.request.urlopen(request, timeout=25) as response:
        return json.loads(response.read().decode("utf-8"))


def today_et() -> pd.Timestamp:
    override = os.environ.get("WNBA_TODAY_OVERRIDE")
    if override:
        return pd.Timestamp(override).tz_localize(ET).normalize()
    return pd.Timestamp.now(tz=ET).normalize()


def date_range_from_env() -> tuple[pd.Timestamp, pd.Timestamp]:
    end = pd.Timestamp(os.environ.get("WNBA_ACTUALS_END_DATE") or today_et().date()).tz_localize(ET).normalize()
    if os.environ.get("WNBA_ACTUALS_START_DATE"):
        start = pd.Timestamp(os.environ["WNBA_ACTUALS_START_DATE"]).tz_localize(ET).normalize()
    else:
        days = int(os.environ.get("WNBA_ACTUALS_DAYS", "30"))
        start = end - pd.Timedelta(days=days - 1)
    return start, end


def parse_number(value: object) -> float:
    return pd.to_numeric(value, errors="coerce")


def parse_minutes(value: object) -> float:
    text = str(value or "").strip()
    if not text:
        return float("nan")
    if ":" in text:
        minutes, seconds = text.split(":", 1)
        return float(parse_number(minutes) or 0) + float(parse_number(seconds) or 0) / 60.0
    return float(parse_number(text))


def parse_made_attempted(value: object) -> tuple[float, float]:
    text = str(value or "").strip()
    if "-" not in text:
        return float("nan"), float("nan")
    made, attempted = text.split("-", 1)
    return parse_number(made), parse_number(attempted)


def scoreboard_events_for_date(game_date: pd.Timestamp) -> list[dict]:
    url = f"{SCOREBOARD_URL}?dates={game_date.strftime('%Y%m%d')}"
    data = fetch_json(url)
    return data.get("events", []) or []


def event_context(event: dict) -> tuple[str, str, str, bool]:
    competition = (event.get("competitions") or [{}])[0]
    status_type = (competition.get("status") or {}).get("type") or {}
    completed = bool(status_type.get("completed"))
    event_date = pd.to_datetime(event.get("date"), utc=True, errors="coerce")
    if pd.isna(event_date):
        game_date = ""
    else:
        game_date = event_date.tz_convert(ET).date().isoformat()
    home = ""
    away = ""
    for competitor in competition.get("competitors", []) or []:
        abbrev = standardize_team_abbrev((competitor.get("team") or {}).get("abbreviation"))
        if competitor.get("homeAway") == "home":
            home = abbrev
        elif competitor.get("homeAway") == "away":
            away = abbrev
    return game_date, home, away, completed


def parse_event_boxscore(event: dict) -> tuple[list[dict], list[dict]]:
    event_id = str(event.get("id", ""))
    game_date, home, away, completed = event_context(event)
    if not event_id or not game_date or not home or not away or not completed:
        return [], []
    data = fetch_json(SUMMARY_URL.format(event_id=event_id))
    player_rows: list[dict] = []
    for team_block in (data.get("boxscore") or {}).get("players", []) or []:
        team = standardize_team_abbrev((team_block.get("team") or {}).get("abbreviation"))
        if not team:
            continue
        opponent = away if team == home else home
        home_away = "H" if team == home else "A"
        stat_groups = team_block.get("statistics") or []
        if not stat_groups:
            continue
        labels = [str(label).upper() for label in stat_groups[0].get("labels", []) or []]
        label_index = {label: idx for idx, label in enumerate(labels)}
        for athlete in stat_groups[0].get("athletes", []) or []:
            athlete_info = athlete.get("athlete") or {}
            player_name = str(athlete_info.get("displayName") or "").strip()
            if not player_name:
                continue
            stats = athlete.get("stats") or []
            def stat(label: str):
                idx = label_index.get(label)
                if idx is None or idx >= len(stats):
                    return float("nan")
                return stats[idx]
            fgm, fga = parse_made_attempted(stat("FG"))
            threes_made, _ = parse_made_attempted(stat("3PT"))
            ftm, fta = parse_made_attempted(stat("FT"))
            row = {
                "game_date": game_date,
                "season": int(str(game_date)[:4]),
                "player_name": player_name,
                "team": team,
                "opponent": opponent,
                "home_away": home_away,
                "minutes": parse_minutes(stat("MIN")),
                "points": parse_number(stat("PTS")),
                "rebounds": parse_number(stat("REB")),
                "assists": parse_number(stat("AST")),
                "threes_made": threes_made,
                "steals": parse_number(stat("STL")),
                "blocks": parse_number(stat("BLK")),
                "turnovers": parse_number(stat("TO")),
                "fga": fga,
                "fgm": fgm,
                "fta": fta,
                "ftm": ftm,
                "offensive_rebounds": parse_number(stat("OREB")),
                "defensive_rebounds": parse_number(stat("DREB")),
                "plus_minus": parse_number(stat("+/-")),
                "player_key": canonicalize_name(player_name),
                "is_home": 1 if home_away == "H" else 0,
                "_data_source": "api:espn_boxscore",
            }
            player_rows.append(row)
    team_rows = build_team_rows(player_rows)
    return player_rows, team_rows


def build_team_rows(player_rows: list[dict]) -> list[dict]:
    if not player_rows:
        return []
    frame = pd.DataFrame(player_rows)
    rows: list[dict] = []
    for (game_date, team, opponent), group in frame.groupby(["game_date", "team", "opponent"], dropna=False):
        opp = frame[(frame["game_date"] == game_date) & (frame["team"] == opponent)]
        rows.append(
            {
                "game_date": game_date,
                "team": team,
                "opponent": opponent,
                "pace": pd.NA,
                "off_rating": pd.NA,
                "def_rating": pd.NA,
                "team_points": pd.to_numeric(group["points"], errors="coerce").sum(),
                "opp_points": pd.to_numeric(opp["points"], errors="coerce").sum() if not opp.empty else pd.NA,
                "team_rebounds": pd.to_numeric(group["rebounds"], errors="coerce").sum(),
                "team_assists": pd.to_numeric(group["assists"], errors="coerce").sum(),
                "team_threes_made": pd.to_numeric(group["threes_made"], errors="coerce").sum(),
                "_data_source": "api:espn_boxscore",
            }
        )
    return rows


def load_existing(path: Path, columns: list[str]) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=columns)
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame(columns=columns)


def append_dedup(existing: pd.DataFrame, new_rows: pd.DataFrame, subset: list[str], columns: list[str]) -> pd.DataFrame:
    combined = pd.concat([existing, new_rows], ignore_index=True, sort=False)
    if combined.empty:
        return pd.DataFrame(columns=columns)
    combined["game_date"] = pd.to_datetime(combined["game_date"], errors="coerce").dt.date.astype(str)
    if "player_name" in combined.columns:
        combined["player_name"] = combined["player_name"].astype(str).str.strip()
        combined["player_key"] = combined["player_name"].map(canonicalize_name)
    for col in ["team", "opponent"]:
        if col in combined.columns:
            combined[col] = combined[col].map(standardize_team_abbrev)
    combined = combined.drop_duplicates(subset=subset, keep="last")
    for col in columns:
        if col not in combined.columns:
            combined[col] = pd.NA
    return combined.reindex(columns=[*columns, *[c for c in combined.columns if c not in columns]])


def fetch_recent_actuals() -> dict:
    logger = setup_logging("fetch_wnba_espn_actuals")
    start, end = date_range_from_env()
    player_rows: list[dict] = []
    team_rows: list[dict] = []
    events_seen = 0
    events_completed = 0
    dates = pd.date_range(start.date(), end.date(), freq="D")
    for day in dates:
        try:
            events = scoreboard_events_for_date(pd.Timestamp(day))
        except Exception as exc:
            logger.warning("ESPN WNBA scoreboard fetch failed for %s: %s", day.date(), exc)
            continue
        for event in events:
            events_seen += 1
            _, _, _, completed = event_context(event)
            if not completed:
                continue
            try:
                players, teams = parse_event_boxscore(event)
            except Exception as exc:
                logger.warning("ESPN WNBA summary fetch failed for event %s: %s", event.get("id"), exc)
                continue
            if players:
                events_completed += 1
                player_rows.extend(players)
                team_rows.extend(teams)
    new_players = pd.DataFrame(player_rows)
    new_teams = pd.DataFrame(team_rows)
    if new_players.empty:
        raise RuntimeError(f"No completed ESPN WNBA actuals were fetched for {start.date()} through {end.date()}")
    player_existing = load_existing(CANONICAL_PLAYER_GAMES_PATH, PLAYER_COLUMNS)
    player_combined = append_dedup(player_existing, new_players, ["game_date", "player_key", "team", "opponent"], PLAYER_COLUMNS)
    player_combined.to_csv(CANONICAL_PLAYER_GAMES_PATH, index=False)
    RAW_PLAYER_GAMES_PATH.parent.mkdir(parents=True, exist_ok=True)
    player_combined.to_csv(RAW_PLAYER_GAMES_PATH, index=False)
    team_existing = load_existing(CANONICAL_TEAM_CONTEXT_PATH, TEAM_COLUMNS)
    team_combined = append_dedup(team_existing, new_teams, ["game_date", "team", "opponent"], TEAM_COLUMNS)
    team_combined.to_csv(CANONICAL_TEAM_CONTEXT_PATH, index=False)
    RAW_TEAM_CONTEXT_PATH.parent.mkdir(parents=True, exist_ok=True)
    team_combined.to_csv(RAW_TEAM_CONTEXT_PATH, index=False)
    payload = {
        "source": "api:espn_boxscore",
        "start_date": str(start.date()),
        "end_date": str(end.date()),
        "events_seen": events_seen,
        "completed_events_ingested": events_completed,
        "player_rows_fetched": int(len(new_players)),
        "team_rows_fetched": int(len(new_teams)),
        "player_rows_total": int(len(player_combined)),
        "team_rows_total": int(len(team_combined)),
        "latest_actual_date": str(pd.to_datetime(player_combined["game_date"], errors="coerce").max().date()),
    }
    report_path = CANONICAL_PLAYER_GAMES_PATH.parent / "wnba_espn_actuals_manifest.json"
    report_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    logger.info("ESPN WNBA actuals updated: %s", payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return payload


def main() -> None:
    fetch_recent_actuals()


if __name__ == "__main__":
    main()
