"""Phase 2 data — full team box-score ingestion + clean possession derivation.

SOURCE NOTE: the directive specified stats.wnba.com, but that host is firewalled
from this (AWS) environment — every request returns HTTP 000 (Akamai datacenter
block). ESPN's API is reachable, is already this project's proven actuals source,
and exposes COMPLETE team box scores (both teams, every game). We ingest from ESPN
behind a pluggable `BoxScoreSource` so stats.wnba.com can be dropped in unchanged
if this ever runs from a non-blocked host.

Pipeline: season scoreboard (game ids, cheap) -> per-game summary (full box, cached)
-> canonical two-row-per-game table -> clean possessions -> fail-closed validation.

Possessions (per directive): FGA + 0.44*FTA - OREB + TOV

Run:  .venv/bin/python -m wnba_v2.data.team_boxscores            # default seasons
      .venv/bin/python -m wnba_v2.data.team_boxscores 2024 2025  # specific seasons
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from datetime import date, timedelta

import numpy as np
import pandas as pd

from wnba_v2 import config as C

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"

CACHE_DIR = C.V2_ROOT / "data" / "team_games" / "_cache"
TEAM_GAMES_PATH = C.V2_ROOT / "data" / "team_games" / "team_game_logs.csv"
LAST_GOOD_PATH = C.V2_ROOT / "data" / "team_games" / "team_game_logs.last_good.csv"
VALIDATION_PATH = C.V2_ROOT / "data" / "team_games" / "validation_report.json"

DEFAULT_SEASONS = [2024, 2025, 2026]
SEASON_WINDOW = ((5, 1), (10, 31))   # WNBA runs ~May–Oct

REQUIRED = ["fga", "fta", "oreb", "tov", "points"]   # needed for clean possessions

# Raw (pre-derive) columns parse_game emits — the basis for re-derivation on merge.
BASE_COLS = ["game_id", "date", "season", "season_type", "team", "opponent", "home_away",
             "points", "fga", "fgm", "fg3a", "fg3m", "fta", "ftm",
             "oreb", "dreb", "reb", "ast", "stl", "blk", "tov", "pf"]


# --------------------------------------------------------------------------- #
# Fetch (pluggable source)
# --------------------------------------------------------------------------- #
def _get(url: str, retries: int = 3, timeout: int = 20) -> dict:
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last = e
            time.sleep(1.0 + i)
    raise RuntimeError(f"fetch failed after {retries}: {url} ({last})")


class BoxScoreSource:
    """Interface. Implement for any provider (ESPN here; stats.wnba.com later)."""
    def list_games(self, season: int) -> list[dict]: raise NotImplementedError
    def game_box(self, game_id: str) -> dict | None: raise NotImplementedError


class ESPNSource(BoxScoreSource):
    def list_games(self, season: int) -> list[dict]:
        (sm, sd), (em, ed) = SEASON_WINDOW
        cur, end = date(season, sm, sd), date(season, em, ed)
        games = {}
        while cur <= end:
            chunk_end = min(cur + timedelta(days=20), end)
            url = f"{ESPN_BASE}/scoreboard?dates={cur:%Y%m%d}-{chunk_end:%Y%m%d}&limit=200"
            try:
                data = _get(url)
            except RuntimeError:
                cur = chunk_end + timedelta(days=1); continue
            for e in data.get("events", []):
                comp = e["competitions"][0]
                if comp["status"]["type"]["name"] != "STATUS_FINAL":
                    continue
                games[e["id"]] = {
                    "game_id": e["id"],
                    "date": e["date"][:10],
                    "season": e.get("season", {}).get("year", season),
                    "season_type": comp["status"]["type"].get("name"),
                }
            cur = chunk_end + timedelta(days=1)
            time.sleep(0.3)
        return list(games.values())

    def game_box(self, game_id: str) -> dict | None:
        cache = CACHE_DIR / f"{game_id}.json"
        if cache.exists():
            return json.loads(cache.read_text())
        try:
            data = _get(f"{ESPN_BASE}/summary?event={game_id}")
        except RuntimeError:
            return None
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(data))
        time.sleep(0.25)
        return data


# --------------------------------------------------------------------------- #
# Parse
# --------------------------------------------------------------------------- #
def _ma(stats: dict, key: str) -> tuple[float, float]:
    """Parse a 'made-attempted' ESPN stat string -> (made, attempted)."""
    v = stats.get(key)
    if isinstance(v, str) and "-" in v:
        a, b = v.split("-", 1)
        try:
            return float(a), float(b)
        except ValueError:
            return np.nan, np.nan
    return np.nan, np.nan


def _num(stats: dict, key: str) -> float:
    try:
        return float(stats.get(key))
    except (TypeError, ValueError):
        return np.nan


def parse_game(summary: dict, meta: dict) -> list[dict]:
    """Return two canonical team rows for a game, or [] if incomplete (fail-closed)."""
    bs = summary.get("boxscore", {})
    teams = bs.get("teams", [])
    header = summary.get("header", {}).get("competitions", [{}])[0].get("competitors", [])
    if len(teams) != 2 or len(header) != 2:
        return []

    score = {c["team"].get("abbreviation"): _to_int(c.get("score")) for c in header}
    home = {c["team"].get("abbreviation"): (c.get("homeAway") == "home") for c in header}

    rows = []
    for t in teams:
        abbr = t["team"].get("abbreviation")
        stats = {s["name"]: s.get("displayValue") for s in t.get("statistics", [])}
        fgm, fga = _ma(stats, "fieldGoalsMade-fieldGoalsAttempted")
        ftm, fta = _ma(stats, "freeThrowsMade-freeThrowsAttempted")
        fg3m, fg3a = _ma(stats, "threePointFieldGoalsMade-threePointFieldGoalsAttempted")
        row = {
            **meta,
            "team": abbr,
            "home_away": "home" if home.get(abbr) else "away",
            "points": score.get(abbr, np.nan),
            "fga": fga, "fgm": fgm, "fg3a": fg3a, "fg3m": fg3m,
            "fta": fta, "ftm": ftm,
            "oreb": _num(stats, "offensiveRebounds"),
            "dreb": _num(stats, "defensiveRebounds"),
            "reb": _num(stats, "totalRebounds"),
            "ast": _num(stats, "assists"),
            "stl": _num(stats, "steals"),
            "blk": _num(stats, "blocks"),
            "tov": _num(stats, "turnovers"),
            "pf": _num(stats, "fouls"),
        }
        rows.append(row)
    # attach opponent abbreviation
    rows[0]["opponent"], rows[1]["opponent"] = rows[1]["team"], rows[0]["team"]
    # fail-closed: drop the whole game if either side is missing a required field
    for r in rows:
        if any(pd.isna(r.get(k)) for k in REQUIRED):
            return []
    return rows


def _to_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return np.nan


# --------------------------------------------------------------------------- #
# Derive + validate
# --------------------------------------------------------------------------- #
def derive(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["possessions"] = df["fga"] + 0.44 * df["fta"] - df["oreb"] + df["tov"]
    # opponent possessions / points via self-join on game_id
    opp = df[["game_id", "team", "possessions", "points"]].rename(
        columns={"team": "opponent", "possessions": "opp_possessions", "points": "opp_points"})
    df = df.merge(opp, on=["game_id", "opponent"], how="left")
    # game pace proxy = average possessions of the two teams (WNBA = 40-min regulation)
    df["game_possessions"] = (df["possessions"] + df["opp_possessions"]) / 2.0
    df["pace_proxy"] = df["game_possessions"]
    df["off_rating"] = 100.0 * df["points"] / df["possessions"]
    df["def_rating"] = 100.0 * df["opp_points"] / df["opp_possessions"]
    df["net_rating"] = df["off_rating"] - df["def_rating"]
    return df.sort_values(["date", "game_id", "home_away"]).reset_index(drop=True)


def validate(df: pd.DataFrame) -> dict:
    """Fail-closed quality gate. Returns a report; raises on corruption."""
    report, problems = {}, []
    # 1. exactly two rows per game
    counts = df.groupby("game_id").size()
    bad_games = counts[counts != 2]
    report["games"] = int(df["game_id"].nunique())
    report["team_rows"] = int(len(df))
    report["games_not_two_rows"] = int(len(bad_games))
    if len(bad_games) > 0:
        problems.append(f"{len(bad_games)} games without exactly 2 team rows")

    # 2. both teams similar possessions
    diff = (df["possessions"] - df["opp_possessions"]).abs()
    report["poss_diff_mean"] = round(float(diff.mean()), 3)
    report["poss_diff_p95"] = round(float(diff.quantile(0.95)), 3)
    report["games_poss_diff_gt8"] = int((diff > 8).sum())
    if diff.mean() > 5:
        problems.append(f"mean both-team possession diff {diff.mean():.2f} > 5 (suspect)")

    # 3. realistic possession distribution (NOT the 20+ std of the corrupt subset)
    report["poss_mean"] = round(float(df["possessions"].mean()), 2)
    report["poss_std"] = round(float(df["possessions"].std()), 2)
    report["poss_min"] = round(float(df["possessions"].min()), 2)
    report["poss_max"] = round(float(df["possessions"].max()), 2)
    if not (60 <= df["possessions"].mean() <= 95):
        problems.append(f"implausible mean possessions {df['possessions'].mean():.1f}")
    if df["possessions"].std() > 12:
        problems.append(f"possession std {df['possessions'].std():.1f} too high (corrupt/incomplete)")

    # 4. completeness
    miss = df[REQUIRED].isna().any(axis=1).mean()
    report["pct_rows_missing_required"] = round(float(miss) * 100, 2)
    if miss > 0.02:
        problems.append(f"{miss*100:.1f}% rows missing required fields")

    # 5. ratings sane
    report["off_rating_mean"] = round(float(df["off_rating"].mean()), 1)
    report["def_rating_mean"] = round(float(df["def_rating"].mean()), 1)

    report["by_season"] = df.groupby("season")["game_id"].nunique().to_dict()
    report["problems"] = problems
    report["passed"] = len(problems) == 0
    if not report["passed"]:
        raise ValueError("Team box-score validation FAILED (fail-closed): " + "; ".join(problems))
    return report


# --------------------------------------------------------------------------- #
# Build
# --------------------------------------------------------------------------- #
def build(seasons: list[int], source: BoxScoreSource | None = None) -> pd.DataFrame:
    source = source or ESPNSource()
    TEAM_GAMES_PATH.parent.mkdir(parents=True, exist_ok=True)
    all_rows, skipped = [], 0
    for season in seasons:
        games = source.list_games(season)
        print(f"  season {season}: {len(games)} final games")
        for meta in games:
            summary = source.game_box(meta["game_id"])
            if summary is None:
                skipped += 1; continue
            rows = parse_game(summary, meta)
            if not rows:
                skipped += 1; continue
            all_rows.extend(rows)
    if not all_rows:
        raise RuntimeError("No team rows ingested — check source reachability.")
    df = derive(pd.DataFrame(all_rows))
    print(f"  parsed {len(df)} team rows ({df['game_id'].nunique()} games); skipped {skipped}")
    report = validate(df)            # fail-closed: raises before any write
    _safe_write(df, report)
    return df


def _safe_write(df: pd.DataFrame, report: dict) -> None:
    """Atomic, last-good-protected write. Only reached after validation passes.
    Backs up the current good file, writes via a temp file, then os.replace()."""
    import os
    TEAM_GAMES_PATH.parent.mkdir(parents=True, exist_ok=True)
    if TEAM_GAMES_PATH.exists() and TEAM_GAMES_PATH.stat().st_size > 0:
        import shutil
        shutil.copy2(TEAM_GAMES_PATH, LAST_GOOD_PATH)
    tmp = TEAM_GAMES_PATH.with_suffix(".tmp.csv")
    df.to_csv(tmp, index=False)
    os.replace(tmp, TEAM_GAMES_PATH)
    VALIDATION_PATH.write_text(json.dumps(report, indent=2, default=str))


def build_incremental(current_season: int, source: BoxScoreSource | None = None) -> pd.DataFrame:
    """Refresh ONLY the current season (cache => only new games are fetched), merge
    with prior-season history, re-derive, validate the FULL set, and safe-write.
    Prior seasons are never lost; a corrupt refresh never overwrites last-good."""
    source = source or ESPNSource()
    fresh_rows = []
    for meta in source.list_games(current_season):
        summary = source.game_box(meta["game_id"])
        if summary is None:
            continue
        fresh_rows.extend(parse_game(summary, meta))
    if not fresh_rows:
        raise RuntimeError(f"No {current_season} rows fetched — refusing to touch last-good.")
    fresh = pd.DataFrame(fresh_rows)[BASE_COLS]

    if TEAM_GAMES_PATH.exists():
        prior = pd.read_csv(TEAM_GAMES_PATH)
        prior = prior[[c for c in BASE_COLS if c in prior.columns]]
        prior = prior[prior["season"] != current_season]
        merged = pd.concat([prior, fresh], ignore_index=True)
    else:
        merged = fresh
    merged = merged.drop_duplicates(["game_id", "team"], keep="last")

    df = derive(merged)
    print(f"  incremental: {len(fresh)} fresh {current_season} rows; merged total "
          f"{len(df)} rows ({df['game_id'].nunique()} games)")
    report = validate(df)            # fail-closed
    _safe_write(df, report)
    return df


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "incremental":
        season = int(args[1]) if len(args) > 1 else max(DEFAULT_SEASONS)
        print(f"Incremental refresh of WNBA team box scores for season {season}")
        build_incremental(season)
    else:
        seasons = [int(a) for a in args] or DEFAULT_SEASONS
        print(f"Full ingest of WNBA team box scores for seasons: {seasons}")
        build(seasons)
    print("\nVALIDATION:")
    print(json.dumps(json.loads(VALIDATION_PATH.read_text()), indent=2, default=str))
    print(f"\nCanonical -> {TEAM_GAMES_PATH}")
