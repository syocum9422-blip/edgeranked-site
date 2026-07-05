"""Phase 6.2 - ESPN-first canonical WNBA datasets.

Builds production-compatible canonical history from ESPN cached summaries. The
stats.wnba.com feed may still enrich elsewhere, but this path is sufficient for
historical player minutes/statistics, starts, positions, team context, and game
logs without stats.wnba.com.

Run:  python3 -m wnba_v2.data.espn_canonical
"""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from wnba_model_config import (
    CANONICAL_PLAYER_GAMES_PATH,
    CANONICAL_TEAM_CONTEXT_PATH,
    RAW_DIR,
)
from wnba_model_utils import canonicalize_name, standardize_team_abbrev
from wnba_v2 import config as C
from wnba_v2.data import player_boxscores, team_boxscores

OUT = C.OUTPUTS / "phase62"
PLAYER_BOXSCORES_PATH = C.V2_ROOT / "data" / "team_games" / "player_boxscores.csv"
TEAM_GAME_LOGS_PATH = team_boxscores.TEAM_GAMES_PATH
SOURCE_VALUE = "espn"
ALLOWED_SOURCES = {"espn", "stats_wnba", "merged"}


@dataclass
class ESPNCanonicalBundle:
    player_games: pd.DataFrame
    team_context: pd.DataFrame
    player_boxscores: pd.DataFrame
    team_game_logs: pd.DataFrame
    validation: dict


def _ensure_espn_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load ESPN-native logs, building player logs from cached summaries if needed."""
    if not TEAM_GAME_LOGS_PATH.exists():
        raise FileNotFoundError(
            f"Missing ESPN team game log {TEAM_GAME_LOGS_PATH}. "
            "Run python3 -m wnba_v2.data.team_boxscores first."
        )
    team_logs = pd.read_csv(TEAM_GAME_LOGS_PATH, parse_dates=["date"])
    if not player_boxscores.PLAYER_GAMES_PATH.exists():
        player_boxscores.build()
    player_logs = pd.read_csv(player_boxscores.PLAYER_GAMES_PATH, parse_dates=["date"])
    return player_logs, team_logs


def _home_away(team_logs: pd.DataFrame) -> pd.DataFrame:
    return team_logs[["game_id", "team", "home_away"]].copy()


def _canonical_player_games(player_logs: pd.DataFrame, team_logs: pd.DataFrame) -> pd.DataFrame:
    frame = player_logs.copy()
    frame = frame.merge(_home_away(team_logs), on=["game_id", "team"], how="left")
    frame["game_date"] = pd.to_datetime(frame["date"]).dt.normalize()
    frame["team"] = frame["team"].map(standardize_team_abbrev)
    frame["opponent"] = frame["opponent"].map(standardize_team_abbrev)
    frame["home_away"] = frame["home_away"].map({"home": "H", "away": "A"}).fillna("A")
    frame["player_key"] = frame["player_name"].map(canonicalize_name)
    frame["is_home"] = (frame["home_away"] == "H").astype(int)
    out = pd.DataFrame({
        "game_date": frame["game_date"],
        "season": frame["season"],
        "game_id": frame["game_id"].astype(str),
        "player_name": frame["player_name"],
        "player_id": frame["player_id"],
        "player_key": frame["player_key"],
        "team": frame["team"],
        "opponent": frame["opponent"],
        "home_away": frame["home_away"],
        "is_home": frame["is_home"],
        "position": frame["position"].fillna("UNK"),
        "starter": frame["starter"].fillna(0).astype(int),
        "played": frame["played"].fillna(0).astype(int),
        "minutes": pd.to_numeric(frame["minutes"], errors="coerce"),
        "points": pd.to_numeric(frame["points"], errors="coerce"),
        "rebounds": pd.to_numeric(frame["reb"], errors="coerce"),
        "assists": pd.to_numeric(frame["ast"], errors="coerce"),
        "threes_made": pd.to_numeric(frame["fg3m"], errors="coerce"),
        "steals": pd.to_numeric(frame["stl"], errors="coerce"),
        "blocks": pd.to_numeric(frame["blk"], errors="coerce"),
        "turnovers": pd.to_numeric(frame["tov"], errors="coerce"),
        "fga": pd.to_numeric(frame["fga"], errors="coerce"),
        "fgm": pd.to_numeric(frame["fgm"], errors="coerce"),
        "fta": pd.to_numeric(frame["fta"], errors="coerce"),
        "ftm": pd.to_numeric(frame["ftm"], errors="coerce"),
        "offensive_rebounds": pd.to_numeric(frame["oreb"], errors="coerce"),
        "defensive_rebounds": pd.to_numeric(frame["dreb"], errors="coerce"),
        "plus_minus": pd.NA,
        "source": SOURCE_VALUE,
        "_data_source": SOURCE_VALUE,
    })
    return out.sort_values(["game_date", "game_id", "team", "starter", "player_name"]).reset_index(drop=True)


def _canonical_team_context(team_logs: pd.DataFrame) -> pd.DataFrame:
    frame = team_logs.copy()
    frame["game_date"] = pd.to_datetime(frame["date"]).dt.normalize()
    frame["team"] = frame["team"].map(standardize_team_abbrev)
    frame["opponent"] = frame["opponent"].map(standardize_team_abbrev)
    out = pd.DataFrame({
        "game_date": frame["game_date"],
        "season": frame["season"],
        "game_id": frame["game_id"].astype(str),
        "team": frame["team"],
        "opponent": frame["opponent"],
        "pace": pd.to_numeric(frame["pace_proxy"], errors="coerce"),
        "off_rating": pd.to_numeric(frame["off_rating"], errors="coerce"),
        "def_rating": pd.to_numeric(frame["def_rating"], errors="coerce"),
        "team_points": pd.to_numeric(frame["points"], errors="coerce"),
        "opp_points": pd.to_numeric(frame["opp_points"], errors="coerce"),
        "team_rebounds": pd.to_numeric(frame["reb"], errors="coerce"),
        "team_assists": pd.to_numeric(frame["ast"], errors="coerce"),
        "team_threes_made": pd.to_numeric(frame["fg3m"], errors="coerce"),
        "team_steals": pd.to_numeric(frame["stl"], errors="coerce"),
        "team_blocks": pd.to_numeric(frame["blk"], errors="coerce"),
        "source": SOURCE_VALUE,
        "_data_source": SOURCE_VALUE,
    })
    return out.sort_values(["game_date", "game_id", "team"]).reset_index(drop=True)


def _compare_current(path: Path, espn: pd.DataFrame, date_col: str) -> dict:
    if not path.exists():
        return {"path": str(path), "exists": False}
    current = pd.read_csv(path, parse_dates=[date_col])
    start = pd.to_datetime(espn[date_col]).min()
    overlap = current[pd.to_datetime(current[date_col]) >= start]
    return {
        "path": str(path),
        "exists": True,
        "current_rows": int(len(current)),
        "current_overlap_rows": int(len(overlap)),
        "espn_rows": int(len(espn)),
        "espn_start_date": str(start.date()),
        "row_delta_vs_overlap": int(len(espn) - len(overlap)),
    }


def validate(player_games: pd.DataFrame, team_context: pd.DataFrame, current_player_path: Path = CANONICAL_PLAYER_GAMES_PATH) -> dict:
    problems: list[str] = []
    played = player_games[player_games["played"] == 1]
    team_game_counts = team_context.groupby("game_id").size()
    player_dupes = int(player_games.duplicated(["game_id", "team", "player_id"]).sum())
    team_dupes = int(team_context.duplicated(["game_id", "team"]).sum())
    starter_counts = player_games.groupby(["game_id", "team"])["starter"].sum()
    missing_minutes_pct = float(played["minutes"].isna().mean() * 100) if len(played) else 100.0
    source_values = set(player_games["source"].dropna().unique()) | set(team_context["source"].dropna().unique())

    if len(team_context) == 0 or len(player_games) == 0:
        problems.append("ESPN canonical outputs are empty")
    if int((team_game_counts != 2).sum()) > 0:
        problems.append("Some ESPN games do not have exactly two team rows")
    if player_dupes:
        problems.append(f"{player_dupes} duplicate ESPN player-game rows")
    if team_dupes:
        problems.append(f"{team_dupes} duplicate ESPN team-game rows")
    if missing_minutes_pct > 0.5:
        problems.append(f"Missing played-minute percentage {missing_minutes_pct:.2f}% > 0.50%")
    if float((starter_counts == 5).mean() * 100) < 95.0:
        problems.append("Starter flag coverage below 95% of team-games with exactly five starters")
    if not source_values.issubset(ALLOWED_SOURCES):
        problems.append(f"Unexpected source values: {sorted(source_values - ALLOWED_SOURCES)}")

    current_cmp = _compare_current(current_player_path, player_games, "game_date")
    if current_cmp.get("exists") and current_cmp["espn_rows"] < current_cmp["current_overlap_rows"]:
        problems.append(
            "ESPN player-game rows regress current overlap coverage: "
            f"{current_cmp['espn_rows']} < {current_cmp['current_overlap_rows']}"
        )

    report = {
        "passed": not problems,
        "problems": problems,
        "source_values": sorted(source_values),
        "game_count": int(team_context["game_id"].nunique()),
        "team_game_rows": int(len(team_context)),
        "player_game_rows": int(len(player_games)),
        "played_player_game_rows": int(len(played)),
        "game_count_parity_bad_games": int((team_game_counts != 2).sum()),
        "missing_minute_pct_played": round(missing_minutes_pct, 4),
        "duplicate_player_games": player_dupes,
        "duplicate_team_games": team_dupes,
        "starter_team_games": int(len(starter_counts)),
        "starter_exactly_five_pct": round(float((starter_counts == 5).mean() * 100), 2),
        "starter_missing_pct": round(float(player_games["starter"].isna().mean() * 100), 4),
        "position_missing_pct": round(float(player_games["position"].isna().mean() * 100), 4),
        "row_count_comparison": {
            "player_games": current_cmp,
            "team_context": _compare_current(CANONICAL_TEAM_CONTEXT_PATH, team_context, "game_date"),
        },
        "by_season": {
            "player_games": player_games.groupby("season").size().to_dict(),
            "team_games": team_context.groupby("season")["game_id"].nunique().to_dict(),
        },
    }
    if problems:
        raise ValueError("ESPN canonical validation FAILED: " + "; ".join(problems))
    return report


def _safe_write(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > 0:
        backup = path.with_suffix(path.suffix + ".last_good")
        shutil.copy2(path, backup)
    tmp = path.with_suffix(path.suffix + ".tmp")
    df.to_csv(tmp, index=False)
    os.replace(tmp, path)


def _write_report(report: dict) -> None:
    lines = [
        "# Phase 6.2 ESPN-First Data Migration",
        "",
        "ESPN is the canonical source for historical WNBA player box scores, minutes, starts, positions, team game logs, and team context.",
        "stats.wnba.com is optional enrichment/fallback only; production historical data no longer requires it.",
        "",
        "## Validation",
        f"Passed: {report['passed']}",
        f"Games: {report['game_count']}",
        f"Team-game rows: {report['team_game_rows']}",
        f"Player-game rows: {report['player_game_rows']}",
        f"Played player-game rows: {report['played_player_game_rows']}",
        f"Missing played minutes: {report['missing_minute_pct_played']}%",
        f"Starter exactly-five coverage: {report['starter_exactly_five_pct']}%",
        f"Duplicate player games: {report['duplicate_player_games']}",
        f"Duplicate team games: {report['duplicate_team_games']}",
        "",
        "## Row Count Comparisons",
    ]
    for name, cmp in report["row_count_comparison"].items():
        if not cmp.get("exists"):
            lines.append(f"- {name}: no prior file at {cmp['path']}")
            continue
        lines.append(
            f"- {name}: current_rows={cmp['current_rows']}, current_overlap_rows={cmp['current_overlap_rows']}, "
            f"espn_rows={cmp['espn_rows']}, espn_start={cmp['espn_start_date']}, "
            f"delta_vs_overlap={cmp['row_delta_vs_overlap']}"
        )
    lines.extend([
        "",
        "## Outputs",
        f"- {CANONICAL_PLAYER_GAMES_PATH}",
        f"- {CANONICAL_TEAM_CONTEXT_PATH}",
        f"- {PLAYER_BOXSCORES_PATH}",
        f"- {TEAM_GAME_LOGS_PATH}",
        "",
        "## Cron Changes Required",
        "Run ESPN canonicalization after the ESPN boxscore refresh and before dataset/model builds:",
        "python3 -m wnba_v2.data.team_boxscores incremental $WNBA_V2_CURRENT_SEASON",
        "python3 -m wnba_v2.data.espn_canonical",
        "python3 build_wnba_dataset.py",
    ])
    (OUT / "phase62_migration_report.md").write_text("\n".join(lines) + "\n")


def build(write_outputs: bool = True) -> ESPNCanonicalBundle:
    OUT.mkdir(parents=True, exist_ok=True)
    player_logs, team_logs = _ensure_espn_inputs()
    player_games = _canonical_player_games(player_logs, team_logs)
    team_context = _canonical_team_context(team_logs)
    validation = validate(player_games, team_context)

    if write_outputs:
        _safe_write(player_games, CANONICAL_PLAYER_GAMES_PATH)
        _safe_write(team_context, CANONICAL_TEAM_CONTEXT_PATH)
        _safe_write(player_games, PLAYER_BOXSCORES_PATH)
        _safe_write(team_logs.assign(source=SOURCE_VALUE, _data_source=SOURCE_VALUE), TEAM_GAME_LOGS_PATH)
        (OUT / "phase62_validation.json").write_text(json.dumps(validation, indent=2, default=str))
        player_games.head(250).to_csv(OUT / "player_games_preview.csv", index=False)
        team_context.head(250).to_csv(OUT / "team_context_preview.csv", index=False)
        _write_report(validation)

    return ESPNCanonicalBundle(
        player_games=player_games,
        team_context=team_context,
        player_boxscores=player_games,
        team_game_logs=team_logs,
        validation=validation,
    )


if __name__ == "__main__":
    bundle = build(write_outputs=True)
    print(json.dumps(bundle.validation, indent=2, default=str))
