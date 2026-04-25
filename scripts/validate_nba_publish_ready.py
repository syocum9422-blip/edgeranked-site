#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
import pandas as pd

BASE_DIR = Path(os.environ.get("EDGERANKED_NBA_BASE_DIR", Path(__file__).resolve().parents[1]))
EXPECTED_DATE = os.environ.get(
    "EDGERANKED_NBA_SLATE_DATE",
    pd.Timestamp.now(tz="America/New_York").strftime("%Y-%m-%d"),
)

REQUIRED_FILES = {
    "projections.csv": {
        "path": BASE_DIR / "projections.csv",
        "date_columns": ["GAME_DATE"],
    },
    "game_lines_today.csv": {
        "path": BASE_DIR / "game_lines_today.csv",
        "date_columns": ["GAME_DATE"],
    },
    "lines_today.csv": {
        "path": BASE_DIR / "lines_today.csv",
        "date_columns": ["START_TIME_ET", "GAME_DATE", "UPDATED_AT_ET"],
    },
    "Best_Bets/nba_best_bets_today.csv": {
        "path": BASE_DIR / "Best_Bets" / "nba_best_bets_today.csv",
        "date_columns": ["DATE"],
    },
}

def fail(message: str) -> None:
    print(f"FAIL {message}")
    raise SystemExit(1)

def read_required_csv(label: str, path: Path) -> pd.DataFrame:
    if not path.exists():
        fail(f"{label}: missing file {path}; expected date {EXPECTED_DATE}")
    try:
        df = pd.read_csv(path)
    except Exception as exc:
        fail(f"{label}: unreadable file {path}: {exc}; expected date {EXPECTED_DATE}")
    if df.empty:
        fail(f"{label}: empty/header-only file {path}; expected date {EXPECTED_DATE}")
    print(f"PASS {label}: found {len(df)} row(s) at {path}")
    return df

def latest_date(df: pd.DataFrame, columns: list[str]) -> str | None:
    for column in columns:
        if column not in df.columns:
            continue
        dates = pd.to_datetime(df[column], errors="coerce").dropna()
        if not dates.empty:
            return dates.max().strftime("%Y-%m-%d")
    return None

def require_current_date(label: str, df: pd.DataFrame, columns: list[str]) -> None:
    found = latest_date(df, columns)
    if found != EXPECTED_DATE:
        fail(f"{label}: stale date {found}; expected {EXPECTED_DATE}; checked columns {', '.join(columns)}")
    print(f"PASS {label}: latest date {found} matches expected {EXPECTED_DATE}")

def validate() -> int:
    print("=== NBA publish readiness validation ===")
    print(f"NBA base dir: {BASE_DIR}")
    print(f"Expected date: {EXPECTED_DATE}")
    loaded = {}
    for label, spec in REQUIRED_FILES.items():
        loaded[label] = read_required_csv(label, spec["path"])
    for label, spec in REQUIRED_FILES.items():
        require_current_date(label, loaded[label], spec["date_columns"])
    print("PASS NBA publish readiness validation complete")
    return 0

if __name__ == "__main__":
    raise SystemExit(validate())
