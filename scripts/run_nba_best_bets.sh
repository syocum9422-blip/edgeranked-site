#!/usr/bin/env bash
set -euo pipefail

echo "=== NBA DAY RUN START ==="

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BASE_DIR="${EDGERANKED_NBA_BASE_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
PYTHON_BIN="${PYTHON_BIN:-$BASE_DIR/.venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
    PYTHON_BIN="python3"
fi
export EDGERANKED_PUBLISH_SPORTS="${EDGERANKED_PUBLISH_SPORTS:-nba}"
BEST_BETS_DIR="$BASE_DIR/Best_Bets"
TARGET_BETS_FILE="$BEST_BETS_DIR/nba_best_bets_today.csv"
BACKUP_BETS_FILE="$BEST_BETS_DIR/nba_top_plays_last_good.csv"
LAST_GOOD_DIR="$BASE_DIR/outputs/nba_last_good"
PUBLISH_SCRIPT="$BASE_DIR/scripts/publish_render_site.sh"
CURRENT_HOUR=$(date +%H)
CURRENT_MINUTE=$(date +%M)
FIRST_RUN_HOUR="09"
FIRST_RUN_MINUTE="15"
FORCE_FULL_RUN="${EDGERANKED_NBA_FULL_RUN:-${EDGERANKED_FORCE_NBA_FULL_RUN:-0}}"

echo "Using Python: $PYTHON_BIN"

cd "$BASE_DIR" || exit 1

mkdir -p "$BEST_BETS_DIR"
mkdir -p "$LAST_GOOD_DIR"

SNAPSHOT_FILES=(
    "projections.csv"
    "Projections_app_view.csv"
    "lines_today.csv"
    "game_lines_today.csv"
    "teams_today.csv"
    "edges_today.csv"
    "Best_Bets/nba_best_bets_today.csv"
)

restore_last_good_snapshot() {
    local restored_any=0
    for relative_path in "${SNAPSHOT_FILES[@]}"; do
        local backup_path="$LAST_GOOD_DIR/$relative_path"
        local target_path="$BASE_DIR/$relative_path"
        if [[ -f "$backup_path" ]]; then
            mkdir -p "$(dirname "$target_path")"
            cp "$backup_path" "$target_path"
            restored_any=1
        fi
    done
    if [[ "$restored_any" == "1" ]]; then
        echo "Restored last good NBA snapshot from $LAST_GOOD_DIR"
    fi
    return 0
}

refresh_last_good_snapshot() {
    for relative_path in "${SNAPSHOT_FILES[@]}"; do
        local source_path="$BASE_DIR/$relative_path"
        local backup_path="$LAST_GOOD_DIR/$relative_path"
        if [[ -f "$source_path" ]]; then
            mkdir -p "$(dirname "$backup_path")"
            cp "$source_path" "$backup_path"
        fi
    done
    echo "Saved last good NBA snapshot to $LAST_GOOD_DIR"
}

restore_last_good_board() {
    if [[ -f "$BACKUP_BETS_FILE" ]]; then
        cp "$BACKUP_BETS_FILE" "$TARGET_BETS_FILE"
        echo "Restored last good top-plays file from backup: $BACKUP_BETS_FILE"
    fi
}

refresh_last_good_board() {
    if [[ -f "$TARGET_BETS_FILE" ]]; then
        cp "$TARGET_BETS_FILE" "$BACKUP_BETS_FILE"
        echo "Saved last good top-plays backup: $BACKUP_BETS_FILE"
    fi
}

on_failure() {
    local exit_code=$?
    echo "ERROR: NBA day run failed with exit code $exit_code"
    restore_last_good_snapshot
    restore_last_good_board
    if [[ -x "$PUBLISH_SCRIPT" ]]; then
        echo "Publishing restored last-good NBA snapshot to the live site..."
        bash "$PUBLISH_SCRIPT" || true
    fi
    exit "$exit_code"
}

trap on_failure ERR

refresh_last_good_board
refresh_last_good_snapshot

if [[ "$FORCE_FULL_RUN" == "1" || "$FORCE_FULL_RUN" == "true" || "$CURRENT_HOUR" == "$FIRST_RUN_HOUR" && "$CURRENT_MINUTE" == "$FIRST_RUN_MINUTE" ]]; then
    IS_FIRST_RUN=1
    echo "Full NBA run: grading prior results, refreshing odds/lines, archiving, and rebuilding top plays"

    unset EDGERANKED_SKIP_GAME_LINES
    unset EDGERANKED_SKIP_NBA_LINES
    unset EDGERANKED_SKIP_BEST_BETS

    echo "Running grading workflow first..."
    bash "$BASE_DIR/scripts/grade_nba_best_bets.sh"
    echo "grading workflow finished"

    echo "Archiving prior best bets if present..."
    "$PYTHON_BIN" archive_best_bets_snapshot.py
else
    IS_FIRST_RUN=0
    echo "Later NBA run: skipping grading, PrizePicks refresh, and best-bets rebuild"
    unset EDGERANKED_SKIP_GAME_LINES
    export EDGERANKED_SKIP_NBA_LINES=1
    export EDGERANKED_SKIP_BEST_BETS=1
fi

echo "Running full NBA pipeline..."
"$PYTHON_BIN" run_nba_pipeline.py
echo "run_nba_pipeline.py finished"

if [[ "$IS_FIRST_RUN" == "1" && ! -f "$TARGET_BETS_FILE" ]]; then
    echo "ERROR: Fresh best bets file was not created at:"
    echo "$TARGET_BETS_FILE"
    exit 1
fi

if [[ ! -f "$TARGET_BETS_FILE" ]]; then
    echo "WARNING: No best bets file is currently present at:"
    echo "$TARGET_BETS_FILE"
fi

echo "Checking Best_Bets folder..."
ls -lah "$BEST_BETS_DIR"

"$PYTHON_BIN" - <<INNERPY
import pandas as pd
path = "$TARGET_BETS_FILE"
try:
    df = pd.read_csv(path)
except FileNotFoundError:
    print("Best bets file not found:", path)
else:
    print("Verified bets file:", path)
    print("Rows:", len(df))
    print("Columns:", list(df.columns))
    if not df.empty and "DATE" in df.columns:
        print("Dates in file:", df["DATE"].astype(str).unique().tolist())
INNERPY

refresh_last_good_board
refresh_last_good_snapshot

echo "=== NBA DAY RUN COMPLETE ==="
