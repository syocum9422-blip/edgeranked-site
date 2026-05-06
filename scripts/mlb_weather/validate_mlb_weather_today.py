#!/usr/bin/env python3
"""
Validate MLB Weather Today JSON Output
Checks structural integrity and data quality of mlb_weather_today.json.
Validates GAME-BASED structure (not team-based).
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


ET = ZoneInfo("America/New_York")


REQUIRED_TOP_FIELDS = [
    "generated_at", "slate_date", "source", "total_games", "games"
]

GAME_REQUIRED_FIELDS = [
    "game_id", "game_date", "away_team", "home_team",
    "venue", "city", "roof_type",
    "latitude", "longitude",
    "temperature_f", "wind_speed_mph", "wind_direction", "rain_chance",
    "label", "summary"
]

MAX_REASONABLE_GAMES = 20

VALID_LABELS = {"Power Boost", "Run Boost", "Pitcher Friendly", "Wind Suppression", "Delay Risk", "Neutral"}
VALID_ROOF_TYPES = {"outdoor", "retractable", "indoor"}


def validate_file_exists(path: str) -> tuple[bool, str]:
    if not os.path.exists(path):
        return False, f"File does not exist: {path}"
    if os.path.getsize(path) == 0:
        return False, f"File is empty: {path}"
    return True, "OK"


def validate_json_structure(data: dict) -> list[str]:
    """Validate JSON structure for game-based output."""
    errors = []
    
    # Check for old "total_teams" field - this is a failure for game-based output
    if "total_teams" in data:
        errors.append("INVALID: 'total_teams' field found - output must be game-based, not team-based. Use 'total_games' instead.")
    
    for field in REQUIRED_TOP_FIELDS:
        if field not in data:
            errors.append(f"Missing required top-level field: {field}")
    
    if "games" in data:
        if not isinstance(data["games"], list):
            errors.append("'games' must be a list")
        elif len(data["games"]) == 0:
            errors.append("'games' list is empty")
        else:
            # Check for total_games > MAX_REASONABLE_GAMES
            total = data.get("total_games", len(data["games"]))
            if total > MAX_REASONABLE_GAMES:
                errors.append(f"INVALID: total_games={total} exceeds maximum reasonable MLB games ({MAX_REASONABLE_GAMES}). Possible duplicate game issue.")
            
            # Check for duplicate game_ids
            game_ids = [g.get("game_id") for g in data["games"] if g.get("game_id")]
            if len(game_ids) != len(set(game_ids)):
                dupes = [gid for gid in game_ids if game_ids.count(gid) > 1]
                errors.append(f"INVALID: duplicate game_id values found: {set(dupes)}")
            
            # Check for duplicate home_team (implies hitter-rows-as-games issue)
            home_counts = {}
            for g in data["games"]:
                ht = g.get("home_team", g.get("team", ""))
                if ht:
                    home_counts[ht] = home_counts.get(ht, 0) + 1
            multi_home = {ht: c for ht, c in home_counts.items() if c > 1}
            if multi_home:
                # Check if this is explained by doubleheaders (home_team appears exactly 2x)
                non_double = {ht: c for ht, c in multi_home.items() if c > 2}
                if non_double:
                    errors.append(f"INVALID: duplicate home_team values found beyond doubleheader count: {non_double}")
                    errors.append(f"  This suggests the output is NOT game-based but row-per-hitter. Fix deduping.")
    else:
        errors.append("'games' field is missing")
    
    return errors


def validate_game(game: dict, index: int) -> list[str]:
    """Validate a single game entry. Returns list of errors."""
    errors = []
    
    # Check home_team and away_team exist (critical for game-based)
    if "home_team" not in game:
        errors.append(f"Game[{index}]: missing required field: home_team")
    if "away_team" not in game:
        errors.append(f"Game[{index}]: missing required field: away_team")
    
    # Check that it's NOT a team-only row (no home_team means it's a team row)
    if "home_team" not in game and "team" in game:
        errors.append(f"Game[{index}]: appears to be a team-only row (has 'team' but no 'home_team'). Must be game-based with home_team and away_team.")
    
    for field in GAME_REQUIRED_FIELDS:
        if field not in game:
            errors.append(f"Game[{index}]: missing required field: {field}")
    
    # Validate temperature
    if "temperature_f" in game:
        try:
            temp = float(game["temperature_f"])
            if temp < -20 or temp > 120:
                errors.append(f"Game[{index}]: temperature_f {temp} out of plausible range (-20 to 120)")
        except (ValueError, TypeError):
            errors.append(f"Game[{index}]: temperature_f is not a number: {game['temperature_f']}")
    
    # Validate wind
    if "wind_speed_mph" in game:
        try:
            wind = float(game["wind_speed_mph"])
            if wind < 0 or wind > 100:
                errors.append(f"Game[{index}]: wind_speed_mph {wind} out of plausible range (0 to 100)")
        except (ValueError, TypeError):
            errors.append(f"Game[{index}]: wind_speed_mph is not a number: {game['wind_speed_mph']}")
    
    # Validate rain
    if "rain_chance" in game:
        try:
            rain = float(game["rain_chance"])
            if rain < 0 or rain > 100:
                errors.append(f"Game[{index}]: rain_chance {rain} out of range (0 to 100)")
        except (ValueError, TypeError):
            errors.append(f"Game[{index}]: rain_chance is not a number: {game['rain_chance']}")
    
    # Validate label
    if "label" in game:
        if game["label"] not in VALID_LABELS:
            errors.append(f"Game[{index}]: label '{game['label']}' not in valid set: {VALID_LABELS}")
    
    # Validate roof_type
    if "roof_type" in game:
        if game["roof_type"] not in VALID_ROOF_TYPES:
            errors.append(f"Game[{index}]: roof_type '{game['roof_type']}' not in valid set: {VALID_ROOF_TYPES}")
    
    return errors


def validate_timestamp(ts: str) -> list[str]:
    """Validate ISO timestamp format."""
    errors = []
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        age = abs((now - dt).total_seconds())
        if age > 86400:
            errors.append(f"Timestamp {ts} is more than 24 hours old (age: {age:.0f}s)")
    except Exception as e:
        errors.append(f"Invalid timestamp format '{ts}': {e}")
    return errors


def validate_game_dates(data: dict) -> list[str]:
    """Validate slate_date and every game_date are today in ET."""
    errors = []
    today = datetime.now(ET).date().isoformat()
    slate_date = data.get("slate_date")
    if slate_date != today:
        errors.append(f"slate_date {slate_date!r} does not match today in ET: {today}")
    for index, game in enumerate(data.get("games", [])):
        game_date = game.get("game_date")
        if game_date != today:
            errors.append(f"Game[{index}] game_date {game_date!r} does not match today in ET: {today}")
    return errors


def main():
    json_path = "mlb/outputs/mlb_weather_today.json"
    
    print("=" * 60)
    print("MLB Weather Today Validation (Game-Based)")
    print("=" * 60)
    
    # Check file exists
    print(f"\n[1] Checking file exists: {json_path}")
    ok, msg = validate_file_exists(json_path)
    print(f"    {'✓' if ok else '✗'} {msg}")
    if not ok:
        print("\n❌ VALIDATION FAILED: File not found or empty")
        return 1
    
    # Load JSON
    print(f"\n[2] Loading JSON")
    try:
        with open(json_path, "r") as f:
            data = json.load(f)
        print(f"    ✓ JSON loaded successfully")
    except json.JSONDecodeError as e:
        print(f"    ✗ JSON decode error: {e}")
        print("\n❌ VALIDATION FAILED: Invalid JSON")
        return 1
    except Exception as e:
        print(f"    ✗ Error reading file: {e}")
        print("\n❌ VALIDATION FAILED: Read error")
        return 1
    
    # Validate structure
    print(f"\n[3] Validating structure (game-based)")
    errors = validate_json_structure(data)
    if errors:
        for err in errors:
            print(f"    ✗ {err}")
        print("\n❌ VALIDATION FAILED: Structure errors")
        return 1
    print(f"    ✓ All required top-level fields present")
    print(f"    ✓ total_games present: {data.get('total_games', '?')}")
    print(f"    ✓ games list present with {len(data.get('games', []))} entries")
    
    # Validate timestamp
    print(f"\n[4] Validating timestamp")
    ts_errors = validate_timestamp(data.get("generated_at", ""))
    if ts_errors:
        for err in ts_errors:
            print(f"    ! {err}")
    else:
        print(f"    ✓ Timestamp valid: {data.get('generated_at')}")

    # Validate game dates against ET today
    print(f"\n[4b] Validating slate/game dates against ET today")
    date_errors = validate_game_dates(data)
    if date_errors:
        for err in date_errors:
            print(f"    ✗ {err}")
        print("\n❌ VALIDATION FAILED: Date errors")
        return 1
    print(f"    ✓ slate_date and all game_date values match ET today")
    
    # Validate each game
    print(f"\n[5] Validating game entries")
    all_errors = []
    for i, game in enumerate(data.get("games", [])):
        game_errors = validate_game(game, i)
        if game_errors:
            all_errors.extend(game_errors)
        else:
            home = game.get("home_team", "?")
            away = game.get("away_team", "?")
            temp = game.get("temperature_f", "?")
            label = game.get("label", "?")
            print(f"    ✓ {away} @ {home}: {temp}°F, {label}")
    
    if all_errors:
        print(f"\n    ✗ Found {len(all_errors)} game entry errors:")
        for err in all_errors[:10]:
            print(f"       - {err}")
        if len(all_errors) > 10:
            print(f"       ... and {len(all_errors) - 10} more")
        print("\n❌ VALIDATION FAILED: Game entry errors")
        return 1
    
    # Validate label distribution
    print(f"\n[6] Label distribution")
    label_counts = {}
    for game in data.get("games", []):
        label = game.get("label", "Unknown")
        label_counts[label] = label_counts.get(label, 0) + 1
    for label, count in sorted(label_counts.items()):
        print(f"    {label}: {count}")
    
    # Validate roof type distribution
    print(f"\n[7] Roof type distribution")
    roof_counts = {}
    for game in data.get("games", []):
        roof = game.get("roof_type", "Unknown")
        roof_counts[roof] = roof_counts.get(roof, 0) + 1
    for roof, count in sorted(roof_counts.items()):
        print(f"    {roof}: {count}")
    
    # Summary
    print(f"\n{'=' * 60}")
    print(f"✓ VALIDATION PASSED (Game-Based)")
    print(f"  File: {json_path}")
    print(f"  Games: {data.get('total_games', '?')}")
    print(f"  Generated: {data.get('generated_at', '?')}")
    print(f"  Source: {data.get('source', '?')}")
    print(f"{'=' * 60}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
