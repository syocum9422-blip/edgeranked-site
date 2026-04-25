import os
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from nba_model.settings import GAME_LINES_PATH


EASTERN = ZoneInfo("America/New_York")
ODDS_API_URL = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds"
BOOKMAKERS = "draftkings,fanduel,betmgm,caesars"
TEAM_ABBREVIATIONS = {
    "Atlanta Hawks": "ATL",
    "Boston Celtics": "BOS",
    "Brooklyn Nets": "BKN",
    "Charlotte Hornets": "CHA",
    "Chicago Bulls": "CHI",
    "Cleveland Cavaliers": "CLE",
    "Dallas Mavericks": "DAL",
    "Denver Nuggets": "DEN",
    "Detroit Pistons": "DET",
    "Golden State Warriors": "GSW",
    "Houston Rockets": "HOU",
    "Indiana Pacers": "IND",
    "LA Clippers": "LAC",
    "Los Angeles Clippers": "LAC",
    "Los Angeles Lakers": "LAL",
    "Memphis Grizzlies": "MEM",
    "Miami Heat": "MIA",
    "Milwaukee Bucks": "MIL",
    "Minnesota Timberwolves": "MIN",
    "New Orleans Pelicans": "NOP",
    "New York Knicks": "NYK",
    "Oklahoma City Thunder": "OKC",
    "Orlando Magic": "ORL",
    "Philadelphia 76ers": "PHI",
    "Phoenix Suns": "PHX",
    "Portland Trail Blazers": "POR",
    "Sacramento Kings": "SAC",
    "San Antonio Spurs": "SAS",
    "Toronto Raptors": "TOR",
    "Utah Jazz": "UTA",
    "Washington Wizards": "WAS",
}


def to_et(value):
    ts = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(ts):
        return pd.NaT
    return ts.tz_convert(EASTERN)


def normalize_team(team_name):
    return TEAM_ABBREVIATIONS.get(str(team_name).strip(), "")


def median_or_none(values):
    clean = [float(v) for v in values if v is not None and not pd.isna(v)]
    if not clean:
        return None
    return float(pd.Series(clean).median())


def fetch_payload():
    api_key = os.environ.get("ODDS_API_KEY", "").strip()
    if not api_key:
        print("Skipping game-line fetch: ODDS_API_KEY is not set.")
        return []

    params = {
        "apiKey": api_key,
        "regions": "us",
        "markets": "spreads,totals,h2h",
        "oddsFormat": "american",
        "bookmakers": BOOKMAKERS,
    }
    response = requests.get(ODDS_API_URL, params=params, timeout=30)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise ValueError("Unexpected odds payload shape")
    return payload


def extract_market_rows(payload):
    rows = []
    today_et = datetime.now(EASTERN).date()

    for game in payload:
        home_team = normalize_team(game.get("home_team"))
        away_team = normalize_team(game.get("away_team"))
        start_time_et = to_et(game.get("commence_time"))

        if not home_team or not away_team or pd.isna(start_time_et):
            continue
        if start_time_et.date() != today_et:
            continue

        home_spreads = []
        away_spreads = []
        totals = []
        home_prices = []
        away_prices = []

        for bookmaker in game.get("bookmakers", []) or []:
            for market in bookmaker.get("markets", []) or []:
                outcomes = market.get("outcomes", []) or []
                key = str(market.get("key", "")).strip().lower()

                if key == "spreads":
                    for outcome in outcomes:
                        point = outcome.get("point")
                        team_name = str(outcome.get("name", "")).strip()
                        if team_name == game.get("home_team"):
                            home_spreads.append(point)
                        elif team_name == game.get("away_team"):
                            away_spreads.append(point)
                elif key == "totals":
                    for outcome in outcomes:
                        totals.append(outcome.get("point"))
                elif key == "h2h":
                    for outcome in outcomes:
                        price = outcome.get("price")
                        team_name = str(outcome.get("name", "")).strip()
                        if team_name == game.get("home_team"):
                            home_prices.append(price)
                        elif team_name == game.get("away_team"):
                            away_prices.append(price)

        home_spread = median_or_none(home_spreads)
        away_spread = median_or_none(away_spreads)
        game_total = median_or_none(totals)
        home_moneyline = median_or_none(home_prices)
        away_moneyline = median_or_none(away_prices)

        rows.append(
            {
                "GAME_DATE": str(start_time_et.date()),
                "START_TIME_ET": start_time_et.isoformat(),
                "HOME_TEAM": home_team,
                "AWAY_TEAM": away_team,
                "HOME_SPREAD": home_spread,
                "AWAY_SPREAD": away_spread,
                "TOTAL": game_total,
                "HOME_MONEYLINE": home_moneyline,
                "AWAY_MONEYLINE": away_moneyline,
            }
        )

    return pd.DataFrame(rows)


def main():
    try:
        payload = fetch_payload()
    except Exception as exc:
        print(f"Skipping game-line fetch due to error: {exc}")
        return

    df = extract_market_rows(payload)
    if df.empty:
        print("No NBA game-line rows found for today's slate.")
        return

    df = df.sort_values(["START_TIME_ET", "HOME_TEAM", "AWAY_TEAM"]).reset_index(drop=True)
    df.to_csv(GAME_LINES_PATH, index=False)
    print(f"Saved game lines: {GAME_LINES_PATH}")
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
