#!/bin/zsh

echo "=== MLB MODEL MANUAL RUN START $(date) ==="

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

echo "Step 1: Fetch lines"
"$PYTHON_BIN" fetch_mlb_lines.py || exit 1

echo "Step 2: Build pitcher strikeout training data"
"$PYTHON_BIN" build_pitcher_strikeout_training_data.py || exit 1

echo "Step 3: Retrain pitcher strikeout model"
"$PYTHON_BIN" train_pitcher_strikeout_model.py || exit 1

echo "Step 4: Run hitter model"
"$PYTHON_BIN" predict_hitter.py || exit 1

echo "Step 5: Run pitcher model"
"$PYTHON_BIN" predict_pitchers.py || exit 1

echo "Step 8: Predict hitter strikeouts"
"$PYTHON_BIN" predict_hitter_strikeouts.py || exit 1

echo "Step 9: Build betting sheet"
"$PYTHON_BIN" build_betting_sheet.py || exit 1

echo "Step 10: Build betting image"
"$PYTHON_BIN" build_mobile_image.py || exit 1

echo "Step 11: Build prediction images"
"$PYTHON_BIN" build_predictions_image.py || exit 1

echo "Step 12: Build betting record image"
"$PYTHON_BIN" build_betting_record_image.py || exit 1

echo "Step 13: Refresh site folder"
mkdir -p site
mkdir -p site/mlb
mkdir -p site/nba

cp -f mlb/outputs/betting_sheet_mobile_today.png site/mlb/
cp -f mlb/outputs/hitter_predictions_today.png site/mlb/
cp -f mlb/outputs/pitcher_predictions_today.png site/mlb/
cp -f mlb/outputs/betting_record.png site/mlb/
cp -f mlb/outputs/edgeranked_logo.png site/ 2>/dev/null

echo "Step 14: Copy clean files to iCloud"
if [[ -n "${EDGERANKED_MLB_ICLOUD_DIR:-}" ]]; then
  ICLOUD_DIR="$EDGERANKED_MLB_ICLOUD_DIR"
elif [[ "$(uname -s)" == "Darwin" ]]; then
  ICLOUD_DIR="$HOME/Library/Mobile Documents/com~apple~CloudDocs/MLB_Model"
else
  ICLOUD_DIR=""
fi

if [[ -n "$ICLOUD_DIR" ]]; then
  mkdir -p "$ICLOUD_DIR"
  cp -f mlb/outputs/betting_sheet_mobile_today.png "$ICLOUD_DIR/"
  cp -f mlb/outputs/hitter_predictions_today.png "$ICLOUD_DIR/"
  cp -f mlb/outputs/pitcher_predictions_today.png "$ICLOUD_DIR/"
  cp -f mlb/outputs/betting_record.png "$ICLOUD_DIR/"
  cp -f mlb/outputs/edgeranked_logo.png "$ICLOUD_DIR/" 2>/dev/null
else
  echo "Skipping iCloud sync on this environment."
fi

echo "=== MLB MODEL MANUAL RUN END $(date) ==="
echo "Manual run complete."
