#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${EDGERANKED_ENV_FILE:-/home/ubuntu/.edgeranked_env}"
GRADE_ONLY=0

if [[ "${1:-}" == "--grade-only" ]]; then
  GRADE_ONLY=1
fi

if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$ENV_FILE"
fi

export EDGERANKED_SITE_REPO_DIR="${EDGERANKED_SITE_REPO_DIR:-/home/ubuntu/EdgeRanked/site}"
export EDGERANKED_WNBA_BASE_DIR="${EDGERANKED_WNBA_BASE_DIR:-/home/ubuntu/EdgeRanked/sports/wnba}"
export EDGERANKED_LIVE_SITE_DIR="${EDGERANKED_LIVE_SITE_DIR:-/home/ubuntu/edgeranked-sportsai}"
export EDGERANKED_PUBLISH_SPORTS="${EDGERANKED_PUBLISH_SPORTS:-wnba}"
export WNBA_PYTHON_BIN="${WNBA_PYTHON_BIN:-$EDGERANKED_WNBA_BASE_DIR/.venv/bin/python}"

if [[ ! -x "$WNBA_PYTHON_BIN" ]]; then
  WNBA_PYTHON_BIN="${PYTHON_BIN:-python3}"
fi

cd "$EDGERANKED_WNBA_BASE_DIR"
echo "=== WNBA GRADING RUN START ==="
"$WNBA_PYTHON_BIN" fill_wnba_actuals.py || true
"$WNBA_PYTHON_BIN" grade_wnba_best_bets.py || true
"$WNBA_PYTHON_BIN" track_wnba_results.py || true
"$WNBA_PYTHON_BIN" calibrate_wnba_model.py || true
if ! "$WNBA_PYTHON_BIN" update_wnba_learning_outputs.py; then
  echo "WARNING: update_wnba_learning_outputs.py failed; continuing WNBA grading workflow."
fi
"$WNBA_PYTHON_BIN" daily_wnba_monitoring_summary.py || echo "WARNING: WNBA monitoring summary generation failed."
echo "=== WNBA GRADING RUN COMPLETE ==="

if [[ "$GRADE_ONLY" != "1" ]]; then
  cd "$EDGERANKED_SITE_REPO_DIR"
  EDGERANKED_PUBLISH_SPORTS=wnba python3 scripts/publish_render_snapshot.py || true
  EDGERANKED_PUBLISH_SPORTS=wnba bash scripts/publish_render_site.sh || true
fi
