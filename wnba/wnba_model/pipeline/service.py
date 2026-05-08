from __future__ import annotations

import os
import shutil
import subprocess
import sys
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
    expected_date = today_et_date()
    if latest_date is None:
        latest_date = latest_file_date(path)
        expected_date = real_today_et_date()

    if latest_date != expected_date:
        raise ValueError(f"{label} is stale. Latest available date: {latest_date}. Expected: {expected_date}.")
    return df


def current_slate_status() -> tuple[bool, str]:
    if not CANONICAL_SCHEDULE_TODAY_PATH.exists():
        return False, f"Missing schedule file: {CANONICAL_SCHEDULE_TODAY_PATH}"

    try:
        schedule = pd.read_csv(CANONICAL_SCHEDULE_TODAY_PATH)
    except Exception as exc:
        return False, f"Could not read schedule file: {exc}"

    if schedule.empty:
        return False, "Schedule file is empty. Treating as no WNBA slate."

    date_col = next((col for col in schedule.columns if str(col).lower() in {"game_date", "date"}), None)
    if not date_col:
        return False, f"Schedule has no game_date/date column. Found: {list(schedule.columns)}"

    dates = pd.to_datetime(schedule[date_col], errors="coerce").dropna()
    if dates.empty:
        return False, "Schedule has no valid game dates."

    today = today_et_date()
    current_rows = schedule[dates.dt.date == today]
    if current_rows.empty:
        latest = dates.max().date()
        return False, f"No WNBA games found for {today}. Latest schedule date is {latest}."

    team_cols = [col for col in ["home_team", "away_team"] if col in schedule.columns]
    if team_cols:
        teams = set()
        for col in team_cols:
            teams.update(str(team).strip().upper() for team in current_rows[col].dropna().tolist() if str(team).strip())
        if len(teams) < 2:
            return False, f"Current WNBA slate has only {len(teams)} teams."

    return True, f"Current WNBA slate rows: {len(current_rows)}"


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
            # Check sportsbook column first for mockbook detection
            if "sportsbook" in df.columns:
                if (df["sportsbook"].astype(str).str.lower() == "mockbook").all():
                    audit["lines_source"] = "csv:mockbook"
                elif (df["sportsbook"].astype(str).str.lower() == "prizepicks").any():
                    audit["lines_source"] = "csv:prizepicks"
                elif "_data_source" in df.columns:
                    audit["lines_source"] = df["_data_source"].iloc[0] if len(df) > 0 else "csv:unknown"
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

        # Audit data sources and optionally fail if not live
        require_live_data_check()

        has_slate, slate_message = current_slate_status()
        print(f"\n===== WNBA Slate Check =====\n{slate_message}")
        if not has_slate:
            restore_last_good_snapshot()
            print("No current WNBA slate. Pipeline finished without rebuilding projections or best bets.")
            return

        run_step(*PIPELINE_STEPS[1])
        run_step(*PIPELINE_STEPS[2])
        run_step(*PIPELINE_STEPS[3])
        ensure_model_outputs()

        run_step(*PIPELINE_STEPS[4])
        run_step(*PIPELINE_STEPS[5])
        ensure_projection_outputs()

        run_step(*PIPELINE_STEPS[6])
        ensure_best_bet_outputs()

    except Exception:
        restore_last_good_snapshot()
        raise

    refresh_last_good_snapshot()
    print("\nWNBA pipeline completed successfully.")


if __name__ == "__main__":
    main()
