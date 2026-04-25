#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="${EDGERANKED_NBA_BASE_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
PYTHON_BIN="${PYTHON_BIN:-$BASE_DIR/.venv/bin/python}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="python3"
fi

export EDGERANKED_NBA_BASE_DIR="$BASE_DIR"
export EDGERANKED_PUBLISH_SPORTS="nba"

cd "$BASE_DIR"

if [[ ! -f "$BASE_DIR/scripts/validate_nba_publish_ready.py" ]]; then
  echo "ERROR: Missing NBA validator: $BASE_DIR/scripts/validate_nba_publish_ready.py"
  exit 1
fi

echo "=== NBA EMERGENCY CURRENT-SLATE PUBLISH ==="
echo "Base dir: $BASE_DIR"
echo "Python: $PYTHON_BIN"
echo "Live site: ${EDGERANKED_LIVE_SITE_DIR:-/home/ubuntu/edgeranked-sportsai}"
echo "Publish scope: $EDGERANKED_PUBLISH_SPORTS"

echo
echo "Step 1/3: rebuild NBA best bets from canonical projections.csv and lines_today.csv"
"$PYTHON_BIN" "$BASE_DIR/build_best_bets.py"

echo
echo "Step 2/3: validate canonical NBA publish inputs"
"$PYTHON_BIN" "$BASE_DIR/scripts/validate_nba_publish_ready.py"

echo
echo "Step 3/3: publish NBA only"
bash "$BASE_DIR/scripts/publish_render_site.sh"

echo
echo "NBA emergency publish complete."
