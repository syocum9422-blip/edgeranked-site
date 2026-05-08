#!/usr/bin/env python3
"""
WNBA prop-lines fetcher using PrizePicks API.

Fetches real WNBA player prop lines from PrizePicks and writes them to
data/raw/wnba_sportsbook_lines_raw.csv in the format expected by the WNBA pipeline.

Usage:
    WNBA_SOURCE_MODE=api   python3 fetch_wnba_lines.py  # fails if no real lines
    WNBA_SOURCE_MODE=auto  python3 fetch_wnba_lines.py  # falls back to CSV if needed
    WNBA_SOURCE_MODE=csv   python3 fetch_wnba_lines.py  # only uses CSV, no API attempt

Output:
    data/raw/wnba_sportsbook_lines_raw.csv
    Columns: player_name, team, opponent, stat, line, over_odds, under_odds, sportsbook, fetched_at, source_mode
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from wnba_model_config import RAW_SPORTSBOOK_LINES_PATH
from wnba_model_utils import setup_logging


WNBA_LEAGUE_ID = "10"
EASTERN = ZoneInfo("America/New_York")
SOURCE_MODE = os.getenv("WNBA_SOURCE_MODE", "auto").strip().lower()


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


def fetch_prizepicks_payload():
    """Fetch WNBA projections from PrizePicks API. Returns (payload, is_off_season) or raises."""
    session = requests.Session()
    session.headers.update(build_headers())

    endpoints = [
        "https://partner-api.prizepicks.com/projections",
        "https://api.prizepicks.com/projections",
    ]

    params = {
        "league_id": WNBA_LEAGUE_ID,
        "per_page": 1000,
        "single_stat": "true",
    }

    errors = []
    for url in endpoints:
        try:
            resp = session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict):
                data_list = data.get("data")
                if data_list is not None:
                    if len(data_list) == 0:
                        # Empty data means off-season
                        print(f"PrizePicks returned empty WNBA data from: {url} (likely off-season)")
                        errors.append(f"{url}: empty data (off-season)")
                    else:
                        print(f"Fetched PrizePicks data from: {url}")
                        return data, False
                else:
                    errors.append(f"{url}: response has no 'data' key (keys: {list(data.keys())})")
            else:
                errors.append(f"{url}: response is not a dict")
        except requests.exceptions.Timeout:
            errors.append(f"{url}: timeout")
        except requests.exceptions.HTTPError as e:
            errors.append(f"{url}: HTTP {e.response.status_code}")
        except Exception as e:
            errors.append(f"{url}: {type(e).__name__}: {e}")

    # If all endpoints returned empty (off-season), raise with special message
    if all("empty data" in e or "off-season" in e for e in errors):
        raise OffSeasonError("PrizePicks WNBA is empty (off-season). WNBA 2026 season starts May 8.")

    error_detail = "; ".join(errors) if errors else "unknown"
    raise RuntimeError(f"Could not fetch PrizePicks WNBA projections. Errors: {error_detail}")


class OffSeasonError(Exception):
    """Raised when PrizePicks returns empty WNBA data (off-season)."""
    pass


def build_player_lookup(included):
    """Build a lookup from player ID to player info from the 'included' array."""
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
            player_lookup[item_id] = {
                "player_name": name,
                "team": team,
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


def extract_rows(payload):
    """Extract projection rows from PrizePicks payload into WNBA format."""
    data = payload.get("data", []) or []
    included = payload.get("included", []) or []

    player_lookup = build_player_lookup(included)
    fetched_at = datetime.now(timezone.utc).isoformat()

    rows = []
    for proj in data:
        attrs = proj.get("attributes", {}) or {}
        player_id = get_related_player_id(proj)
        player_info = player_lookup.get(player_id, {})

        player_name = str(player_info.get("player_name", "")).strip()
        if not player_name:
            continue

        stat = (
            attrs.get("stat_type")
            or attrs.get("market")
            or attrs.get("prop_type")
            or ""
        )
        stat = str(stat).strip().lower()

        # Map PrizePicks stat names to WNBA internal stat names
        stat_mapping = {
            "pts": "points",
            "reb": "rebounds",
            "ast": "assists",
            "3pm": "threes_made",
            "fg3m": "threes_made",
            "stl": "steals",
            "blk": "blocks",
            "points": "points",
            "rebounds": "rebounds",
            "assists": "assists",
            "threes made": "threes_made",
            "steals": "steals",
            "blocks": "blocks",
        }
        stat = stat_mapping.get(stat, stat)

        line = attrs.get("line_score") or attrs.get("line")
        if line is None:
            continue

        # PrizePicks doesn't provide opponent or odds; use placeholders
        rows.append({
            "player_name": player_name,
            "team": player_info.get("team", ""),
            "opponent": "",
            "stat": stat,
            "line": pd.to_numeric(line, errors="coerce"),
            "over_odds": None,
            "under_odds": None,
            "sportsbook": "prizepicks",
            "fetched_at": fetched_at,
            "source_mode": "prizepicks_api",
        })

    df = pd.DataFrame(rows)
    return df


def filter_and_normalize(df):
    """Filter to today's slate and normalize stat names."""
    if df.empty:
        return df

    # Drop rows without valid lines
    df = df.dropna(subset=["player_name", "stat", "line"])
    df["player_name"] = df["player_name"].astype(str).str.strip()
    df["stat"] = df["stat"].astype(str).str.strip().str.lower()

    # Filter to only supported stat types
    valid_stats = {"points", "rebounds", "assists", "threes_made", "steals", "blocks",
                   "pra", "pr", "pa", "ra", "sb"}
    df = df[df["stat"].isin(valid_stats)]

    if df.empty:
        return df

    # For duplicates (same player+stat), keep the first occurrence
    df = df.drop_duplicates(subset=["player_name", "stat"], keep="first")

    return df.reset_index(drop=True)


def load_csv_fallback(logger):
    """Load existing CSV as fallback. Returns (DataFrame, source_label)."""
    if not RAW_SPORTSBOOK_LINES_PATH.exists():
        return pd.DataFrame(), "none"

    df = pd.read_csv(RAW_SPORTSBOOK_LINES_PATH)
    if df.empty:
        return pd.DataFrame(), "csv:empty"

    # Check if existing data is mockbook
    if "sportsbook" in df.columns:
        if (df["sportsbook"].astype(str).str.lower() == "mockbook").all():
            return df, "csv:mockbook"
        if (df["sportsbook"].astype(str).str.lower() == "prizepicks").any():
            return df, "csv:prizepicks"

    return df, "csv:unknown"


def write_lines(df, source_mode, logger):
    """Write lines to the raw CSV file with metadata."""
    if df.empty:
        logger.error("Cannot write empty lines DataFrame to %s", RAW_SPORTSBOOK_LINES_PATH)
        raise ValueError("No WNBA lines to write")

    # Ensure columns are in expected order
    columns = ["player_name", "team", "opponent", "stat", "line", "over_odds", "under_odds", "sportsbook", "fetched_at", "source_mode"]
    for col in columns:
        if col not in df.columns:
            df[col] = None

    df = df[columns]
    df.to_csv(RAW_SPORTSBOOK_LINES_PATH, index=False)
    logger.info("Wrote %d lines to %s [source=%s]", len(df), RAW_SPORTSBOOK_LINES_PATH, source_mode)


def main():
    logger = setup_logging("fetch_wnba_lines")
    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    logger.info("Starting WNBA lines fetch. SOURCE_MODE=%s", SOURCE_MODE)

    if SOURCE_MODE == "csv":
        # CSV-only mode: never attempt API
        logger.info("SOURCE_MODE=csv: loading only from CSV, no API attempt")
        df, source = load_csv_fallback(logger)
        if df.empty:
            logger.error("No CSV fallback available at %s", RAW_SPORTSBOOK_LINES_PATH)
            raise FileNotFoundError(f"No WNBA lines CSV found at {RAW_SPORTSBOOK_LINES_PATH}")
        write_lines(df, source, logger)
        return

    # auto or api mode: try PrizePicks first
    try:
        payload, is_off_season = fetch_prizepicks_payload()
        raw_df = extract_rows(payload)
        filtered_df = filter_and_normalize(raw_df)

        if filtered_df.empty:
            logger.warning("PrizePicks returned no usable WNBA projection rows (off-season or API issue)")
            if SOURCE_MODE == "api":
                raise ValueError(
                    "WNBA_SOURCE_MODE=api but PrizePicks returned 0 usable WNBA lines. "
                    "The WNBA season may be off-season or PrizePicks may be unavailable."
                )
            # auto mode: fall back to CSV
            logger.info("Falling back to CSV")
            df, source = load_csv_fallback(logger)
            if df.empty:
                raise ValueError("No CSV fallback available and PrizePicks returned empty data")
            write_lines(df, source, logger)
            return

        # Check for tiny slate (likely off-season)
        unique_players = filtered_df["player_name"].nunique()
        logger.info("PrizePicks returned %d lines for %d unique players", len(filtered_df), unique_players)

        if unique_players < 5:
            logger.warning("PrizePicks returned only %d players (off-season indicator)", unique_players)
            if SOURCE_MODE == "api":
                raise ValueError(
                    f"WNBA_SOURCE_MODE=api but PrizePicks returned only {unique_players} players. "
                    "This likely means the WNBA season is off-season. "
                    "Use WNBA_SOURCE_MODE=auto to fall back to CSV."
                )
            # auto mode: warn and fall back to CSV
            logger.warning("Tiny WNBA slate from PrizePicks; falling back to CSV")
            csv_df, csv_source = load_csv_fallback(logger)
            if not csv_df.empty:
                write_lines(csv_df, csv_source, logger)
            else:
                # Still write the PrizePicks data even if small, better than nothing
                write_lines(filtered_df, "prizepicks_api:small_slate", logger)
            return

        write_lines(filtered_df, "prizepicks_api", logger)

        # Print sample
        logger.info("Sample lines:")
        for _, row in filtered_df.head(10).iterrows():
            logger.info("  %s | %s | %s | line=%.1f", row["player_name"], row["team"], row["stat"], row["line"])

    except OffSeasonError as exc:
        logger.warning("WNBA is off-season: %s", exc)
        if SOURCE_MODE == "api":
            raise RuntimeError(
                f"WNBA_SOURCE_MODE=api but WNBA is off-season. "
                f"{exc} Use WNBA_SOURCE_MODE=auto to fall back to CSV/mock lines."
            ) from exc
        # auto mode: fall back to CSV
        logger.info("auto mode: falling back to CSV (WNBA off-season)")
        df, source = load_csv_fallback(logger)
        if df.empty:
            raise RuntimeError("WNBA is off-season and no CSV fallback available")
        write_lines(df, source, logger)

    except Exception as exc:
        logger.error("WNBA lines fetch failed: %s", exc)
        if SOURCE_MODE == "api":
            raise
        # auto mode: fall back to CSV
        logger.info("auto mode: falling back to CSV after error")
        df, source = load_csv_fallback(logger)
        if df.empty:
            raise RuntimeError(f"WNBA lines fetch failed ({exc}) and no CSV fallback available")
        write_lines(df, source, logger)


if __name__ == "__main__":
    main()
