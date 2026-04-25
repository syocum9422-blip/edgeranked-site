#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SITE_REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
LIVE_SITE_DIR="${EDGERANKED_LIVE_SITE_DIR:-/home/ubuntu/edgeranked-sportsai}"
ENV_FILE="${EDGERANKED_ENV_FILE:-/home/ubuntu/.edgeranked_env}"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

MLB_PIPELINE_DIR="${EDGERANKED_MLB_PIPELINE_DIR:-/home/ubuntu/mlb_model}"
MLB_PYTHON_BIN="${MLB_PYTHON_BIN:-$MLB_PIPELINE_DIR/.venv/bin/python}"

if [[ ! -x "$MLB_PYTHON_BIN" ]]; then
  MLB_PYTHON_BIN="python3"
fi

export EDGERANKED_LIVE_SITE_DIR="$LIVE_SITE_DIR"
export EDGERANKED_MLB_BASE_DIR="${EDGERANKED_MLB_BASE_DIR:-$LIVE_SITE_DIR}"
export EDGERANKED_MLB_SOURCE_DIR="${EDGERANKED_MLB_SOURCE_DIR:-$LIVE_SITE_DIR}"
export EDGERANKED_MLB_PIPELINE_DIR="$MLB_PIPELINE_DIR"
export MLB_READER_MODE="${MLB_READER_MODE:-legacy}"
export MLB_PUBLISH_MODE="${MLB_PUBLISH_MODE:-legacy}"

SKIP_MARKER="$MLB_PIPELINE_DIR/.skip_results_refresh"
EMAIL_SKIP_MARKER="$MLB_PIPELINE_DIR/.skip_mlb_email"
CURRENT_HOUR="$(TZ=America/New_York date +%H)"

cleanup() {
  rm -f "$SKIP_MARKER" "$EMAIL_SKIP_MARKER"
}
trap cleanup EXIT

cd "$MLB_PIPELINE_DIR"

if [[ "$CURRENT_HOUR" == "09" ]]; then
  rm -f "$SKIP_MARKER" "$EMAIL_SKIP_MARKER"
  echo "9am ET MLB run: including results refresh"
else
  touch "$SKIP_MARKER" "$EMAIL_SKIP_MARKER"
  echo "Later MLB run: skipping results refresh and email"
fi

"$MLB_PYTHON_BIN" "$MLB_PIPELINE_DIR/run_model.py"

mkdir -p "$LIVE_SITE_DIR/mlb/outputs" "$LIVE_SITE_DIR/data/mlb"

cp -f "$MLB_PIPELINE_DIR/mlb/outputs/betting_sheet_today.csv" "$LIVE_SITE_DIR/mlb/outputs/" 2>/dev/null || true
cp -f "$MLB_PIPELINE_DIR/mlb/outputs/hitter_summary_today.csv" "$LIVE_SITE_DIR/mlb/outputs/" 2>/dev/null || true
cp -f "$MLB_PIPELINE_DIR/mlb/outputs/mlb_pitcher_projections_today.csv" "$LIVE_SITE_DIR/mlb/outputs/" 2>/dev/null || true
cp -f "$MLB_PIPELINE_DIR/mlb/outputs/pitcher_props_today.csv" "$LIVE_SITE_DIR/mlb/outputs/" 2>/dev/null || true
cp -f "$MLB_PIPELINE_DIR/mlb/outputs/fantasy_projections_today.csv" "$LIVE_SITE_DIR/mlb/outputs/" 2>/dev/null || true
cp -f "$MLB_PIPELINE_DIR/mlb/outputs/hitter_tracking.csv" "$LIVE_SITE_DIR/mlb/outputs/" 2>/dev/null || true
cp -f "$MLB_PIPELINE_DIR/mlb/outputs/pitcher_tracking.csv" "$LIVE_SITE_DIR/mlb/outputs/" 2>/dev/null || true
cp -f "$MLB_PIPELINE_DIR/mlb/outputs/bet_history.csv" "$LIVE_SITE_DIR/mlb/outputs/" 2>/dev/null || true
cp -f "$MLB_PIPELINE_DIR/mlb/outputs/daily_betting_summary.csv" "$LIVE_SITE_DIR/mlb/outputs/" 2>/dev/null || true

cp -f "$MLB_PIPELINE_DIR/data/mlb/lines_today.csv" "$LIVE_SITE_DIR/data/mlb/" 2>/dev/null || true
cp -f "$MLB_PIPELINE_DIR/data/mlb/lines_today_raw.csv" "$LIVE_SITE_DIR/data/mlb/" 2>/dev/null || true
cp -f "$MLB_PIPELINE_DIR/data/mlb/lines_today_audit.json" "$LIVE_SITE_DIR/data/mlb/" 2>/dev/null || true

echo "MLB live artifact sync complete."
