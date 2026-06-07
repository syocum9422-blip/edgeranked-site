from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from wnba_model_config import (
    CANONICAL_PLAYER_GAMES_PATH,
    PROJECTIONS_ARCHIVE_DIR,
    PROJECTIONS_PATH,
)
from fetch_wnba_espn_actuals import fetch_recent_actuals
from wnba_model_utils import canonicalize_name, setup_logging, standardize_team_abbrev


LEARNING_DIR = PROJECTIONS_PATH.parent / "learning"
ERRORS_DIR = LEARNING_DIR / "errors"
PROJECTION_ERRORS_PATH = ERRORS_DIR / "projection_errors.csv"
MINUTES_ERRORS_PATH = ERRORS_DIR / "minutes_errors.csv"
UNMATCHED_PROJECTION_ERRORS_PATH = ERRORS_DIR / "unmatched_projection_errors.csv"
UNMATCHED_MINUTES_ERRORS_PATH = ERRORS_DIR / "unmatched_minutes_errors.csv"
JOIN_DIAGNOSTICS_PATH = PROJECTIONS_PATH.parent / "data" / "processed" / "wnba_join_diagnostics_report.csv"
UNMATCHED_ACTUALS_PATH = PROJECTIONS_PATH.parent / "data" / "processed" / "wnba_unmatched_actuals_report.csv"

PROJECTION_ERROR_COLUMNS = [
    "slate_date",
    "game_date",
    "player_name",
    "player_id",
    "player_key",
    "team",
    "opponent",
    "stat",
    "projected_value",
    "actual_value",
    "error",
    "absolute_error",
    "squared_error",
    "source_file",
    "created_at_utc",
]

MINUTES_ERROR_COLUMNS = [
    "slate_date",
    "game_date",
    "player_name",
    "player_id",
    "player_key",
    "team",
    "opponent",
    "projected_minutes",
    "actual_minutes",
    "error",
    "absolute_error",
    "squared_error",
    "source_file",
    "created_at_utc",
]

UNMATCHED_PROJECTION_COLUMNS = [
    "slate_date",
    "game_date",
    "player_name",
    "player_id",
    "player_key",
    "team",
    "opponent",
    "stat",
    "projected_value",
    "source_file",
    "reason",
    "candidate_actual_rows",
    "created_at_utc",
]

UNMATCHED_MINUTES_COLUMNS = [
    "slate_date",
    "game_date",
    "player_name",
    "player_id",
    "player_key",
    "team",
    "opponent",
    "projected_minutes",
    "source_file",
    "reason",
    "candidate_actual_rows",
    "created_at_utc",
]

STAT_PROJECTION_MAP = {
    "points": ["PTS_PROJ", "pts_proj"],
    "rebounds": ["REB_PROJ", "reb_proj"],
    "assists": ["AST_PROJ", "ast_proj"],
    "threes_made": ["FG3M_PROJ", "fg3m_proj"],
    "steals": ["STL_PROJ", "stl_proj"],
    "blocks": ["BLK_PROJ", "blk_proj"],
}


def created_at_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_csv(path: Path, frame: pd.DataFrame, columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if frame.empty:
        pd.DataFrame(columns=columns).to_csv(path, index=False)
    else:
        frame.reindex(columns=columns).to_csv(path, index=False)


def projection_sources() -> dict[str, Path]:
    sources: dict[str, Path] = {}
    current_candidates = [PROJECTIONS_PATH]
    archive_candidates = sorted(PROJECTIONS_ARCHIVE_DIR.glob("wnba_projections_*.csv"))

    for path in [*archive_candidates, *current_candidates]:
        if not path.exists():
            continue
        try:
            frame = pd.read_csv(path, nrows=5)
        except Exception:
            continue
        if frame.empty:
            continue
        date_series = pd.Series(dtype="object")
        for candidate in ["GAME_DATE", "game_date", "DATE", "date"]:
            if candidate in frame.columns:
                date_series = pd.to_datetime(frame[candidate], errors="coerce").dropna()
                if not date_series.empty:
                    break
        if date_series.empty:
            stem_parts = path.stem.rsplit("_", 1)
            if len(stem_parts) == 2 and stem_parts[1].isdigit() and len(stem_parts[1]) == 8:
                slate_date = f"{stem_parts[1][0:4]}-{stem_parts[1][4:6]}-{stem_parts[1][6:8]}"
            else:
                continue
        else:
            slate_date = date_series.iloc[0].date().isoformat()
        existing = sources.get(slate_date)
        if existing is None or path == PROJECTIONS_PATH or path.stat().st_mtime > existing.stat().st_mtime:
            sources[slate_date] = path
    return dict(sorted(sources.items()))


def normalize_projection_frame(frame: pd.DataFrame, source_path: Path, slate_date: str) -> pd.DataFrame:
    normalized = frame.copy()
    date_series = pd.Series([slate_date] * len(normalized), index=normalized.index, dtype="object")
    for candidate in ["GAME_DATE", "game_date", "DATE", "date"]:
        if candidate in normalized.columns:
            parsed = pd.to_datetime(normalized[candidate], errors="coerce").dt.date.astype(str)
            date_series = parsed.where(parsed != "NaT", slate_date)
            break
    normalized["slate_date"] = date_series.astype(str)
    normalized["game_date"] = normalized["slate_date"]
    player_name_series = normalized["PLAYER_NAME"] if "PLAYER_NAME" in normalized.columns else normalized.get("player_name")
    if player_name_series is None:
        player_name_series = pd.Series([""] * len(normalized), index=normalized.index)
    normalized["player_name"] = player_name_series.astype(str)
    player_key_series = normalized["PLAYER_KEY"] if "PLAYER_KEY" in normalized.columns else normalized.get("player_key")
    if player_key_series is None:
        player_key_series = pd.Series([""] * len(normalized), index=normalized.index)
    normalized["player_key"] = player_key_series.fillna("").astype(str)
    missing_key = normalized["player_key"].str.strip() == ""
    normalized.loc[missing_key, "player_key"] = normalized.loc[missing_key, "player_name"].map(canonicalize_name)
    normalized["player_id"] = normalized["player_key"]
    team_series = normalized["TEAM_ABBREVIATION"] if "TEAM_ABBREVIATION" in normalized.columns else normalized.get("team")
    opponent_series = normalized["OPPONENT_ABBREVIATION"] if "OPPONENT_ABBREVIATION" in normalized.columns else normalized.get("opponent")
    normalized["team"] = (team_series if team_series is not None else pd.Series([""] * len(normalized), index=normalized.index)).map(standardize_team_abbrev)
    normalized["opponent"] = (opponent_series if opponent_series is not None else pd.Series([""] * len(normalized), index=normalized.index)).map(standardize_team_abbrev)
    normalized["source_file"] = str(source_path)
    return normalized


def projection_value(row: pd.Series, candidates: list[str]) -> float:
    for candidate in candidates:
        if candidate in row.index:
            value = pd.to_numeric(row.get(candidate), errors="coerce")
            if pd.notna(value):
                return float(value)
    return np.nan


def load_actuals() -> pd.DataFrame:
    if not CANONICAL_PLAYER_GAMES_PATH.exists():
        return pd.DataFrame()
    actuals = pd.read_csv(CANONICAL_PLAYER_GAMES_PATH)
    if actuals.empty:
        return actuals
    actuals["game_date"] = pd.to_datetime(actuals.get("game_date"), errors="coerce").dt.date.astype(str)
    actuals["player_name"] = actuals.get("player_name").astype(str)
    if "player_key" not in actuals.columns:
        actuals["player_key"] = actuals["player_name"].map(canonicalize_name)
    actuals["player_key"] = actuals["player_key"].fillna("").astype(str)
    actuals["name_key"] = actuals["player_name"].map(canonicalize_name)
    actuals["team"] = actuals.get("team", "").map(standardize_team_abbrev)
    actuals["opponent"] = actuals.get("opponent", "").map(standardize_team_abbrev)
    return actuals


def match_actual_row(actuals: pd.DataFrame, projection_row: pd.Series) -> tuple[pd.Series | None, str, int]:
    game_date = str(projection_row.get("game_date", ""))
    player_key = str(projection_row.get("player_key", "")).strip()
    player_name = str(projection_row.get("player_name", ""))
    team = str(projection_row.get("team", "")).strip().upper()
    opponent = str(projection_row.get("opponent", "")).strip().upper()

    candidates = actuals[actuals["game_date"] == game_date].copy()
    if candidates.empty:
        return None, "no_actual_rows_for_game_date", 0

    if player_key:
        exact = candidates[candidates["player_key"].astype(str).str.strip() == player_key]
        if len(exact) == 1:
            return exact.iloc[0], "", 1
        if len(exact) > 1:
            narrowed = exact[
                (exact["team"].astype(str).str.upper() == team)
                & (exact["opponent"].astype(str).str.upper() == opponent)
            ]
            if len(narrowed) == 1:
                return narrowed.iloc[0], "", 1
            return None, "multiple_actual_rows_for_player_key", len(exact)

    name_key = canonicalize_name(player_name)
    by_name = candidates[candidates["name_key"] == name_key]
    if len(by_name) == 1:
        return by_name.iloc[0], "", 1
    if len(by_name) > 1:
        narrowed = by_name[
            (by_name["team"].astype(str).str.upper() == team)
            & (by_name["opponent"].astype(str).str.upper() == opponent)
        ]
        if len(narrowed) == 1:
            return narrowed.iloc[0], "", 1
        return None, "multiple_actual_rows_for_player_name", len(by_name)

    return None, "no_safe_player_match", 0


def build_error_outputs(actuals: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    projection_rows: list[dict] = []
    minutes_rows: list[dict] = []
    unmatched_projection_rows: list[dict] = []
    unmatched_minutes_rows: list[dict] = []
    timestamp = created_at_utc()

    for slate_date, source_path in projection_sources().items():
        frame = pd.read_csv(source_path)
        if frame.empty:
            continue
        normalized = normalize_projection_frame(frame, source_path, slate_date)
        for _, row in normalized.iterrows():
            actual_row, reason, candidate_count = match_actual_row(actuals, row)
            projected_minutes = projection_value(row, ["PRED_MIN", "projected_minutes", "MIN_PROJ"])
            if actual_row is None:
                unmatched_minutes_rows.append(
                    {
                        "slate_date": slate_date,
                        "game_date": row.get("game_date"),
                        "player_name": row.get("player_name"),
                        "player_id": row.get("player_id"),
                        "player_key": row.get("player_key"),
                        "team": row.get("team"),
                        "opponent": row.get("opponent"),
                        "projected_minutes": projected_minutes,
                        "source_file": row.get("source_file"),
                        "reason": reason,
                        "candidate_actual_rows": candidate_count,
                        "created_at_utc": timestamp,
                    }
                )
                for stat, projection_columns in STAT_PROJECTION_MAP.items():
                    unmatched_projection_rows.append(
                        {
                            "slate_date": slate_date,
                            "game_date": row.get("game_date"),
                            "player_name": row.get("player_name"),
                            "player_id": row.get("player_id"),
                            "player_key": row.get("player_key"),
                            "team": row.get("team"),
                            "opponent": row.get("opponent"),
                            "stat": stat,
                            "projected_value": projection_value(row, projection_columns),
                            "source_file": row.get("source_file"),
                            "reason": reason,
                            "candidate_actual_rows": candidate_count,
                            "created_at_utc": timestamp,
                        }
                    )
                continue

            actual_minutes = pd.to_numeric(actual_row.get("minutes"), errors="coerce")
            if pd.notna(projected_minutes) and pd.notna(actual_minutes):
                minutes_error = projected_minutes - actual_minutes
                minutes_rows.append(
                    {
                        "slate_date": slate_date,
                        "game_date": row.get("game_date"),
                        "player_name": row.get("player_name"),
                        "player_id": row.get("player_id"),
                        "player_key": row.get("player_key"),
                        "team": row.get("team"),
                        "opponent": row.get("opponent"),
                        "projected_minutes": projected_minutes,
                        "actual_minutes": actual_minutes,
                        "error": minutes_error,
                        "absolute_error": abs(minutes_error),
                        "squared_error": minutes_error**2,
                        "source_file": row.get("source_file"),
                        "created_at_utc": timestamp,
                    }
                )
            else:
                unmatched_minutes_rows.append(
                    {
                        "slate_date": slate_date,
                        "game_date": row.get("game_date"),
                        "player_name": row.get("player_name"),
                        "player_id": row.get("player_id"),
                        "player_key": row.get("player_key"),
                        "team": row.get("team"),
                        "opponent": row.get("opponent"),
                        "projected_minutes": projected_minutes,
                        "source_file": row.get("source_file"),
                        "reason": "missing_projected_or_actual_minutes",
                        "candidate_actual_rows": 1,
                        "created_at_utc": timestamp,
                    }
                )

            for stat, projection_columns in STAT_PROJECTION_MAP.items():
                projected_value = projection_value(row, projection_columns)
                actual_value = pd.to_numeric(actual_row.get(stat), errors="coerce")
                if pd.isna(projected_value) or pd.isna(actual_value):
                    unmatched_projection_rows.append(
                        {
                            "slate_date": slate_date,
                            "game_date": row.get("game_date"),
                            "player_name": row.get("player_name"),
                            "player_id": row.get("player_id"),
                            "player_key": row.get("player_key"),
                            "team": row.get("team"),
                            "opponent": row.get("opponent"),
                            "stat": stat,
                            "projected_value": projected_value,
                            "source_file": row.get("source_file"),
                            "reason": "missing_projected_or_actual_value",
                            "candidate_actual_rows": 1,
                            "created_at_utc": timestamp,
                        }
                    )
                    continue
                error = projected_value - actual_value
                projection_rows.append(
                    {
                        "slate_date": slate_date,
                        "game_date": row.get("game_date"),
                        "player_name": row.get("player_name"),
                        "player_id": row.get("player_id"),
                        "player_key": row.get("player_key"),
                        "team": row.get("team"),
                        "opponent": row.get("opponent"),
                        "stat": stat,
                        "projected_value": projected_value,
                        "actual_value": actual_value,
                        "error": error,
                        "absolute_error": abs(error),
                        "squared_error": error**2,
                        "source_file": row.get("source_file"),
                        "created_at_utc": timestamp,
                    }
                )

    projection_df = pd.DataFrame(projection_rows).drop_duplicates(
        subset=["slate_date", "player_key", "stat", "source_file"],
        keep="last",
    )
    minutes_df = pd.DataFrame(minutes_rows).drop_duplicates(
        subset=["slate_date", "player_key", "source_file"],
        keep="last",
    )
    unmatched_projection_df = pd.DataFrame(unmatched_projection_rows).drop_duplicates(
        subset=["slate_date", "player_key", "stat", "source_file", "reason"],
        keep="last",
    )
    unmatched_minutes_df = pd.DataFrame(unmatched_minutes_rows).drop_duplicates(
        subset=["slate_date", "player_key", "source_file", "reason"],
        keep="last",
    )
    return projection_df, minutes_df, unmatched_projection_df, unmatched_minutes_df



def projection_player_rows() -> pd.DataFrame:
    rows = []
    for slate_date, source_path in projection_sources().items():
        frame = pd.read_csv(source_path)
        if frame.empty:
            continue
        rows.append(normalize_projection_frame(frame, source_path, slate_date))
    if not rows:
        return pd.DataFrame()
    return pd.concat(rows, ignore_index=True, sort=False)


def write_join_diagnostics(
    actuals: pd.DataFrame,
    projection_errors: pd.DataFrame,
    minutes_errors: pd.DataFrame,
    unmatched_projection_errors: pd.DataFrame,
    unmatched_minutes_errors: pd.DataFrame,
) -> None:
    projections = projection_player_rows()
    prediction_player_rows = int(len(projections))
    prediction_stat_rows = prediction_player_rows * len(STAT_PROJECTION_MAP)
    matched_stat_rows = int(len(projection_errors))
    projection_dates = set(projections.get("game_date", pd.Series(dtype=str)).dropna().astype(str))
    actuals_in_scope = actuals[actuals["game_date"].astype(str).isin(projection_dates)].copy() if projection_dates else actuals.iloc[0:0].copy()
    unmatched_by_reason = (
        unmatched_projection_errors.groupby("reason").size().reset_index(name="rows")
        if not unmatched_projection_errors.empty
        else pd.DataFrame(columns=["reason", "rows"])
    )
    summary_rows = [
        {"metric": "prediction_player_rows", "value": prediction_player_rows, "detail": ""},
        {"metric": "prediction_stat_rows", "value": prediction_stat_rows, "detail": ""},
        {"metric": "actual_player_rows_in_scope", "value": int(len(actuals_in_scope)), "detail": ""},
        {"metric": "matched_projection_stat_rows", "value": matched_stat_rows, "detail": ""},
        {"metric": "matched_minutes_rows", "value": int(len(minutes_errors)), "detail": ""},
        {"metric": "unmatched_projection_stat_rows", "value": int(len(unmatched_projection_errors)), "detail": ""},
        {"metric": "unmatched_minutes_rows", "value": int(len(unmatched_minutes_errors)), "detail": ""},
    ]
    for _, row in unmatched_by_reason.iterrows():
        summary_rows.append({"metric": "unmatched_predictions_by_reason", "value": int(row["rows"]), "detail": row["reason"]})

    if not projections.empty and not actuals_in_scope.empty:
        pred_keys = set(zip(projections["game_date"].astype(str), projections["player_key"].astype(str), projections["team"].astype(str)))
        actual_work = actuals_in_scope.copy()
        actual_work["_join_key"] = list(zip(actual_work["game_date"].astype(str), actual_work["player_key"].astype(str), actual_work["team"].astype(str)))
        unmatched_actuals = actual_work[~actual_work["_join_key"].isin(pred_keys)].copy()
        unmatched_actuals["reason"] = "no_projection_for_player_team_date"
        unmatched_actuals.drop(columns=["_join_key"], errors="ignore").to_csv(UNMATCHED_ACTUALS_PATH, index=False)
        summary_rows.append({"metric": "unmatched_actual_player_rows", "value": int(len(unmatched_actuals)), "detail": "no_projection_for_player_team_date"})
    else:
        pd.DataFrame(columns=list(actuals.columns) + ["reason"]).to_csv(UNMATCHED_ACTUALS_PATH, index=False)
        summary_rows.append({"metric": "unmatched_actual_player_rows", "value": 0, "detail": "no_actuals_or_predictions_in_scope"})

    JOIN_DIAGNOSTICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(summary_rows).to_csv(JOIN_DIAGNOSTICS_PATH, index=False)

def main() -> None:
    logger = setup_logging("update_wnba_learning_outputs")
    LEARNING_DIR.mkdir(parents=True, exist_ok=True)
    ERRORS_DIR.mkdir(parents=True, exist_ok=True)

    fetch_recent_actuals()
    actuals = load_actuals()
    if actuals.empty:
        logger.warning("WNBA learning outputs skipped: no actual player games found at %s", CANONICAL_PLAYER_GAMES_PATH)
        write_csv(PROJECTION_ERRORS_PATH, pd.DataFrame(), PROJECTION_ERROR_COLUMNS)
        write_csv(MINUTES_ERRORS_PATH, pd.DataFrame(), MINUTES_ERROR_COLUMNS)
        write_csv(UNMATCHED_PROJECTION_ERRORS_PATH, pd.DataFrame(), UNMATCHED_PROJECTION_COLUMNS)
        write_csv(UNMATCHED_MINUTES_ERRORS_PATH, pd.DataFrame(), UNMATCHED_MINUTES_COLUMNS)
        return

    projection_df, minutes_df, unmatched_projection_df, unmatched_minutes_df = build_error_outputs(actuals)
    write_csv(PROJECTION_ERRORS_PATH, projection_df, PROJECTION_ERROR_COLUMNS)
    write_csv(MINUTES_ERRORS_PATH, minutes_df, MINUTES_ERROR_COLUMNS)
    write_csv(UNMATCHED_PROJECTION_ERRORS_PATH, unmatched_projection_df, UNMATCHED_PROJECTION_COLUMNS)
    write_csv(UNMATCHED_MINUTES_ERRORS_PATH, unmatched_minutes_df, UNMATCHED_MINUTES_COLUMNS)

    write_join_diagnostics(actuals, projection_df, minutes_df, unmatched_projection_df, unmatched_minutes_df)

    logger.info(
        "WNBA learning outputs updated | projection_errors=%s | minutes_errors=%s | unmatched_projection=%s | unmatched_minutes=%s",
        len(projection_df),
        len(minutes_df),
        len(unmatched_projection_df),
        len(unmatched_minutes_df),
    )


if __name__ == "__main__":
    main()
