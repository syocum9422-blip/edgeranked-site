#!/bin/zsh

caffeinate -s &

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR"
PYTHON_BIN="${MLB_PYTHON_BIN:-$PROJECT_DIR/.venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" && -x "$PROJECT_DIR/../.venv/bin/python" ]]; then
  PYTHON_BIN="$PROJECT_DIR/../.venv/bin/python"
fi
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="python3"
fi

cd "$PROJECT_DIR" || exit 1
if [[ -n "${EDGERANKED_MLB_ICLOUD_DIR:-}" ]]; then
  ICLOUD_DIR="$EDGERANKED_MLB_ICLOUD_DIR"
elif [[ "$(uname -s)" == "Darwin" ]]; then
  ICLOUD_DIR="$HOME/Library/Mobile Documents/com~apple~CloudDocs/MLB_Model"
else
  ICLOUD_DIR=""
fi

echo "=== NIGHT RUN START $(date) ==="

"$PYTHON_BIN" "$PROJECT_DIR/auto_grade_hitters_api.py"
"$PYTHON_BIN" "$PROJECT_DIR/hitter_calibration_report.py"
"$PYTHON_BIN" "$PROJECT_DIR/auto_grade_pitchers_api.py"
"$PYTHON_BIN" "$PROJECT_DIR/pitcher_calibration_report.py"
"$PYTHON_BIN" "$PROJECT_DIR/grade_betting_sheet_api.py"
"$PYTHON_BIN" "$PROJECT_DIR/retrain_daily_models.py"

if [[ -n "$ICLOUD_DIR" ]]; then
  mkdir -p "$ICLOUD_DIR"
  cp -f "$PROJECT_DIR/mlb/outputs/hitter_tracking.csv" "$ICLOUD_DIR/" 2>/dev/null
  cp -f "$PROJECT_DIR/mlb/outputs/pitcher_tracking.csv" "$ICLOUD_DIR/" 2>/dev/null
  cp -f "$PROJECT_DIR/mlb/outputs/bet_history.csv" "$ICLOUD_DIR/" 2>/dev/null
else
  echo "Skipping iCloud sync on this environment."
fi

echo "=== NIGHT RUN END $(date) ==="
