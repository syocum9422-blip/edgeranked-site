from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import urllib.request
from collections import Counter
from pathlib import Path

import pandas as pd

from wnba_model.settings import (
    APP_VIEW_PROJECTIONS_PATH,
    BASE_DIR,
    BEST_BETS_ARCHIVE_PATH,
    BEST_BETS_PATH,
    CANONICAL_PLAYER_GAMES_PATH,
    CANONICAL_SCHEDULE_TODAY_PATH,
    CANONICAL_SPORTSBOOK_LINES_PATH,
    DATA_MODELS_DIR,
    DATASET_PATH,
    LAST_GOOD_DIR,
    MINUTES_MODEL_PATH,
    MODEL_REPORT_PATH,
    PROJECTIONS_PATH,
    SIMULATION_DETAIL_PATH,
    STAT_TARGETS,
    TODAY_FEATURES_PATH,
    TODAY_OVERRIDE,
)


PIPELINE_STEPS = [
    ("Fetch WNBA data", "fetch_wnba_data.py"),
    ("Build WNBA dataset", "build_wnba_dataset.py"),
    ("Train WNBA stat models", "train_wnba_models.py"),
    ("Train WNBA minutes model", "train_wnba_minutes_model.py"),
    ("Build WNBA today features", "build_wnba_features_today.py"),
    ("Simulate WNBA today", "simulate_wnba_today.py"),
    ("Build WNBA best bets", "build_wnba_best_bets.py"),
]

SNAPSHOT_FILES = [
    PROJECTIONS_PATH,
    APP_VIEW_PROJECTIONS_PATH,
    BEST_BETS_PATH,
    BEST_BETS_ARCHIVE_PATH,
]

MAX_UPCOMING_SLATE_DAYS = 3
SLATE_TEAM_AUDIT_PATH = BASE_DIR / "data" / "processed" / "wnba_slate_team_audit.csv"
PLAYER_COVERAGE_AUDIT_PATH = BASE_DIR / "data" / "processed" / "wnba_player_coverage_audit.csv"
PRODUCTION_STATUS_PATH = BASE_DIR / "data" / "processed" / "wnba_production_status.json"
SLATE_VALIDATION_MANIFEST_PATH = BASE_DIR / "data" / "processed" / "wnba_slate_validation_manifest.json"
INGESTION_MANIFEST_PATH = BASE_DIR / "data" / "processed" / "wnba_ingestion_manifest.json"
LEARNING_MANIFEST_PATH = BASE_DIR / "data" / "processed" / "wnba_learning_manifest.json"
BACKTEST_REPORT_PATH = BASE_DIR / "data" / "processed" / "wnba_backtest_report.csv"
WNBA_TEAM_ALIASES = {"GS": "GSV", "LV": "LVA", "NY": "NYL", "WSH": "WAS"}


def env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "y"}


def project_python() -> str:
    venv_python = BASE_DIR / ".venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)
    return sys.executable


def today_et_date() -> pd.Timestamp.date:
    if TODAY_OVERRIDE:
        return pd.Timestamp(TODAY_OVERRIDE).date()
    return pd.Timestamp.now(tz="America/New_York").date()


def live_site_status_path() -> Path:
    live_root = Path(os.environ.get("EDGERANKED_LIVE_SITE_DIR", "/home/ubuntu/edgeranked-sportsai"))
    return live_root / "wnba" / "data" / "processed" / "wnba_production_status.json"


def csv_len(path: Path) -> int:
    try:
        if not path.exists():
            return 0
        return len(pd.read_csv(path))
    except Exception:
        return 0


def csv_teams(path: Path, *candidates: str) -> list[str]:
    try:
        if not path.exists():
            return []
        df = pd.read_csv(path)
    except Exception:
        return []
    return sorted(teams_from_column(df, *candidates))


def slate_audit_teams() -> list[str]:
    try:
        audit = pd.read_csv(SLATE_TEAM_AUDIT_PATH)
    except Exception:
        return []
    if audit.empty or "team" not in audit.columns:
        return []
    if "included" in audit.columns:
        audit = audit[audit["included"].astype(bool)]
    return sorted(set(audit["team"].dropna().astype(str).str.upper()))


def player_audit_summary() -> tuple[int, int, dict[str, int]]:
    try:
        audit = pd.read_csv(PLAYER_COVERAGE_AUDIT_PATH)
    except Exception:
        return 0, 0, {}
    if audit.empty or "included" not in audit.columns:
        return 0, 0, {}
    included = audit["included"].astype(bool)
    excluded = audit[~included].copy()
    reasons = Counter(excluded["reason"].fillna("unknown").astype(str)) if "reason" in excluded.columns else Counter()
    return int(included.sum()), int((~included).sum()), dict(sorted(reasons.items()))


def write_production_status(
    status: str,
    *,
    error: str = "",
    published: str = "no",
    stale_output_blocked: str = "yes",
) -> dict:
    included_players, excluded_players, excluded_reasons = player_audit_summary()
    payload = {
        "WNBA_PRODUCTION_STATUS": status,
        "status": status.lower(),
        "generated_at": pd.Timestamp.now(tz="America/New_York").isoformat(),
        "slate_date": str(selected_slate_date() or today_et_date()),
        "canonical_teams": slate_audit_teams(),
        "projected_teams": csv_teams(PROJECTIONS_PATH, "TEAM_ABBREVIATION", "team", "TEAM"),
        "included_players": included_players,
        "excluded_players": excluded_players,
        "excluded_reasons": excluded_reasons,
        "published": published,
        "stale_output_blocked": stale_output_blocked,
        "message": "WNBA refresh failed; check back shortly." if status == "FAIL" else "WNBA refresh passed.",
        "error": error,
    }
    for path in [PRODUCTION_STATUS_PATH, live_site_status_path()]:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        except Exception as exc:
            print(f"WARNING: could not write WNBA production status to {path}: {exc}")
    return payload


def print_production_summary(payload: dict) -> None:
    print("\n===== WNBA Production Summary =====")
    for key in [
        "WNBA_PRODUCTION_STATUS",
        "canonical_teams",
        "projected_teams",
        "included_players",
        "excluded_players",
        "excluded_reasons",
        "published",
        "stale_output_blocked",
    ]:
        value = payload.get(key)
        print(f"{key}={json.dumps(value, sort_keys=True) if isinstance(value, (list, dict)) else value}")
    if payload.get("error"):
        print(f"error={payload['error']}")


def selected_slate_date() -> object:
    value = os.environ.get("WNBA_SELECTED_SLATE_DATE")
    if not value:
        return None
    return pd.Timestamp(value).date()


def real_today_et_date() -> pd.Timestamp.date:
    return pd.Timestamp.now(tz="America/New_York").date()


def run_step(label: str, script_name: str) -> None:
    script_path = BASE_DIR / script_name
    if not script_path.exists():
        raise FileNotFoundError(f"Missing pipeline script: {script_path}")

    cmd = [project_python(), str(script_path)]
    print(f"\n===== {label} =====")
    print("Running:", " ".join(cmd))
    result = subprocess.run(cmd, cwd=BASE_DIR)
    if result.returncode != 0:
        raise RuntimeError(f"Step failed: {label} ({script_name})")


def validate_csv(path: Path, label: str, allow_empty: bool = False) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing {label}: {path}")

    df = pd.read_csv(path)
    if df.empty and not allow_empty:
        raise ValueError(f"{label} exists but is empty: {path}")

    print(f"{label} rows: {len(df)}")
    return df


def latest_date_from_columns(df: pd.DataFrame, candidates: list[str]) -> object:
    lookup = {str(column).lower(): column for column in df.columns}
    for candidate in candidates:
        column = lookup.get(candidate.lower())
        if not column:
            continue
        dates = pd.to_datetime(df[column], errors="coerce").dropna()
        if not dates.empty:
            return dates.max().date()
    return None


def latest_file_date(path: Path) -> object:
    if not path.exists():
        return None
    modified_at = pd.Timestamp(path.stat().st_mtime, unit="s", tz="UTC")
    return modified_at.tz_convert("America/New_York").date()


def validate_current_file(path: Path, label: str, date_columns: list[str], allow_empty: bool = False) -> pd.DataFrame:
    df = validate_csv(path, label, allow_empty=allow_empty)
    if df.empty and allow_empty:
        return df

    latest_date = latest_date_from_columns(df, date_columns)
    expected_date = selected_slate_date() or today_et_date()
    if latest_date is None:
        latest_date = latest_file_date(path)
        expected_date = selected_slate_date() or real_today_et_date()

    if latest_date != expected_date:
        raise ValueError(f"{label} is stale. Latest available date: {latest_date}. Expected: {expected_date}.")
    return df




def _json_default(value):
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return str(value)


def normalize_team_code(value: object) -> str:
    text = str(value or "").strip().upper()
    return WNBA_TEAM_ALIASES.get(text, text)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=_json_default) + "\n", encoding="utf-8")


def fetch_trusted_espn_slate(slate_date: object) -> list[dict]:
    url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard?dates={pd.Timestamp(slate_date).strftime('%Y%m%d')}"
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    rows = []
    for event in payload.get("events", []) or []:
        competition = (event.get("competitions") or [{}])[0]
        competitors = competition.get("competitors", []) or []
        home = next((item for item in competitors if item.get("homeAway") == "home"), None)
        away = next((item for item in competitors if item.get("homeAway") == "away"), None)
        if not home or not away:
            continue
        rows.append(
            {
                "game_id": str(event.get("id", "")),
                "home_team": normalize_team_code((home.get("team") or {}).get("abbreviation", "")),
                "away_team": normalize_team_code((away.get("team") or {}).get("abbreviation", "")),
                "start_time_utc": pd.to_datetime(event.get("date", ""), utc=True, errors="coerce").strftime("%Y-%m-%dT%H:%MZ"),
            }
        )
    return sorted(rows, key=lambda item: (item["start_time_utc"], item["away_team"], item["home_team"]))


def normalize_schedule_rows(schedule: pd.DataFrame, slate_date: object) -> list[dict]:
    if schedule.empty:
        return []
    date_col = next((col for col in schedule.columns if str(col).lower() in {"game_date", "date"}), None)
    frame = schedule.copy()
    if date_col:
        parsed = pd.to_datetime(frame[date_col], errors="coerce")
        frame = frame[parsed.dt.date == pd.Timestamp(slate_date).date()].copy()
    rows = []
    for _, row in frame.iterrows():
        start_raw = row.get("start_time_utc", row.get("start_time", ""))
        start = pd.to_datetime(start_raw, utc=True, errors="coerce")
        rows.append(
            {
                "game_id": str(row.get("game_id", "")),
                "home_team": normalize_team_code(row.get("home_team", "")),
                "away_team": normalize_team_code(row.get("away_team", "")),
                "start_time_utc": "" if pd.isna(start) else start.strftime("%Y-%m-%dT%H:%MZ"),
            }
        )
    return sorted(rows, key=lambda item: (item["start_time_utc"], item["away_team"], item["home_team"]))


def validate_slate_against_trusted_source(slate_date: object) -> dict:
    generated = normalize_schedule_rows(pd.read_csv(CANONICAL_SCHEDULE_TODAY_PATH), slate_date)
    trusted = fetch_trusted_espn_slate(slate_date)
    generated_keys = [(row["away_team"], row["home_team"], row["start_time_utc"]) for row in generated]
    trusted_keys = [(row["away_team"], row["home_team"], row["start_time_utc"]) for row in trusted]
    duplicate_keys = [list(key) for key, count in Counter(generated_keys).items() if count > 1]
    payload = {
        "generated_at": pd.Timestamp.now(tz="America/New_York").isoformat(),
        "slate_date": str(slate_date),
        "trusted_source": "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard",
        "expected_game_count": len(trusted),
        "generated_game_count": len(generated),
        "trusted_games": trusted,
        "generated_games": generated,
        "missing_games": [list(key) for key in sorted(set(trusted_keys) - set(generated_keys))],
        "unexpected_games": [list(key) for key in sorted(set(generated_keys) - set(trusted_keys))],
        "duplicate_games": duplicate_keys,
        "status": "PASS",
    }
    if payload["expected_game_count"] != payload["generated_game_count"] or payload["missing_games"] or payload["unexpected_games"] or payload["duplicate_games"]:
        payload["status"] = "FAIL"
    write_json(SLATE_VALIDATION_MANIFEST_PATH, payload)
    if payload["status"] != "PASS":
        raise RuntimeError(f"WNBA slate validation failed: {payload}")
    return payload


def file_manifest_entry(path: Path, date_columns: list[str]) -> dict:
    entry = {"path": str(path), "exists": path.exists(), "rows": 0, "modified_at_et": None, "latest_date": None, "columns": []}
    if not path.exists():
        return entry
    entry["modified_at_et"] = pd.Timestamp(path.stat().st_mtime, unit="s", tz="UTC").tz_convert("America/New_York").isoformat()
    try:
        df = pd.read_csv(path)
    except Exception as exc:
        entry["error"] = str(exc)
        return entry
    entry["rows"] = int(len(df))
    entry["columns"] = list(df.columns)
    latest = latest_date_from_columns(df, date_columns)
    entry["latest_date"] = str(latest) if latest else None
    return entry


def write_ingestion_manifest() -> dict:
    files = {
        "schedule": file_manifest_entry(CANONICAL_SCHEDULE_TODAY_PATH, ["game_date", "date", "game_date_et"]),
        "player_games": file_manifest_entry(CANONICAL_PLAYER_GAMES_PATH, ["game_date", "date"]),
        "team_context": file_manifest_entry(BASE_DIR / "data" / "raw" / "wnba_team_context.csv", ["game_date", "date"]),
        "sportsbook_lines": file_manifest_entry(CANONICAL_SPORTSBOOK_LINES_PATH, ["game_date", "date"]),
        "player_status": file_manifest_entry(BASE_DIR / "data" / "raw" / "wnba_player_status.csv", ["game_date", "date"]),
        "today_features": file_manifest_entry(TODAY_FEATURES_PATH, ["game_date", "date"]),
    }
    payload = {"generated_at": pd.Timestamp.now(tz="America/New_York").isoformat(), "files": files, "data_source_audit": audit_data_sources()}
    write_json(INGESTION_MANIFEST_PATH, payload)
    return payload


def write_learning_manifest() -> dict:
    graded_path = BASE_DIR / "Best_Bets" / "graded_bets.csv"
    history_path = BASE_DIR / "Best_Bets" / "wnba_bets_history.csv"
    errors_path = BASE_DIR / "learning" / "errors" / "projection_errors.csv"
    graded = pd.read_csv(graded_path) if graded_path.exists() else pd.DataFrame()
    history = pd.read_csv(history_path) if history_path.exists() else pd.DataFrame()
    errors = pd.read_csv(errors_path) if errors_path.exists() else pd.DataFrame()
    result_col = next((col for col in ["bet_result", "RESULT", "result"] if col in graded.columns), None)
    date_col = next((col for col in ["bet_date", "DATE", "date"] if col in graded.columns), None)
    graded_results = graded[graded[result_col].astype(str).str.lower().isin({"win", "loss"})].copy() if result_col else pd.DataFrame()
    accuracy = float((graded_results[result_col].astype(str).str.lower() == "win").mean()) if not graded_results.empty else None
    payload = {
        "generated_at": pd.Timestamp.now(tz="America/New_York").isoformat(),
        "last_graded_date": None if not date_col or graded.empty else str(pd.to_datetime(graded[date_col], errors="coerce").max().date()),
        "games_graded": int(graded_results[date_col].nunique()) if date_col and not graded_results.empty else 0,
        "predictions_graded": int(len(graded_results)),
        "accuracy": accuracy,
        "brier": None,
        "log_loss": None,
        "calibration_by_confidence_bucket": {},
        "files_updated": [str(path) for path in [graded_path, history_path, errors_path] if path.exists()],
        "history_rows": int(len(history)),
        "projection_error_rows": int(len(errors)),
        "no_new_completed_games": bool(graded_results.empty),
    }
    if not graded_results.empty and "confidence" in graded_results.columns:
        payload["calibration_by_confidence_bucket"] = graded_results.groupby("confidence")[result_col].apply(lambda s: float((s.astype(str).str.lower() == "win").mean())).to_dict()
    write_json(LEARNING_MANIFEST_PATH, payload)
    return payload


def write_backtest_report() -> pd.DataFrame:
    path = BASE_DIR / "Best_Bets" / "wnba_bets_history.csv"
    history = pd.read_csv(path) if path.exists() else pd.DataFrame()
    rows = []
    for days in [7, 14, 30]:
        row = {"window_days": days, "graded_predictions": 0, "wins": 0, "losses": 0, "accuracy": None, "primary_failure_source": "no_graded_predictions"}
        if not history.empty:
            date_col = next((col for col in ["bet_date", "DATE", "date"] if col in history.columns), None)
            result_col = next((col for col in ["bet_result", "RESULT", "result"] if col in history.columns), None)
            if date_col and result_col:
                work = history.copy()
                work["_date"] = pd.to_datetime(work[date_col], errors="coerce").dt.date
                cutoff = today_et_date() - pd.Timedelta(days=days - 1)
                work = work[work["_date"] >= cutoff]
                graded = work[work[result_col].astype(str).str.lower().isin({"win", "loss"})]
                wins = int((graded[result_col].astype(str).str.lower() == "win").sum())
                losses = int((graded[result_col].astype(str).str.lower() == "loss").sum())
                row.update({"graded_predictions": int(len(graded)), "wins": wins, "losses": losses, "accuracy": wins / (wins + losses) if wins + losses else None})
                if row["graded_predictions"]:
                    row["primary_failure_source"] = "calibration_or_model_quality_requires_review"
        rows.append(row)
    report = pd.DataFrame(rows)
    report.to_csv(BACKTEST_REPORT_PATH, index=False)
    return report

def current_slate_status() -> tuple[object, str]:
    if not CANONICAL_SCHEDULE_TODAY_PATH.exists():
        return None, f"Missing schedule file: {CANONICAL_SCHEDULE_TODAY_PATH}"

    try:
        schedule = pd.read_csv(CANONICAL_SCHEDULE_TODAY_PATH)
    except Exception as exc:
        return None, f"Could not read schedule file: {exc}"

    if schedule.empty:
        return None, "Schedule file is empty. Treating as no WNBA slate."

    date_col = next((col for col in schedule.columns if str(col).lower() in {"game_date", "date"}), None)
    if not date_col:
        return None, f"Schedule has no game_date/date column. Found: {list(schedule.columns)}"

    dates = pd.to_datetime(schedule[date_col], errors="coerce").dropna()
    if dates.empty:
        return None, "Schedule has no valid game dates."

    today = today_et_date()
    date_values = pd.to_datetime(schedule[date_col], errors="coerce")
    today_rows = schedule[date_values.dt.date == today]
    selected_date = today
    selected_rows = today_rows
    reason = "today"

    if today_rows.empty:
        max_date = (pd.Timestamp(today) + pd.Timedelta(days=MAX_UPCOMING_SLATE_DAYS)).date()
        upcoming_dates = sorted(
            {
                value.date()
                for value in date_values.dropna()
                if today < value.date() <= max_date
            }
        )
        if not upcoming_dates:
            latest = dates.max().date()
            return None, f"No WNBA games found for {today}. Latest schedule date is {latest}."
        selected_date = upcoming_dates[0]
        selected_rows = schedule[date_values.dt.date == selected_date]
        reason = "no_games_next_available"

    team_cols = [col for col in ["home_team", "away_team"] if col in schedule.columns]
    if team_cols:
        teams = set()
        for col in team_cols:
            teams.update(str(team).strip().upper() for team in selected_rows[col].dropna().tolist() if str(team).strip())
        if len(teams) < 2:
            return None, f"Selected WNBA slate has only {len(teams)} teams."

    return selected_date, (
        f"selected_slate_date={selected_date}\n"
        f"reason={reason}\n"
        f"WNBA slate rows: {len(selected_rows)}"
    )


def filter_schedule_to_slate_date(slate_date: object) -> None:
    schedule = pd.read_csv(CANONICAL_SCHEDULE_TODAY_PATH)
    date_col = next((col for col in schedule.columns if str(col).lower() in {"game_date", "date"}), None)
    if not date_col:
        raise ValueError(f"Schedule has no game_date/date column. Found: {list(schedule.columns)}")

    date_values = pd.to_datetime(schedule[date_col], errors="coerce")
    selected = schedule[date_values.dt.date == slate_date].copy()
    if selected.empty:
        raise ValueError(f"No schedule rows found for selected_slate_date={slate_date}")
    selected.to_csv(CANONICAL_SCHEDULE_TODAY_PATH, index=False)


def snapshot_target(path: Path) -> Path:
    return LAST_GOOD_DIR / path.relative_to(BASE_DIR)


def refresh_last_good_snapshot() -> None:
    LAST_GOOD_DIR.mkdir(parents=True, exist_ok=True)
    saved = 0
    for source_path in SNAPSHOT_FILES:
        if not source_path.exists():
            continue
        backup_path = snapshot_target(source_path)
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, backup_path)
        saved += 1
    print(f"Saved WNBA last-good snapshot files: {saved}")


def restore_last_good_snapshot() -> None:
    restored = 0
    for target_path in SNAPSHOT_FILES:
        backup_path = snapshot_target(target_path)
        if not backup_path.exists():
            continue
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup_path, target_path)
        restored += 1
    if restored:
        print(f"Restored WNBA last-good snapshot files: {restored}")


def ensure_core_inputs_after_fetch() -> None:
    validate_csv(CANONICAL_PLAYER_GAMES_PATH, "wnba_player_games.csv")
    validate_csv(CANONICAL_SPORTSBOOK_LINES_PATH, "wnba_sportsbook_lines.csv", allow_empty=True)


def ensure_model_outputs() -> None:
    validate_csv(DATASET_PATH, "wnba_training_dataset.csv")
    validate_csv(MODEL_REPORT_PATH, "wnba_model_report.csv")
    for stat in STAT_TARGETS:
        model_path = DATA_MODELS_DIR / f"wnba_{stat}_model.joblib"
        if not model_path.exists():
            raise FileNotFoundError(f"Missing trained WNBA stat model: {model_path}")
    if not MINUTES_MODEL_PATH.exists():
        raise FileNotFoundError(f"Missing trained WNBA minutes model: {MINUTES_MODEL_PATH}")


def ensure_projection_outputs() -> None:
    validate_csv(TODAY_FEATURES_PATH, "wnba_today_features.csv")
    validate_current_file(PROJECTIONS_PATH, "projections.csv", ["GAME_DATE", "DATE", "game_date"])
    validate_current_file(APP_VIEW_PROJECTIONS_PATH, "Projections_app_view.csv", ["GAME_DATE", "DATE", "game_date"])
    validate_csv(SIMULATION_DETAIL_PATH, "wnba_simulation_detail.csv", allow_empty=True)


def ensure_best_bet_outputs() -> None:
    allow_empty = env_flag("EDGERANKED_WNBA_ALLOW_EMPTY_BEST_BETS")
    validate_current_file(BEST_BETS_PATH, "wnba_best_bets_today.csv", ["DATE", "bet_date"], allow_empty=allow_empty)
    validate_current_file(
        BEST_BETS_ARCHIVE_PATH,
        "Best_Bets/wnba_best_bets_today.csv",
        ["DATE", "bet_date"],
        allow_empty=allow_empty,
    )


def teams_from_column(df: pd.DataFrame, *candidates: str) -> set[str]:
    for candidate in candidates:
        if candidate in df.columns:
            return set(df[candidate].dropna().astype(str).str.upper())
    return set()


def require_publish_safety_check() -> None:
    slate_audit = validate_csv(SLATE_TEAM_AUDIT_PATH, "wnba_slate_team_audit.csv")
    player_audit = validate_csv(PLAYER_COVERAGE_AUDIT_PATH, "wnba_player_coverage_audit.csv")
    features = validate_csv(TODAY_FEATURES_PATH, "wnba_today_features.csv")
    projections = validate_csv(PROJECTIONS_PATH, "projections.csv")
    app_view = validate_csv(APP_VIEW_PROJECTIONS_PATH, "Projections_app_view.csv")
    simulation_detail = validate_csv(SIMULATION_DETAIL_PATH, "wnba_simulation_detail.csv", allow_empty=True)

    included_slate = slate_audit[slate_audit["included"].astype(bool)].copy()
    slate_teams = set(included_slate["team"].dropna().astype(str).str.upper())
    if not slate_teams:
        raise ValueError("WNBA publish safety check failed: no included slate teams in audit.")

    feature_teams = teams_from_column(features, "team", "TEAM")
    projection_teams = teams_from_column(projections, "TEAM_ABBREVIATION", "team", "TEAM")
    app_teams = teams_from_column(app_view, "TEAM", "TEAM_ABBREVIATION", "team")

    if feature_teams != slate_teams:
        raise ValueError(f"WNBA feature teams disagree with slate teams. features={sorted(feature_teams)} slate={sorted(slate_teams)}")
    if projection_teams != slate_teams:
        raise ValueError(f"WNBA projection teams disagree with slate teams. projections={sorted(projection_teams)} slate={sorted(slate_teams)}")
    if app_teams != slate_teams:
        raise ValueError(f"WNBA app-view teams disagree with slate teams. app={sorted(app_teams)} slate={sorted(slate_teams)}")

    for label, frame, columns in [
        ("features", features, ["opponent", "OPPONENT", "OPPONENT_ABBREVIATION"]),
        ("projections", projections, ["opponent", "OPPONENT", "OPPONENT_ABBREVIATION"]),
        ("app_view", app_view, ["OPPONENT", "OPPONENT_ABBREVIATION", "opponent"]),
    ]:
        for column in columns:
            if column in frame.columns and (frame[column].astype(str).str.upper() == "UNKNOWN").any():
                raise ValueError(f"WNBA publish safety check failed: {label} contains UNKNOWN opponents.")

    if "_data_source" in features.columns and (features["_data_source"].astype(str) == "baseline_live_line").any():
        raise ValueError("WNBA publish safety check failed: features contain baseline_live_line rows.")

    included_players = player_audit[player_audit["included"].astype(bool)].copy()
    if "history_source" in included_players.columns and (included_players["history_source"].astype(str) == "baseline_live_line").any():
        raise ValueError("WNBA publish safety check failed: included player audit contains baseline_live_line rows.")

    if not simulation_detail.empty:
        sportsbooks = set(simulation_detail.get("sportsbook", pd.Series(dtype=str)).dropna().astype(str).str.lower())
        if sportsbooks != {"prizepicks"}:
            raise ValueError(f"WNBA publish safety check failed: sportsbook set is {sorted(sportsbooks)}, expected ['prizepicks'].")

    excluded_slate_players = player_audit[
        player_audit["team"].astype(str).str.upper().isin(slate_teams)
        & ~player_audit["included"].astype(bool)
        & ~player_audit["reason"].astype(str).isin(["no_history_found", "api_error", "excluded_not_on_canonical_slate"])
    ]
    if not excluded_slate_players.empty:
        details = excluded_slate_players[["player_name", "team", "reason"]].to_dict("records")
        raise ValueError(f"WNBA publish safety check failed: slate live-line players excluded: {details}")

    print("WNBA publish safety check: PASSED")


def audit_data_sources() -> dict:
    """Audit all data sources and return status with source labels."""
    from wnba_model_config import (
        CANONICAL_PLAYER_STATUS_PATH,
        CANONICAL_SCHEDULE_TODAY_PATH,
        CANONICAL_SPORTSBOOK_LINES_PATH,
    )

    audit = {
        "schedule_source": "unknown",
        "lines_source": "unknown",
        "injuries_source": "unknown",
        "live_data_ready": False,
        "blocking_reasons": [],
        "warnings": [],
    }

    # Check sportsbook lines source
    if CANONICAL_SPORTSBOOK_LINES_PATH.exists():
        try:
            df = pd.read_csv(CANONICAL_SPORTSBOOK_LINES_PATH)
            if "_data_source" in df.columns and len(df) > 0:
                audit["lines_source"] = str(df["_data_source"].iloc[0])
            # Check sportsbook column for legacy files without explicit source metadata.
            elif "sportsbook" in df.columns:
                if (df["sportsbook"].astype(str).str.lower() == "mockbook").all():
                    audit["lines_source"] = "csv:mockbook"
                elif (df["sportsbook"].astype(str).str.lower() == "prizepicks").any():
                    audit["lines_source"] = "csv:prizepicks"
                else:
                    audit["lines_source"] = "csv:unknown"
            elif "_data_source" in df.columns:
                audit["lines_source"] = df["_data_source"].iloc[0] if len(df) > 0 else "csv:empty"
            else:
                audit["lines_source"] = "csv:unknown"
        except Exception:
            audit["lines_source"] = "error:could_not_read"
    else:
        audit["lines_source"] = "missing"

    # Check schedule source
    if CANONICAL_SCHEDULE_TODAY_PATH.exists():
        try:
            df = pd.read_csv(CANONICAL_SCHEDULE_TODAY_PATH)
            if "_data_source" in df.columns:
                audit["schedule_source"] = df["_data_source"].iloc[0] if len(df) > 0 else "csv:empty"
            elif not df.empty:
                # Check for test date in data
                for col in df.columns:
                    if str(col).lower() in ("game_date", "date"):
                        sample_date = str(df[col].iloc[0]) if len(df) > 0 else ""
                        if "2025-07-05" in sample_date:
                            audit["schedule_source"] = "csv:test_date"
                            break
                if audit["schedule_source"] == "unknown":
                    audit["schedule_source"] = "csv:real"
            else:
                audit["schedule_source"] = "csv:empty"
        except Exception:
            audit["schedule_source"] = "error:could_not_read"
    else:
        audit["schedule_source"] = "missing"

    # Check player status source
    if CANONICAL_PLAYER_STATUS_PATH.exists():
        try:
            df = pd.read_csv(CANONICAL_PLAYER_STATUS_PATH)
            if df.empty or len(df) == 0:
                audit["injuries_source"] = "missing:empty_rows"
            elif "_data_source" in df.columns:
                audit["injuries_source"] = df["_data_source"].iloc[0]
            else:
                audit["injuries_source"] = "csv:manual"
        except Exception:
            audit["injuries_source"] = "error:could_not_read"
    else:
        audit["injuries_source"] = "missing:file_not_found"

    # Determine live_data_ready
    is_mock_lines = "mockbook" in audit["lines_source"].lower() or "csv:mockbook" in audit["lines_source"].lower()
    is_test_schedule = "test" in audit["schedule_source"].lower()
    is_missing_injuries = "missing" in audit["injuries_source"].lower() or "empty" in audit["injuries_source"].lower()

    if is_mock_lines:
        audit["blocking_reasons"].append(f"Lines are mock (source={audit['lines_source']})")
    if is_test_schedule:
        audit["blocking_reasons"].append(f"Schedule is test data (source={audit['schedule_source']})")
    if is_missing_injuries:
        audit["blocking_reasons"].append(f"Injuries are missing (source={audit['injuries_source']})")

    audit["live_data_ready"] = not is_mock_lines and not is_test_schedule

    return audit


def print_data_source_audit(audit: dict) -> None:
    """Print data source audit in a readable format."""
    print("\n===== WNBA Data Source Audit =====")
    print(f"  Lines source:    {audit['lines_source']}")
    print(f"  Schedule source: {audit['schedule_source']}")
    print(f"  Injuries source: {audit['injuries_source']}")
    print(f"  Live data ready: {audit['live_data_ready']}")
    if audit["blocking_reasons"]:
        print("  Blocking reasons:")
        for reason in audit["blocking_reasons"]:
            print(f"    - {reason}")
    if audit["warnings"]:
        print("  Warnings:")
        for warning in audit["warnings"]:
            print(f"    - {warning}")


def require_live_data_check() -> None:
    """If EDGERANKED_WNBA_REQUIRE_LIVE_DATA=1, fail if data sources are not live."""
    if not env_flag("EDGERANKED_WNBA_REQUIRE_LIVE_DATA"):
        return

    audit = audit_data_sources()
    print_data_source_audit(audit)

    if not audit["live_data_ready"]:
        blocking = "; ".join(audit["blocking_reasons"])
        raise RuntimeError(
            f"EDGERANKED_WNBA_REQUIRE_LIVE_DATA=1 but data sources are not live. {blocking}. "
            "Either set EDGERANKED_WNBA_REQUIRE_LIVE_DATA=0 to allow fallback, "
            "or ensure real data sources are configured."
        )

    print("  Live data check: PASSED")


def main() -> None:
    refresh_last_good_snapshot()

    try:
        run_step(*PIPELINE_STEPS[0])
        ensure_core_inputs_after_fetch()
        write_ingestion_manifest()

        # Audit data sources and optionally fail if not live
        require_live_data_check()

        slate_date, slate_message = current_slate_status()
        print(f"\n===== WNBA Slate Check =====\n{slate_message}")
        if not slate_date:
            restore_last_good_snapshot()
            print("No current WNBA slate. Pipeline finished without rebuilding projections or best bets.")
            return
        os.environ["WNBA_SELECTED_SLATE_DATE"] = str(slate_date)
        validate_slate_against_trusted_source(slate_date)
        filter_schedule_to_slate_date(slate_date)
        write_ingestion_manifest()
        run_step("Auto backfill WNBA live players", "auto_backfill_wnba_live_players.py")

        run_step(*PIPELINE_STEPS[1])
        run_step(*PIPELINE_STEPS[2])
        run_step(*PIPELINE_STEPS[3])
        ensure_model_outputs()

        run_step(*PIPELINE_STEPS[4])
        run_step(*PIPELINE_STEPS[5])
        ensure_projection_outputs()

        run_step(*PIPELINE_STEPS[6])
        ensure_best_bet_outputs()
        require_publish_safety_check()
        write_ingestion_manifest()
        write_learning_manifest()
        write_backtest_report()

    except Exception as exc:
        write_ingestion_manifest()
        write_learning_manifest()
        write_backtest_report()
        restore_last_good_snapshot()
        payload = write_production_status("FAIL", error=str(exc), published="no", stale_output_blocked="yes")
        print_production_summary(payload)
        raise

    refresh_last_good_snapshot()
    payload = write_production_status("PASS", published="no", stale_output_blocked="yes")
    print_production_summary(payload)
    print("\nWNBA pipeline completed successfully.")


if __name__ == "__main__":
    main()
