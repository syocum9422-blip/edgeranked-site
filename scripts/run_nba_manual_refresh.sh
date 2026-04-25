#!/usr/bin/env bash
set -e

echo "=== MANUAL NBA REFRESH START ==="

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BASE_DIR="${EDGERANKED_NBA_BASE_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
PYTHON_BIN="${PYTHON_BIN:-$BASE_DIR/.venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
    PYTHON_BIN="python3"
fi
BEST_BETS_DIR="$BASE_DIR/Best_Bets"
TARGET_BETS_FILE="$BEST_BETS_DIR/nba_best_bets_today.csv"
LAST_GOOD_DIR="$BASE_DIR/outputs/nba_last_good"
PUBLISH_SCRIPT="$BASE_DIR/scripts/publish_render_site.sh"

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

on_failure() {
    local exit_code=$?
    echo "ERROR: Manual NBA refresh failed with exit code $exit_code"
    restore_last_good_snapshot
    if [[ -x "$PUBLISH_SCRIPT" ]]; then
        echo "Publishing restored last-good NBA snapshot to the live site..."
        bash "$PUBLISH_SCRIPT" || true
    fi
    exit "$exit_code"
}

trap on_failure ERR

refresh_last_good_snapshot

export NBA_SKIP_TRAINING=1

echo "Running manual NBA pipeline without retraining..."
"$PYTHON_BIN" run_nba_pipeline.py
echo "run_nba_pipeline.py finished"

if [[ ! -f "$TARGET_BETS_FILE" ]]; then
    echo "ERROR: Best bets file not found at:"
    echo "$TARGET_BETS_FILE"
    exit 1
fi

echo "Checking Best_Bets folder..."
ls -lah "$BEST_BETS_DIR"

"$PYTHON_BIN" - <<PY
import pandas as pd
path = "$TARGET_BETS_FILE"
df = pd.read_csv(path)
print("Verified bets file:", path)
print("Rows:", len(df))
print("Columns:", list(df.columns))
if not df.empty and "DATE" in df.columns:
    print("Dates in file:", df["DATE"].astype(str).unique().tolist())
PY

refresh_last_good_snapshot

echo "=== MANUAL NBA REFRESH COMPLETE ==="
