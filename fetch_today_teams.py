import csv
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from urllib.request import Request, urlopen

API_KEY = "5f4e5a46-0c06-4ff5-82f2-f9a1461a32f7"
BASE_DIR = Path(__file__).resolve().parent
TEAMS_TODAY_PATH = BASE_DIR / "teams_today.csv"
GAME_LINES_PATH = BASE_DIR / "game_lines_today.csv"
ET = ZoneInfo("America/New_York")


def today_et():
    return datetime.now(ET).date().isoformat()


def write_games(games, source):
    teams = set()
    with TEAMS_TODAY_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["TEAM_ABBREVIATION", "OPPONENT", "MATCHUP"])
        for home, visitor in games:
            home = str(home).strip().upper()
            visitor = str(visitor).strip().upper()
            if not home or not visitor or home == visitor:
                continue
            teams.add(home)
            teams.add(visitor)
            writer.writerow([home, visitor, f"{home} vs. {visitor}"])
            writer.writerow([visitor, home, f"{visitor} @ {home}"])
    print("Date used:", today_et())
    print("Source used:", source)
    print("Games returned:", len(games))
    print("Teams returned:", len(teams))
    print(sorted(teams))
    return bool(games)


def games_from_market_lines():
    if not GAME_LINES_PATH.exists():
        return []
    today = today_et()
    games = []
    with GAME_LINES_PATH.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            game_date = str(row.get("GAME_DATE", "")).strip()[:10]
            if game_date != today:
                continue
            home = row.get("HOME_TEAM")
            away = row.get("AWAY_TEAM")
            if home and away:
                games.append((home, away))
    return games


def games_from_balldontlie():
    today = today_et()
    url = f"https://api.balldontlie.io/v1/games?dates[]={today}&per_page=100"
    req = Request(url, headers={"Authorization": API_KEY})
    with urlopen(req, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))
    games = []
    for game in data.get("data", []):
        home = game["home_team"]["abbreviation"]
        visitor = game["visitor_team"]["abbreviation"]
        games.append((home, visitor))
    return games


market_games = games_from_market_lines()
if market_games:
    write_games(market_games, str(GAME_LINES_PATH))
else:
    write_games(games_from_balldontlie(), "balldontlie")
