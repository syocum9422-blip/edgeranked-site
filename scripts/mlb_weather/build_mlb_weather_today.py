#!/usr/bin/env python3
"""
Build MLB Weather Today Script v2
Game-based output: one row per MLB game with home/away weather.
Fetches real weather data from Open-Meteo for today's MLB games.
Uses existing MLB projection files to determine today's slate.
"""

import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests


ET = ZoneInfo("America/New_York")
REPO_ROOT = Path(__file__).resolve().parents[2]
LIVE_MLB_BASE = Path(os.environ.get("EDGERANKED_MLB_BASE_DIR", "/home/ubuntu/edgeranked-sportsai"))
MAX_SLATE_SOURCE_AGE_HOURS = 36

# -------------------------------------------------------------------
# MLB Team to Ballpark / City / Coordinates Mapping
# -------------------------------------------------------------------
TEAM_VENUES = {
    "Arizona Diamondbacks": {"abbr": "ARI", "venue": "Chase Field", "city": "Phoenix", "state": "AZ", "lat": 33.4455, "lon": -112.0663, "roof": "retractable"},
    "Atlanta Braves": {"abbr": "ATL", "venue": "Truist Park", "city": "Cumberland", "state": "GA", "lat": 33.8912, "lon": -84.4684, "roof": "outdoor"},
    "Baltimore Orioles": {"abbr": "BAL", "venue": "Oriole Park at Camden Yards", "city": "Baltimore", "state": "MD", "lat": 39.2840, "lon": -76.6211, "roof": "outdoor"},
    "Boston Red Sox": {"abbr": "BOS", "venue": "Fenway Park", "city": "Boston", "state": "MA", "lat": 42.3467, "lon": -71.0972, "roof": "outdoor"},
    "Chicago Cubs": {"abbr": "CHC", "venue": "Wrigley Field", "city": "Chicago", "state": "IL", "lat": 41.9484, "lon": -87.6553, "roof": "outdoor"},
    "Chicago White Sox": {"abbr": "CWS", "venue": "Guaranteed Rate Field", "city": "Chicago", "state": "IL", "lat": 41.8299, "lon": -87.6540, "roof": "outdoor"},
    "Cincinnati Reds": {"abbr": "CIN", "venue": "Great American Ball Park", "city": "Cincinnati", "state": "OH", "lat": 39.0979, "lon": -84.5071, "roof": "outdoor"},
    "Cleveland Guardians": {"abbr": "CLE", "venue": "Progressive Field", "city": "Cleveland", "state": "OH", "lat": 41.4959, "lon": -81.6872, "roof": "retractable"},
    "Colorado Rockies": {"abbr": "COL", "venue": "Coors Field", "city": "Denver", "state": "CO", "lat": 39.7561, "lon": -104.9942, "roof": "outdoor"},
    "Detroit Tigers": {"abbr": "DET", "venue": "Comerica Park", "city": "Detroit", "state": "MI", "lat": 42.3267, "lon": -83.0499, "roof": "outdoor"},
    "Houston Astros": {"abbr": "HOU", "venue": "Minute Maid Park", "city": "Houston", "state": "TX", "lat": 29.7570, "lon": -95.3558, "roof": "retractable"},
    "Kansas City Royals": {"abbr": "KC", "venue": "Kauffman Stadium", "city": "Kansas City", "state": "MO", "lat": 39.0517, "lon": -94.4807, "roof": "outdoor"},
    "Los Angeles Angels": {"abbr": "LAA", "venue": "Angel Stadium", "city": "Anaheim", "state": "CA", "lat": 33.8003, "lon": -117.8828, "roof": "outdoor"},
    "Los Angeles Dodgers": {"abbr": "LAD", "venue": "Dodger Stadium", "city": "Los Angeles", "state": "CA", "lat": 34.0637, "lon": -118.1384, "roof": "outdoor"},
    "Miami Marlins": {"abbr": "MIA", "venue": "LoanDepot Park", "city": "Miami", "state": "FL", "lat": 25.9567, "lon": -80.2378, "roof": "retractable"},
    "Milwaukee Brewers": {"abbr": "MIL", "venue": "American Family Field", "city": "Milwaukee", "state": "WI", "lat": 43.0280, "lon": -87.9709, "roof": "retractable"},
    "Minnesota Twins": {"abbr": "MIN", "venue": "Target Field", "city": "Minneapolis", "state": "MN", "lat": 44.9818, "lon": -93.2773, "roof": "outdoor"},
    "New York Mets": {"abbr": "NYM", "venue": "Citi Field", "city": "Queens", "state": "NY", "lat": 40.7559, "lon": -73.8457, "roof": "outdoor"},
    "New York Yankees": {"abbr": "NYY", "venue": "Yankee Stadium", "city": "Bronx", "state": "NY", "lat": 40.8296, "lon": -73.9264, "roof": "outdoor"},
    "Oakland Athletics": {"abbr": "OAK", "venue": "Oakland Coliseum", "city": "Oakland", "state": "CA", "lat": 37.7516, "lon": -122.2009, "roof": "outdoor"},
    "Philadelphia Phillies": {"abbr": "PHI", "venue": "Citizens Bank Park", "city": "Philadelphia", "state": "PA", "lat": 39.9051, "lon": -75.1666, "roof": "outdoor"},
    "Pittsburgh Pirates": {"abbr": "PIT", "venue": "PNC Park", "city": "Pittsburgh", "state": "PA", "lat": 40.4420, "lon": -79.9902, "roof": "outdoor"},
    "San Diego Padres": {"abbr": "SD", "venue": "Petco Park", "city": "San Diego", "state": "CA", "lat": 32.7077, "lon": -117.1563, "roof": "outdoor"},
    "San Francisco Giants": {"abbr": "SF", "venue": "Oracle Park", "city": "San Francisco", "state": "CA", "lat": 37.7786, "lon": -122.3893, "roof": "outdoor"},
    "Seattle Mariners": {"abbr": "SEA", "venue": "T-Mobile Park", "city": "Seattle", "state": "WA", "lat": 47.5913, "lon": -122.1414, "roof": "outdoor"},
    "St. Louis Cardinals": {"abbr": "STL", "venue": "Busch Stadium", "city": "St. Louis", "state": "MO", "lat": 38.6382, "lon": -90.1923, "roof": "outdoor"},
    "Tampa Bay Rays": {"abbr": "TB", "venue": "Tropicana Field", "city": "St. Petersburg", "state": "FL", "lat": 27.7698, "lon": -82.6533, "roof": "indoor"},
    "Texas Rangers": {"abbr": "TEX", "venue": "Globe Life Field", "city": "Arlington", "state": "TX", "lat": 32.7473, "lon": -97.0820, "roof": "retractable"},
    "Toronto Blue Jays": {"abbr": "TOR", "venue": "Rogers Centre", "city": "Toronto", "state": "ON", "lat": 43.6415, "lon": -79.3887, "roof": "retractable"},
    "Washington Nationals": {"abbr": "WAS", "venue": "Nationals Park", "city": "Washington", "state": "DC", "lat": 38.8722, "lon": -77.0073, "roof": "outdoor"},
}

# Build reverse lookup by abbreviation
ABBR_TO_VENUE = {v["abbr"]: v for k, v in TEAM_VENUES.items()}
NAME_TO_VENUE = {k: v for k, v in TEAM_VENUES.items()}
NAME_TO_VENUE["Athletics"] = TEAM_VENUES["Oakland Athletics"]


TEAM_ALIASES = {
    "A's": "Athletics",
    "Oakland A's": "Athletics",
    "Oakland Athletics": "Athletics",
    "ATH": "Athletics",
    "AZ": "Arizona Diamondbacks",
    "ARZ": "Arizona Diamondbacks",
    "CWS": "Chicago White Sox",
    "CHW": "Chicago White Sox",
    "WSH": "Washington Nationals",
    "WAS": "Washington Nationals",
    "SDP": "San Diego Padres",
    "SFG": "San Francisco Giants",
    "KCR": "Kansas City Royals",
    "TBR": "Tampa Bay Rays",
    "LAD": "Los Angeles Dodgers",
    "LAA": "Los Angeles Angels",
    "NYM": "New York Mets",
    "NYY": "New York Yankees",
}


def normalize_team_name(value: str) -> str:
    """Normalize team names/abbreviations used across model outputs and MLB schedule."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw in TEAM_ALIASES:
        return TEAM_ALIASES[raw]
    upper = raw.upper()
    if upper in TEAM_ALIASES:
        return TEAM_ALIASES[upper]
    if upper in ABBR_TO_VENUE:
        for name, venue in TEAM_VENUES.items():
            if venue["abbr"] == upper:
                return "Athletics" if name == "Oakland Athletics" else name
    return raw


def team_key(value: str) -> str:
    return normalize_team_name(value).lower()


def today_et():
    return datetime.now(ET).date()


def path_mtime_et(path: Path):
    return datetime.fromtimestamp(path.stat().st_mtime, tz=ET)


def csv_row_count(path: Path) -> int:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as handle:
            return max(sum(1 for _ in handle) - 1, 0)
    except Exception:
        return 0


def source_candidates():
    """Return slate source candidates. Prefer active MLB model outputs first."""
    active_model_base = Path("/home/ubuntu/mlb_model")

    candidates = [
        ("active_model_full_board", active_model_base / "mlb" / "outputs" / "hitter_predictions_full.csv"),
        ("active_model_today_board", active_model_base / "mlb" / "outputs" / "hitter_predictions_today.csv"),
        ("active_model_pitcher_props", active_model_base / "mlb" / "outputs" / "pitcher_props_today.csv"),
    ]

    bases = []
    for base in [LIVE_MLB_BASE, REPO_ROOT]:
        if base not in bases:
            bases.append(base)

    for base in bases:
        candidates.extend([
            ("canonical_full_board", base / "outputs" / "canonical" / "hitter_predictions_full.csv"),
            ("site_summary", base / "outputs" / "site" / "hitter_summary_today.csv"),
            ("live_full_board", base / "mlb" / "outputs" / "hitter_predictions_full.csv"),
            ("live_summary", base / "mlb" / "outputs" / "hitter_summary_today.csv"),
            ("pitcher_props", base / "mlb" / "outputs" / "pitcher_props_today.csv"),
        ])

    return candidates

def select_current_slate_source():
    """Select a current MLB slate file and reject stale candidates."""
    now = datetime.now(ET)
    today = today_et()
    checked = []
    for kind, path in source_candidates():
        if not path.exists():
            checked.append(f"{kind}: missing {path}")
            continue
        mtime = path_mtime_et(path)
        age_hours = (now - mtime).total_seconds() / 3600
        rows = csv_row_count(path)
        checked.append(f"{kind}: {path} mtime_et={mtime.isoformat()} rows={rows}")
        if mtime.date() == today and age_hours <= MAX_SLATE_SOURCE_AGE_HOURS and rows > 0:
            print(f"Slate source selected: {path}")
            print(f"Slate source type: {kind}")
            print(f"Slate source mtime ET: {mtime.isoformat()}")
            print(f"Slate source rows: {rows}")
            return kind, path, mtime

    print("Checked slate sources:")
    for item in checked:
        print(f"  {item}")
    raise RuntimeError(f"No current MLB slate source found for {today.isoformat()} ET")


# -------------------------------------------------------------------
# Weather Label Logic
# -------------------------------------------------------------------
def compute_weather_label(temp_f: float, wind_mph: float, rain_chance: float, roof: str) -> str:
    """Determine the primary weather label for a game."""
    if roof == "indoor":
        return "Neutral"
    if rain_chance >= 60:
        return "Delay Risk"
    if wind_mph >= 20:
        return "Wind Suppression"
    if temp_f >= 85 and rain_chance < 30:
        return "Power Boost"
    if 10 <= wind_mph < 20 and rain_chance < 40:
        return "Run Boost"
    if temp_f <= 60 and wind_mph < 10:
        return "Pitcher Friendly"
    return "Neutral"


def compute_weather_summary(temp_f: float, wind_mph: float, wind_dir: str, rain_chance: float, roof: str) -> str:
    """Generate a human-readable weather summary."""
    if roof == "indoor":
        return "Roofed stadium - weather controlled"
    
    parts = []
    if temp_f >= 85:
        parts.append("Hot")
    elif temp_f >= 70:
        parts.append("Warm")
    elif temp_f >= 55:
        parts.append("Mild")
    else:
        parts.append("Cool")
    
    if wind_mph >= 15:
        parts.append(f"windy ({wind_mph:.0f} mph {wind_dir})")
    elif wind_mph >= 8:
        parts.append(f"breezy ({wind_mph:.0f} mph {wind_dir})")
    else:
        parts.append("calm")
    
    if rain_chance >= 50:
        parts.append(f"rain likely ({rain_chance:.0f}%)")
    elif rain_chance >= 25:
        parts.append(f"rain possible ({rain_chance:.0f}%)")
    
    return ", ".join(parts)


# -------------------------------------------------------------------
# Game Discovery from MLB files
# -------------------------------------------------------------------
def fetch_mlb_schedule_home_away(game_date: str) -> dict:
    """Fetch official MLB schedule so deduped model matchups get correct venues."""
    url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={game_date}"
    lookup = {}
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        payload = response.json()
        for date_block in payload.get("dates", []):
            for game in date_block.get("games", []):
                teams = game.get("teams", {})
                away = normalize_team_name(teams.get("away", {}).get("team", {}).get("name"))
                home = normalize_team_name(teams.get("home", {}).get("team", {}).get("name"))
                if away and home:
                    lookup[tuple(sorted([team_key(away), team_key(home)]))] = {
                        "away_team_name": away,
                        "home_team_name": home,
                    }
        print(f"MLB schedule matchups loaded: {len(lookup)} for {game_date}")
    except Exception as exc:
        print(f"Warning: MLB schedule lookup failed: {exc}")
    return lookup


def discover_games_from_slate_source(source_path: Path, game_date: str):
    """Extract unique MLB games from the selected current model slate source."""
    schedule_lookup = fetch_mlb_schedule_home_away(game_date)
    pair_to_first_seen = {}

    with open(source_path, "r", encoding="utf-8", errors="ignore") as f:
        reader = csv.DictReader(f)
        for row in reader:
            team = (row.get("team") or row.get("Team") or "").strip()
            opp = (row.get("opponent") or row.get("Opponent") or "").strip()
            if not team or not opp:
                continue
            team = normalize_team_name(team)
            opp = normalize_team_name(opp)
            key = tuple(sorted([team_key(team), team_key(opp)]))
            if key not in pair_to_first_seen:
                pair_to_first_seen[key] = (team, opp)

    games = []
    for matchup_key, (team, opp) in pair_to_first_seen.items():
        scheduled = schedule_lookup.get(matchup_key)
        if scheduled:
            games.append(scheduled)
        elif team in NAME_TO_VENUE or team in ABBR_TO_VENUE:
            games.append({"home_team_name": team, "away_team_name": opp})
            print(f"  Warning: schedule match not found for {team} vs {opp}; using first-seen team as home")
        elif opp in NAME_TO_VENUE or opp in ABBR_TO_VENUE:
            games.append({"home_team_name": opp, "away_team_name": team})
            print(f"  Warning: schedule match not found for {team} vs {opp}; using opponent as home")
        else:
            print(f"  Warning: could not identify teams for '{team}' vs '{opp}', skipping")

    return games


# -------------------------------------------------------------------
# Open-Meteo Weather Fetch
# -------------------------------------------------------------------
def fetch_weather(lat: float, lon: float) -> dict:
    """Fetch current weather from Open-Meteo API (no API key required)."""
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        f"&current=temperature_2m,wind_speed_10m,wind_gusts_10m,wind_direction_10m,precipitation_probability,precipitation,weather_code"
        f"&temperature_unit=fahrenheit&wind_speed_unit=mph&precipitation_unit=inch"
        f"&timezone=auto"
    )
    
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        current = data.get("current", {})
        wind_degrees = current.get("wind_direction_10m", 0)
        gust = current.get("wind_gusts_10m")
        return {
            "temperature_f": round(current.get("temperature_2m", 70)),
            "wind_speed_mph": round(current.get("wind_speed_10m", 0)),
            "wind_gust_mph": round(gust) if gust is not None else None,
            "wind_direction": degrees_to_cardinal(wind_degrees),
            "wind_direction_degrees": round(wind_degrees) if wind_degrees is not None else None,
            "rain_chance": round(current.get("precipitation_probability", 0)),
            "precipitation_inches": current.get("precipitation", 0),
            "weather_code": current.get("weather_code", 0),
            "fetched": True,
        }
    except Exception as e:
        print(f"  Warning: weather fetch failed: {e}")
        return {
            "temperature_f": 70,
            "wind_speed_mph": 10,
            "wind_gust_mph": None,
            "wind_direction": "CALM",
            "wind_direction_degrees": None,
            "rain_chance": 20,
            "precipitation_inches": 0,
            "weather_code": 0,
            "fetched": False,
            "error": str(e),
        }


def degrees_to_cardinal(degrees: float) -> str:
    """Convert wind degrees to cardinal direction."""
    if degrees is None:
        return "CALM"
    directions = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
                   "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    idx = round(degrees / 22.5) % 16
    return directions[idx]


# -------------------------------------------------------------------
# Main Build Function
# -------------------------------------------------------------------
def build_weather_today():
    """Build MLB weather data for today's slate (game-based)."""
    output_dir = REPO_ROOT / "mlb" / "outputs"
    os.makedirs(output_dir, exist_ok=True)
    game_date = today_et().isoformat()

    print("Selecting current MLB slate source...")
    source_kind, source_path, source_mtime = select_current_slate_source()
    print(f"Discovering MLB games from {source_path}...")
    raw_games = discover_games_from_slate_source(source_path, game_date)
    
    if not raw_games:
        print("Error: could not discover any games")
        return None
    
    print(f"  Found {len(raw_games)} unique game matchups")
    
    # Build game-based output
    games = []
    for idx, rg in enumerate(raw_games):
        home_name = rg["home_team_name"]
        away_name = rg["away_team_name"]
        
        home_venue = NAME_TO_VENUE.get(home_name) or ABBR_TO_VENUE.get(home_name)
        if home_venue is None:
            print(f"  Warning: no venue for home team '{home_name}', skipping")
            continue
        
        away_venue = NAME_TO_VENUE.get(away_name) or ABBR_TO_VENUE.get(away_name)
        away_abbr = away_venue["abbr"] if away_venue else away_name[:3].upper()
        
        print(f"Fetching weather for {away_name} @ {home_name} ({home_venue['venue']})...")
        weather = fetch_weather(home_venue["lat"], home_venue["lon"])
        
        label = compute_weather_label(
            weather["temperature_f"],
            weather["wind_speed_mph"],
            weather["rain_chance"],
            home_venue["roof"]
        )
        
        summary = compute_weather_summary(
            weather["temperature_f"],
            weather["wind_speed_mph"],
            weather["wind_direction"],
            weather["rain_chance"],
            home_venue["roof"]
        )
        
        game_id = f"{game_date}-{away_venue['abbr'] if away_venue else 'UNK'}-{home_venue['abbr']}"
        
        game = {
            "game_id": game_id,
            "game_date": game_date,
            "away_team": away_venue["abbr"] if away_venue else away_abbr,
            "away_team_name": away_name,
            "home_team": home_venue["abbr"],
            "home_team_name": home_name,
            "venue": home_venue["venue"],
            "city": f"{home_venue['city']}, {home_venue['state']}",
            "roof_type": home_venue["roof"],
            "latitude": home_venue["lat"],
            "longitude": home_venue["lon"],
            "temperature_f": weather["temperature_f"],
            "wind_speed_mph": weather["wind_speed_mph"],
            "wind_gust_mph": weather.get("wind_gust_mph"),
            "wind_direction": weather["wind_direction"],
            "wind_direction_degrees": weather.get("wind_direction_degrees"),
            "rain_chance": weather["rain_chance"],
            "precipitation_inches": weather.get("precipitation_inches", 0),
            "weather_code": weather.get("weather_code", 0),
            "label": label,
            "summary": summary,
            "weather_fetched": weather.get("fetched", False),
        }
        games.append(game)
        print(f"  {away_venue['abbr'] if away_venue else away_abbr} @ {home_venue['abbr']}: {weather['temperature_f']}°F, {weather['wind_speed_mph']} mph {weather['wind_direction']}, {weather['rain_chance']}% rain - {label}")

    invalid_dates = sorted({g["game_date"] for g in games if g.get("game_date") != game_date})
    if invalid_dates:
        raise RuntimeError(f"Generated game_date mismatch: expected {game_date}, found {invalid_dates}")
    
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "slate_date": game_date,
        "source": "Open-Meteo (no API key)",
        "slate_source": str(source_path),
        "slate_source_type": source_kind,
        "slate_source_mtime_et": source_mtime.isoformat(),
        "total_games": len(games),
        "games": games,
    }
    
    output_path = output_dir / "mlb_weather_today.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)
    
    print(f"\nMLB weather data saved to {output_path}")
    print(f"Total games: {len(games)}")
    
    # Label summary
    label_counts = {}
    for g in games:
        label_counts[g["label"]] = label_counts.get(g["label"], 0) + 1
    print("Label distribution:", label_counts)
    
    return output_path


if __name__ == "__main__":
    build_weather_today()
