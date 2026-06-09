#!/usr/bin/env python3
"""Safely refresh the authoritative team batting strikeout-rate snapshot used by
the Ks Threat board's Opponent K Rate display.

Fetches current-season MLB team batting K% from FanGraphs (the same source as the
existing snapshot), validates it hard, and only then atomically replaces the
destination file(s). On any fetch or validation failure the existing file is left
untouched and the process exits nonzero with a clear log, so a bad upstream pull
can never corrupt the display.

Output columns (unchanged schema): team, k_pct, pa, so, source, fetched_date

Usage:
    refresh_team_batting_k.py [--season YYYY] [--dest PATH ...] [--timeout SECS]

If no --dest is given it writes to <repo>/site/data/mlb/team_batting_k_pct_season.csv.
The MLB daily wrapper passes the live read dir(s) explicitly.
"""

from __future__ import annotations

import argparse
import csv
import datetime
import os
import sys
import tempfile
from pathlib import Path

import requests

FANGRAPHS_URL = "https://www.fangraphs.com/api/leaders/major-league/data"
SOURCE_LABEL = "FanGraphs team batting (full-season, PA-weighted)"
K_PCT_MIN = 0.15
K_PCT_MAX = 0.27
EXPECTED_TEAM_COUNT = 30

# FanGraphs team abbreviation -> canonical full name. The canonical full names
# match the forms mlb_canonical_team_key() resolves in app.py and the values in
# pitcher_tracking.csv's `opponent` column, so the lookup keys line up.
ABBR_TO_FULL = {
    "ARI": "Arizona Diamondbacks", "AZ": "Arizona Diamondbacks",
    "ATL": "Atlanta Braves",
    "BAL": "Baltimore Orioles",
    "BOS": "Boston Red Sox",
    "CHC": "Chicago Cubs",
    "CHW": "Chicago White Sox", "CWS": "Chicago White Sox",
    "CIN": "Cincinnati Reds",
    "CLE": "Cleveland Guardians",
    "COL": "Colorado Rockies",
    "DET": "Detroit Tigers",
    "HOU": "Houston Astros",
    "KC": "Kansas City Royals", "KCR": "Kansas City Royals",
    "LAA": "Los Angeles Angels",
    "LAD": "Los Angeles Dodgers",
    "MIA": "Miami Marlins",
    "MIL": "Milwaukee Brewers",
    "MIN": "Minnesota Twins",
    "NYM": "New York Mets",
    "NYY": "New York Yankees",
    "ATH": "Athletics", "OAK": "Athletics",
    "PHI": "Philadelphia Phillies",
    "PIT": "Pittsburgh Pirates",
    "SD": "San Diego Padres", "SDP": "San Diego Padres",
    "SF": "San Francisco Giants", "SFG": "San Francisco Giants",
    "SEA": "Seattle Mariners",
    "STL": "St. Louis Cardinals",
    "TB": "Tampa Bay Rays", "TBR": "Tampa Bay Rays",
    "TEX": "Texas Rangers",
    "TOR": "Toronto Blue Jays",
    "WSH": "Washington Nationals", "WSN": "Washington Nationals",
}
EXPECTED_TEAMS = frozenset(ABBR_TO_FULL.values())

FIELDNAMES = ["team", "k_pct", "pa", "so", "source", "fetched_date"]


def log(msg: str) -> None:
    print(f"[refresh_team_batting_k] {msg}", flush=True)


def fetch_rows(season: int, timeout: int) -> list[dict]:
    """Pull team batting K% from FanGraphs. Raises on any HTTP/parse problem."""
    params = {
        "pos": "all", "stats": "bat", "lg": "all",
        "season": str(season), "season1": str(season),
        "ind": "0", "qual": "0", "type": "8", "team": "0,ts",
        "pageitems": "2000",
    }
    headers = {
        "User-Agent": "Mozilla/5.0 AppleWebKit/537.36 Chrome/120 Safari/537.36",
        "Accept": "application/json",
    }
    resp = requests.get(FANGRAPHS_URL, params=params, headers=headers, timeout=timeout)
    resp.raise_for_status()
    payload = resp.json()
    data = payload["data"] if isinstance(payload, dict) and "data" in payload else payload
    if not isinstance(data, list) or not data:
        raise ValueError("FanGraphs returned no team rows")

    today = datetime.date.today().isoformat()
    rows = []
    for raw in data:
        abbr = str(raw.get("TeamName") or "").strip()
        full = ABBR_TO_FULL.get(abbr)
        if not full:
            raise ValueError(f"Unrecognized FanGraphs team abbreviation: {abbr!r}")
        rows.append({
            "team": full,
            "k_pct": round(float(raw["K%"]), 4),
            "pa": int(raw["PA"]),
            "so": int(raw["SO"]),
            "source": SOURCE_LABEL,
            "fetched_date": today,
        })
    rows.sort(key=lambda r: r["team"])
    return rows


def validate_rows(rows: list[dict]) -> list[str]:
    """Return a list of human-readable validation errors (empty == valid)."""
    errors: list[str] = []
    teams = [r["team"] for r in rows]

    if len(rows) != EXPECTED_TEAM_COUNT:
        errors.append(f"expected {EXPECTED_TEAM_COUNT} teams, got {len(rows)}")

    dupes = sorted({t for t in teams if teams.count(t) > 1})
    if dupes:
        errors.append(f"duplicate canonical teams: {dupes}")

    missing = sorted(EXPECTED_TEAMS - set(teams))
    if missing:
        errors.append(f"missing teams: {missing}")

    unexpected = sorted(set(teams) - EXPECTED_TEAMS)
    if unexpected:
        errors.append(f"unexpected teams: {unexpected}")

    for r in rows:
        k = r["k_pct"]
        if not (K_PCT_MIN <= k <= K_PCT_MAX):
            errors.append(f"{r['team']}: k_pct {k} outside [{K_PCT_MIN}, {K_PCT_MAX}]")
        if r["pa"] <= 0:
            errors.append(f"{r['team']}: PA not positive ({r['pa']})")
        if r["so"] <= 0:
            errors.append(f"{r['team']}: SO not positive ({r['so']})")

    return errors


def atomic_write(rows: list[dict], dest: Path) -> None:
    """Write rows to a temp file in dest's directory, then atomically replace dest."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{dest.stem}.", suffix=".tmp", dir=str(dest.parent)
    )
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            writer.writeheader()
            writer.writerows(rows)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, dest)  # atomic on POSIX
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def default_dest() -> Path:
    # <repo>/site/data/mlb/team_batting_k_pct_season.csv  (this file lives at
    # <repo>/site/scripts/mlb/refresh_team_batting_k.py -> parents[1] == site)
    return Path(__file__).resolve().parents[1] / "data" / "mlb" / "team_batting_k_pct_season.csv"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, default=datetime.date.today().year,
                        help="MLB season year (default: current year)")
    parser.add_argument("--dest", action="append", default=None,
                        help="Destination CSV path (repeatable). Default: repo site/data/mlb copy")
    parser.add_argument("--timeout", type=int, default=60, help="HTTP timeout seconds")
    args = parser.parse_args()

    dests = [Path(d) for d in (args.dest or [str(default_dest())])]

    # 1) Fetch (failure => keep existing files, exit nonzero)
    try:
        log(f"Fetching {args.season} team batting K% from FanGraphs...")
        rows = fetch_rows(args.season, args.timeout)
        log(f"Fetched {len(rows)} team rows.")
    except Exception as e:
        log(f"ERROR: fetch failed: {type(e).__name__}: {e}")
        log("Existing snapshot left unchanged. Exiting nonzero.")
        return 2

    # 2) Validate (failure => keep existing files, exit nonzero)
    errors = validate_rows(rows)
    if errors:
        log("ERROR: validation failed:")
        for err in errors:
            log(f"  - {err}")
        log("Existing snapshot left unchanged. Exiting nonzero.")
        return 3

    fetched_date = rows[0]["fetched_date"]
    log(f"Validation passed: {len(rows)} teams, k_pct in "
        f"[{min(r['k_pct'] for r in rows):.4f}, {max(r['k_pct'] for r in rows):.4f}], "
        f"fetched_date={fetched_date}")

    # 3) Install atomically to every destination (only after validation passed)
    install_failed = False
    for dest in dests:
        try:
            atomic_write(rows, dest)
            log(f"OK: wrote {dest}")
        except Exception as e:
            install_failed = True
            log(f"ERROR: failed to write {dest}: {type(e).__name__}: {e}")
    if install_failed:
        log("At least one destination failed. Exiting nonzero.")
        return 4

    log(f"Refresh complete. fetched_date={fetched_date}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
