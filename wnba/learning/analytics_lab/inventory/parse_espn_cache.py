"""Phase 2A — canonical player-game and team-game history from the ESPN cache.

Reparses every cached ESPN game summary into the lab's canonical tables. This is
the authoritative history for all lab work; it supersedes
``replay/build_history.py``, which merged the V2 box-score CSV (stale after
2026-06-28) onto the game index.

Design rules:

* Identity is by **ESPN numeric id** — ``player_id``, ``team_id``,
  ``opponent_id`` — never by name. A traded player keeps one ``player_id`` and
  carries whichever ``team_id`` appeared on that game's box score, so history
  stays correct across trades.
* Time is stored twice and never conflated: ``start_utc`` is the exact tip-off
  instant; ``slate_date_et`` is the derived America/New_York calendar date. The
  production ``game_date`` (a UTC date) is deliberately not reproduced.
* Uniqueness is explicit: ``(player_id, game_id)`` and ``(team_id, game_id)``.

Local cache only; no network access. Idempotent and resumable — parsed games are
cached in a per-game manifest and skipped on rerun unless ``--rebuild``.

Outputs (parquet + csv, under ``data/normalized/``):
    player_games.parquet / .csv
    team_games.parquet / .csv
    parse_manifest.csv
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from analytics_lab.config import lab_config as C
else:
    from ..config import lab_config as C

SEASON_TYPES = {1: "preseason", 2: "regular", 3: "postseason"}

# ESPN athlete stat keys -> lab column names. Order matches `keys`.
ATHLETE_STAT_MAP = {
    "minutes": "minutes",
    "points": "points",
    "rebounds": "rebounds",
    "assists": "assists",
    "turnovers": "turnovers",
    "steals": "steals",
    "blocks": "blocks",
    "offensiveRebounds": "offensive_rebounds",
    "defensiveRebounds": "defensive_rebounds",
    "fouls": "fouls",
    "plusMinus": "plus_minus",
}
# Keys stored as "made-attempted" pairs.
ATHLETE_SPLIT_MAP = {
    "fieldGoalsMade-fieldGoalsAttempted": ("fgm", "fga"),
    "threePointFieldGoalsMade-threePointFieldGoalsAttempted": ("threes_made", "threes_attempted"),
    "freeThrowsMade-freeThrowsAttempted": ("ftm", "fta"),
}
TEAM_STAT_MAP = {
    "totalRebounds": "team_rebounds",
    "offensiveRebounds": "team_offensive_rebounds",
    "defensiveRebounds": "team_defensive_rebounds",
    "assists": "team_assists",
    "steals": "team_steals",
    "blocks": "team_blocks",
    "turnovers": "team_turnovers",
    "totalTurnovers": "team_total_turnovers",
    "fouls": "team_fouls",
    "pointsInPaint": "team_points_in_paint",
    "fastBreakPoints": "team_fast_break_points",
    "turnoverPoints": "team_turnover_points",
}
TEAM_SPLIT_MAP = {
    "fieldGoalsMade-fieldGoalsAttempted": ("team_fgm", "team_fga"),
    "threePointFieldGoalsMade-threePointFieldGoalsAttempted": ("team_threes_made", "team_threes_attempted"),
    "freeThrowsMade-freeThrowsAttempted": ("team_ftm", "team_fta"),
}


def _number(value: object) -> float | None:
    """ESPN reports '--', '', '+5' and plain numbers in the same slot."""
    if value is None:
        return None
    text = str(value).strip().replace("+", "")
    if text in {"", "--", "-"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _split_pair(value: object) -> tuple[float | None, float | None]:
    if value is None or "-" not in str(value):
        return None, None
    made, _, attempted = str(value).partition("-")
    return _number(made), _number(attempted)


def _parse_game(game_id: str, payload: dict) -> tuple[list[dict], list[dict], dict]:
    """Return (player rows, team rows, manifest row) for one cached game."""
    header = payload.get("header") or {}
    competition = (header.get("competitions") or [{}])[0]
    season = header.get("season") or {}
    season_year = season.get("year")
    season_type = SEASON_TYPES.get(season.get("type"), "unknown")

    start_raw = competition.get("date")
    status = ((competition.get("status") or {}).get("type") or {})
    completed = bool(status.get("completed"))

    competitors = competition.get("competitors") or []
    by_id: dict[str, dict] = {}
    for side in competitors:
        team = side.get("team") or {}
        if team.get("id"):
            by_id[str(team["id"])] = {
                "team_id": str(team["id"]),
                "team_abbrev": team.get("abbreviation"),
                "home_away": side.get("homeAway"),
                "score": _number(side.get("score")),
            }
    opponent_of = {}
    ids = list(by_id)
    if len(ids) == 2:
        opponent_of = {ids[0]: ids[1], ids[1]: ids[0]}

    manifest = {
        "game_id": game_id,
        "start_utc": start_raw,
        "season": season_year,
        "season_type": season_type,
        "completed": completed,
        "teams_found": len(by_id),
        "status_detail": status.get("name"),
    }

    if not start_raw or len(by_id) != 2:
        manifest["skip_reason"] = "missing tip-off time" if not start_raw else "team count != 2"
        return [], [], manifest

    start_ts = pd.Timestamp(start_raw).tz_convert("UTC")
    slate_date_et = start_ts.tz_convert(C.SLATE_TIMEZONE).date().isoformat()
    common = {
        "game_id": game_id,
        "start_utc": start_ts.isoformat(),
        "slate_date_et": slate_date_et,
        "tip_hour_et": start_ts.tz_convert(C.SLATE_TIMEZONE).hour,
        "season": season_year,
        "season_type": season_type,
        "completed": completed,
    }

    # --- player rows --------------------------------------------------------
    player_rows: list[dict] = []
    starters_by_team: dict[str, int] = {}
    for team_block in (payload.get("boxscore") or {}).get("players", []) or []:
        team_id = str((team_block.get("team") or {}).get("id") or "")
        side = by_id.get(team_id, {})
        opponent_id = opponent_of.get(team_id)
        starters_by_team[team_id] = 0
        for stat_block in team_block.get("statistics", []) or []:
            keys = stat_block.get("keys") or []
            for athlete in stat_block.get("athletes", []) or []:
                info = athlete.get("athlete") or {}
                if not info.get("id"):
                    continue
                stats = athlete.get("stats") or []
                row = {
                    **common,
                    "player_id": str(info["id"]),
                    "player_name": info.get("displayName"),
                    "jersey": info.get("jersey"),
                    "position": (info.get("position") or {}).get("abbreviation"),
                    "team_id": team_id,
                    "team_abbrev": side.get("team_abbrev"),
                    "opponent_id": opponent_id,
                    "opponent_abbrev": (by_id.get(opponent_id) or {}).get("team_abbrev"),
                    "home_away": side.get("home_away"),
                    "is_home": 1 if side.get("home_away") == "home" else 0,
                    "starter": int(bool(athlete.get("starter"))),
                    "active": int(bool(athlete.get("active"))),
                    "did_not_play": int(bool(athlete.get("didNotPlay"))),
                    "dnp_reason": athlete.get("reason") if athlete.get("didNotPlay") else None,
                    "ejected": int(bool(athlete.get("ejected"))),
                    "team_score": side.get("score"),
                    "opponent_score": (by_id.get(opponent_id) or {}).get("score"),
                }
                starters_by_team[team_id] += row["starter"]
                lookup = dict(zip(keys, stats))
                for key, column in ATHLETE_STAT_MAP.items():
                    row[column] = _number(lookup.get(key))
                for key, (made_col, att_col) in ATHLETE_SPLIT_MAP.items():
                    row[made_col], row[att_col] = _split_pair(lookup.get(key))
                # A DNP has no stat line; zero is the truthful value, not null.
                if row["did_not_play"]:
                    for column in list(ATHLETE_STAT_MAP.values()):
                        if column != "plus_minus":
                            row[column] = 0.0
                row["played"] = 0 if row["did_not_play"] else 1
                player_rows.append(row)

    # --- team rows ----------------------------------------------------------
    team_rows: list[dict] = []
    for team_block in (payload.get("boxscore") or {}).get("teams", []) or []:
        team_id = str((team_block.get("team") or {}).get("id") or "")
        if team_id not in by_id:
            continue
        side = by_id[team_id]
        opponent_id = opponent_of.get(team_id)
        row = {
            **common,
            "team_id": team_id,
            "team_abbrev": side.get("team_abbrev"),
            "opponent_id": opponent_id,
            "opponent_abbrev": (by_id.get(opponent_id) or {}).get("team_abbrev"),
            "home_away": side.get("home_away"),
            "is_home": 1 if side.get("home_away") == "home" else 0,
            "team_points": side.get("score"),
            "opponent_points": (by_id.get(opponent_id) or {}).get("score"),
            "starters_flagged": starters_by_team.get(team_id),
        }
        lookup = {s.get("name"): s.get("displayValue") for s in team_block.get("statistics", []) or []}
        for key, column in TEAM_STAT_MAP.items():
            row[column] = _number(lookup.get(key))
        for key, (made_col, att_col) in TEAM_SPLIT_MAP.items():
            row[made_col], row[att_col] = _split_pair(lookup.get(key))
        team_rows.append(row)

    manifest["player_rows"] = len(player_rows)
    manifest["team_rows"] = len(team_rows)
    manifest["starters_flagged"] = sum(starters_by_team.values())
    return player_rows, team_rows, manifest


def _add_possessions(teams: pd.DataFrame) -> pd.DataFrame:
    """Standard possession estimate, then pace and ratings.

    poss = FGA - OREB + TOV + 0.44*FTA. Game possessions average the two sides,
    because the two estimates differ slightly and a shared value keeps a game's
    two rows internally consistent.
    """
    frame = teams.copy()
    turnovers = frame["team_total_turnovers"].fillna(frame["team_turnovers"])
    frame["possessions"] = (
        frame["team_fga"] - frame["team_offensive_rebounds"] + turnovers + 0.44 * frame["team_fta"]
    )
    shared = frame.groupby("game_id")["possessions"].transform("mean")
    frame["game_possessions"] = shared
    # 40-minute game; pace is possessions per 40 minutes, which for a regulation
    # game equals the possession count itself. Overtime is not adjusted for here
    # and is flagged rather than silently corrected.
    frame["pace"] = shared
    frame["off_rating"] = 100.0 * frame["team_points"] / shared.replace(0, pd.NA)
    frame["def_rating"] = 100.0 * frame["opponent_points"] / shared.replace(0, pd.NA)
    frame["net_rating"] = frame["off_rating"] - frame["def_rating"]
    return frame


def parse_cache(rebuild: bool = False) -> dict:
    cache_dir = C.V2_ESPN_CACHE_DIR
    if not cache_dir.exists():
        raise FileNotFoundError(f"ESPN summary cache not found at {cache_dir}")

    files = sorted(cache_dir.glob("*.json"))
    player_path = C.lab_path("normalized", "player_games.parquet")
    team_path = C.lab_path("normalized", "team_games.parquet")
    manifest_path = C.lab_path("normalized", "parse_manifest.csv")

    done: set[str] = set()
    old_players = old_teams = old_manifest = None
    if not rebuild and manifest_path.exists() and player_path.exists() and team_path.exists():
        old_manifest = pd.read_csv(manifest_path, dtype={"game_id": str})
        old_players = pd.read_parquet(player_path)
        old_teams = pd.read_parquet(team_path)
        done = set(old_manifest["game_id"].astype(str))

    players: list[dict] = []
    teams: list[dict] = []
    manifests: list[dict] = []
    failures: list[dict] = []

    for path in files:
        game_id = path.stem
        if game_id in done:
            continue
        try:
            payload = json.loads(path.read_text())
        except Exception as exc:
            failures.append({"game_id": game_id, "error": f"{type(exc).__name__}: {exc}"})
            manifests.append({"game_id": game_id, "skip_reason": f"unreadable: {type(exc).__name__}"})
            continue
        try:
            player_rows, team_rows, manifest = _parse_game(game_id, payload)
        except Exception as exc:
            failures.append({"game_id": game_id, "error": f"{type(exc).__name__}: {exc}"})
            manifests.append({"game_id": game_id, "skip_reason": f"parse error: {type(exc).__name__}"})
            continue
        players.extend(player_rows)
        teams.extend(team_rows)
        manifests.append(manifest)

    player_frame = pd.DataFrame(players)
    team_frame = pd.DataFrame(teams)
    manifest_frame = pd.DataFrame(manifests)
    if old_players is not None:
        player_frame = pd.concat([old_players, player_frame], ignore_index=True)
        team_frame = pd.concat([old_teams, team_frame], ignore_index=True)
        manifest_frame = pd.concat([old_manifest, manifest_frame], ignore_index=True)

    if not player_frame.empty:
        player_frame = (player_frame.drop_duplicates(["player_id", "game_id"], keep="last")
                                    .sort_values(["start_utc", "team_id", "player_id"])
                                    .reset_index(drop=True))
    if not team_frame.empty:
        team_frame = (team_frame.drop_duplicates(["team_id", "game_id"], keep="last")
                                 .sort_values(["start_utc", "team_id"]).reset_index(drop=True))
        team_frame = _add_possessions(team_frame)
    manifest_frame = manifest_frame.drop_duplicates("game_id", keep="last").reset_index(drop=True)

    player_frame.to_parquet(player_path, index=False)
    team_frame.to_parquet(team_path, index=False)
    C.write_csv(player_frame, "normalized", "player_games.csv")
    C.write_csv(team_frame, "normalized", "team_games.csv")
    C.write_csv(manifest_frame, "normalized", "parse_manifest.csv")

    return {
        "cache_files": len(files),
        "newly_parsed": len(manifests),
        "failures": failures,
        "players": player_frame,
        "teams": team_frame,
        "manifest": manifest_frame,
    }


def report(result: dict) -> None:
    players, teams, manifest = result["players"], result["teams"], result["manifest"]
    skipped = manifest[manifest.get("skip_reason").notna()] if "skip_reason" in manifest else manifest.iloc[0:0]

    print("PHASE 2A — ESPN CACHE REPARSE")
    print(f"  cache files discovered   {result['cache_files']}")
    print(f"  newly parsed this run    {result['newly_parsed']}")
    print(f"  games in manifest        {len(manifest)}")
    print(f"  games skipped            {len(skipped)}")
    print(f"  parse failures           {len(result['failures'])}")
    for failure in result["failures"][:5]:
        print(f"    {failure['game_id']}: {failure['error']}")
    print(f"  player-game rows         {len(players)}")
    print(f"  team-game rows           {len(teams)}")
    if players.empty:
        return

    print(f"  date range (ET slate)    {players.slate_date_et.min()} -> {players.slate_date_et.max()}")
    print(f"  duplicate (player_id, game_id)  {players.duplicated(['player_id','game_id']).sum()}")
    print(f"  duplicate (team_id, game_id)    {teams.duplicated(['team_id','game_id']).sum()}")
    print(f"  missing player_id        {players.player_id.isna().sum()}")
    print(f"  missing team_id          {players.team_id.isna().sum()}")
    print(f"  missing opponent_id      {players.opponent_id.isna().sum()}")
    print(f"  missing tip time         {players.start_utc.isna().sum()}")
    print(f"  missing position         {players.position.isna().sum()}")

    print("\n  season / type counts")
    counts = players.groupby(["season", "season_type"]).agg(
        player_rows=("player_id", "size"), games=("game_id", "nunique"),
        players=("player_id", "nunique"), first=("slate_date_et", "min"), last=("slate_date_et", "max"),
    )
    print(counts.to_string().replace("\n", "\n    "))

    anomalies = teams[teams.starters_flagged != 5]
    print(f"\n  starter-count anomalies (team-games without exactly 5)  {len(anomalies)}")
    if not anomalies.empty:
        print(anomalies[["game_id", "team_abbrev", "starters_flagged"]].head().to_string())

    dnp = players[players.did_not_play == 1]
    print(f"\n  DNP rows {len(dnp)} ({len(dnp)/len(players):.1%} of player-games)")
    reasons = dnp.dnp_reason.fillna("(none given)").value_counts()
    print(f"    distinct reasons {reasons.size}; top:")
    for reason, count in reasons.head(6).items():
        print(f"      {str(reason)[:44]:<46} {count}")
    injury_like = dnp[~dnp.dnp_reason.fillna("").str.upper().isin(
        {"COACH'S DECISION", "COACHES DECISION", ""})]
    print(f"    non-coach's-decision (injury/rest/personal) {len(injury_like)} "
          f"({len(injury_like)/max(len(dnp),1):.1%} of DNPs)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rebuild", action="store_true", help="reparse every cached game")
    report(parse_cache(rebuild=parser.parse_args().rebuild))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
