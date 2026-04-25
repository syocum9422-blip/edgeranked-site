#!/usr/bin/env bash
set -e

echo "=== GRADING RUN START ==="

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BASE_DIR="${EDGERANKED_NBA_BASE_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
PYTHON_BIN="${PYTHON_BIN:-$BASE_DIR/.venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
    PYTHON_BIN="python3"
fi
ARCHIVE_DIR="$BASE_DIR/Best_Bets/archive"

cd "$BASE_DIR" || exit 1

LATEST_ARCHIVE=$("$PYTHON_BIN" - <<PY
import os
archive_dir = "$ARCHIVE_DIR"
paths = []
if os.path.exists(archive_dir):
    for name in os.listdir(archive_dir):
        if name.startswith("nba_best_bets_") and name.endswith(".csv"):
            paths.append(os.path.join(archive_dir, name))
print(sorted(paths)[-1] if paths else "")
PY
)

if [[ -z "$LATEST_ARCHIVE" ]]; then
    echo "ERROR: No archived best bets file found in $ARCHIVE_DIR"
    exit 1
fi

echo "Using archived bets file: $LATEST_ARCHIVE"
export NBA_BETS_INPUT_PATH="$LATEST_ARCHIVE"

echo "Running fill_actuals.py..."
"$PYTHON_BIN" fill_actuals.py
echo "fill_actuals.py finished"

echo "Running grade_best_bets.py..."
"$PYTHON_BIN" grade_best_bets.py
echo "grade_best_bets.py finished"

echo "Running track_results.py..."
"$PYTHON_BIN" track_results.py
echo "track_results.py finished"

echo "Running calibrate_model.py..."
"$PYTHON_BIN" calibrate_model.py
echo "calibrate_model.py finished"

echo "Running generate_results_page.py..."
"$PYTHON_BIN" generate_results_page.py
echo "generate_results_page.py finished"

echo "=== GRADING RUN COMPLETE ==="
