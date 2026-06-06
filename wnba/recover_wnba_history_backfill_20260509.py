from __future__ import annotations

import time
import unicodedata
from pathlib import Path

import pandas as pd
import requests


BASE_DIR = Path(__file__).resolve().parent
RAW_DIR = BASE_DIR / "data" / "raw"
REPORT_PATH = RAW_DIR / "wnba_history_backfill_report_20260509.csv"
PLAYER_GAMES_PATH = RAW_DIR / "wnba_player_games.csv"
PLAYER_GAMES_RAW_PATH = RAW_DIR / "wnba_player_games_raw.csv"
BACKFILLED_PATH = RAW_DIR / "wnba_player_games_backfilled_20260509.csv"

SEASONS = (2025, 2024, 2023)
SOURCE_TO_LEAGUE = {
    "api:espn:wnba:gamelog": "wnba",
    "api:espn:womens-college-basketball:gamelog": "womens-college-basketball",
}
TEAM_STANDARD = {
    "NY": "NYL",
    "WSH": "WAS",
    "GS": "GSV",
    "LV": "LVA",
    "LA": "LAS",
    "CONN": "CON",
}
REQUIRED_TEAMS = {"ATL", "CHI", "DAL", "IND", "LVA", "MIN", "PHX", "POR"}


def canonicalize_name(value: object) -> str:
    if pd.isna(value):
        return ""
    return " ".join(str(value).replace(".", " ").replace(",", " ").lower().split())


def strip_accents(value: object) -> str:
    text = "".join(c for c in unicodedata.normalize("NFKD", str(value)) if not unicodedata.combining(c))
    return " ".join(text.replace(".", " ").replace(",", " ").lower().split())


def standardize_team(value: object) -> str:
    token = str(value).strip().upper()
    return TEAM_STANDARD.get(token, token)


def parse_numeric(value: object) -> float:
    return pd.to_numeric(value, errors="coerce")


def parse_made_attempted(value: object) -> tuple[float, float]:
    text = str(value or "").strip()
    if "-" not in text:
        return float("nan"), float("nan")
    made, attempted = text.split("-", 1)
    return parse_numeric(made), parse_numeric(attempted)


def fetch_json(session: requests.Session, url: str) -> dict:
    response = session.get(url, timeout=30)
    response.raise_for_status()
    time.sleep(0.08)
    return response.json()


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
                        "team": standardize_team(current_team),
                        "opponent": standardize_team((event.get("opponent") or {}).get("abbreviation", "")),
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


def fetch_game_logs(
    session: requests.Session,
    player_name: str,
    current_team: str,
    source: str,
    athlete_id: str,
) -> tuple[list[dict], str]:
    primary_league = SOURCE_TO_LEAGUE.get(source)
    if not primary_league:
        raise ValueError(f"Unsupported source for {player_name}: {source}")

    rows = fetch_game_logs_for_league(session, player_name, current_team, primary_league, athlete_id)
    if rows:
        return rows, primary_league

    if primary_league == "wnba":
        fallback_league = "womens-college-basketball"
        fallback_rows = fetch_game_logs_for_league(session, player_name, current_team, fallback_league, athlete_id)
        if fallback_rows:
            return fallback_rows, fallback_league
    return rows, primary_league


def report_players(report: pd.DataFrame) -> pd.DataFrame:
    required = ["player_name", "team", "source", "athlete_id"]
    missing = [column for column in required if column not in report.columns]
    if missing:
        raise ValueError(f"Backfill report missing required columns: {missing}")

    players = report[required].dropna(subset=["player_name", "source", "athlete_id"]).copy()
    players["player_key"] = players["player_name"].map(canonicalize_name)
    players["team"] = players["team"].map(standardize_team)
    players["athlete_id"] = players["athlete_id"].astype(str).str.replace(r"\.0$", "", regex=True)
    return players.drop_duplicates("player_key", keep="last")


def rebuild_history(existing: pd.DataFrame, fetched: pd.DataFrame, target_keys: set[str]) -> pd.DataFrame:
    keys = existing["player_name"].map(canonicalize_name) if "player_name" in existing.columns else pd.Series(dtype=str)
    kept = existing[~keys.isin(target_keys)].copy()
    rebuilt = pd.concat([kept, fetched.reindex(columns=existing.columns)], ignore_index=True)
    dedupe_columns = [column for column in ["game_date", "player_key", "player_name", "team", "opponent"] if column in rebuilt.columns]
    sort_columns = [column for column in ["player_key", "player_name", "game_date", "team", "opponent"] if column in rebuilt.columns]
    rebuilt = rebuilt.drop_duplicates(subset=dedupe_columns, keep="last")
    return rebuilt.sort_values(sort_columns).reset_index(drop=True)


def main() -> None:
    report = report_players(pd.read_csv(REPORT_PATH))
    existing = pd.read_csv(PLAYER_GAMES_PATH)
    existing_raw = pd.read_csv(PLAYER_GAMES_RAW_PATH)

    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "application/json"})

    rows: list[dict] = []
    summary_rows: list[dict] = []
    for _, player in report.iterrows():
        player_rows, league_used = fetch_game_logs(
            session=session,
            player_name=str(player["player_name"]),
            current_team=str(player["team"]),
            source=str(player["source"]),
            athlete_id=str(player["athlete_id"]),
        )
        rows.extend(player_rows)
        summary_rows.append(
            {
                "player_name": player["player_name"],
                "team": player["team"],
                "source": player["source"],
                "league_used": league_used,
                "athlete_id": player["athlete_id"],
                "rows_fetched": len(player_rows),
            }
        )

    fetched = pd.DataFrame(rows)
    if fetched.empty:
        raise RuntimeError("No ESPN game logs were fetched from the backfill report.")

    target_keys = set(report["player_key"])
    rebuilt = rebuild_history(existing, fetched, target_keys)
    rebuilt_raw = rebuild_history(existing_raw, fetched.reindex(columns=existing_raw.columns), target_keys)

    rebuilt.to_csv(PLAYER_GAMES_PATH, index=False)
    rebuilt_raw.to_csv(PLAYER_GAMES_RAW_PATH, index=False)
    rebuilt.to_csv(BACKFILLED_PATH, index=False)

    teams = set(rebuilt["team"].dropna().astype(str).map(standardize_team))
    missing_teams = sorted(REQUIRED_TEAMS - teams)
    if missing_teams:
        raise RuntimeError(f"Backfilled history missing required teams: {missing_teams}")

    print("WNBA history backfill recovery complete.")
    print(f"Report players: {len(report)}")
    print(f"Fetched rows: {len(fetched)}")
    print(f"{PLAYER_GAMES_PATH}: {len(rebuilt)} rows")
    print(f"{PLAYER_GAMES_RAW_PATH}: {len(rebuilt_raw)} rows")
    print(f"{BACKFILLED_PATH}: {len(rebuilt)} rows")
    print(f"Required teams present: {', '.join(sorted(REQUIRED_TEAMS))}")
    print(pd.DataFrame(summary_rows).to_string(index=False))


if __name__ == "__main__":
    main()
